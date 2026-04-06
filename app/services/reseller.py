"""Reseller service – check inventory and request availability from fixed resellers.

Flow:
1. Buyer submits a request → matching checks reseller inventory first
2. If a reseller has tickets → send availability check to reseller via WhatsApp
3. Reseller confirms → continue normal reservation flow
4. Reseller denies or no response → mark as unavailable, fall through to regular offers
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fixed_reseller import FixedReseller
from app.models.reseller_inventory import ResellerInventory, InventoryStatus

logger = logging.getLogger(__name__)


async def find_reseller_inventory(
    db: AsyncSession,
    event_name: str,
    quantity: int,
    max_price: float = None,
    event_date=None,
) -> Optional[ResellerInventory]:
    """Check if any fixed reseller has matching tickets available.

    Returns the best matching inventory item, or None.
    """
    name_lower = event_name.strip().lower()

    # Get all available inventory
    query = (
        select(ResellerInventory)
        .join(FixedReseller, ResellerInventory.reseller_id == FixedReseller.id)
        .where(
            and_(
                FixedReseller.active == True,
                ResellerInventory.status == InventoryStatus.AVAILABLE,
                ResellerInventory.quantity >= quantity,
            )
        )
        .order_by(ResellerInventory.price_per_ticket.asc())
    )

    result = await db.execute(query)
    items = list(result.scalars().all())

    for item in items:
        # Fuzzy match: check if event names overlap
        item_name_lower = item.event_name.strip().lower()
        if name_lower in item_name_lower or item_name_lower in name_lower:
            # Date check if both have dates
            if event_date and item.event_date and item.event_date != event_date:
                continue
            # Price check
            if max_price and float(item.price_per_ticket) > max_price:
                continue
            return item

    return None


async def request_availability_check(
    db: AsyncSession,
    inventory_item: ResellerInventory,
    buyer_phone: str,
) -> bool:
    """Send availability check to the reseller via WhatsApp.

    Returns True if message was sent successfully.
    """
    from app.services.whatsapp import send_text_message

    # Get reseller info
    result = await db.execute(
        select(FixedReseller).where(FixedReseller.id == inventory_item.reseller_id)
    )
    reseller = result.scalar_one_or_none()
    if not reseller or not reseller.phone:
        logger.error(f"Reseller #{inventory_item.reseller_id} has no phone number")
        return False

    # Update inventory status
    inventory_item.status = InventoryStatus.CHECKING
    inventory_item.last_check_at = datetime.now(timezone.utc)
    inventory_item.last_check_buyer_phone = buyer_phone
    await db.flush()

    # Send WhatsApp to reseller
    msg = (
        f"Hey {reseller.name}! 👋\n\n"
        f"Er is een koper voor *{inventory_item.event_name}*"
    )
    if inventory_item.event_date:
        msg += f" ({inventory_item.event_date.strftime('%d/%m/%Y')})"
    msg += (
        f" — {inventory_item.quantity}x tickets.\n\n"
        f"Zijn deze nog beschikbaar? Antwoord met *ja* of *nee*."
    )

    try:
        await send_text_message(reseller.phone, msg)
        logger.info(f"Availability check sent to reseller {reseller.name} ({reseller.phone})")
        return True
    except Exception as e:
        logger.error(f"Failed to send availability check to {reseller.phone}: {e}")
        return False


async def handle_reseller_response(
    db: AsyncSession,
    reseller_phone: str,
    confirmed: bool,
) -> Optional[str]:
    """Handle reseller's response to availability check.

    Returns a reply message for the reseller, or None if no pending check found.
    """
    # Find the reseller
    result = await db.execute(
        select(FixedReseller).where(FixedReseller.phone == reseller_phone)
    )
    reseller = result.scalar_one_or_none()
    if not reseller:
        return None

    # Find the CHECKING inventory item
    result = await db.execute(
        select(ResellerInventory).where(
            and_(
                ResellerInventory.reseller_id == reseller.id,
                ResellerInventory.status == InventoryStatus.CHECKING,
            )
        ).order_by(ResellerInventory.last_check_at.desc()).limit(1)
    )
    item = result.scalar_one_or_none()
    if not item:
        return None

    buyer_phone = item.last_check_buyer_phone

    if confirmed:
        item.status = InventoryStatus.CONFIRMED
        await db.flush()

        # Notify buyer that tickets are available from reseller
        if buyer_phone:
            from app.services.whatsapp import send_text_message
            try:
                await send_text_message(
                    buyer_phone,
                    f"Goed nieuws! Er zijn tickets beschikbaar voor *{item.event_name}* "
                    f"via een van onze vaste verkopers. 🎉\n\n"
                    f"We regelen het verder voor je!"
                )
            except Exception as e:
                logger.error(f"Failed to notify buyer {buyer_phone}: {e}")

        return (
            f"Top, bedankt! We koppelen de koper aan je voor *{item.event_name}*. "
            f"Je hoort van ons zodra de aanbetaling binnen is!"
        )
    else:
        item.status = InventoryStatus.UNAVAILABLE
        await db.flush()

        # Notify buyer
        if buyer_phone:
            from app.services.whatsapp import send_text_message
            try:
                await send_text_message(
                    buyer_phone,
                    f"Helaas, de tickets voor *{item.event_name}* via onze vaste verkoper "
                    f"zijn niet meer beschikbaar. We zoeken verder voor je!"
                )
            except Exception as e:
                logger.error(f"Failed to notify buyer {buyer_phone}: {e}")

        return "Oké, bedankt voor de update! We laten de koper weten."
