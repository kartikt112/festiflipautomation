"""Pydantic schemas for reservations and payments."""

from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from decimal import Decimal


class ReservationCreate(BaseModel):
    buy_request_id: int
    sell_offer_id: int
    quantity: int = 1


class ReservationResponse(BaseModel):
    id: int
    buy_request_id: int
    sell_offer_id: int
    quantity: int
    deposit_amount: Decimal
    remaining_amount: Decimal
    minimum_applied: bool
    stripe_session_id: Optional[str] = None
    stripe_checkout_url: Optional[str] = None
    status: str
    expires_at: datetime
    paid_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PaymentResponse(BaseModel):
    id: int
    reservation_id: int
    deposit_amount: Decimal
    minimum_applied: bool
    stripe_session_id: Optional[str] = None
    stripe_payment_intent_id: Optional[str] = None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class DepositCalculation(BaseModel):
    """Result of deposit calculation."""
    price_per_ticket: Decimal
    quantity: int
    gross_deposit: Decimal      # 7.5% of total
    deposit_amount: Decimal     # max(gross_deposit, min_per_ticket * qty)
    remaining_amount: Decimal   # total - deposit
    minimum_applied: bool       # True if €5 minimum was used
    total_price: Decimal
