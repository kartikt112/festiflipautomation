"""WhatsApp Business API integration via Meta Cloud API."""

import httpx
import logging
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

BASE_URL = f"{settings.WHATSAPP_API_URL}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
HEADERS = {
    "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
    "Content-Type": "application/json",
}


async def send_text_message(phone: str, text: str) -> dict:
    """Send a free-form text message via WhatsApp.

    Args:
        phone: Recipient phone in E.164 format (e.g., +31612345678)
        text: Message text

    Returns:
        WhatsApp API response
    """
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone.lstrip("+"),
        "type": "text",
        "text": {"preview_url": True, "body": text},
    }

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(BASE_URL, json=payload, headers=HEADERS)

        if response.status_code != 200:
            logger.error(f"WhatsApp send failed: {response.status_code} {response.text}")
            response.raise_for_status()

        result = response.json()
        logger.info(f"WhatsApp message sent to {phone}: {result}")
        return result


async def send_media_message(
    phone: str, media_url: str, caption: Optional[str] = None
) -> dict:
    """Send an image/document via WhatsApp.

    Args:
        phone: Recipient phone in E.164 format
        media_url: Public URL of the media
        caption: Optional caption

    Returns:
        WhatsApp API response
    """
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone.lstrip("+"),
        "type": "image",
        "image": {"link": media_url},
    }
    if caption:
        payload["image"]["caption"] = caption

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(BASE_URL, json=payload, headers=HEADERS)
        response.raise_for_status()
        return response.json()


async def mark_as_read(message_id: str) -> dict:
    """Mark a message as read (blue ticks)."""
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    }

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(BASE_URL, json=payload, headers=HEADERS)
        return response.json()


async def download_media(media_id: str) -> Optional[str]:
    """Get the download URL for a WhatsApp media file.

    Args:
        media_id: The media ID from the webhook payload

    Returns:
        The download URL string, or None on failure
    """
    media_url = f"{settings.WHATSAPP_API_URL}/{media_id}"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(media_url, headers=HEADERS)
            response.raise_for_status()
            data = response.json()
            url = data.get("url")
            logger.info(f"Media URL retrieved for {media_id}")
            return url
    except Exception as e:
        logger.error(f"Failed to get media URL for {media_id}: {e}")
        return None


async def download_media_content(media_url: str) -> Optional[str]:
    """Download media content and return as base64 string.

    Args:
        media_url: The download URL from download_media()

    Returns:
        Base64-encoded content string, or None on failure
    """
    import base64

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(media_url, headers=HEADERS)
            response.raise_for_status()
            content = response.content
            return base64.b64encode(content).decode("utf-8")
    except Exception as e:
        logger.error(f"Failed to download media content: {e}")
        return None


async def upload_media_to_whatsapp(file_bytes: bytes, mime_type: str, filename: str) -> Optional[str]:
    """Upload a media file to WhatsApp and return the media ID.

    Args:
        file_bytes: Raw file bytes
        mime_type: MIME type (e.g. image/jpeg, audio/ogg, video/mp4)
        filename: Original filename

    Returns:
        WhatsApp media ID, or None on failure
    """
    upload_url = f"{settings.WHATSAPP_API_URL}/{settings.WHATSAPP_PHONE_NUMBER_ID}/media"

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                upload_url,
                headers={"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"},
                files={"file": (filename, file_bytes, mime_type)},
                data={"messaging_product": "whatsapp", "type": mime_type},
            )
            response.raise_for_status()
            media_id = response.json().get("id")
            logger.info(f"Media uploaded: {media_id}")
            return media_id
    except Exception as e:
        logger.error(f"Media upload failed: {e}")
        return None


async def send_media_by_type(
    phone: str, media_id: str, media_type: str, caption: Optional[str] = None
) -> dict:
    """Send media by type using a WhatsApp media ID.

    Args:
        phone: Recipient phone in E.164 format
        media_id: WhatsApp media ID from upload_media_to_whatsapp()
        media_type: One of 'image', 'video', 'audio', 'document'
        caption: Optional caption (not supported for audio)
    """
    media_obj = {"id": media_id}
    if caption and media_type != "audio":
        media_obj["caption"] = caption

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone.lstrip("+"),
        "type": media_type,
        media_type: media_obj,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(BASE_URL, json=payload, headers=HEADERS)
        if response.status_code != 200:
            logger.error(f"WhatsApp media send failed: {response.status_code} {response.text}")
            response.raise_for_status()
        result = response.json()
        logger.info(f"WhatsApp {media_type} sent to {phone}: {result}")
        return result
