"""AI Log model – audit trail for all AI classification decisions."""

from sqlalchemy import Column, Integer, String, Float, DateTime, JSON
from sqlalchemy.sql import func

from app.database import Base


class AILog(Base):
    __tablename__ = "ai_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    phone = Column(String(20), nullable=False, index=True)
    raw_message = Column(String(2000), nullable=False)
    ai_response = Column(JSON, nullable=True)
    intent = Column(String(50), nullable=True)
    confidence = Column(Float, nullable=True)
    classification_method = Column(String(20), nullable=True)  # "RULES" or "AI"
    prompt_version = Column(String(20), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
