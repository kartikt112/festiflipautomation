"""Fetch recent conversation history for a phone number."""

from typing import List, Dict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_message import ChatMessage, MessageDirection

# Max messages to fetch (keeps token usage low)
MAX_HISTORY_MESSAGES = 10


async def get_recent_history(
    db: AsyncSession, phone: str, limit: int = MAX_HISTORY_MESSAGES
) -> List[Dict[str, str]]:
    """Fetch recent chat messages for a phone number.

    Returns a list of dicts with 'role' (user/assistant) and 'content',
    ordered oldest-first so they can be directly injected into OpenAI messages.
    """
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.phone == phone)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    )
    rows = result.scalars().all()

    # Reverse to get chronological order (oldest first)
    rows = list(reversed(rows))

    history = []
    for msg in rows:
        role = "user" if msg.direction == MessageDirection.INBOUND else "assistant"
        # Truncate very long messages to save tokens
        body = msg.body[:500] if msg.body else ""
        if body:
            history.append({"role": role, "content": body})

    return history
