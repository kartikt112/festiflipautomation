import os
import httpx
import logging
from typing import Optional

logger = logging.getLogger(__name__)

WHAPI_URL = "https://gate.whapi.cloud"
WHAPI_TOKEN = os.getenv("WHAPI_TOKEN")

from app.config import settings

# The specific WhatsApp group to send notifications to
NOTIFICATION_GROUP_ID = "120363423980604716@g.us"

async def send_group_notification(message: str) -> bool:
    """
    Send a WhatsApp notification to the designated operations group
    using the unofficial Whapi cloud API.
    """
    whapi_token = settings.WHAPI_TOKEN
    if not whapi_token:
        logger.warning("WHAPI_TOKEN not set in settings. Skipping group notification.")
        return False

    url = f"{WHAPI_URL}/messages/text"
    headers = {
        "Authorization": f"Bearer {whapi_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "to": NOTIFICATION_GROUP_ID,
        "body": message
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code == 200:
                logger.info(f"Group notification sent successfully.")
                return True
            else:
                logger.error(f"Failed to send Whapi notification. Status: {response.status_code}, Error: {response.text}")
                return False
    except Exception as e:
        logger.exception("Exception sending Whapi group notification")
        return False


async def send_whapi_dm(chat_id: str, message: str) -> bool:
    """Send a direct message to a user via Whapi.

    Args:
        chat_id: Whapi chat ID, e.g. "31637194374@s.whatsapp.net"
        message: Text to send
    """
    whapi_token = settings.WHAPI_TOKEN
    if not whapi_token:
        logger.warning("WHAPI_TOKEN not set. Skipping DM.")
        return False

    url = f"{WHAPI_URL}/messages/text"
    headers = {
        "Authorization": f"Bearer {whapi_token}",
        "Content-Type": "application/json",
    }
    payload = {"to": chat_id, "body": message}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code == 200:
                logger.info(f"Whapi DM sent to {chat_id}")
                return True
            else:
                logger.error(f"Whapi DM failed. Status: {response.status_code}, Error: {response.text}")
                return False
    except Exception as e:
        logger.exception(f"Exception sending Whapi DM to {chat_id}")
        return False
