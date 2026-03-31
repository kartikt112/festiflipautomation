"""Reservation model – links buyer to seller with deposit tracking."""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Numeric, ForeignKey, Enum as SAEnum
from sqlalchemy.sql import func
import enum

from app.database import Base


class ReservationStatus(str, enum.Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class Reservation(Base):
    __tablename__ = "reservations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    buy_request_id = Column(Integer, ForeignKey("buy_requests.id"), nullable=False, index=True)
    sell_offer_id = Column(Integer, ForeignKey("sell_offers.id"), nullable=False, index=True)
    quantity = Column(Integer, nullable=False, default=1)

    # Financial
    deposit_amount = Column(Numeric(10, 2), nullable=False)
    remaining_amount = Column(Numeric(10, 2), nullable=False)
    minimum_applied = Column(Boolean, default=False, nullable=False)

    # Stripe
    stripe_session_id = Column(String(255), nullable=True, unique=True)
    stripe_checkout_url = Column(String(500), nullable=True)

    # Status
    status = Column(SAEnum(ReservationStatus), default=ReservationStatus.PENDING, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    paid_at = Column(DateTime(timezone=True), nullable=True)

    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
