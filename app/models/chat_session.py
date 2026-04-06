"""Chat session model – per-phone conversation state for the AI state machine."""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, JSON
from sqlalchemy.sql import func
from sqlalchemy.ext.mutable import MutableDict, MutableList

from app.database import Base


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    phone = Column(String(20), unique=True, nullable=False, index=True)  # E.164
    current_intent = Column(String(50), nullable=True)
    current_step = Column(String(50), default="IDLE", nullable=False)
    # For AI routing: store chat context
    message_history = Column(MutableList.as_mutable(JSON), default=list, nullable=False)
    collected_data = Column(MutableDict.as_mutable(JSON), default=dict, nullable=False)
    bot_paused = Column(Boolean, default=False, nullable=False, server_default="0")
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
