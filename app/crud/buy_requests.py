"""CRUD operations for buy requests."""

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List

from app.models.buy_request import BuyRequest, BuyStatus
from app.schemas.buy_request import BuyRequestCreate


async def create_buy_request(db: AsyncSession, data: BuyRequestCreate) -> BuyRequest:
    request = BuyRequest(**data.model_dump())
    db.add(request)
    await db.flush()
    await db.refresh(request)
    return request


async def get_buy_request(db: AsyncSession, request_id: int) -> Optional[BuyRequest]:
    result = await db.execute(select(BuyRequest).where(BuyRequest.id == request_id))
    return result.scalar_one_or_none()


async def get_waiting_requests(
    db: AsyncSession,
    event_name: Optional[str] = None,
    limit: int = 50,
) -> List[BuyRequest]:
    query = select(BuyRequest).where(BuyRequest.status == BuyStatus.WAITING)
    if event_name:
        query = query.where(BuyRequest.event_name.ilike(f"%{event_name}%"))
    query = query.order_by(BuyRequest.created_at.desc()).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_all_requests(db: AsyncSession, limit: int = 100) -> List[BuyRequest]:
    result = await db.execute(
        select(BuyRequest).order_by(BuyRequest.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def update_request_status(
    db: AsyncSession, request_id: int, status: BuyStatus
) -> Optional[BuyRequest]:
    await db.execute(
        update(BuyRequest).where(BuyRequest.id == request_id).values(status=status)
    )
    await db.flush()
    return await get_buy_request(db, request_id)


async def get_requests_by_phone(db: AsyncSession, phone: str) -> List[BuyRequest]:
    result = await db.execute(
        select(BuyRequest).where(BuyRequest.phone == phone).order_by(BuyRequest.created_at.desc())
    )
    return list(result.scalars().all())
