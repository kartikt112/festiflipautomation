"""Chat message log model – stores all WhatsApp messages (inbound + outbound) for dashboard viewing."""

from sqlalchemy import Column, Integer, String, DateTime, Text, Enum as SAEnum
from sqlalchemy.sql import func
import enum

from app.database import Base


class MessageDirection(str, enum.Enum):
    INBOUND = "INBOUND"    # User → FestiFlip
    OUTBOUND = "OUTBOUND"  # FestiFlip → User


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    phone = Column(String(20), nullable=False, index=True)   # E.164
    direction = Column(SAEnum(MessageDirection), nullable=False)
    body = Column(Text, nullable=False)
    message_type = Column(String(20), default="text")  # text, image, etc.

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
