"""Reseller inventory model – tickets available from fixed resellers."""

import enum
from sqlalchemy import Column, Integer, String, Boolean, Date, Numeric, DateTime, ForeignKey, Enum as SAEnum
from sqlalchemy.sql import func

from app.database import Base


class InventoryStatus(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    CHECKING = "CHECKING"       # Availability check sent to reseller
    CONFIRMED = "CONFIRMED"     # Reseller confirmed it's still available
    SOLD = "SOLD"
    UNAVAILABLE = "UNAVAILABLE" # Reseller said it's gone


class ResellerInventory(Base):
    __tablename__ = "reseller_inventory"

    id = Column(Integer, primary_key=True, autoincrement=True)
    reseller_id = Column(Integer, ForeignKey("fixed_resellers.id"), nullable=False, index=True)

    event_name = Column(String(255), nullable=False, index=True)
    event_date = Column(Date, nullable=True)
    ticket_type = Column(String(100), nullable=True)
    quantity = Column(Integer, nullable=False, default=1)
    price_per_ticket = Column(Numeric(10, 2), nullable=False)

    status = Column(SAEnum(InventoryStatus), default=InventoryStatus.AVAILABLE, nullable=False)

    # Track availability checks
    last_check_at = Column(DateTime(timezone=True), nullable=True)
    last_check_buyer_phone = Column(String(20), nullable=True)

    notes = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
