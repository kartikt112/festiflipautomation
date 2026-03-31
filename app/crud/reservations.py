"""CRUD operations for reservations."""

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from datetime import datetime, timezone

from app.models.reservation import Reservation, ReservationStatus


async def create_reservation(db: AsyncSession, **kwargs) -> Reservation:
    reservation = Reservation(**kwargs)
    db.add(reservation)
    await db.flush()
    await db.refresh(reservation)
    return reservation


async def get_reservation(db: AsyncSession, reservation_id: int) -> Optional[Reservation]:
    result = await db.execute(select(Reservation).where(Reservation.id == reservation_id))
    return result.scalar_one_or_none()


async def get_reservation_by_stripe_session(
    db: AsyncSession, stripe_session_id: str
) -> Optional[Reservation]:
    result = await db.execute(
        select(Reservation).where(Reservation.stripe_session_id == stripe_session_id)
    )
    return result.scalar_one_or_none()


async def get_expired_reservations(db: AsyncSession) -> List[Reservation]:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Reservation)
        .where(Reservation.status == ReservationStatus.PENDING)
        .where(Reservation.expires_at <= now)
    )
    return list(result.scalars().all())


async def mark_reservation_paid(
    db: AsyncSession, reservation_id: int
) -> Optional[Reservation]:
    now = datetime.now(timezone.utc)
    await db.execute(
        update(Reservation)
        .where(Reservation.id == reservation_id)
        .values(status=ReservationStatus.PAID, paid_at=now)
    )
    await db.flush()
    return await get_reservation(db, reservation_id)


async def mark_reservation_expired(
    db: AsyncSession, reservation_id: int
) -> Optional[Reservation]:
    await db.execute(
        update(Reservation)
        .where(Reservation.id == reservation_id)
        .values(status=ReservationStatus.EXPIRED)
    )
    await db.flush()
    return await get_reservation(db, reservation_id)


async def get_all_reservations(db: AsyncSession, limit: int = 100) -> List[Reservation]:
    result = await db.execute(
        select(Reservation).order_by(Reservation.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())
