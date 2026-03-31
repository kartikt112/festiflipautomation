"""CRUD operations for chat sessions (conversation state)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.models.chat_session import ChatSession


async def get_or_create_session(db: AsyncSession, phone: str) -> ChatSession:
    result = await db.execute(
        select(ChatSession).where(ChatSession.phone == phone)
    )
    session = result.scalar_one_or_none()
    if session is None:
        session = ChatSession(phone=phone, collected_data={})
        db.add(session)
        await db.flush()
        await db.refresh(session)
    return session


async def update_session(
    db: AsyncSession,
    phone: str,
    current_intent: Optional[str] = None,
    current_step: Optional[str] = None,
    collected_data: Optional[dict] = None,
) -> ChatSession:
    session = await get_or_create_session(db, phone)
    if current_intent is not None:
        session.current_intent = current_intent
    if current_step is not None:
        session.current_step = current_step
    if collected_data is not None:
        session.collected_data = collected_data
    await db.flush()
    await db.refresh(session)
    return session


async def reset_session(db: AsyncSession, phone: str) -> ChatSession:
    return await update_session(
        db, phone,
        current_intent=None,
        current_step="IDLE",
        collected_data={},
    )
