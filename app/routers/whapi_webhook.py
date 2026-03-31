"""Whapi webhook router – auto-redirects users who message the Festi chat number
to the main FestiFlip WhatsApp Business number."""

import logging
from fastapi import APIRouter, Request
from app.services.whapi import send_whapi_dm
from app.message_templates.templates import FESTIFLIP_CONTACT

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["Whapi"])

# The main WhatsApp Business number as a clickable wa.me link
_MAIN_NUMBER_LINK = FESTIFLIP_CONTACT.replace(" ", "").replace("+", "")
_REDIRECT_MESSAGE = (
    "👋 Hoi! Dit nummer wordt alleen gebruikt voor groepsmeldingen.\n\n"
    "Wil je tickets kopen of verkopen? Stuur dan een bericht naar ons "
    f"hoofdnummer:\n\n"
    f"👉 https://wa.me/{_MAIN_NUMBER_LINK}\n\n"
    "Daar helpt onze bot je direct verder! 🎟️"
)


@router.post("/whapi")
async def receive_whapi_message(request: Request):
    """Handle incoming messages on the Whapi (Festi chat) number.

    Whapi sends webhooks in its own format. We extract the sender and
    reply with a redirect to the main FestiFlip number.
    """
    body = await request.json()
    logger.info(f"Whapi webhook received: {body}")

    try:
        messages = body.get("messages", [])
        if not messages:
            return {"status": "ok"}

        for msg in messages:
            # Skip outgoing messages (from_me = True)
            if msg.get("from_me", False):
                continue

            # Skip group messages — only redirect DMs
            chat_id = msg.get("chat_id", "")
            if chat_id.endswith("@g.us"):
                continue

            sender = msg.get("chat_id", "")  # e.g. "31637194374@s.whatsapp.net"
            if not sender:
                continue

            logger.info(f"Whapi DM from {sender}, sending redirect")
            await send_whapi_dm(sender, _REDIRECT_MESSAGE)

    except Exception as e:
        logger.error(f"Whapi webhook error: {e}", exc_info=True)

    return {"status": "ok"}
