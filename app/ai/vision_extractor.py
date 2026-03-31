"""Vision-based ticket data extraction using OpenAI GPT-4o.

When a seller sends a photo of their ticket/event, this module uses
GPT-4o's vision capabilities to extract structured data (event name,
date, ticket type, quantity, price, venue, etc.).
"""

import json
import logging
from typing import Optional, Dict

from openai import AsyncOpenAI
from app.config import settings

logger = logging.getLogger(__name__)
client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

VISION_EXTRACTION_PROMPT = """Je bent een ticket-data extractie assistent.
Analyseer de afbeelding van een ticket of evenement en extraheer de volgende gegevens.

Geef ALLEEN JSON terug met de gevonden velden:
{
  "event_name": "Naam van het evenement/festival/concert",
  "event_date": "Datum in YYYY-MM-DD formaat (of null)",
  "ticket_type": "Type ticket (bijv. Weekend, Dagticket, VIP) of null",
  "quantity": 1,
  "price_per_ticket": "Prijs in euro's (alleen het getal, float) of null",
  "venue": "Locatie/venue naam of null",
  "seat_info": "Stoelnummer of vak informatie of null",
  "barcode_visible": true/false,
  "confidence": 0.0 tot 1.0
}

Regels:
- Geef ALLEEN geldig JSON terug, geen uitleg.
- Als je een veld niet kunt vinden op de afbeelding, zet het op null.
- Probeer altijd minstens de event_name te vinden.
- Als de afbeelding GEEN ticket of evenement toont, geef: {"error": "no_ticket_found", "confidence": 0.0}
- Datums altijd in YYYY-MM-DD formaat.
- Prijzen altijd als float (zonder € teken).
"""


async def extract_ticket_from_image(image_url: str) -> Optional[Dict]:
    """Extract ticket data from an image using GPT-4o vision.

    Args:
        image_url: URL of the image (WhatsApp media URL or public URL)

    Returns:
        Dict with extracted ticket data, or None on failure.
        Keys: event_name, event_date, ticket_type, quantity,
              price_per_ticket, venue, seat_info, barcode_visible, confidence
    """
    if not settings.OPENAI_API_KEY:
        logger.warning("OpenAI API key not configured – skipping vision extraction")
        return None

    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "Je bent een JSON-only data-extractie assistent. Geef alleen geldig JSON terug.",
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": VISION_EXTRACTION_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": image_url, "detail": "high"},
                        },
                    ],
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=500,
        )

        result = json.loads(response.choices[0].message.content)

        # Check for error response
        if result.get("error"):
            logger.info(f"Vision extraction: no ticket found – {result.get('error')}")
            return None

        # Validate we got at least an event name
        if not result.get("event_name"):
            logger.info("Vision extraction: no event_name extracted")
            return None

        logger.info(
            f"Vision extraction successful: {result.get('event_name')} "
            f"(confidence: {result.get('confidence', 0)})"
        )
        return result

    except json.JSONDecodeError as e:
        logger.error(f"Vision extraction returned invalid JSON: {e}")
        return None
    except Exception as e:
        logger.error(f"Vision extraction error: {e}")
        return None


async def extract_ticket_from_base64(image_base64: str, media_type: str = "image/jpeg") -> Optional[Dict]:
    """Extract ticket data from a base64-encoded image.

    Args:
        image_base64: Base64-encoded image data
        media_type: MIME type of the image (e.g., image/jpeg, image/png)

    Returns:
        Dict with extracted ticket data, or None on failure.
    """
    data_url = f"data:{media_type};base64,{image_base64}"
    return await extract_ticket_from_image(data_url)
