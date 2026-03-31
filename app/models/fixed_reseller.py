"""Fixed Reseller model – permanent reseller records from legacy system."""

from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func

from app.database import Base


class FixedReseller(Base):
    __tablename__ = "fixed_resellers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    phone = Column(String(20), nullable=True, unique=True)
    pricing_model = Column(String(200), nullable=True)
    notes = Column(String(1000), nullable=True)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
