"""Pending seller confirmation model.

When a buyer matches with a sell offer that is older than 2 hours,
we ask the seller to confirm they still have the ticket before
creating a reservation. This model tracks those pending confirmations.
"""

from sqlalchemy import Column, Integer, String, DateTime, Enum as SAEnum, ForeignKey
from sqlalchemy.sql import func
import enum

from app.database import Base


class ConfirmationStatus(str, enum.Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class PendingConfirmation(Base):
    __tablename__ = "pending_confirmations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sell_offer_id = Column(Integer, ForeignKey("sell_offers.id"), nullable=False, index=True)
    buy_request_id = Column(Integer, ForeignKey("buy_requests.id"), nullable=False, index=True)
    seller_phone = Column(String(20), nullable=False, index=True)
    buyer_phone = Column(String(20), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)

    status = Column(SAEnum(ConfirmationStatus), default=ConfirmationStatus.PENDING, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
