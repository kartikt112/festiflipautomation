"""Deposit calculation service.

Commission rules:
  - 7.5% of ticket price per ticket
  - Minimum €5 per ticket
  - Deposit = max(7.5% * price * qty, €5 * qty)
"""

from decimal import Decimal, ROUND_HALF_UP
from app.schemas.reservation import DepositCalculation

COMMISSION_RATE = Decimal("0.075")
MINIMUM_PER_TICKET = Decimal("5.00")


def calculate_deposit(price_per_ticket: Decimal, quantity: int) -> DepositCalculation:
    """Calculate the deposit amount following FestiFlip commission rules.

    Args:
        price_per_ticket: Price per ticket in EUR
        quantity: Number of tickets

    Returns:
        DepositCalculation with all financial details
    """
    price = Decimal(str(price_per_ticket))
    qty = Decimal(str(quantity))
    total_price = price * qty

    # 7.5% of total
    gross_deposit = (total_price * COMMISSION_RATE).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    # Minimum €5 per ticket
    minimum_total = MINIMUM_PER_TICKET * qty

    # Apply the higher of the two
    minimum_applied = gross_deposit < minimum_total
    deposit_amount = max(gross_deposit, minimum_total)

    # Cap deposit at total price — buyer should never pay more than the ticket costs
    if deposit_amount > total_price:
        deposit_amount = total_price
        minimum_applied = True

    remaining_amount = total_price - deposit_amount

    return DepositCalculation(
        price_per_ticket=price,
        quantity=quantity,
        gross_deposit=gross_deposit,
        deposit_amount=deposit_amount,
        remaining_amount=remaining_amount,
        minimum_applied=minimum_applied,
        total_price=total_price,
    )
