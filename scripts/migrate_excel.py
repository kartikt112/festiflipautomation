"""Excel → Database migration script.

Usage:
    python scripts/migrate_excel.py --sell-file sell_offers.xlsx --buy-file buy_requests.xlsx [--dry-run]
"""

import argparse
import asyncio
import logging
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from datetime import datetime, timezone

from app.database import async_session, init_db
from app.models.sell_offer import SellOffer, VerificationStatus, OfferStatus
from app.models.buy_request import BuyRequest, BuySource, BuyStatus

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def normalize_phone(phone) -> str:
    """Normalize phone number to E.164 format."""
    if pd.isna(phone) or not phone:
        return ""
    phone = str(phone).strip().replace(" ", "").replace("-", "")
    if phone.startswith("06"):
        phone = "+31" + phone[1:]
    elif phone.startswith("6") and len(phone) == 9:
        phone = "+31" + phone
    elif not phone.startswith("+"):
        phone = "+" + phone
    return phone


def normalize_timestamp(ts) -> datetime:
    """Normalize timestamp to UTC."""
    if pd.isna(ts):
        return datetime.now(timezone.utc)
    if isinstance(ts, str):
        for fmt in ["%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%d-%m-%Y %H:%M:%S"]:
            try:
                return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    if isinstance(ts, datetime):
        return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts
    return datetime.now(timezone.utc)


async def import_sell_offers(file_path: str, dry_run: bool = False):
    """Import sell offers from Excel."""
    logger.info(f"Reading sell offers from: {file_path}")
    df = pd.read_excel(file_path)
    logger.info(f"Found {len(df)} rows")

    # Map column names (adjust based on actual Excel headers)
    column_map = {
        "Voornaam": "first_name",
        "Achternaam": "last_name",
        "Telefoonnummer": "phone",
        "E-mailadres": "email",
        "Instagram": "instagram",
        "Geslacht": "gender",
        "Geboortedatum": "birth_date",
        "Stad": "city",
        "Postcode": "postcode",
        "Evenement": "event_name",
        "Datum evenement": "event_date",
        "Aantal": "quantity",
        "Prijs per ticket": "price_per_ticket",
        "Totale prijs": "total_price",
        "Type verkoop": "sale_type",
        "Bron ticket": "ticket_source",
        "Timestamp": "timestamp",
    }

    duplicates = 0
    imported = 0
    errors = 0

    async with async_session() as db:
        for _, row in df.iterrows():
            try:
                phone = normalize_phone(row.get("Telefoonnummer", ""))
                if not phone:
                    logger.warning(f"Skipping row with no phone: {row.to_dict()}")
                    errors += 1
                    continue

                event_name = str(row.get("Evenement", row.get("event_name", "Unknown")))

                offer = SellOffer(
                    timestamp=normalize_timestamp(row.get("Timestamp")),
                    first_name=str(row.get("Voornaam", row.get("first_name", "Unknown"))),
                    last_name=str(row.get("Achternaam", row.get("last_name", ""))) if not pd.isna(row.get("Achternaam", row.get("last_name"))) else None,
                    phone=phone,
                    email=str(row.get("E-mailadres", "")) if not pd.isna(row.get("E-mailadres")) else None,
                    event_name=event_name,
                    quantity=int(row.get("Aantal", row.get("quantity", 1))),
                    price_per_ticket=float(row.get("Prijs per ticket", row.get("price_per_ticket", 0))),
                    verification_status=VerificationStatus.UNVERIFIED,
                    status=OfferStatus.AVAILABLE,
                )

                if not dry_run:
                    db.add(offer)
                imported += 1

            except Exception as e:
                logger.error(f"Error importing row: {e}")
                errors += 1

        if not dry_run:
            await db.commit()

    logger.info(f"Sell offers: imported={imported}, duplicates={duplicates}, errors={errors}")
    if dry_run:
        logger.info("DRY RUN – no data was written")


async def import_buy_requests(file_path: str, dry_run: bool = False):
    """Import buy requests from Excel."""
    logger.info(f"Reading buy requests from: {file_path}")
    df = pd.read_excel(file_path)
    logger.info(f"Found {len(df)} rows")

    imported = 0
    errors = 0

    async with async_session() as db:
        for _, row in df.iterrows():
            try:
                phone = normalize_phone(row.get("Telefoonnummer", ""))
                if not phone:
                    errors += 1
                    continue

                request = BuyRequest(
                    timestamp=normalize_timestamp(row.get("Timestamp")),
                    first_name=str(row.get("Voornaam", row.get("first_name", "Unknown"))),
                    last_name=str(row.get("Achternaam", "")) if not pd.isna(row.get("Achternaam")) else None,
                    phone=phone,
                    email=str(row.get("E-mailadres", "")) if not pd.isna(row.get("E-mailadres")) else None,
                    event_name=str(row.get("Evenement", row.get("event_name", "Unknown"))),
                    quantity=int(row.get("Aantal", row.get("quantity", 1))),
                    source=BuySource.FORM,
                    status=BuyStatus.WAITING,
                )

                if not dry_run:
                    db.add(request)
                imported += 1

            except Exception as e:
                logger.error(f"Error importing row: {e}")
                errors += 1

        if not dry_run:
            await db.commit()

    logger.info(f"Buy requests: imported={imported}, errors={errors}")
    if dry_run:
        logger.info("DRY RUN – no data was written")


async def main():
    parser = argparse.ArgumentParser(description="Import Excel data into FestiFlip DB")
    parser.add_argument("--sell-file", help="Path to Sell Offers Excel file")
    parser.add_argument("--buy-file", help="Path to Buy Requests Excel file")
    parser.add_argument("--dry-run", action="store_true", help="Validate without writing")
    args = parser.parse_args()

    # Initialize DB tables
    await init_db()

    if args.sell_file:
        await import_sell_offers(args.sell_file, args.dry_run)
    if args.buy_file:
        await import_buy_requests(args.buy_file, args.dry_run)

    if not args.sell_file and not args.buy_file:
        logger.error("Please specify --sell-file and/or --buy-file")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
