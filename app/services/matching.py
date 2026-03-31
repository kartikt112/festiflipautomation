"""Buy ↔ Sell matching service."""

import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from decimal import Decimal

from app.models.sell_offer import SellOffer, OfferStatus

logger = logging.getLogger(__name__)


def _strip_ticket_type(name: str) -> str:
    """Remove parenthetical ticket-type suffix, e.g. 'Coldplay Concert (VIP-ticket)' → 'coldplay concert'."""
    import re
    return re.sub(r"\s*\(.*?\)\s*$", "", name).strip()


def _names_match(a: str, b: str) -> bool:
    """Fuzzy event name match: substring check OR significant word overlap."""
    if a in b or b in a:
        return True
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return False
    overlap = words_a & words_b
    smaller = min(len(words_a), len(words_b))
    return len(overlap) / smaller >= 0.5


async def find_matching_offers(
    db: AsyncSession,
    event_name: str,
    quantity: int = 1,
    max_price: Optional[Decimal] = None,
    ticket_type: Optional[str] = None,
    event_date: Optional[str] = None,
) -> List[SellOffer]:
    """Find available sell offers matching a buy request using AI semantic matching.

    Args:
        event_name: Event to search for
        quantity: Minimum quantity needed
        max_price: Maximum price per ticket (optional)
        ticket_type: Optional specific ticket type (e.g. "Weekend")
        event_date: Buyer's requested event date (YYYY-MM-DD) for date filtering

    Returns:
        List of matching SellOffer records, sorted by price ascending
    """
    # 1. Fetch all available offers that meet basic criteria
    query = (
        select(SellOffer)
        .where(SellOffer.status == OfferStatus.AVAILABLE)
        .where(SellOffer.quantity >= quantity)
    )

    if max_price is not None:
        query = query.where(SellOffer.price_per_ticket <= max_price)

    query = query.order_by(SellOffer.price_per_ticket.asc())
    result = await db.execute(query)
    all_offers = list(result.scalars().all())

    if not all_offers:
        return []

    # 2. Deduplicate (event_name, ticket_type, event_date) to save tokens
    unique_configs = {}
    mapped_for_ai = []

    for offer in all_offers:
        offer_date = getattr(offer, 'event_date', None)
        offer_date_str = str(offer_date) if offer_date else ""
        key = (offer.event_name.lower(), getattr(offer, 'ticket_type', ''), offer_date_str)
        if key not in unique_configs:
            ai_id = len(unique_configs) + 1
            unique_configs[key] = ai_id
            entry = {
                "id": ai_id,
                "event_name": offer.event_name,
                "ticket_type": offer.ticket_type or "Unspecified",
            }
            if offer_date_str:
                entry["event_date"] = offer_date_str
            mapped_for_ai.append(entry)

    # 3. Ask AI to find matching IDs from the unique list
    from app.ai.matcher import ai_find_matching_offer_ids
    matched_ai_ids = await ai_find_matching_offer_ids(
        buyer_event_name=event_name,
        buyer_ticket_type=ticket_type,
        available_offers=mapped_for_ai,
        buyer_event_date=event_date,
    )
    
    # 4. Filter the original offers by checking if their configuration was matched by AI
    matched_offers = []
    for offer in all_offers:
        offer_date = getattr(offer, 'event_date', None)
        offer_date_str = str(offer_date) if offer_date else ""
        key = (offer.event_name.lower(), getattr(offer, 'ticket_type', ''), offer_date_str)
        offer_ai_id = unique_configs.get(key)
        if offer_ai_id in matched_ai_ids:
            matched_offers.append(offer)

    logger.info(f"AI Matcher: Found {len(matched_offers)} offers out of {len(all_offers)} total active offers.")
    return matched_offers


async def auto_match_and_notify(
    db: AsyncSession,
    buy_request_id: int,
    event_name: str,
    quantity: int = 1,
    max_price: Optional[Decimal] = None,
    buyer_phone: Optional[str] = None,
    ticket_type: Optional[str] = None,
    event_date: Optional[str] = None,
) -> Optional[dict]:
    """Find the best match and create reservation or request seller confirmation.

    Fresh offers (≤2h): immediately create reservation with Stripe link.
    Stale offers (>2h): ask seller to confirm availability first.

    Returns dict with reservation details (incl. checkout_url), or None if no matches.
    """
    from datetime import datetime, timezone, timedelta

    matches = await find_matching_offers(db, event_name, quantity, max_price, ticket_type, event_date=event_date)

    if not matches:
        return None

    # Filter out self-matches (buyer can't buy from themselves)
    matches = [m for m in matches if m.phone != buyer_phone]
    if not matches:
        return None

    best = matches[0]  # Cheapest available

    # Check freshness – is the offer recent enough to trust availability?
    now = datetime.now(timezone.utc)
    offer_age = now - best.created_at.replace(tzinfo=timezone.utc) if best.created_at.tzinfo is None else now - best.created_at
    is_fresh = offer_age <= timedelta(hours=48)

    if is_fresh:
        # FRESH OFFER: Create reservation directly
        return await _create_direct_reservation(db, buy_request_id, best, quantity, buyer_phone)
    else:
        # STALE OFFER: Ask seller to confirm availability first
        try:
            await _request_seller_confirmation(db, buy_request_id, best, quantity, buyer_phone)
            return {"pending_confirmation": True}  # Match found but awaiting seller confirmation
        except Exception:
            # Message to seller failed – fall through to broadcast
            logger.warning(f"Seller confirmation failed for offer #{best.id}, falling back to broadcast")
            return None


async def _create_direct_reservation(
    db: AsyncSession,
    buy_request_id: int,
    offer: SellOffer,
    quantity: int,
    buyer_phone: Optional[str],
) -> Optional[dict]:
    """Create reservation directly for fresh offers (≤2h old)."""
    try:
        from app.services.reservation import create_new_reservation

        result = await create_new_reservation(
            db,
            buy_request_id=buy_request_id,
            sell_offer_id=offer.id,
            quantity=quantity,
            notify_buyer=False,  # Caller (state machine) sends its own message
        )
        logger.info(
            f"Auto-matched buyer {buyer_phone} → offer #{offer.id} "
            f"({offer.event_name}), reservation #{result['reservation_id']}"
        )
        return result

    except Exception as e:
        logger.error(f"Auto-match reservation failed: {e}")
        if buyer_phone:
            from app.services.whatsapp import send_text_message

            try:
                await send_text_message(
                    buyer_phone,
                    f"Er zijn tickets beschikbaar voor {offer.event_name}! "
                    "We regelen de betaallink voor je, een moment geduld.",
                )
            except Exception as send_err:
                logger.error(f"Failed to notify buyer about available tickets: {send_err}")
        return None


async def _request_seller_confirmation(
    db: AsyncSession,
    buy_request_id: int,
    offer: SellOffer,
    quantity: int,
    buyer_phone: Optional[str],
):
    """Ask seller to confirm they still have the ticket (for offers >2h old)."""
    from app.models.pending_confirmation import PendingConfirmation, ConfirmationStatus
    from app.services.whatsapp import send_text_message
    from app.message_templates.templates import (
        seller_availability_check,
        buyer_waiting_for_seller,
    )

    # Create pending confirmation record
    pending = PendingConfirmation(
        sell_offer_id=offer.id,
        buy_request_id=buy_request_id,
        seller_phone=offer.phone,
        buyer_phone=buyer_phone or "",
        quantity=quantity,
        status=ConfirmationStatus.PENDING,
    )
    db.add(pending)
    await db.flush()

    # Message the seller
    message_sent = False
    try:
        msg = seller_availability_check(
            event_name=offer.event_name,
            quantity=quantity,
            price_per_ticket=float(offer.price_per_ticket),
        )
        await send_text_message(offer.phone, msg)
        message_sent = True
        logger.info(f"Seller confirmation requested: {offer.phone} for offer #{offer.id}")

        # Log outbound message to chat_messages for traceability
        from app.models.chat_message import ChatMessage, MessageDirection
        db.add(ChatMessage(
            phone=offer.phone,
            direction=MessageDirection.OUTBOUND,
            body=msg,
        ))
    except Exception as e:
        logger.error(f"Failed to send seller confirmation request: {e}")
        # Roll back the pending confirmation – seller never got the message
        await db.rollback()
        raise  # Let caller know matching failed

    # Note: buyer "waiting for seller" message is sent by the state machine caller,
    # so we don't send a duplicate here.

    # Tag the seller's session so "ja"/"nee" routes through _pending_action
    try:
        from app.crud.chat_sessions import get_or_create_session, update_session
        seller_session = await get_or_create_session(db, offer.phone)
        seller_data = dict(seller_session.collected_data or {})
        seller_data["_pending_action"] = "seller_confirmation"
        await update_session(db, offer.phone, collected_data=seller_data)
    except Exception as e:
        logger.warning(f"Could not tag seller session with _pending_action: {e}")
        # Session tagging failed but message was sent — still commit the PendingConfirmation

    await db.commit()


async def handle_seller_confirmation(
    db: AsyncSession,
    seller_phone: str,
    confirmed: bool,
) -> Optional[str]:
    """Handle seller's response to an availability check.

    Args:
        db: Database session
        seller_phone: Seller's phone (E.164)
        confirmed: True if seller confirmed, False if declined

    Returns:
        Reply message for the seller, or None.
    """
    from sqlalchemy import select
    from app.models.pending_confirmation import PendingConfirmation, ConfirmationStatus
    from app.services.whatsapp import send_text_message
    from datetime import datetime, timezone

    # Find the most recent pending confirmation for this seller
    query = (
        select(PendingConfirmation)
        .where(
            PendingConfirmation.seller_phone == seller_phone,
            PendingConfirmation.status == ConfirmationStatus.PENDING,
        )
        .order_by(PendingConfirmation.created_at.desc())
        .limit(1)
    )
    result = await db.execute(query)
    pending = result.scalar_one_or_none()

    if not pending:
        return None  # No pending confirmation for this seller

    if confirmed:
        # Seller says YES – create reservation + Stripe link
        pending.status = ConfirmationStatus.CONFIRMED
        pending.resolved_at = datetime.now(timezone.utc)

        try:
            from app.services.reservation import create_new_reservation

            res_result = await create_new_reservation(
                db,
                buy_request_id=pending.buy_request_id,
                sell_offer_id=pending.sell_offer_id,
                quantity=pending.quantity,
                notify_buyer=True,  # Auto-send deposit link to buyer
            )

            await db.commit()

            logger.info(
                f"Seller {seller_phone} confirmed offer #{pending.sell_offer_id}. "
                f"Reservation created, buyer {pending.buyer_phone} notified."
            )

            return (
                "✅ Bedankt voor je bevestiging!\n\n"
                "We hebben de koper een betaallink gestuurd. "
                "Zodra de aanbetaling is betaald, ontvangt de koper jouw nummer "
                "en stuurt diegene jou een appje."
            )

        except Exception as e:
            logger.error(f"Failed to create reservation after seller confirmation: {e}")
            # Rollback the confirmation status change since reservation failed
            await db.rollback()
            return (
                "Er ging iets mis bij het aanmaken van de reservering. "
                "Ons team kijkt ernaar. 🙏"
            )

    else:
        # Seller says NO – mark declined, notify buyer
        pending.status = ConfirmationStatus.DECLINED
        pending.resolved_at = datetime.now(timezone.utc)

        # Notify buyer the seller's ticket is no longer available
        buyer_notified = False
        if pending.buyer_phone:
            try:
                from app.crud.sell_offers import get_sell_offer
                offer = await get_sell_offer(db, pending.sell_offer_id)
                event_name = offer.event_name if offer else "het evenement"

                await send_text_message(
                    pending.buyer_phone,
                    f"Helaas, de verkoper heeft bevestigd dat de tickets voor "
                    f"{event_name} niet meer beschikbaar zijn. 😔\n\n"
                    "We blijven zoeken en laten je weten zodra er nieuwe tickets zijn!"
                )
                buyer_notified = True
            except Exception as e:
                logger.error(f"Failed to notify buyer about declined confirmation: {e}")

        await db.commit()

        if not buyer_notified and pending.buyer_phone:
            logger.warning(f"Buyer {pending.buyer_phone} was NOT notified about declined offer #{pending.sell_offer_id}")

        return (
            "Bedankt voor je eerlijke antwoord! 👍\n\n"
            "We hebben je aanbod bijgewerkt. Als je later weer tickets wilt verkopen, "
            "stuur ons dan gerust een berichtje."
        )


async def process_waitlist(db: AsyncSession, sell_offer: SellOffer):
    """Check if any waiting buy requests match this new sell offer."""
    from app.models.buy_request import BuyRequest, BuyStatus
    from app.services.reservation import create_new_reservation
    from app.services.whatsapp import send_text_message
    from app.message_templates.templates import waitlist_match_message

    logger.info(f"Processing waitlist for new offer #{sell_offer.id}: {sell_offer.event_name}")

    query = (
        select(BuyRequest)
        .where(
            BuyRequest.status == BuyStatus.WAITING,
            BuyRequest.quantity <= sell_offer.quantity,
        )
        .order_by(BuyRequest.created_at.asc())
    )
    
    result = await db.execute(query)
    waiting_requests = result.scalars().all()

    offer_name_lower = sell_offer.event_name.lower()
    offer_base = _strip_ticket_type(offer_name_lower)
    matches = []

    for req in waiting_requests:
        # Skip if buyer is the same person as the seller
        if req.phone == sell_offer.phone:
            logger.info(f"Skipping req #{req.id}: same phone as seller ({req.phone})")
            continue

        req_name_lower = req.event_name.lower()
        req_base = _strip_ticket_type(req_name_lower)
        if _names_match(req_base, offer_base):
            # Date filter: if both have dates, they must match
            if req.event_date and sell_offer.event_date and req.event_date != sell_offer.event_date:
                logger.info(f"Skipping req #{req.id}: date {req.event_date} != offer date {sell_offer.event_date}")
                continue

            # Price filter: skip if buyer's max price is below seller's price
            if req.max_price_per_ticket and req.max_price_per_ticket < sell_offer.price_per_ticket:
                logger.info(f"Skipping req #{req.id}: max_price {req.max_price_per_ticket} < offer price {sell_offer.price_per_ticket}")
                continue
            
            # Ticket type filter: if both specify a type, they should match
            if req.ticket_type and sell_offer.ticket_type:
                if req.ticket_type.lower() != sell_offer.ticket_type.lower():
                    logger.info(f"Skipping req #{req.id}: ticket_type '{req.ticket_type}' != '{sell_offer.ticket_type}'")
                    continue
            
            matches.append(req)

    logger.info(f"Found {len(matches)} potential waitlist matches.")

    current_quantity: int = int(sell_offer.quantity)
    
    for req in matches:
        if current_quantity < req.quantity:
            continue
        
        # Re-check offer availability (may have been reserved by earlier iteration)
        await db.refresh(sell_offer)
        if sell_offer.status != OfferStatus.AVAILABLE:
            logger.info(f"Offer #{sell_offer.id} is no longer AVAILABLE (status={sell_offer.status}), stopping waitlist.")
            break
            
        try:
            res_result = await create_new_reservation(
                db,
                buy_request_id=req.id,
                sell_offer_id=sell_offer.id,
                quantity=req.quantity,
                notify_buyer=False,
            )
            
            msg = waitlist_match_message(
                event_name=sell_offer.event_name,
                deposit_amount=res_result["deposit_amount"],
                checkout_url=res_result["checkout_url"],
            )
            await send_text_message(req.phone, msg)
            logger.info(f"Waitlist match: buyer {req.phone} notified for {sell_offer.event_name}")
            
            current_quantity = int(current_quantity) - int(req.quantity)
            if current_quantity <= 0:
                break
                
        except Exception as e:
            logger.error(f"Failed to process waitlist match for req #{req.id}: {e}")

