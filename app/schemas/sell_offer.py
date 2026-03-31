"""Pydantic schemas for sell offers."""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import date, datetime
from decimal import Decimal


class SellOfferCreate(BaseModel):
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
    price_per_ticket: Decimal = Field(ge=0)
    total_price: Optional[Decimal] = None
    sale_type: Optional[str] = None
    ticket_source: Optional[str] = None
    section: Optional[str] = None
    row: Optional[str] = None
    seat_numbers: Optional[str] = None
    proof_url: Optional[str] = None
    agreement_accepted: bool = False


class SellOfferResponse(BaseModel):
    id: int
    first_name: str
    last_name: Optional[str] = None
    phone: str
    event_name: str
    event_date: Optional[date] = None
    ticket_type: Optional[str] = None
    quantity: int
    price_per_ticket: Decimal
    total_price: Optional[Decimal] = None
    section: Optional[str] = None
    row: Optional[str] = None
    verification_status: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SellOfferPublic(BaseModel):
    """Public listing – no personal info, no exact seats (compliance)."""
    id: int
    event_name: str
    event_date: Optional[date] = None
    ticket_type: Optional[str] = None
    quantity: int
    price_per_ticket: Decimal
    section: Optional[str] = None
    status: str

    model_config = {"from_attributes": True}
