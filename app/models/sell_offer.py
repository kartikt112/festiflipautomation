"""Sell Offer model – maps to the Sell Sheet (FestiFlip – Sell)."""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Numeric, Date, Enum as SAEnum
from sqlalchemy.sql import func
import enum

from app.database import Base


class VerificationStatus(str, enum.Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    TRUSTED = "TRUSTED"


class OfferStatus(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    SOLD = "SOLD"
    CANCELLED = "CANCELLED"


class SellOffer(Base):
    __tablename__ = "sell_offers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), nullable=True)  # Original form timestamp

    # Personal info (maps to Sell Sheet)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=True)
    phone = Column(String(20), nullable=False, index=True)  # E.164
    email = Column(String(255), nullable=True)
    instagram = Column(String(100), nullable=True)
    gender = Column(String(20), nullable=True)
    birth_date = Column(Date, nullable=True)
    city = Column(String(100), nullable=True)
    postcode = Column(String(20), nullable=True)

    # Ticket details
    event_name = Column(String(255), nullable=False, index=True)
    event_date = Column(Date, nullable=True)
    ticket_type = Column(String(100), nullable=True)  # e.g. "Weekender", "Dagticket", "Night Ticket"
    quantity = Column(Integer, nullable=False, default=1)
    price_per_ticket = Column(Numeric(10, 2), nullable=False)
    total_price = Column(Numeric(10, 2), nullable=True)
    sale_type = Column(String(50), nullable=True)  # e.g., "Verkoop", "Ruilen"
    ticket_source = Column(String(100), nullable=True)  # e.g., "Ticketmaster"
    section = Column(String(100), nullable=True)  # Vak
    row = Column(String(50), nullable=True)
    seat_numbers = Column(String(200), nullable=True)  # NOT shown publicly

    # Verification
    proof_url = Column(String(500), nullable=True)
    agreement_accepted = Column(Boolean, default=False, nullable=False)
    verification_status = Column(
        SAEnum(VerificationStatus),
        default=VerificationStatus.UNVERIFIED,
        nullable=False,
    )
    status = Column(SAEnum(OfferStatus), default=OfferStatus.AVAILABLE, nullable=False)

    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
