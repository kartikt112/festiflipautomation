import json
import logging
from typing import List, Optional
from openai import AsyncOpenAI
from app.config import settings

logger = logging.getLogger(__name__)

async def ai_find_matching_offer_ids(
    buyer_event_name: str,
    buyer_ticket_type: Optional[str],
    available_offers: List[dict],
    buyer_event_date: Optional[str] = None,
) -> List[int]:
    """
    Given a buyer's requested event name, ticket type, and date, and a list of available offers,
    uses AI to determine which offers semantically match the request.

    available_offers format: [{"id": 1, "event_name": "...", "ticket_type": "...", "event_date": "..."}, ...]
    """
    if not available_offers:
        return []

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    # Format offers for the prompt
    offers_json = json.dumps(available_offers, ensure_ascii=False, indent=2)
    buyer_type_str = buyer_ticket_type if buyer_ticket_type else "Any/Unspecified"
    buyer_date_str = buyer_event_date if buyer_event_date else "Not specified"

    prompt = f"""You are an intelligent event matching assistant for a ticket platform in the Netherlands.
A buyer is looking for tickets.

Buyer Request:
- Event Name: "{buyer_event_name}"
- Ticket Type: "{buyer_type_str}"
- Event Date: "{buyer_date_str}"

Here is a list of currently available ticket offers:
{offers_json}

Your task: Find ALL offer IDs from the available offers list that match the buyer's request.
Rules:
1. Semantically match the event names (e.g. "T-Swift" matches "Taylor Swift Convex", "Lowlands" matches "Lowlands Festival").
2. Ticket types must match acceptably. If the buyer asked for "Weekend" and the seller offers "Weekend", that's a match. If the buyer specified no ticket type, any type for that event matches. If they don't match (e.g., "Saturday" vs "Sunday"), do not include it.
3. **CRITICAL: Event dates MUST match.** If the buyer specifies a date and the offer has a date, they must be for the same date (or very close, e.g. multi-day festival). An offer for "Thuishaven 5 april" does NOT match a buyer looking for "Thuishaven 18 april". If the buyer has no date, any date for that event matches. If the offer has no date, it can still match.
4. Return ONLY a valid JSON array of integers containing the matching IDs.
5. Do not include any markdown formatting, backticks, or explanation. Just the raw JSON array. Ex: [1, 4, 7]
6. If NO offers match, return an empty array: []
"""

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.0,
            max_tokens=150,
        )
        
        content = response.choices[0].message.content.strip()
        
        # Clean up in case the model returns markdown despite instructions
        if content.startswith("```json"):
            content = content[7:]
        if content.endswith("```"):
            content = content[:-3]
            
        content = content.strip()
        
        matching_ids = json.loads(content)
        if isinstance(matching_ids, list) and all(isinstance(i, int) for i in matching_ids):
            logger.info(f"AI Matcher: Buyer wants '{buyer_event_name}' ({buyer_ticket_type}). AI matched IDs: {matching_ids}")
            return matching_ids
        else:
            logger.error(f"AI Matcher returned invalid format: {content}")
            return []
            
    except Exception as e:
        logger.error(f"Error calling AI matcher: {e}")
        return []
