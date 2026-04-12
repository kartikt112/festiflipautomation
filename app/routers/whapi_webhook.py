"""Whapi webhook router – auto-detects groups and redirects DMs."""

import logging
from fastapi import APIRouter, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.whapi import send_whapi_dm, register_group_if_new
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
async def receive_whapi_message(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle incoming messages on the Whapi (Festi chat) number.

    - Group messages: auto-detect and register new groups
    - DMs: redirect to main FestiFlip number
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

            chat_id = msg.get("chat_id", "")

            # Group messages: auto-detect new groups
            if chat_id.endswith("@g.us"):
                group_name = msg.get("chat_name", "") or msg.get("subject", "")
                is_new = await register_group_if_new(db, chat_id, group_name)
                if is_new:
                    await db.commit()
                    logger.info(f"New group registered: {chat_id} ({group_name})")
                continue

            # DMs: redirect to main number
            if not chat_id:
                continue

            logger.info(f"Whapi DM from {chat_id}, sending redirect")
            await send_whapi_dm(chat_id, _REDIRECT_MESSAGE)

    except Exception as e:
        logger.error(f"Whapi webhook error: {e}", exc_info=True)

    return {"status": "ok"}
