"""WhatsApp webhook router – receives and processes inbound messages."""

import logging
from fastapi import APIRouter, Request, HTTPException, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.ai.state_machine import process_message
from app.services.whatsapp import (
    send_text_message, mark_as_read,
    download_media, download_media_content,
)
from app.models.webhook_log import WebhookLog
from app.models.chat_message import ChatMessage, MessageDirection

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["WhatsApp"])


@router.get("/whatsapp")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """WhatsApp webhook verification endpoint (GET)."""
    if hub_mode == "subscribe" and hub_verify_token == settings.WHATSAPP_VERIFY_TOKEN:
        logger.info("WhatsApp webhook verified")
        return int(hub_challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/whatsapp")
async def receive_message(request: Request, db: AsyncSession = Depends(get_db)):
    """WhatsApp webhook receiver (POST) – processes inbound messages."""
    body = await request.json()

    # Log the webhook
    webhook_log = WebhookLog(
        source="whatsapp",
        event_type="message",
        payload=body,
        status="received",
    )
    db.add(webhook_log)

    try:
        # Extract message data from Meta's webhook format
        entry = body.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            # Not a message event (could be status update)
            return {"status": "ok"}

        message_data = messages[0]
        phone = message_data.get("from", "")
        message_id = message_data.get("id", "")
        message_type = message_data.get("type", "")

        # Extract WhatsApp push name (profile name) for display
        contacts = value.get("contacts", [])
        push_name = contacts[0].get("profile", {}).get("name", "") if contacts else ""

        if not phone:
            return {"status": "ok"}

        # Mark as read
        try:
            await mark_as_read(message_id)
        except Exception as e:
            logger.debug(f"Failed to mark message {message_id} as read: {e}")

        # Format phone to E.164
        if not phone.startswith("+"):
            phone = f"+{phone}"

        # Handle IMAGE messages – extract ticket data via Vision AI
        if message_type == "image":
            # Log inbound image
            db.add(ChatMessage(phone=phone, direction=MessageDirection.INBOUND, body="[📷 Afbeelding]", message_type="image"))
            reply = await _handle_image_message(db, phone, message_data)
            if reply:
                db.add(ChatMessage(phone=phone, direction=MessageDirection.OUTBOUND, body=reply))
                await send_text_message(phone, reply)
            webhook_log.status = "processed"
            await db.commit()
            return {"status": "ok"}

        # Handle TEXT messages
        if message_type != "text":
            logger.info(f"Ignoring unsupported message type: {message_type}")
            return {"status": "ok"}

        text = message_data.get("text", {}).get("body", "")
        if not text:
            return {"status": "ok"}

        # Detect forwarded messages (Meta includes context.forwarded or context.frequently_forwarded)
        context = message_data.get("context", {})
        is_forwarded = context.get("forwarded", False) or context.get("frequently_forwarded", False)
        if is_forwarded:
            text = f"[Doorgestuurd] {text}"
            logger.info(f"Forwarded message detected from {phone}")

        # Log inbound message
        db.add(ChatMessage(phone=phone, direction=MessageDirection.INBOUND, body=text))

        # Fetch or create session to pass to router
        from app.crud.chat_sessions import get_or_create_session
        session = await get_or_create_session(db, phone)

        if settings.USE_AI_ROUTER:
            from app.ai.agent_router import process_message as ai_process
            reply = await ai_process(db, session, phone, text)
        else:
            # Legacy State Machine
            from app.ai.state_machine import process_message as legacy_process
            reply = await legacy_process(db, phone, text, push_name=push_name)

        # Send reply and log outbound
        if reply:
            db.add(ChatMessage(phone=phone, direction=MessageDirection.OUTBOUND, body=reply))
            await send_text_message(phone, reply)

        webhook_log.status = "processed"
        await db.commit()

        return {"status": "ok"}

    except Exception as e:
        logger.error(f"WhatsApp webhook error: {e}", exc_info=True)
        # Rollback any partial state from failed processing
        await db.rollback()
        # Log the error in a clean transaction
        error_log = WebhookLog(
            source="whatsapp",
            event_type="message",
            status="error",
            error_message=str(e)[:1000],
        )
        db.add(error_log)
        await db.commit()
        return {"status": "error"}


async def _handle_image_message(
    db: AsyncSession, phone: str, message_data: dict
) -> str:
    """Process an incoming image message – extract ticket data via Vision AI.

    Flow:
    1. Download the image from WhatsApp Media API
    2. Run GPT-4o vision extraction
    3. If data found: inject into state machine as SELL_OFFER (confirm or collect)
    4. If no data: ask the user to describe the ticket in text
    """
    from app.ai.vision_extractor import extract_ticket_from_base64
    from app.crud.chat_sessions import update_session, get_or_create_session
    from app.ai.extractor import validate_entities

    # Check if this might be a payment proof screenshot
    session = await get_or_create_session(db, phone)
    session_data = session.collected_data or {}
    pending_action = session_data.get("_pending_action", "")
    caption_lower = (message_data.get("image", {}).get("caption", "") or "").lower()

    # If buyer just completed a purchase, or caption mentions "betaald"/"payment"
    is_payment_context = (
        pending_action in ("undo_buy",)
        or "betaald" in caption_lower or "betaling" in caption_lower
        or "payment" in caption_lower or "bewijs" in caption_lower
    )
    if is_payment_context:
        return (
            "Bedankt voor je betaalbewijs! 📸\n\n"
            "Als je via onze betaallink hebt betaald, ontvang je automatisch "
            "de contactgegevens van de verkoper zodra de betaling is bevestigd.\n\n"
            "Heb je op een andere manier betaald? Neem dan contact op met ons team."
        )

    image_data = message_data.get("image", {})
    media_id = image_data.get("id")
    caption = image_data.get("caption", "")

    if not media_id:
        return "Sorry, ik kon de afbeelding niet verwerken. Stuur het opnieuw of beschrijf je ticket in tekst."

    # Step 1: Get the download URL
    media_url = await download_media(media_id)
    if not media_url:
        return "Sorry, ik kon de afbeelding niet downloaden. Probeer het opnieuw."

    # Step 2: Download the image content
    image_base64 = await download_media_content(media_url)
    if not image_base64:
        return "Sorry, ik kon de afbeelding niet laden. Probeer het opnieuw."

    # Step 3: Extract ticket data using Vision AI
    extracted = await extract_ticket_from_base64(image_base64)

    if not extracted:
        return (
            "Ik kon geen ticketgegevens herkennen in deze afbeelding. 🤔\n\n"
            "Kun je de gegevens van je ticket beschrijven? Bijvoorbeeld:\n"
            "- Evenement naam\n"
            "- Datum\n"
            "- Prijs per ticket\n"
            "- Aantal tickets"
        )

    # Step 4: Inject extracted data into state machine as SELL_OFFER
    logger.info(f"Vision extracted ticket data for {phone}: {extracted}")

    # Map vision output to state machine format
    collected = {
        "event_name": extracted.get("event_name"),
        "event_date": extracted.get("event_date"),
        "ticket_type": extracted.get("ticket_type"),
        "quantity": extracted.get("quantity", 1),
        "price_per_ticket": extracted.get("price_per_ticket"),
    }
    # Remove None values
    collected = {k: v for k, v in collected.items() if v is not None}

    # Check what's missing
    missing = validate_entities("SELL_OFFER", collected)

    if not missing:
        # All data found – go to confirmation
        await update_session(
            db, phone,
            current_intent="SELL_OFFER",
            current_step="CONFIRMING",
            collected_data=collected,
        )

        # Build confirmation message
        lines = [
            "📸 Ik heb de volgende gegevens uit je ticket gehaald:\n",
            "📋 Kloppen deze gegevens?\n",
        ]
        if collected.get("event_name"):
            lines.append(f"🎟️ Evenement: {collected['event_name']}")
        if collected.get("event_date"):
            lines.append(f"📅 Datum: {collected['event_date']}")
        if collected.get("ticket_type"):
            lines.append(f"🎫 Type: {collected['ticket_type']}")
        if collected.get("quantity"):
            lines.append(f"🔢 Aantal: {collected['quantity']}")
        if collected.get("price_per_ticket"):
            lines.append(f"💰 Prijs per ticket: €{collected['price_per_ticket']}")
        lines.append("\nTyp 'ja' om te bevestigen of 'nee' om opnieuw te beginnen.")
        return "\n".join(lines)
    else:
        # Some data missing – save what we have and ask for the rest
        await update_session(
            db, phone,
            current_intent="SELL_OFFER",
            current_step="COLLECTING",
            collected_data=collected,
        )

        found_parts = []
        if collected.get("event_name"):
            found_parts.append(f"🎟️ Evenement: {collected['event_name']}")
        if collected.get("event_date"):
            found_parts.append(f"📅 Datum: {collected['event_date']}")
        if collected.get("quantity"):
            found_parts.append(f"🔢 Aantal: {collected['quantity']}")
        if collected.get("price_per_ticket"):
            found_parts.append(f"💰 Prijs: €{collected['price_per_ticket']}")

        found_str = "\n".join(found_parts)

        from app.message_templates.templates import ask_missing_field
        next_q = ask_missing_field(missing[0], "SELL_OFFER")

        return (
            f"📸 Ik heb het volgende uit je ticket gehaald:\n{found_str}\n\n"
            f"Ik mis nog wat gegevens.\n{next_q}"
        )
