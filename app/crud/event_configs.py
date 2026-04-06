"""CRUD operations for EventConfig – price rules and edition settings."""

from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event_config import EventConfig


async def get_all_configs(db: AsyncSession) -> List[EventConfig]:
    result = await db.execute(
        select(EventConfig).order_by(EventConfig.event_keyword.asc())
    )
    return list(result.scalars().all())


async def get_config_by_id(db: AsyncSession, config_id: int) -> Optional[EventConfig]:
    result = await db.execute(
        select(EventConfig).where(EventConfig.id == config_id)
    )
    return result.scalar_one_or_none()


async def find_matching_config(
    db: AsyncSession, event_name: str, event_date=None
) -> Optional[EventConfig]:
    """Find an EventConfig that fuzzy-matches the event name (keyword in name).

    If event_date is provided, prefer a config that also matches the date.
    Falls back to a config without a date constraint.
    """
    configs = await get_all_configs(db)
    name_lower = event_name.strip().lower()

    # First pass: match keyword + date
    if event_date:
        for cfg in configs:
            if cfg.event_keyword.lower() in name_lower and cfg.event_date == event_date:
                return cfg

    # Second pass: match keyword only (no date constraint)
    for cfg in configs:
        if cfg.event_keyword.lower() in name_lower and cfg.event_date is None:
            return cfg

    # Third pass: keyword in name, any config (date-specific but still relevant)
    for cfg in configs:
        if cfg.event_keyword.lower() in name_lower:
            return cfg

    return None


async def should_ask_edition(db: AsyncSession, event_name: str) -> bool:
    """Check if this event requires an edition question."""
    configs = await get_all_configs(db)
    name_lower = event_name.strip().lower()
    for cfg in configs:
        if cfg.event_keyword.lower() in name_lower and cfg.ask_edition:
            return True
    return False
