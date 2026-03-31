"""Buy Request model – maps to the Buy Form Responses (Zoeken naar Tickets)."""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Numeric, Date, Enum as SAEnum
from sqlalchemy.sql import func
import enum

from app.database import Base


class BuySource(str, enum.Enum):
    FORM = "FORM"
    WHATSAPP = "WHATSAPP"


class BuyStatus(str, enum.Enum):
    WAITING = "WAITING"
    MATCHED = "MATCHED"
    EXPIRED = "EXPIRED"


class BuyRequest(Base):
    __tablename__ = "buy_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), nullable=True)  # Original form timestamp

    # Personal info (maps to Buy Form)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=True)
    phone = Column(String(20), nullable=False, index=True)  # E.164
    email = Column(String(255), nullable=True)
    instagram = Column(String(100), nullable=True)
    gender = Column(String(20), nullable=True)
    birth_date = Column(Date, nullable=True)
    city = Column(String(100), nullable=True)
    postcode = Column(String(20), nullable=True)

    # Ticket request details
    event_name = Column(String(255), nullable=False, index=True)
    event_date = Column(Date, nullable=True)
    ticket_type = Column(String(100), nullable=True)  # e.g. "Weekender", "Dagticket", "Night Ticket"
    quantity = Column(Integer, nullable=False, default=1)
    max_price_per_ticket = Column(Numeric(10, 2), nullable=True)

    # Metadata
    agreement_accepted = Column(Boolean, default=False, nullable=False)
    source = Column(SAEnum(BuySource), default=BuySource.WHATSAPP, nullable=False)
    status = Column(SAEnum(BuyStatus), default=BuyStatus.WAITING, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
