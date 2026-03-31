"""CRUD operations for sell offers."""

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List

from app.models.sell_offer import SellOffer, OfferStatus, VerificationStatus
from app.schemas.sell_offer import SellOfferCreate


async def cancel_duplicate_offers(
    db: AsyncSession, phone: str, event_name: str
) -> int:
    """Cancel previous AVAILABLE offers from the same seller for the same event.

    This prevents stale pricing issues — e.g. seller lists at €60, then re-lists
    at €80. Without this, the old €60 offer stays active and may incorrectly match
    a buyer with max price €70.

    Returns the number of offers cancelled.
    """
    import logging
    logger = logging.getLogger(__name__)

    # Find all AVAILABLE offers from this seller for a matching event
    result = await db.execute(
        select(SellOffer).where(
            SellOffer.phone == phone,
            SellOffer.status == OfferStatus.AVAILABLE,
            SellOffer.event_name.ilike(f"%{event_name.split()[0]}%") if event_name else SellOffer.event_name == event_name,
        )
    )
    existing_offers = list(result.scalars().all())

    cancelled = 0
    for existing in existing_offers:
        # Fuzzy match: check if event names overlap significantly
        existing_lower = existing.event_name.lower().strip()
        new_lower = event_name.lower().strip()
        if existing_lower in new_lower or new_lower in existing_lower:
            existing.status = OfferStatus.CANCELLED
            cancelled += 1
            logger.info(
                f"Auto-cancelled offer #{existing.id} ({existing.event_name}, "
                f"€{existing.price_per_ticket}) — replaced by new offer from {phone}"
            )

    if cancelled:
        await db.flush()

    return cancelled


async def create_sell_offer(db: AsyncSession, data: SellOfferCreate) -> SellOffer:
    # Cancel any previous offers from this seller for the same event
    if data.phone and data.event_name:
        await cancel_duplicate_offers(db, data.phone, data.event_name)

    offer = SellOffer(**data.model_dump())
    if offer.total_price is None and offer.price_per_ticket and offer.quantity:
        offer.total_price = offer.price_per_ticket * offer.quantity
    db.add(offer)
    await db.flush()
    await db.refresh(offer)
    return offer


async def get_sell_offer(db: AsyncSession, offer_id: int) -> Optional[SellOffer]:
    result = await db.execute(select(SellOffer).where(SellOffer.id == offer_id))
    return result.scalar_one_or_none()


async def get_available_offers(
    db: AsyncSession,
    event_name: Optional[str] = None,
    limit: int = 50,
) -> List[SellOffer]:
    query = select(SellOffer).where(SellOffer.status == OfferStatus.AVAILABLE)
    if event_name:
        query = query.where(SellOffer.event_name.ilike(f"%{event_name}%"))
    query = query.order_by(SellOffer.created_at.desc()).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_all_offers(db: AsyncSession, limit: int = 100) -> List[SellOffer]:
    result = await db.execute(
        select(SellOffer).order_by(SellOffer.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def update_offer_status(
    db: AsyncSession, offer_id: int, status: OfferStatus
) -> Optional[SellOffer]:
    await db.execute(
        update(SellOffer).where(SellOffer.id == offer_id).values(status=status)
    )
    await db.flush()
    return await get_sell_offer(db, offer_id)


async def verify_seller(
    db: AsyncSession, offer_id: int, status: VerificationStatus
) -> Optional[SellOffer]:
    await db.execute(
        update(SellOffer)
        .where(SellOffer.id == offer_id)
        .values(verification_status=status)
    )
    await db.flush()
    return await get_sell_offer(db, offer_id)


async def get_offers_by_phone(db: AsyncSession, phone: str) -> List[SellOffer]:
    result = await db.execute(
        select(SellOffer).where(SellOffer.phone == phone).order_by(SellOffer.created_at.desc())
    )
    return list(result.scalars().all())


async def count_available_for_event(db: AsyncSession, event_name: str) -> int:
    from sqlalchemy import func
    result = await db.execute(
        select(func.coalesce(func.sum(SellOffer.quantity), 0))
        .where(SellOffer.event_name.ilike(f"%{event_name}%"))
        .where(SellOffer.status == OfferStatus.AVAILABLE)
    )
    return int(result.scalar() or 0)
