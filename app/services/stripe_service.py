"""Stripe integration service – deposit-only Checkout sessions."""

import asyncio
import stripe
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

# Configure Stripe
stripe.api_key = settings.STRIPE_SECRET_KEY


async def create_deposit_session(
    reservation_id: int,
    deposit_amount: float,
    event_name: str,
    buyer_email: Optional[str] = None,
) -> dict:
    """Create a Stripe Checkout session for the deposit payment.

    Args:
        reservation_id: Internal reservation ID
        deposit_amount: Amount in EUR (deposit only, NOT full ticket price)
        event_name: Event name for the line item description
        buyer_email: Optional email to prefill

    Returns:
        dict with 'session_id' and 'checkout_url'
    """
    try:
        session_params = {
            "payment_method_types": ["ideal", "card"],
            "line_items": [
                {
                    "price_data": {
                        "currency": "eur",
                        "unit_amount": int(deposit_amount * 100),  # Stripe uses cents
                        "product_data": {
                            "name": "Ticket aanbetaling",
                            "description": f"Aanbetaling voor {event_name}",
                        },
                    },
                    "quantity": 1,
                },
            ],
            "mode": "payment",
            "success_url": f"{settings.STRIPE_SUCCESS_URL}?session_id={{CHECKOUT_SESSION_ID}}",
            "cancel_url": settings.STRIPE_CANCEL_URL,
            "metadata": {
                "reservation_id": str(reservation_id),
                "type": "deposit",
            },
            "expires_at": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),  # 1 hour to match reservation timeout
        }

        if buyer_email:
            session_params["customer_email"] = buyer_email

        session = await asyncio.to_thread(stripe.checkout.Session.create, **session_params)

        logger.info(
            f"Stripe session created: {session.id} for reservation {reservation_id}"
        )

        return {
            "session_id": session.id,
            "checkout_url": session.url,
        }

    except stripe.StripeError as e:
        logger.error(f"Stripe error creating session: {e}")
        raise


def verify_webhook_signature(payload: bytes, sig_header: str) -> dict:
    """Verify and parse a Stripe webhook event.

    Args:
        payload: Raw request body
        sig_header: Stripe-Signature header

    Returns:
        Parsed event dict

    Raises:
        stripe.SignatureVerificationError: If signature is invalid
    """
    event = stripe.Webhook.construct_event(
        payload,
        sig_header,
        settings.STRIPE_WEBHOOK_SECRET,
    )
    return event


async def create_refund(payment_intent_id: str, reason: str = "requested_by_customer") -> dict:
    """Create a refund for a payment.

    Args:
        payment_intent_id: Stripe PaymentIntent ID
        reason: Refund reason

    Returns:
        Refund object
    """
    try:
        refund = await asyncio.to_thread(
            stripe.Refund.create,
            payment_intent=payment_intent_id,
            reason=reason,
        )
        logger.info(f"Refund created: {refund.id} for {payment_intent_id}")
        return refund
    except stripe.StripeError as e:
        logger.error(f"Stripe refund error: {e}")
        raise
