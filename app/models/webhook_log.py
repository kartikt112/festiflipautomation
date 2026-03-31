"""Webhook log model – stores all incoming webhook events for debugging."""

from sqlalchemy import Column, Integer, String, DateTime, JSON
from sqlalchemy.sql import func

from app.database import Base


class WebhookLog(Base):
    __tablename__ = "webhook_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(50), nullable=False)  # "stripe" or "whatsapp"
    event_type = Column(String(100), nullable=True)
    event_id = Column(String(255), nullable=True, index=True)
    payload = Column(JSON, nullable=True)
    status = Column(String(50), default="received", nullable=False)
    error_message = Column(String(1000), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
