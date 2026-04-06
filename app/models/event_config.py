"""Event configuration model – admin-managed price rules and edition settings per event."""

from sqlalchemy import Column, Integer, String, Boolean, Date, Numeric, DateTime
from sqlalchemy.sql import func

from app.database import Base


class EventConfig(Base):
    __tablename__ = "event_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Fuzzy match key — partial name like "DGTL", "Thuishaven", "Fanta"
    event_keyword = Column(String(255), nullable=False, index=True)

    # Optional date for events with multiple editions (e.g. DGTL Saturday vs Sunday)
    event_date = Column(Date, nullable=True)

    # Price boundaries (nullable = no limit on that side)
    min_price = Column(Numeric(10, 2), nullable=True)
    max_price = Column(Numeric(10, 2), nullable=True)

    # FEATURE 10: Does this event have multiple editions that need to be asked?
    ask_edition = Column(Boolean, default=False, nullable=False, server_default="0")

    # Admin notes
    notes = Column(String(500), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
