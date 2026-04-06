"""Group post queue service – FIFO cooldown per event for group messages.

Logic:
- When a new sell offer is created, queue the group message instead of posting immediately.
- Only post if no other POSTED (active) listing for the same event+date exists.
- When a listing is sold or expires, post the next QUEUED entry for that event.
"""

import logging
from datetime import date, datetime, timezone
from typing import Optional
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.group_post_queue import GroupPostQueue, PostStatus

logger = logging.getLogger(__name__)


def _normalize_event_key(event_name: str) -> str:
    """Normalize event name for comparison (lowercase, stripped)."""
    return event_name.strip().lower()


async def enqueue_group_post(
    db: AsyncSession,
    sell_offer_id: int,
    event_name: str,
    event_date: Optional[date],
    message_body: str,
) -> bool:
    """Add a group post to the queue. Posts immediately if no active listing for this event.

    Returns True if posted immediately, False if queued.
    """
    # Check if there's already a POSTED entry for this event+date
    has_active = await _has_active_post(db, event_name, event_date)

    entry = GroupPostQueue(
        sell_offer_id=sell_offer_id,
        event_name=event_name,
        event_date=event_date,
        message_body=message_body,
        status=PostStatus.QUEUED,
    )
    db.add(entry)
    await db.flush()

    if not has_active:
        # No active listing — post immediately
        return await _post_entry(db, entry)
    else:
        logger.info(
            f"Group post queued for {event_name} (offer #{sell_offer_id}) — "
            f"active listing already exists"
        )
        return False


async def promote_next_for_event(
    db: AsyncSession,
    event_name: str,
    event_date: Optional[date] = None,
) -> bool:
    """After a listing is sold/expired, post the next queued entry for this event.

    Called from the scheduler or after a sale completes.
    Returns True if a new entry was posted.
    """
    # First, mark any POSTED entries for this event as EXPIRED (the sold one)
    # (the caller should have already updated the sell offer status)

    # Find the next QUEUED entry for this event
    key = _normalize_event_key(event_name)
    query = (
        select(GroupPostQueue)
        .where(
            and_(
                func.lower(GroupPostQueue.event_name) == key,
                GroupPostQueue.status == PostStatus.QUEUED,
            )
        )
        .order_by(GroupPostQueue.created_at.asc())
        .limit(1)
    )

    # Filter by date if provided
    if event_date:
        query = (
            select(GroupPostQueue)
            .where(
                and_(
                    func.lower(GroupPostQueue.event_name) == key,
                    GroupPostQueue.event_date == event_date,
                    GroupPostQueue.status == PostStatus.QUEUED,
                )
            )
            .order_by(GroupPostQueue.created_at.asc())
            .limit(1)
        )

    result = await db.execute(query)
    next_entry = result.scalar_one_or_none()

    if next_entry:
        # Check if the event date hasn't passed
        if next_entry.event_date and next_entry.event_date < date.today():
            next_entry.status = PostStatus.EXPIRED
            await db.flush()
            logger.info(f"Skipped expired queued post for {event_name} (date passed)")
            # Try the next one recursively
            return await promote_next_for_event(db, event_name, event_date)

        return await _post_entry(db, next_entry)

    return False


async def mark_posted_as_expired(
    db: AsyncSession,
    sell_offer_id: int,
) -> None:
    """Mark the POSTED group entry for a specific sell offer as EXPIRED."""
    result = await db.execute(
        select(GroupPostQueue).where(
            and_(
                GroupPostQueue.sell_offer_id == sell_offer_id,
                GroupPostQueue.status == PostStatus.POSTED,
            )
        )
    )
    entry = result.scalar_one_or_none()
    if entry:
        entry.status = PostStatus.EXPIRED
        await db.flush()


async def _has_active_post(
    db: AsyncSession, event_name: str, event_date: Optional[date]
) -> bool:
    """Check if there's already a POSTED (active) group message for this event."""
    key = _normalize_event_key(event_name)
    conditions = [
        func.lower(GroupPostQueue.event_name) == key,
        GroupPostQueue.status == PostStatus.POSTED,
    ]
    if event_date:
        conditions.append(GroupPostQueue.event_date == event_date)

    result = await db.execute(
        select(func.count(GroupPostQueue.id)).where(and_(*conditions))
    )
    count = result.scalar() or 0
    return count > 0


async def _post_entry(db: AsyncSession, entry: GroupPostQueue) -> bool:
    """Actually send the group message and mark as POSTED."""
    from app.services.whapi import send_group_notification

    try:
        sent = await send_group_notification(entry.message_body)
        if sent:
            entry.status = PostStatus.POSTED
            entry.posted_at = datetime.now(timezone.utc)
            await db.flush()
            logger.info(f"Group post sent for {entry.event_name} (offer #{entry.sell_offer_id})")
            return True
        else:
            logger.error(f"Failed to send group post for {entry.event_name}")
            return False
    except Exception as e:
        logger.error(f"Error posting group message: {e}")
        return False
