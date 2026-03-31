"""Broadcast service — notify subscribers when new tickets are listed."""

import asyncio
import logging
from typing import List
from decimal import Decimal

from app.config import settings
from app.services.whatsapp import send_text_message
from app.message_templates.templates import broadcast_listing_message

logger = logging.getLogger(__name__)


def get_broadcast_numbers() -> List[str]:
    """Parse BROADCAST_NUMBERS from config into a list of phone numbers."""
    raw = settings.BROADCAST_NUMBERS.strip()
    if not raw:
        return []
    return [n.strip() for n in raw.split(",") if n.strip()]


async def broadcast_new_listing(
    event_name: str,
    quantity: int,
    price_per_ticket: Decimal,
    seller_phone: str = "",
) -> int:
    """Send a new listing notification to all broadcast subscribers.

    Args:
        event_name: Name of the event
        quantity: Number of tickets available
        price_per_ticket: Price per ticket in EUR
        seller_phone: Seller's phone (excluded from broadcast — they already know)

    Returns:
        Number of messages successfully sent
    """
    numbers = get_broadcast_numbers()
    if not numbers:
        logger.info("No broadcast numbers configured, skipping notification")
        return 0

    # Don't send the broadcast to the seller themselves
    numbers = [n for n in numbers if n != seller_phone and n != seller_phone.lstrip("+")]

    message = broadcast_listing_message(
        event_name=event_name,
        quantity=quantity,
        price_per_ticket=price_per_ticket,
    )

    sent = 0
    for phone in numbers:
        try:
            # Ensure phone has + prefix
            if not phone.startswith("+"):
                phone = f"+{phone}"
            await send_text_message(phone, message)
            sent += 1
            logger.info(f"Broadcast sent to {phone}")
        except Exception as e:
            logger.error(f"Broadcast to {phone} failed: {e}")

    logger.info(f"Broadcast complete: {sent}/{len(numbers)} messages sent")
    return sent

async def broadcast_buy_request(
    event_name: str,
    event_date: str,
    quantity: int,
    requester_phone: str = "",
) -> int:
    """Send a 'searching for tickets' notification to all broadcast subscribers."""
    from app.message_templates.templates import searching_broadcast
    
    numbers = get_broadcast_numbers()
    if not numbers:
        return 0

    # formatting the template
    message = searching_broadcast(
        event_name=event_name,
        event_date=event_date,
        quantity=quantity,
    )

    sent = 0
    # Filter out requester if they happen to be in the list (unlikely but safe)
    recipients = [n for n in numbers if n != requester_phone]

    for phone in recipients:
        try:
             # Ensure phone has + prefix if missing (though config should have it)
            target = phone if phone.startswith("+") else f"+{phone}"
            await send_text_message(target, message)
            sent += 1
            logger.info(f"Search broadcast sent to {target}")
        except Exception as e:
            logger.error(f"Search broadcast to {phone} failed: {e}")

    return sent
