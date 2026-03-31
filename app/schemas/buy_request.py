"""Pydantic schemas for buy requests."""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import date, datetime
from decimal import Decimal


class BuyRequestCreate(BaseModel):
    first_name: str
    last_name: Optional[str] = None
    phone: str
    email: Optional[str] = None
    instagram: Optional[str] = None
    gender: Optional[str] = None
    birth_date: Optional[date] = None
    city: Optional[str] = None
    postcode: Optional[str] = None
    event_name: str
    event_date: Optional[date] = None
    ticket_type: Optional[str] = None
    quantity: int = Field(ge=1, default=1)
    max_price_per_ticket: Optional[Decimal] = None
    agreement_accepted: bool = False
    source: str = "WHATSAPP"


class BuyRequestResponse(BaseModel):
    id: int
    first_name: str
    last_name: Optional[str] = None
    phone: str
    event_name: str
    event_date: Optional[date] = None
    ticket_type: Optional[str] = None
    quantity: int
    max_price_per_ticket: Optional[Decimal] = None
    source: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
