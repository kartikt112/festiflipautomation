"""Reservation lifecycle service – create, expire, complete."""

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.crud import sell_offers as sell_crud
from app.crud import buy_requests as buy_crud
from app.crud import reservations as res_crud
from app.crud import payments as pay_crud
from app.models.sell_offer import OfferStatus
from app.models.buy_request import BuyStatus
from app.models.reservation import ReservationStatus
from app.models.payment import PaymentStatus
from app.services.deposit import calculate_deposit
from app.services.stripe_service import create_deposit_session
from app.services.whatsapp import send_text_message
from app.message_templates.templates import (
    deposit_payment_message,
    payment_received_message,
    reservation_expired_message,
    seller_buyer_found_message,
)

logger = logging.getLogger(__name__)


async def create_new_reservation(
    db: AsyncSession,
    buy_request_id: int,
    sell_offer_id: int,
    quantity: int = 1,
    notify_buyer: bool = True,
) -> dict:
    """Create a reservation with deposit calculation and Stripe session.

    Flow:
    1. Validate offer is AVAILABLE
    2. Calculate deposit (7.5%, min €5)
    3. Lock the offer (set to RESERVED)
    4. Create Stripe Checkout session
    5. Create reservation record
    6. Send deposit link to buyer via WhatsApp

    Returns:
        dict with reservation details and Stripe checkout URL
    """
    # 1. Get and validate offer
    offer = await sell_crud.get_sell_offer(db, sell_offer_id)
    if not offer or offer.status != OfferStatus.AVAILABLE:
        raise ValueError("Offer is not available")

    if quantity > offer.quantity:
        raise ValueError(f"Requested {quantity} tickets but only {offer.quantity} available")

    # Get buy request
    buy_request = await buy_crud.get_buy_request(db, buy_request_id)
    if not buy_request:
        raise ValueError("Buy request not found")

    # 2. Calculate deposit
    deposit = calculate_deposit(offer.price_per_ticket, quantity)

    # 3. Lock the offer
    await sell_crud.update_offer_status(db, sell_offer_id, OfferStatus.RESERVED)
    await buy_crud.update_request_status(db, buy_request_id, BuyStatus.MATCHED)

    # 4. Create Stripe session
    stripe_result = await create_deposit_session(
        reservation_id=0,  # Will update after creation
        deposit_amount=float(deposit.deposit_amount),
        event_name=offer.event_name,
        buyer_email=buy_request.email,
    )

    # 5. Create reservation
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.RESERVATION_TIMEOUT_MINUTES
    )

    reservation = await res_crud.create_reservation(
        db,
        buy_request_id=buy_request_id,
        sell_offer_id=sell_offer_id,
        quantity=quantity,
        deposit_amount=deposit.deposit_amount,
        remaining_amount=deposit.remaining_amount,
        minimum_applied=deposit.minimum_applied,
        stripe_session_id=stripe_result["session_id"],
        stripe_checkout_url=stripe_result["checkout_url"],
        status=ReservationStatus.PENDING,
        expires_at=expires_at,
    )

    # Create pending payment record
    await pay_crud.create_payment(
        db,
        reservation_id=reservation.id,
        deposit_amount=deposit.deposit_amount,
        minimum_applied=deposit.minimum_applied,
        stripe_session_id=stripe_result["session_id"],
        status=PaymentStatus.PENDING,
    )

    # 6. Send deposit link to buyer (skip if caller will send its own message)
    if notify_buyer:
        try:
            message = deposit_payment_message(
                deposit_amount=deposit.deposit_amount,
                remaining_amount=deposit.remaining_amount,
                stripe_link=stripe_result["checkout_url"],
            )
            await send_text_message(buy_request.phone, message)
        except Exception as e:
            logger.error(f"Failed to send WhatsApp deposit link to {buy_request.phone}: {e}")
            # Rollback – buyer never got the payment link, so reservation is useless
            await db.rollback()
            raise RuntimeError(f"Reservation created but buyer notification failed: {e}") from e

    await db.commit()

    return {
        "reservation_id": reservation.id,
        "deposit_amount": float(deposit.deposit_amount),
        "remaining_amount": float(deposit.remaining_amount),
        "minimum_applied": deposit.minimum_applied,
        "checkout_url": stripe_result["checkout_url"],
        "expires_at": reservation.expires_at.isoformat(),
    }


async def complete_reservation(
    db: AsyncSession,
    reservation_id: int,
    stripe_payment_intent_id: str,
    webhook_event_id: str,
) -> bool:
    """Complete a reservation after successful Stripe payment.

    Flow:
    1. Check idempotency (has this event been processed?)
    2. Mark reservation as PAID
    3. Mark offer as SOLD
    4. Record payment
    5. Send seller contact to buyer via WhatsApp

    Returns:
        True if processed, False if duplicate
    """
    # 1. Idempotency check
    existing = await pay_crud.get_payment_by_webhook_event(db, webhook_event_id)
    if existing:
        logger.info(f"Duplicate webhook event {webhook_event_id}, skipping")
        return False

    # 2. Mark reservation as PAID
    reservation = await res_crud.mark_reservation_paid(db, reservation_id)
    if not reservation:
        raise ValueError(f"Reservation {reservation_id} not found")

    # 3. Update offer status
    await sell_crud.update_offer_status(
        db, reservation.sell_offer_id, OfferStatus.SOLD
    )

    # 4. Update payment record
    payment = await pay_crud.get_payment_by_reservation(db, reservation_id)
    if payment:
        payment.status = PaymentStatus.COMPLETED
        payment.stripe_payment_intent_id = stripe_payment_intent_id
        payment.webhook_event_id = webhook_event_id
        await db.flush()

    # 5. Send seller contact to buyer + notify seller with calculation
    seller_contact_sent = False
    try:
        offer = await sell_crud.get_sell_offer(db, reservation.sell_offer_id)
        buy_request = await buy_crud.get_buy_request(db, reservation.buy_request_id)

        if offer and buy_request:
            # 5a. Send seller contact to buyer
            message = payment_received_message(
                seller_name=f"{offer.first_name} {offer.last_name or ''}".strip(),
                seller_phone=offer.phone,
            )
            await send_text_message(buy_request.phone, message)
            seller_contact_sent = True

            # 5b. Notify seller: buyer found + calculation
            try:
                seller_msg = seller_buyer_found_message(
                    event_name=offer.event_name,
                    price_per_ticket=float(offer.price_per_ticket),
                    quantity=reservation.quantity,
                )
                await send_text_message(offer.phone, seller_msg)
                logger.info(f"Seller {offer.phone} notified about buyer for {offer.event_name}")
            except Exception as seller_err:
                logger.error(f"Failed to notify seller {offer.phone}: {seller_err}")
    except Exception as e:
        logger.error(f"Failed to send seller contact to buyer: {e}")

    await db.commit()

    if not seller_contact_sent:
        logger.critical(
            f"PAYMENT COMPLETED but seller contact NOT sent for reservation #{reservation_id}. "
            "Manual follow-up required!"
        )

    return True


async def expire_pending_reservations(db: AsyncSession) -> int:
    """Expire all reservations past their timeout.

    Returns:
        Number of expired reservations
    """
    expired = await res_crud.get_expired_reservations(db)
    count = 0

    for reservation in expired:
        # Return offer to available
        await sell_crud.update_offer_status(
            db, reservation.sell_offer_id, OfferStatus.AVAILABLE
        )

        # Mark reservation expired
        await res_crud.mark_reservation_expired(db, reservation.id)

        # Notify buyer
        try:
            buy_request = await buy_crud.get_buy_request(db, reservation.buy_request_id)
            if buy_request:
                message = reservation_expired_message()
                await send_text_message(buy_request.phone, message)
        except Exception as e:
            logger.error(f"Failed to send expiry notification for reservation #{reservation.id} to buyer: {e}")

        count += 1

    if count > 0:
        await db.commit()
        logger.info(f"Expired {count} reservations")

    return count
