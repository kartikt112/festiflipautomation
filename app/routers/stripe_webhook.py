"""Stripe webhook router – handles payment confirmations."""

import logging
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.stripe_service import verify_webhook_signature
from app.services.reservation import complete_reservation
from app.crud.reservations import get_reservation_by_stripe_session
from app.models.webhook_log import WebhookLog

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["Stripe"])


@router.post("/stripe")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle Stripe webhook events.

    Primary event: checkout.session.completed
    Flow: verify signature → check idempotency → mark paid → release seller contact
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    # Log the webhook
    webhook_log = WebhookLog(
        source="stripe",
        status="received",
    )
    db.add(webhook_log)

    try:
        # Verify signature (fraud prevention)
        event = verify_webhook_signature(payload, sig_header)

        webhook_log.event_type = event.get("type", "")
        webhook_log.event_id = event.get("id", "")
        webhook_log.payload = event

    except Exception as e:
        logger.error(f"Stripe signature verification failed: {e}")
        await db.rollback()
        # Log failure in clean transaction
        error_log = WebhookLog(
            source="stripe",
            status="signature_failed",
            error_message=str(e)[:1000],
        )
        db.add(error_log)
        await db.commit()
        raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        event_type = event.get("type", "")

        if event_type == "checkout.session.completed":
            session_data = event["data"]["object"]
            stripe_session_id = session_data["id"]
            payment_intent_id = session_data.get("payment_intent", "")
            event_id = event["id"]

            # Find reservation
            reservation = await get_reservation_by_stripe_session(db, stripe_session_id)
            if not reservation:
                logger.warning(f"No reservation for Stripe session {stripe_session_id}")
                webhook_log.status = "no_reservation"
                await db.commit()
                return {"status": "ok"}

            # Complete the reservation (idempotent)
            processed = await complete_reservation(
                db,
                reservation_id=reservation.id,
                stripe_payment_intent_id=payment_intent_id,
                webhook_event_id=event_id,
            )

            webhook_log.status = "processed" if processed else "duplicate"
            logger.info(
                f"Stripe payment {'processed' if processed else 'duplicate'} "
                f"for reservation {reservation.id}"
            )

        else:
            # Log but don't process other event types
            webhook_log.status = "ignored"
            logger.info(f"Ignoring Stripe event type: {event_type}")

        await db.commit()
        return {"status": "ok"}

    except Exception as e:
        logger.error(f"Stripe webhook processing error: {e}", exc_info=True)
        await db.rollback()
        # Log error in clean transaction
        error_log = WebhookLog(
            source="stripe",
            event_type=event.get("type", ""),
            event_id=event.get("id", ""),
            status="error",
            error_message=str(e)[:1000],
        )
        db.add(error_log)
        await db.commit()
        raise HTTPException(status_code=500, detail="Processing failed")
