import logging
import json
from openai import AsyncOpenAI
from app.config import settings

logger = logging.getLogger(__name__)

# Lazy-initialized client
_client = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


class EventVerifier:
    async def verify_event(self, event_name: str) -> dict:
        """
        Verify if an event is real using OpenAI's knowledge.
        Returns dict with is_real, ticket_types, etc.
        """
        try:
            logger.info(f"Verifying event with AI: {event_name}")
            client = _get_client()

            prompt = (
                f"You are an expert event verifier. Analyze the event '{event_name}'.\n"
                "1. Is this a real, known event series? (is_real)\n"
                "2. What are the OFFICIAL ticket types usually sold? (ticket_types)\n"
                "   Examples: 'Weekend Ticket', 'Day Ticket (Friday)', 'Camping', 'Night Ticket', etc.\n"
                "3. Is the name ambiguous? (ambiguous)\n"
                "4. Is this a MULTI-DAY festival (like Lowlands, Pinkpop, Defqon.1) or a single-day concert? (is_multi_day)\n"
                "5. What are the typical event dates for the upcoming edition? (event_dates) - format: YYYY-MM-DD\n\n"
                "Return ONLY JSON:\n"
                "{\n"
                '  "is_real": true,\n'
                '  "official_name": "Lowlands Festival",\n'
                '  "ticket_types": ["Weekend Ticket", "Day Ticket (Friday)", "Day Ticket (Saturday)"],\n'
                '  "is_multi_day": true,\n'
                '  "event_dates": "2025-08-15 to 2025-08-17",\n'
                '  "ambiguous": false,\n'
                '  "reasoning": "Annual 3-day festival in Biddinghuizen."\n'
                "}"
            )

            response = await client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an event verification assistant. Return only valid JSON.",
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )

            result = json.loads(response.choices[0].message.content)

            # Default values
            result.setdefault("is_real", False)
            result.setdefault("ticket_types", [])
            result.setdefault("ambiguous", False)
            result.setdefault("is_multi_day", False)
            result.setdefault("event_dates", None)

            return result

        except Exception as e:
            logger.error(f"Event verification failed: {e}")
            return {"is_real": True, "ticket_types": [], "ambiguous": False, "reasoning": f"Verification error: {e}"}

# Singleton instance
verifier = EventVerifier()
