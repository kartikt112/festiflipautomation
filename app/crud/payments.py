"""CRUD operations for payments."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List

from app.models.payment import Payment, PaymentStatus


async def create_payment(db: AsyncSession, **kwargs) -> Payment:
    payment = Payment(**kwargs)
    db.add(payment)
    await db.flush()
    await db.refresh(payment)
    return payment


async def get_payment_by_webhook_event(
    db: AsyncSession, webhook_event_id: str
) -> Optional[Payment]:
    """Check for idempotency – has this webhook already been processed?"""
    result = await db.execute(
        select(Payment).where(Payment.webhook_event_id == webhook_event_id)
    )
    return result.scalar_one_or_none()


async def get_payment_by_reservation(
    db: AsyncSession, reservation_id: int
) -> Optional[Payment]:
    result = await db.execute(
        select(Payment).where(Payment.reservation_id == reservation_id)
    )
    return result.scalar_one_or_none()


async def get_all_payments(db: AsyncSession, limit: int = 100) -> List[Payment]:
    result = await db.execute(
        select(Payment).order_by(Payment.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())
