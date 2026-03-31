"""Escalation service – notify the platform owner when buyers face issues."""

import logging
from app.config import settings
from app.services.whatsapp import send_text_message
from app.message_templates.templates import (
    escalation_entrance_blocked_owner,
    escalation_missing_proof_owner,
)

logger = logging.getLogger(__name__)


async def escalate_entrance_blocked(buyer_phone: str, event_name: str = "") -> bool:
    """Send escalation to owner when a buyer can't enter the event.

    Args:
        buyer_phone: The buyer's phone number (E.164)
        event_name: Optional event name for context

    Returns:
        True if alert was sent successfully
    """
    owner = settings.OWNER_PHONE
    if not owner:
        logger.warning("OWNER_PHONE not configured – skipping entrance escalation")
        return False

    message = escalation_entrance_blocked_owner(buyer_phone, event_name)

    try:
        await send_text_message(owner, message)
        logger.info(f"Entrance escalation sent to owner for buyer {buyer_phone}")
        return True
    except Exception as e:
        logger.error(f"Entrance escalation failed: {e}")
        return False


async def escalate_missing_proof(buyer_phone: str, details: str = "") -> bool:
    """Send escalation to owner when a buyer reports missing proof/payment info.

    Triggered when the seller is not sharing proof of payment, proof of ticket
    ownership, email address, or other necessary verification info.

    Args:
        buyer_phone: The buyer's phone number (E.164)
        details: Additional context from the buyer's message

    Returns:
        True if alert was sent successfully
    """
    owner = settings.OWNER_PHONE
    if not owner:
        logger.warning("OWNER_PHONE not configured – skipping proof escalation")
        return False

    message = escalation_missing_proof_owner(buyer_phone, details)

    try:
        await send_text_message(owner, message)
        logger.info(f"Missing-proof escalation sent to owner for buyer {buyer_phone}")
        return True
    except Exception as e:
        logger.error(f"Missing-proof escalation failed: {e}")
        return False
