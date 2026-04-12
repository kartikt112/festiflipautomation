"""WhatsApp group model — tracks groups the Whapi number is in for broadcasting."""

from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func

from app.database import Base


class WhatsAppGroup(Base):
    __tablename__ = "whatsapp_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(String(100), unique=True, nullable=False, index=True)  # e.g. "120363...@g.us"
    group_name = Column(String(255), nullable=True)
    enabled = Column(Boolean, default=True, nullable=False, server_default="1")
    auto_detected = Column(Boolean, default=True, nullable=False, server_default="1")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
