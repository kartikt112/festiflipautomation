"""Payment model – records Stripe deposit payments with idempotency."""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Numeric, ForeignKey, Enum as SAEnum
from sqlalchemy.sql import func
import enum

from app.database import Base


class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    REFUNDED = "REFUNDED"
    FAILED = "FAILED"


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    reservation_id = Column(Integer, ForeignKey("reservations.id"), nullable=False, index=True)

    # Financial
    deposit_amount = Column(Numeric(10, 2), nullable=False)
    minimum_applied = Column(Boolean, default=False, nullable=False)

    # Stripe
    stripe_session_id = Column(String(255), nullable=True, index=True)
    stripe_payment_intent_id = Column(String(255), nullable=True, unique=True)

    # Idempotency
    webhook_event_id = Column(String(255), nullable=True, unique=True)

    # Status
    status = Column(SAEnum(PaymentStatus), default=PaymentStatus.PENDING, nullable=False)

    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
