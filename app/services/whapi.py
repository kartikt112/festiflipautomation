import asyncio
import httpx
import logging
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

WHAPI_URL = "https://gate.whapi.cloud"

# Legacy fallback — used only if DB has no groups yet
_LEGACY_GROUP_ID = "120363423980604716@g.us"


async def _send_to_group(group_id: str, message: str) -> bool:
    """Send a message to a single WhatsApp group via Whapi."""
    whapi_token = settings.WHAPI_TOKEN
    if not whapi_token:
        logger.warning("WHAPI_TOKEN not set. Skipping group send.")
        return False

    url = f"{WHAPI_URL}/messages/text"
    headers = {
        "Authorization": f"Bearer {whapi_token}",
        "Content-Type": "application/json",
    }
    payload = {"to": group_id, "body": message}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code == 200:
                logger.info(f"Whapi message sent to group {group_id}")
                return True
            else:
                logger.error(f"Whapi group send failed. Group: {group_id}, Status: {response.status_code}, Error: {response.text}")
                return False
    except Exception as e:
        logger.exception(f"Exception sending to group {group_id}")
        return False


async def send_group_notification(message: str) -> bool:
    """Legacy single-group send — kept for backward compatibility.

    Sends to the legacy hardcoded group. Use broadcast_to_all_groups() instead.
    """
    return await _send_to_group(_LEGACY_GROUP_ID, message)


async def broadcast_to_all_groups(db, message: str) -> dict:
    """Send a message to ALL enabled WhatsApp groups.

    Args:
        db: AsyncSession
        message: Text to broadcast

    Returns:
        {"sent": N, "failed": N}
    """
    from sqlalchemy import select
    from app.models.whatsapp_group import WhatsAppGroup

    result = await db.execute(
        select(WhatsAppGroup).where(WhatsAppGroup.enabled == True)
    )
    groups = list(result.scalars().all())

    # Fallback: if no groups in DB yet, use legacy group
    if not groups:
        logger.info("No groups in DB, falling back to legacy group")
        sent = await _send_to_group(_LEGACY_GROUP_ID, message)
        return {"sent": 1 if sent else 0, "failed": 0 if sent else 1}

    sent = 0
    failed = 0
    for group in groups:
        ok = await _send_to_group(group.group_id, message)
        if ok:
            sent += 1
        else:
            failed += 1
        # Rate limit: small delay between sends
        if len(groups) > 1:
            await asyncio.sleep(0.5)

    logger.info(f"Broadcast complete: {sent} sent, {failed} failed across {len(groups)} groups")
    return {"sent": sent, "failed": failed}


async def fetch_groups_from_whapi() -> list:
    """Fetch all groups the Whapi number is in via the Whapi API.

    Returns list of {"id": "...@g.us", "name": "..."} dicts.
    """
    whapi_token = settings.WHAPI_TOKEN
    if not whapi_token:
        logger.warning("WHAPI_TOKEN not set. Cannot fetch groups.")
        return []

    url = f"{WHAPI_URL}/groups"
    headers = {
        "Authorization": f"Bearer {whapi_token}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                # Whapi returns {"groups": [...]} or {"chats": [...]}
                groups = data.get("groups", data.get("chats", []))
                return [
                    {
                        "id": g.get("id", g.get("chat_id", "")),
                        "name": g.get("name", g.get("subject", "")),
                    }
                    for g in groups
                    if (g.get("id", g.get("chat_id", "")) or "").endswith("@g.us")
                ]
            else:
                logger.error(f"Whapi groups fetch failed. Status: {response.status_code}, Error: {response.text}")
                return []
    except Exception as e:
        logger.exception("Exception fetching Whapi groups")
        return []


async def sync_groups_to_db(db) -> int:
    """Sync groups from Whapi API into the database.

    Returns number of NEW groups discovered.
    """
    from sqlalchemy import select
    from app.models.whatsapp_group import WhatsAppGroup

    api_groups = await fetch_groups_from_whapi()
    if not api_groups:
        return 0

    new_count = 0
    for g in api_groups:
        gid = g["id"]
        gname = g.get("name", "")

        # Check if already exists
        result = await db.execute(
            select(WhatsAppGroup).where(WhatsAppGroup.group_id == gid)
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Update name if changed
            if gname and existing.group_name != gname:
                existing.group_name = gname
        else:
            # New group
            db.add(WhatsAppGroup(
                group_id=gid,
                group_name=gname or None,
                enabled=True,
                auto_detected=True,
            ))
            new_count += 1

    await db.flush()
    logger.info(f"Group sync: {new_count} new groups, {len(api_groups)} total from Whapi")
    return new_count


async def register_group_if_new(db, group_id: str, group_name: str = "") -> bool:
    """Register a group if we haven't seen it before (auto-detection from webhooks).

    Returns True if it was a new group.
    """
    from sqlalchemy import select
    from app.models.whatsapp_group import WhatsAppGroup

    result = await db.execute(
        select(WhatsAppGroup).where(WhatsAppGroup.group_id == group_id)
    )
    if result.scalar_one_or_none():
        return False  # Already known

    db.add(WhatsAppGroup(
        group_id=group_id,
        group_name=group_name or None,
        enabled=True,
        auto_detected=True,
    ))
    await db.flush()
    logger.info(f"Auto-detected new group: {group_id} ({group_name})")
    return True


async def send_whapi_dm(chat_id: str, message: str) -> bool:
    """Send a direct message to a user via Whapi."""
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
