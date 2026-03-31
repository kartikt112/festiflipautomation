"""AI-powered entity extraction for the state machine.

Smart extraction layer that uses OpenAI to understand natural language inputs
when the simple regex can't parse them. This handles cases like:
- "volgende week donderdag" → 2025-06-26
- "honderd euro" → 100.0
- "een stuk of vijf" → 5
- "twee dagkaarten" → quantity=2, ticket_type="dagkaart"
"""

import json
import re
import logging
from datetime import date
from openai import AsyncOpenAI
from app.config import settings

logger = logging.getLogger(__name__)
client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

# Dutch number words for fast regex path
DUTCH_NUMBERS = {
    "een": 1, "één": 1, "eentje": 1,
    "twee": 2, "drie": 3, "vier": 4, "vijf": 5,
    "zes": 6, "zeven": 7, "acht": 8, "negen": 9, "tien": 10,
}

from typing import Optional


def _try_fast_extract(message: str, expected_field: str) -> Optional[dict]:
    """Try fast regex extraction for obvious simple inputs. Returns None if unsure."""
    msg = message.strip()
    msg_lower = msg.lower()

    if expected_field == "quantity":
        # Pure number
        m = re.match(r"^(\d+)$", msg)
        if m:
            return {"quantity": int(m.group(1))}
        # Dutch number word alone
        for word, num in DUTCH_NUMBERS.items():
            if msg_lower == word:
                return {"quantity": num}

    elif expected_field in ("price_per_ticket", "max_price"):
        # €90 or 90 euro
        m = re.search(r"€\s*(\d+[.,]?\d*)", msg)
        if m:
            return {expected_field: float(m.group(1).replace(",", "."))}
        m = re.search(r"(\d+[.,]?\d*)\s*euro", msg_lower)
        if m:
            return {expected_field: float(m.group(1).replace(",", "."))}
        m = re.search(r"max(?:imaal)?\s*(\d+[.,]?\d*)", msg_lower)
        if m:
            return {expected_field: float(m.group(1).replace(",", "."))}
        # Bare number only if nothing else makes sense
        m = re.match(r"^(\d+[.,]?\d*)$", msg)
        if m:
            return {expected_field: float(m.group(1).replace(",", "."))}

    elif expected_field == "event_date":
        # ISO date
        m = re.match(r"^\d{4}-\d{2}-\d{2}$", msg)
        if m:
            return {"event_date": msg}
        # DD-MM-YYYY
        m = re.match(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$", msg)
        if m:
            return {"event_date": f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"}

    elif expected_field == "event_name":
        # AI-first approach: only fast-accept unambiguous proper nouns (1-3 words, no Dutch function words)
        # Everything else goes to AI extraction for reliable classification
        if msg and len(msg) < 60 and not re.match(r"^\d+$", msg):
            words = msg_lower.split()
            _DUTCH_FUNCTION_WORDS = {
                "ik", "je", "jij", "hij", "zij", "we", "wij", "het", "de", "een",
                "ben", "bent", "is", "zijn", "was", "wil", "kan", "heb", "heeft",
                "maar", "want", "omdat", "als", "dat", "dit", "die", "wat", "wie",
                "hoe", "waar", "wanneer", "waarom", "niet", "geen", "wel", "ook",
                "ja", "nee", "ok", "oke", "sorry", "hallo", "hoi", "hey",
                "nog", "al", "er", "naar", "van", "voor", "met", "op", "in",
                "verkoper", "koper", "betaling", "ticket", "tickets",
            }
            if len(words) <= 3 and not (set(words) & _DUTCH_FUNCTION_WORDS):
                return {"event_name": msg}

    return None


async def ai_extract_value(
    message: str,
    expected_field: str,
    intent: str,
    collected_data: dict,
    conversation_history: list = None,
) -> dict:
    """Use AI to extract a structured value from a natural language reply.
    
    Args:
        message: The user's raw message
        expected_field: Which field we're trying to extract (event_name, event_date, quantity, etc.)
        intent: BUY_REQUEST or SELL_OFFER
        collected_data: What we've collected so far
        
    Returns:
        Dict with extracted field(s), or empty dict if extraction failed
    """
    # 1. Try fast regex first (free, instant)
    fast = _try_fast_extract(message, expected_field)
    if fast is not None:
        return fast

    # 2. Circuit breaker: skip AI if OpenAI is down for this request
    try:
        from app.ai.state_machine import _ai_is_available
        if not _ai_is_available():
            return {}
    except ImportError:
        pass

    # 3. Use AI for complex cases
    today_str = date.today().strftime("%Y-%m-%d")
    intent_nl = "kopen" if intent == "BUY_REQUEST" else "verkopen"
    
    # Build context of what we already have
    context_parts = []
    if collected_data.get("event_name"):
        context_parts.append(f"Evenement: {collected_data['event_name']}")
    if collected_data.get("event_date"):
        context_parts.append(f"Datum: {collected_data['event_date']}")
    if collected_data.get("quantity"):
        context_parts.append(f"Aantal: {collected_data['quantity']}")
    if collected_data.get("max_price") or collected_data.get("price_per_ticket"):
        price = collected_data.get("max_price") or collected_data.get("price_per_ticket")
        context_parts.append(f"Prijs: €{price}")
    context_str = ", ".join(context_parts) if context_parts else "nog niets"
    
    field_descriptions = {
        "event_name": (
            "De naam van het evenement/festival/concert. "
            "BELANGRIJK: Als het bericht GEEN evenementnaam bevat maar conversatie is "
            "(klacht, vraag, ontkenning, intentie-wissel, chat), geef value: null, confident: false. "
            "Een evenementnaam is een eigennaam (bijv. Dekmantel, Lowlands, Tomorrowland), "
            "GEEN Nederlandse zin of gespreksreactie."
        ),
        "event_date": f"De datum van het evenement (vandaag is {today_str}). Parse ook relatieve datums zoals 'volgende week', 'over 2 maanden', etc. ALS DE GEBRUIKER GEEN DATUM NOEMT, geef dan null terug. Vul NOOIT standaard de datum van vandaag in.",
        "quantity": "Het aantal tickets",
        "max_price": "De maximale prijs per ticket die de koper wil betalen (in euro's)",
        "price_per_ticket": "De verkoopprijs per ticket (in euro's)",
        "ticket_type": "Het type ticket (bijv. Weekender, Dagticket, Night Ticket)",
    }
    
    prompt = f"""Je bent een data-extractie assistent. De gebruiker wil tickets {intent_nl}.
We hebben al: {context_str}

We zoeken nu specifiek: {field_descriptions.get(expected_field, expected_field)}

De gebruiker zei: "{message}"

Extraheer de waarde en geef ALLEEN JSON terug in dit formaat:
{{"field": "{expected_field}", "value": <extracted_value>, "confident": true/false}}

Regels:
- Voor datums: geef altijd formaat YYYY-MM-DD. Vandaag is {today_str}. ALS DE GEBRUIKER GEEN DATUM NOEMT, geef null terug. Vul NOOIT standaard vandaag in.
- Voor prijzen: geef alleen het getal (float), zonder € of "euro"
- Voor aantallen: geef alleen het getal (int)
- Voor tekst: geef de tekst zonder aanhalingstekens
- Als je NIET kunt extraheren wat we zoeken, geef: {{"field": "{expected_field}", "value": null, "confident": false}}
- Als het bericht MEERDERE velden tegelijk bevat, extraheer ze allemaal als extra velden in het JSON object
"""

    try:
        # Build messages with conversation context
        messages = [
            {"role": "system", "content": "Je bent een data-extractie assistent. Geef ALLEEN valid JSON terug."},
        ]
        if conversation_history:
            messages.append({
                "role": "system",
                "content": "Recente gespreksgeschiedenis:",
            })
            for msg in conversation_history[-6:]:  # Last 6 messages max
                messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": prompt})

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=150,
        )
        
        result = json.loads(response.choices[0].message.content)
        logger.info(f"AI extraction for '{expected_field}': {result}")
        
        extracted = {}

        # Primary field
        value = result.get("value")
        confident = result.get("confident", False)  # Safe default: require explicit confidence

        if value is not None:
            # For event_name, REQUIRE explicit confidence — reject uncertain extractions
            if expected_field == "event_name" and not confident:
                logger.info(f"AI rejected event_name (low confidence): '{value}'")
                return {}

            # For other fields, also require confidence
            if not confident:
                return {}

            field = result.get("field", expected_field)

            # Type coercion
            if field in ("quantity",) and value is not None:
                try:
                    value = int(value)
                except (ValueError, TypeError):
                    value = None
            elif field in ("max_price", "price_per_ticket") and value is not None:
                try:
                    value = float(value)
                except (ValueError, TypeError):
                    value = None

            if value is not None:
                extracted[field] = value
        
        # Check for bonus fields (AI detected multiple values)
        for bonus_field in ("event_name", "event_date", "quantity", "max_price", "price_per_ticket", "ticket_type"):
            if bonus_field != expected_field and bonus_field in result and result[bonus_field] is not None:
                extracted[bonus_field] = result[bonus_field]
        
        return extracted
        
    except Exception as e:
        logger.error(f"AI extraction failed: {e}")
        try:
            from app.ai.state_machine import _ai_mark_failed
            _ai_mark_failed()
        except ImportError:
            pass
        # Only fall back to raw message for ticket_type — never for event_name (too risky)
        if expected_field in ("ticket_type",):
            return {expected_field: message.strip()}
        return {}
