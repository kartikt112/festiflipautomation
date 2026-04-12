"""Conversation state machine – guides users through data collection."""

import re
import logging
from typing import Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.crud.chat_sessions import get_or_create_session, update_session, reset_session
from app.crud.chat_history import get_recent_history
from app.crud.sell_offers import create_sell_offer
from app.crud.buy_requests import create_buy_request
from app.ai.classifier import classify_message, ClassificationResult
from app.ai.extractor import validate_entities, normalize_entities
from app.schemas.sell_offer import SellOfferCreate
from app.schemas.buy_request import BuyRequestCreate
from app.message_templates.templates import (
    ask_missing_field as _ask_missing_field_raw,
    seller_confirmation_message,
    welcome_message as _welcome_message_raw,
)
from app.services.matching import auto_match_and_notify
from app.models.ai_log import AILog


# Language-aware wrappers — automatically pass _lang() to templates
def ask_missing_field(field_name: str, intent: str = "BUY_REQUEST") -> str:
    return _ask_missing_field_raw(field_name, intent, lang=_lang())

def welcome_message() -> str:
    return _welcome_message_raw(lang=_lang())

logger = logging.getLogger(__name__)

# State constants
IDLE = "IDLE"
COLLECTING = "COLLECTING"
CONFIRMING = "CONFIRMING"
COMPLETE = "COMPLETE"

# Session timeout: reset stale sessions older than this
SESSION_TIMEOUT_HOURS = 24

# ── Per-phone message lock ──
# Prevents concurrent messages from the same user from racing each other.
# Messages are serialized per phone number so session reads/writes don't collide.
import asyncio as _asyncio
import weakref as _weakref

_phone_locks: dict[str, _asyncio.Lock] = {}
_phone_locks_guard = _asyncio.Lock()

async def _get_phone_lock(phone: str) -> _asyncio.Lock:
    """Get or create an asyncio.Lock for a specific phone number.
    Cleans up unlocked entries when the dict grows beyond 500 to prevent memory leaks."""
    async with _phone_locks_guard:
        # Periodic cleanup: remove locks that aren't held
        if len(_phone_locks) > 500:
            to_remove = [p for p, lk in _phone_locks.items() if not lk.locked()]
            for p in to_remove:
                del _phone_locks[p]
        lock = _phone_locks.get(phone)
        if lock is None:
            lock = _asyncio.Lock()
            _phone_locks[phone] = lock
        return lock

# ── OpenAI circuit breaker ──
# If OpenAI fails, skip subsequent AI calls for this request to avoid
# partial state corruption and unnecessary timeouts.
import time as _time

class _CircuitBreaker:
    """Per-request circuit breaker for OpenAI calls.
    If any OpenAI call fails, subsequent AI calls in the same request
    are skipped to avoid timeouts and inconsistent state."""
    __slots__ = ("tripped", "last_failure")
    def __init__(self):
        self.tripped = False
        self.last_failure = 0.0
    def trip(self):
        self.tripped = True
        self.last_failure = _time.monotonic()
    def is_open(self) -> bool:
        return self.tripped

# Contextvars to share circuit breaker across async calls within one request
import contextvars
_request_circuit: contextvars.ContextVar[Optional[_CircuitBreaker]] = contextvars.ContextVar(
    "_request_circuit", default=None
)

def _ai_is_available() -> bool:
    """Check if OpenAI calls should proceed (circuit breaker not tripped)."""
    cb = _request_circuit.get()
    return cb is None or not cb.is_open()

def _ai_mark_failed():
    """Mark OpenAI as failed for this request."""
    cb = _request_circuit.get()
    if cb:
        cb.trip()

# ── Per-request language ──
_request_lang: contextvars.ContextVar[str] = contextvars.ContextVar("_request_lang", default="nl")

def _lang() -> str:
    """Get the detected language for the current request."""
    return _request_lang.get()

# ── Language detection ──
# Strong English signals — phrases that don't appear in Dutch messages
_EN_SIGNALS = {"i want", "i need", "i have", "i'd like", "looking for",
               "how much", "what is", "can i", "change the",
               "sell my", "buy tickets", "thank you", "please help"}

def _detect_language(message: str, session_lang: str = None) -> str:
    """Detect if user is writing in English or Dutch. Returns 'en' or 'nl'.
    Sticky: once set to 'en', stays until user switches back to Dutch.
    Requires 2+ signals for first detection to avoid false positives."""
    msg = message.strip().lower()
    en_count = sum(1 for sig in _EN_SIGNALS if sig in msg)
    # Require 2+ signals for initial switch to English (avoid false positives)
    # But only 1 signal if already in English (sticky)
    if session_lang == "en" and en_count >= 1:
        return "en"
    if en_count >= 2:
        return "en"
    if session_lang == "en":
        # Check for Dutch switch-back
        _nl_signals = ("ik wil", "ik zoek", "hoeveel", "te koop",
                       "verkopen", "kopen", "stuks", "per stuk")
        nl_count = sum(1 for sig in _nl_signals if sig in msg)
        if nl_count >= 1:
            return "nl"
        return "en"  # Sticky — keep English until Dutch detected
    return "nl"  # Default Dutch

# ── Bilingual response helpers ──
def _t(nl: str, en: str) -> str:
    """Return Dutch or English string based on current request language."""
    return en if _lang() == "en" else nl

# Dutch number words → digits
DUTCH_NUMBERS = {
    "een": 1, "één": 1, "eentje": 1,
    "twee": 2, "drie": 3, "vier": 4, "vijf": 5,
    "zes": 6, "zeven": 7, "acht": 8, "negen": 9, "tien": 10,
}


def _map_price_field(entities: dict, intent: str) -> dict:
    """Centralized price field mapping between max_price and price_per_ticket."""
    if intent == "SELL_OFFER":
        if entities.get("max_price") is not None and not entities.get("price_per_ticket"):
            entities["price_per_ticket"] = entities.pop("max_price")
        elif entities.get("max_price") is not None and entities.get("price_per_ticket") is not None:
            # Both set for SELL_OFFER — keep price_per_ticket, drop max_price
            entities.pop("max_price")
    elif intent == "BUY_REQUEST":
        if entities.get("price_per_ticket") is not None and not entities.get("max_price"):
            entities["max_price"] = entities.pop("price_per_ticket")
        elif entities.get("price_per_ticket") is not None and entities.get("max_price") is not None:
            # Both set for BUY_REQUEST — keep max_price, drop price_per_ticket
            entities.pop("price_per_ticket")
    return entities


def _sanitize_entities(entities: dict, intent: str) -> dict:
    """Single validation point for all extracted entities."""
    _REJECT_NAMES = {"ja", "nee", "yes", "no", "ok", "oke", "stop", "reset", "cancel"}

    if entities.get("event_name"):
        en = str(entities["event_name"]).strip()
        en_lower = en.lower()
        if en_lower in _REJECT_NAMES or len(en) < 2 or len(en) > 60:
            logger.info(f"Sanitize rejected event_name: '{en}'")
            entities.pop("event_name")

    if entities.get("quantity"):
        try:
            q = int(entities["quantity"])
            if q <= 0 or q > 999:
                entities.pop("quantity")
        except (ValueError, TypeError):
            entities.pop("quantity")

    for price_field in ("price_per_ticket", "max_price"):
        if entities.get(price_field):
            try:
                p = float(entities[price_field])
                if p <= 0:
                    entities.pop(price_field)
            except (ValueError, TypeError):
                entities.pop(price_field)

    entities = _map_price_field(entities, intent)
    return entities


def _parse_dutch_number(text: str):
    """Parse a number from text, supporting Dutch words and digits."""
    text = text.strip().lower()
    for word, num in DUTCH_NUMBERS.items():
        if word in text.split():
            return num
    match = re.search(r"\d+", text)
    if match:
        return int(match.group())
    return None



def _fill_template_with_data(intent: str, collected: dict) -> str:
    """Build a fill-in template pre-filled with any data already collected."""
    from app.message_templates.templates import sell_fill_template, buy_fill_template
    event_name = collected.get("event_name") or ""
    event_date = collected.get("event_date") or ""
    quantity = str(collected["quantity"]) if collected.get("quantity") else ""
    if intent == "SELL_OFFER":
        price = str(collected["price_per_ticket"]) if collected.get("price_per_ticket") else ""
        return sell_fill_template(event_name=event_name, event_date=event_date, quantity=quantity, price=price)
    else:
        price = str(collected["max_price"]) if collected.get("max_price") else ""
        return buy_fill_template(event_name=event_name, event_date=event_date, quantity=quantity, price=price)


async def _verify_event_data(db: AsyncSession, phone: str, data: dict) -> Tuple[dict, Optional[str]]:
    """Verify event name and enrich data. Returns (updated_data, response_message).
    If response_message is present, we should stop and force interaction (ambiguity/error).
    """
    if data.get("event_name") and not data.get("_verified"):
        try:
            from app.services.verifier import verifier
            v_result = await verifier.verify_event(data["event_name"])

            if v_result.get("is_real"):
                data["_verified"] = True
                if v_result.get("official_name"):
                    data["event_name"] = v_result["official_name"]
                
                data["_ticket_types"] = v_result.get("ticket_types", [])
                data["_is_multi_day"] = v_result.get("is_multi_day", False)
                
                # Auto-fill event date from verifier if not already set
                if not data.get("event_date") and v_result.get("event_dates"):
                    data["_suggested_dates"] = v_result["event_dates"]
                
                # TICKET TYPE CHECK — only for multi-day festivals
                ticket_types = v_result.get("ticket_types", [])
                is_multi_day = v_result.get("is_multi_day", False)
                
                if is_multi_day and len(ticket_types) > 1 and not data.get("ticket_type"):
                    types_str = ", ".join(ticket_types[:5])
                    return data, f"Voor {data['event_name']} zijn er verschillende tickets: {types_str}. Welk type zoek je?"
            else:
                # Not found logic
                if not data.get("_verification_warning_sent"):
                    data["_verification_warning_sent"] = True
                    return data, f"Ik kan '{data['event_name']}' niet vinden als een bekend evenement. Weet je zeker dat de schrijfwijze klopt? Zo ja, typ 'ja' om door te gaan."
                else:
                    data["_verified"] = True
        except Exception as e:
            logger.error(f"Verification error: {e}")
            # Fail open
            data["_verified"] = True
            
    return data, None


async def _ai_detect_intent_switch(message: str, current_intent: str) -> Optional[str]:
    """AI-first: detect if the user wants to switch from buy↔sell.

    Returns the NEW intent ("BUY_REQUEST" or "SELL_OFFER") if a switch is detected,
    or None if no switch.
    """
    if not _ai_is_available():
        return None
    from openai import AsyncOpenAI
    import json

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    current_nl = "KOPEN" if current_intent == "BUY_REQUEST" else "VERKOPEN"
    other_nl = "VERKOPEN" if current_intent == "BUY_REQUEST" else "KOPEN"
    other_intent = "SELL_OFFER" if current_intent == "BUY_REQUEST" else "BUY_REQUEST"

    prompt = f"""De gebruiker is bezig met tickets {current_nl}. Analyseer dit bericht:

"{message}"

Wil de gebruiker SWITCHEN naar {other_nl} in plaats daarvan?

Voorbeelden van switchen:
- "nee ik wil eigenlijk verkopen" → JA
- "wacht, ik wil ze juist kopen" → JA
- "ik ben geen koper maar verkoper" → JA
- "nee maar k ben verkoper he" → JA

Voorbeelden van NIET switchen:
- "thuishaven, 3 stuks, 80 euro" → NEE (gewoon data)
- "wat is de prijs?" → NEE (vraag)
- "maak het 90 euro" → NEE (correctie)

Geef alleen JSON: {{"switch": true/false}}"""

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Je bent een JSON parser. Geef alleen geldig JSON terug."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=50,
        )
        result = json.loads(response.choices[0].message.content)
        if result.get("switch"):
            return other_intent
        return None
    except Exception as e:
        logger.error(f"AI intent switch detection error: {e}")
        _ai_mark_failed()
        return None


async def _ai_detect_rebuy_intent(message: str) -> bool:
    """AI-first: detect if the user wants to re-purchase / buy again.

    Catches any phrasing like "alsnog kopen", "koop het maar", "wil die tickets nog",
    "kan ik het toch bestellen", etc. — without hardcoded phrase lists.
    """
    if not _ai_is_available():
        return False
    from openai import AsyncOpenAI
    import json

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    prompt = f"""Analyseer dit Nederlandse bericht. Wil de gebruiker iets (opnieuw) KOPEN of BESTELLEN?

Let op: het gaat om een GENERIEKE koopwens zonder specifiek evenement.
Voorbeelden van JA: "alsnog kopen", "koop het maar", "wil die tickets nog", "doe maar", "ik wil toch kopen", "kan ik het nog bestellen?"
Voorbeelden van NEE: "ik wil tickets kopen voor Lowlands" (specifiek evenement), "hoi", "nee", "bedankt", "hoe werkt het?"

Bericht: "{message}"

Geef alleen JSON: {{"is_rebuy": true/false}}"""

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Je bent een JSON parser. Geef alleen geldig JSON terug."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=50,
        )
        result = json.loads(response.choices[0].message.content)
        return bool(result.get("is_rebuy", False))
    except Exception as e:
        logger.error(f"AI rebuy detection error: {e}")
        _ai_mark_failed()
        return False


async def _ai_resolve_relative_date(date_text: str) -> str:
    """AI-first: resolve relative Dutch date expressions to YYYY-MM-DD.

    Handles: "volgende week donderdag", "over 2 weken", "aankomende zaterdag",
    "morgen", "overmorgen", "deze vrijdag", etc.

    Returns YYYY-MM-DD string or empty string if it can't resolve.
    """
    if not _ai_is_available():
        return ""
    from openai import AsyncOpenAI
    from datetime import date
    import json

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    today = date.today().strftime("%Y-%m-%d")
    weekday_nl = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]
    today_day = weekday_nl[date.today().weekday()]

    prompt = f"""Vandaag is {today} ({today_day}).
De gebruiker zei als datum: "{date_text}"

Geef de exacte datum in YYYY-MM-DD formaat als JSON: {{"date": "YYYY-MM-DD"}}
Als je de datum niet kunt bepalen: {{"date": null}}

BELANGRIJK: "komende", "aankomende", "aanstaande" = de EERSTVOLGENDE keer dat die dag voorkomt.
- Als vandaag zondag is en iemand zegt "komende zondag", bedoelen ze VOLGENDE zondag (7 dagen later), niet vandaag.
- "komende zaterdag" = de eerstvolgende zaterdag NA vandaag.
- "dit weekend" = de eerstvolgende zaterdag + zondag NA vandaag.

Voorbeelden (als vandaag {today} {today_day} is):
- "volgende week donderdag" → de donderdag van volgende week
- "morgen" → {today} + 1 dag
- "aankomende zaterdag" / "komende zaterdag" → eerstvolgende zaterdag NA vandaag
- "komende zondag" → eerstvolgende zondag NA vandaag
- "over 2 weken" → {today} + 14 dagen
- "dit weekend" → eerstvolgende zaterdag NA vandaag

Geef alleen JSON."""

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Je bent een JSON parser. Geef alleen geldig JSON terug."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=30,
        )
        result = json.loads(response.choices[0].message.content)
        resolved = result.get("date")
        if resolved and re.match(r"\d{4}-\d{2}-\d{2}", str(resolved)):
            return resolved
        return ""
    except Exception as e:
        logger.error(f"AI date resolution error: {e}")
        _ai_mark_failed()
        return ""


async def _ai_extract_correction(message: str, intent: str, collected_data: dict) -> dict:
    """AI-first: extract corrected values from a message during CONFIRMING state.

    When the user says things like "Verander de prijs naar 80 euro" or "het zijn 3 tickets",
    extract the corrected field(s).
    """
    if not _ai_is_available():
        return {}
    from openai import AsyncOpenAI
    import json

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    # Build current data summary
    summary = ", ".join(f"{k}={v}" for k, v in collected_data.items() if not k.startswith("_") and v is not None)

    prompt = f"""De gebruiker heeft ticket-gegevens bevestigd en wil nu iets WIJZIGEN.
Huidige gegevens: {summary}

Het bericht van de gebruiker: "{message}"

Welk veld wil de gebruiker wijzigen? Geef alleen de NIEUWE waarde(s) als JSON.

Mogelijke velden: event_name, event_date (YYYY-MM-DD), quantity (integer), price_per_ticket (number), max_price (number)

Regels:
- Geef alleen velden die de gebruiker WIL WIJZIGEN
- Als de gebruiker een prijs noemt, gebruik price_per_ticket (voor verkoop) of max_price (voor koop)
- Geef null voor velden die NIET gewijzigd worden
- Als je niets kunt herkennen, geef een leeg object {{}}

Geef alleen JSON, geen uitleg."""

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Je bent een JSON parser. Geef alleen geldig JSON terug."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=200,
        )
        result = json.loads(response.choices[0].message.content)
        return {k: v for k, v in result.items() if v is not None and k in (
            "event_name", "event_date", "quantity", "price_per_ticket", "max_price"
        )}
    except Exception as e:
        logger.error(f"AI correction extraction error: {e}")
        _ai_mark_failed()
        return {}


async def _ai_is_confirmation(message: str) -> bool:
    """AI-first: detect if a message is a confirmation (yes/agree) in the CONFIRMING context.

    Only called when the message doesn't match known confirm/deny words.
    Returns True if the user is confirming, False otherwise.
    """
    if not _ai_is_available():
        return False
    from openai import AsyncOpenAI
    import json

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    prompt = f"""De gebruiker heeft net een overzicht van hun ticket-gegevens gezien en moet bevestigen of afwijzen.
De gebruiker zei: "{message}"

Is dit een BEVESTIGING (ja/akkoord/klopt)? Geef JSON:
{{"confirm": true}} als de gebruiker bevestigt/akkoord gaat
{{"confirm": false}} als de gebruiker iets anders doet (afwijzen, corrigeren, vraag stellen, etc.)

Voorbeelden bevestiging: "zeker weten!", "doe maar", "ja dat klopt helemaal", "lekker doen", "gaan!", "prima zo", "helemaal top"
Voorbeelden NIET bevestiging: "de prijs moet anders", "nee", "wacht even", "hoeveel kost het?", "verander het aantal"

Geef alleen JSON."""

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Je bent een JSON parser. Geef alleen geldig JSON terug."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=20,
        )
        result = json.loads(response.choices[0].message.content)
        return result.get("confirm", False) is True
    except Exception as e:
        logger.error(f"AI confirmation check error: {e}")
        _ai_mark_failed()
        return False  # Safe fallback: don't auto-confirm on error


async def _ai_extract_event_correction(message: str, current_event: str) -> str:
    """AI-first: detect if the user is correcting the event name during COLLECTING.

    Handles all natural phrasings:
    - "het evenement is X", "de naam is X", "ik bedoel X"
    - "nee het heet X", "X is het evenement", "X heet het"
    - "niet Y maar X"

    Returns the corrected event name, or empty string if no correction detected.
    """
    if not _ai_is_available():
        return ""
    from openai import AsyncOpenAI
    import json

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    prompt = f"""Het huidige evenement in het systeem is: "{current_event}"
De gebruiker zei: "{message}"

Probeert de gebruiker de evenementnaam te CORRIGEREN of te VERANDEREN?

Als JA: geef de NIEUWE evenementnaam als JSON: {{"event_name": "de nieuwe naam"}}
Als NEE (de gebruiker praat over iets anders): geef {{"event_name": null}}

Voorbeelden:
- "het evenement is Thuishaven" → {{"event_name": "Thuishaven"}}
- "ik bedoel Dekmantel" → {{"event_name": "Dekmantel"}}
- "nee het heet Lowlands" → {{"event_name": "Lowlands"}}
- "de naam is DGTL" → {{"event_name": "DGTL"}}
- "niet {current_event} maar Soenda" → {{"event_name": "Soenda"}}
- "X heet het" → {{"event_name": "X"}}
- "hoeveel kost het?" → {{"event_name": null}}
- "2 stuks" → {{"event_name": null}}

Geef alleen JSON."""

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Je bent een JSON parser. Geef alleen geldig JSON terug."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=50,
        )
        result = json.loads(response.choices[0].message.content)
        name = result.get("event_name")
        if name and isinstance(name, str) and len(name.strip()) >= 2:
            return name.strip()
        return ""
    except Exception as e:
        logger.error(f"AI event correction error: {e}")
        _ai_mark_failed()
        return ""


async def _ai_interpret_multi_event_control(message: str, total: int, done: int) -> dict:
    """AI-first: interpret a message during multi-event flow.

    Returns: {"action": "done"} or {"action": "change_count", "new_count": N} or {"action": "continue"}
    """
    if not _ai_is_available():
        return {"action": "done"}  # Safe: release user from flow on AI outage
    from openai import AsyncOpenAI
    from app.config import settings
    import json

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    prompt = f"""De gebruiker is bezig met het invoeren van meerdere evenementen (tickets verkopen).
Status: {done} van {total} evenementen ingevoerd.

De gebruiker zei: "{message}"

Wat bedoelt de gebruiker? Geef ALLEEN JSON terug:
- Als de gebruiker KLAAR is / wil stoppen / wil annuleren / gefrustreerd is / zegt dat dit alles was: {{"action": "done"}}
- Als de gebruiker het AANTAL wil WIJZIGEN (bijv. "alleen 2", "maar drie"): {{"action": "change_count", "new_count": <getal>}}
- Als de gebruiker NIEUWE EVENT DATA stuurt (evenementnaam, datum, prijs, etc.): {{"action": "continue"}}

BELANGRIJK: als de gebruiker negatief/gefrustreerd klinkt of wil stoppen, kies ALTIJD "done". Liever onterecht stoppen dan de gebruiker vastzetten.

Voorbeelden:
- "alleen deze twee kaartjes" → {{"action": "change_count", "new_count": 2}}
- "klaar" → {{"action": "done"}}
- "dat was het" → {{"action": "done"}}
- "maar 2 evenementen" → {{"action": "change_count", "new_count": 2}}
- "Thuishaven, 5 april, 3 stuks" → {{"action": "continue"}}
- "nee toch maar 4" → {{"action": "change_count", "new_count": 4}}
- "ik wil niet meer" → {{"action": "done"}}
- "laat maar" → {{"action": "done"}}
- "dit is verkeerd" → {{"action": "done"}}
- "nee stop" → {{"action": "done"}}
- "ik ben klaar" → {{"action": "done"}}
- "dit klopt niet" → {{"action": "done"}}
- "vergeet het" → {{"action": "done"}}
- "nee" → {{"action": "done"}}"""

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Je bent een JSON parser. Geef alleen geldig JSON terug."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=50,
        )
        result = json.loads(response.choices[0].message.content)
        logger.info(f"Multi-event control AI: {result}")
        return result
    except Exception as e:
        logger.error(f"Multi-event control AI failed: {e}")
        _ai_mark_failed()
        return {"action": "done"}  # Safe fallback: let user out rather than trap them


async def _split_multi_event_message(message: str) -> list:
    """Use GPT to split a message containing multiple events into separate listing blocks.

    Returns a list of dicts with keys: event_name, event_date, quantity, price_per_ticket.
    Returns empty list if the message is about a single event.
    """
    if not _ai_is_available():
        return []
    from openai import AsyncOpenAI
    from app.config import settings
    import json

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    from datetime import date
    today = date.today()

    prompt = f"""Analyseer dit Nederlandse bericht. Bevat het meerdere evenementen waarvoor iemand tickets wil verkopen/kopen?
Datum vandaag: {today.strftime('%Y-%m-%d')}

Als JA (2+ verschillende evenementen): geef {{"events": [...]}} met per evenement: {{"event_name": "...", "event_date": "...", "quantity": N, "price_per_ticket": N}}
Als NEE (slechts 1 evenement): geef {{"events": []}}

Regels:
- Gebruik null voor ontbrekende velden
- event_date in YYYY-MM-DD formaat. Als er geen jaar genoemd wordt, gebruik {today.year} (of {today.year + 1} als de datum al verstreken is)
- quantity en price_per_ticket als getallen
- BELANGRIJK: Als er twee of meer VERSCHILLENDE evenementnamen worden genoemd (bijv. "thuishaven" EN "scaleup030"), dan zijn het meerdere evenementen — zelfs als ze in één doorlopend bericht staan zonder duidelijke scheiding.
- De scheiding kan zijn: komma, newline, "en", "---", of gewoon achter elkaar.
- Voorbeeld: "thuishaven lammers\\n2026-03-03\\n2 stukken\\n90 euros,\\nevent is scaleup030, 3 mei, 2 stuks, 30 euro" = 2 evenementen.

Bericht: "{message}"

Geef alleen JSON, geen uitleg."""

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Je bent een JSON parser. Geef alleen geldig JSON terug."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=500,
        )
        result = json.loads(response.choices[0].message.content)
        # Handle both {"listings": [...]} and direct [...] formats
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            for key in ("listings", "events", "items", "data"):
                if isinstance(result.get(key), list):
                    return result[key]
        return []
    except Exception as e:
        logger.error(f"Multi-event split error: {e}")
        _ai_mark_failed()
        return []


async def _handle_batch_sell(db: AsyncSession, phone: str, blocks: list) -> str:
    """Process multiple sell listings.

    blocks can be either:
    - list of raw text strings (from --- split)
    - list of dicts with keys like event_name, quantity, etc. (from GPT splitter)
    """
    from app.ai.extractor import normalize_entities
    saved = []
    failed = []

    for i, block in enumerate(blocks, 1):
        if isinstance(block, dict):
            # Pre-parsed from GPT splitter
            entities = {k: v for k, v in block.items() if v is not None}
            entities = normalize_entities(entities)
        else:
            # Raw text block — use AI classifier for entity extraction
            block_classification = await classify_message(block)
            entities = {k: v for k, v in (block_classification.entities or {}).items() if v is not None}
            entities = normalize_entities(entities)

        # Centralized price field mapping
        entities = _map_price_field(entities, "SELL_OFFER")

        missing = validate_entities("SELL_OFFER", entities)
        if missing:
            preview = block.split("\n")[0][:40] if isinstance(block, str) else entities.get("event_name", "?")
            failed.append((i, preview, missing))
        else:
            entities["phone"] = phone
            offer = await _save_sell_offer(db, entities)
            saved.append((entities.get("event_name", "?"), entities.get("quantity", 1)))

            # Broadcast + waitlist per offer
            try:
                from app.services.broadcast import broadcast_new_listing
                from decimal import Decimal
                price = Decimal(str(entities.get("price_per_ticket", 0)))
                await broadcast_new_listing(
                    event_name=entities.get("event_name", ""),
                    quantity=entities.get("quantity", 1),
                    price_per_ticket=price,
                    seller_phone=phone,
                )
            except Exception:
                pass
            try:
                from app.services.matching import process_waitlist
                await process_waitlist(db, offer)
            except Exception:
                pass
            try:
                from app.services.group_queue import enqueue_group_post
                from app.message_templates.templates import sell_offer_group_broadcast
                from datetime import date as _dt
                _evt_date = None
                if entities.get("event_date"):
                    try: _evt_date = _dt.fromisoformat(str(entities["event_date"]))
                    except (ValueError, TypeError): pass
                await enqueue_group_post(
                    db, sell_offer_id=offer.id,
                    event_name=entities.get("event_name", ""),
                    event_date=_evt_date,
                    message_body=sell_offer_group_broadcast(
                        event_name=entities.get("event_name", ""),
                        event_date=entities.get("event_date", ""),
                        quantity=entities.get("quantity", 1),
                        price_per_ticket=entities.get("price_per_ticket", "N/A"),
                        ticket_type=entities.get("ticket_type", ""),
                    ),
                )
            except Exception:
                pass

    await db.commit()

    # Keep intent for follow-up
    await update_session(db, phone, current_intent="SELL_OFFER", current_step=IDLE, collected_data={})

    # Build response
    lines = []
    if saved:
        lines.append(f"✅ {len(saved)} aanbod(en) opgeslagen:\n")
        for name, qty in saved:
            lines.append(f"  • {name} ({qty}x)")
    if failed:
        lines.append(f"\n⚠️ {len(failed)} aanbod(en) niet compleet:\n")
        for idx, preview, missing_fields in failed:
            lines.append(f"  • #{idx} \"{preview}...\" — mist: {', '.join(missing_fields)}")
        lines.append("\nStuur de ontbrekende gegevens opnieuw per aanbod.")

    lines.append("\n🎟️ Heb je nog meer tickets? Typ *ja* voor een nieuw formulier.")
    return "\n".join(lines)


async def _handle_multi_event_batch(
    db: AsyncSession, phone: str, blocks: list, multi_total: int, multi_done: int
) -> str:
    """Process multiple events sent in one message during multi-event flow.

    Unlike _handle_batch_sell(), this respects the multi-event tracking
    (_multi_event_total / _multi_event_done) and continues the flow.
    """
    from app.message_templates.templates import sell_fill_template

    saved = []
    failed = []

    for block in blocks:
        if isinstance(block, dict):
            entities = {k: v for k, v in block.items() if v is not None}
            entities = normalize_entities(entities)
        else:
            block_classification = await classify_message(block)
            entities = {k: v for k, v in (block_classification.entities or {}).items() if v is not None}
            entities = normalize_entities(entities)

        entities = _map_price_field(entities, "SELL_OFFER")
        entities = _sanitize_entities(entities, "SELL_OFFER")

        missing = validate_entities("SELL_OFFER", entities)
        if missing:
            preview = block.split("\n")[0][:40] if isinstance(block, str) else entities.get("event_name", "?")
            failed.append((preview, missing))
        else:
            entities["phone"] = phone
            offer = await _save_sell_offer(db, entities)
            multi_done += 1
            evt = entities.get("event_name", "?")
            qty = entities.get("quantity", 1)
            price = entities.get("price_per_ticket", 0)
            saved.append((evt, qty, price))

            # Broadcast + waitlist per offer
            try:
                from app.services.broadcast import broadcast_new_listing
                from decimal import Decimal
                await broadcast_new_listing(
                    event_name=evt, quantity=qty,
                    price_per_ticket=Decimal(str(price)), seller_phone=phone,
                )
            except Exception:
                pass
            try:
                from app.services.matching import process_waitlist
                await process_waitlist(db, offer)
            except Exception:
                pass
            try:
                from app.services.group_queue import enqueue_group_post
                from app.message_templates.templates import sell_offer_group_broadcast
                from datetime import date as _dt
                _evt_date = None
                if entities.get("event_date"):
                    try: _evt_date = _dt.fromisoformat(str(entities["event_date"]))
                    except (ValueError, TypeError): pass
                await enqueue_group_post(
                    db, sell_offer_id=offer.id,
                    event_name=evt, event_date=_evt_date,
                    message_body=sell_offer_group_broadcast(
                        event_name=evt,
                        event_date=entities.get("event_date", ""),
                        quantity=qty,
                        price_per_ticket=price,
                    ),
                )
            except Exception:
                pass

    await db.commit()

    # Build response
    lines = []
    for evt, qty, price in saved:
        lines.append(f"✅ *{evt}* opgeslagen! ({qty}x €{price})")

    if failed:
        for preview, missing_fields in failed:
            lines.append(f"⚠️ \"{preview}\" — mist: {', '.join(missing_fields)}")

    # Continue multi-event flow or finish
    if multi_total and multi_done < multi_total:
        remaining = multi_total - multi_done
        await update_session(
            db, phone,
            current_intent="SELL_OFFER",
            current_step=COLLECTING,
            collected_data={"_multi_event_total": multi_total, "_multi_event_done": multi_done},
        )
        lines.append(f"\n📋 {multi_done}/{multi_total} evenementen gedaan — nog {remaining} te gaan.\n")
        lines.append(sell_fill_template())
    elif multi_total and multi_done >= multi_total:
        await update_session(db, phone, current_intent=None, current_step=IDLE, collected_data={})
        lines.append(f"\n🎉 Alle {multi_total} evenementen zijn opgeslagen! Je hoort van ons zodra er kopers zijn.")
    else:
        # No multi_total set — just finish
        await update_session(db, phone, current_intent="SELL_OFFER", current_step=IDLE, collected_data={})
        lines.append("\n🎟️ Heb je nog meer tickets? Typ *ja* voor een nieuw formulier.")

    return "\n".join(lines)


async def process_message(
    db: AsyncSession, phone: str, message: str, push_name: str = ""
) -> str:
    """Process an incoming WhatsApp message through the state machine.

    Args:
        db: Database session
        phone: Sender phone (E.164)
        message: Message text
        push_name: WhatsApp profile name (from webhook contacts)

    Returns:
        Reply message to send back
    """
    # Serialize messages per phone to prevent race conditions (D2).
    # Without this, rapid messages ("Coldplay", "2 tickets", "max €100")
    # all read the same session state and overwrite each other's data.
    phone_lock = await _get_phone_lock(phone)
    async with phone_lock:
        return await _process_message_inner(db, phone, message, push_name=push_name)


async def _process_message_inner(
    db: AsyncSession, phone: str, message: str, push_name: str = ""
) -> str:
    """Inner message processor — called under per-phone lock."""
    # Get or create conversation session
    session = await get_or_create_session(db, phone)

    # Store WhatsApp push_name in session for use when saving offers/requests
    if push_name and push_name.strip():
        data = dict(session.collected_data or {})
        if data.get("_push_name") != push_name:
            data["_push_name"] = push_name.strip()
            await update_session(db, phone, collected_data=data)
            session = await get_or_create_session(db, phone)

    # FIX 3: If bot is paused for this chat (admin takeover), skip all processing
    if getattr(session, "bot_paused", False):
        logger.info(f"Bot paused for {phone}, skipping auto-reply")
        return ""

    # Detect user language (sticky: once English, stays English until Dutch detected)
    session_lang = (session.collected_data or {}).get("_lang", "nl")
    lang = _detect_language(message, session_lang)
    _request_lang.set(lang)
    if lang != session_lang:
        data = dict(session.collected_data or {})
        data["_lang"] = lang
        await update_session(db, phone, collected_data=data)
        session = await get_or_create_session(db, phone)

    # Fetch recent conversation history for AI context
    conversation_history = await get_recent_history(db, phone)

    # GLOBAL reset/stop — works from ANY state
    msg_lower = message.strip().lower()
    _RESET_EXACT = {"stop", "reset", "annuleer", "cancel", "opnieuw", "herstart", "restart",
                    "laat maar", "vergeet het", "nee stop", "stop maar", "ik stop",
                    "start over", "never mind", "forget it"}
    _RESET_CONTAINS = ("ik wil niet meer", "ik wil stoppen", "laat maar zitten",
                       "dit klopt niet", "dit is verkeerd", "begin opnieuw",
                       "i want to stop", "start over", "i don't want")
    if msg_lower in _RESET_EXACT or any(phrase in msg_lower for phrase in _RESET_CONTAINS):
        await reset_session(db, phone)
        return _t("Oké, we beginnen opnieuw! Wil je tickets kopen of verkopen?",
                   "OK, starting fresh! Do you want to buy or sell tickets?")

    # Fix #5: Session timeout — reset stale sessions (>24h inactive)
    # Notifies user and preserves a summary so they can pick up where they left off.
    if session.current_step != IDLE and session.last_updated:
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        last = session.last_updated
        if last.tzinfo is None:
            from datetime import timezone as tz
            last = last.replace(tzinfo=tz.utc)
        if now - last > timedelta(hours=SESSION_TIMEOUT_HOURS):
            logger.info(f"Session timeout for {phone}: last updated {last}")
            # Build summary of expired session for future context
            expired_data = dict(session.collected_data or {})
            expired_intent = session.current_intent
            expired_step = session.current_step
            summary_parts = []
            if expired_intent:
                summary_parts.append(f"intent={expired_intent}")
            if expired_data.get("event_name"):
                summary_parts.append(f"event={expired_data['event_name']}")
            if expired_data.get("quantity"):
                summary_parts.append(f"qty={expired_data['quantity']}")
            for pf in ("max_price", "price_per_ticket"):
                if expired_data.get(pf):
                    summary_parts.append(f"{pf}={expired_data[pf]}")
            expired_summary = ", ".join(summary_parts) if summary_parts else None

            # Reset but store the summary so AI knows what the user was doing
            await update_session(
                db, phone,
                current_intent=None,
                current_step=IDLE,
                collected_data={"_expired_session": expired_summary} if expired_summary else {},
            )
            session = await get_or_create_session(db, phone)

            # Build a notification message
            intent_nl = "kopen" if expired_intent == "BUY_REQUEST" else "verkopen"
            notify = "Hey! 👋 Je was eerder bezig met tickets "
            if expired_data.get("event_name"):
                notify += f"{intent_nl} voor *{expired_data['event_name']}*, "
            else:
                notify += f"{intent_nl}, "
            notify += "maar je sessie is verlopen.\n\n"
            notify += "Wil je verdergaan waar je was gebleven? Stuur gewoon je gegevens opnieuw, of begin iets nieuws!"
            return notify

    # Per-request circuit breaker — trips on first OpenAI failure, skips subsequent calls
    _cb = _CircuitBreaker()
    _request_circuit.set(_cb)

    # AI-first: ALWAYS classify every message — extracts ALL entities in one call
    try:
        classification = await classify_message(message, conversation_history)
    except Exception as e:
        logger.error(f"Classifier failed for {phone}: {e}")
        _cb.trip()
        # Graceful degradation: preserve current state, don't let re-classification corrupt it
        if session.current_step == COLLECTING:
            missing = validate_entities(session.current_intent, session.collected_data or {})
            if missing:
                return ask_missing_field(missing[0], session.current_intent)
            # All data present — offer confirmation
            return _format_confirmation(session.current_intent, session.collected_data or {})
        elif session.current_step == CONFIRMING:
            # Preserve confirmation state — re-show the summary
            return (
                _t("Er ging even iets mis, maar je gegevens zijn bewaard. "
                   "Typ *ja* om te bevestigen of *nee* om te wijzigen.\n\n",
                   "Something went wrong, but your data is saved. "
                   "Type *yes* to confirm or *no* to change.\n\n")
                + _format_confirmation(session.current_intent, session.collected_data or {})
            )
        return _t("Er ging even iets mis aan onze kant. Probeer het nog een keer! 🙏",
                   "Something went wrong on our end. Please try again! 🙏")

    # Log AI decision
    ai_log = AILog(
        phone=phone,
        raw_message=message,
        ai_response=classification.raw_ai_response,
        intent=classification.intent,
        confidence=classification.confidence,
        classification_method=classification.method,
        prompt_version=classification.prompt_version,
    )
    db.add(ai_log)

    # GLOBALLY INTERCEPT ESCALATION & GENERAL QUESTIONS
    if classification.intent == "ENTRANCE_BLOCKED":
        from app.services.escalation import escalate_entrance_blocked
        from app.message_templates.templates import escalation_entrance_blocked_user
        event_name = (classification.entities or {}).get("event_name", "")
        await escalate_entrance_blocked(phone, event_name)
        await reset_session(db, phone)
        return escalation_entrance_blocked_user()

    elif classification.intent == "MISSING_PROOF":
        from app.services.escalation import escalate_missing_proof
        from app.message_templates.templates import escalation_missing_proof_user
        await escalate_missing_proof(phone, message)
        await reset_session(db, phone)
        return escalation_missing_proof_user()

    elif classification.intent == "SUPPORT":
        await reset_session(db, phone)
        return "Ik heb je bericht doorgezet naar ons team, ze nemen zo snel mogelijk contact met je op!"

    elif classification.intent == "GENERAL_QUESTION":
        # BUG 7 FIX: If user is mid-flow (COLLECTING/CONFIRMING), check if the message
        # contains entity-like data (dates, numbers, prices) before intercepting as Q&A.
        # Messages like "het is op 3 maart" or "De datum is 3 maart 2026" should be
        # treated as data input, not general questions.
        if session.current_step in (COLLECTING, CONFIRMING):
            # Check if classifier already extracted entities despite GENERAL_QUESTION intent
            real_entities = {
                k: v for k, v in (classification.entities or {}).items()
                if v is not None and k in ("event_name", "event_date", "ticket_type", "quantity", "max_price", "price_per_ticket")
            }
            # Also check for entity-like data the classifier missed.
            # Instead of fragile regex patterns, use a broad heuristic first,
            # then let the collecting/confirming handler's AI extractor do the real work.
            if not real_entities:
                _msg_lower = message.strip().lower()
                # Broad heuristic: if message contains a number, price keyword, date keyword,
                # or correction keyword, it's likely data input, not a question.
                _has_data_signal = bool(
                    # Any number in the message (prices, quantities, dates)
                    re.search(r'\d', _msg_lower)
                    # Correction/update verbs
                    or re.search(r'(?:verhoog|verlaag|wijzig|verander|aanpas|maak|zet)', _msg_lower)
                    # Price keywords without numbers (e.g., "gratis", "maximaal")
                    or re.search(r'(?:euro|€|prijs|kosten|bedrag|gratis|maximaal|max)', _msg_lower)
                    # Date keywords
                    or re.search(r'(?:volgende|aankomende|komende|morgen|overmorgen|januari|februari|maart|april|mei|juni|juli|augustus|september|oktober|november|december)', _msg_lower)
                    # Quantity keywords
                    or re.search(r'(?:stuks?|tickets?|kaarten?|aantal)', _msg_lower)
                )
                if _has_data_signal:
                    real_entities = {"_data_signal_detected": True}
            # In CONFIRMING, always let the handler process — it has confirm/deny/correction logic
            # that the Q&A handler would swallow (e.g., "doe maar", "klopt niet", "verander het")
            if session.current_step == CONFIRMING:
                real_entities = real_entities or {"_confirming_bypass": True}
            if real_entities:
                # This message contains usable data — let the collecting/confirming handler process it
                logger.info(f"GENERAL_QUESTION bypassed for {phone}: message contains entities {list(real_entities.keys())}")
                pass  # Fall through to the state router below
            else:
                from app.ai.qa import answer_general_question
                _role = "seller" if session.current_intent == "SELL_OFFER" else "buyer" if session.current_intent == "BUY_REQUEST" else None
                answer = await answer_general_question(message, conversation_history, user_role=_role)
                if session.current_step == COLLECTING:
                    from app.ai.extractor import validate_entities
                    missing = validate_entities(session.current_intent, session.collected_data or {})
                    if missing:
                        from app.message_templates.templates import ask_missing_field as _amf
                        answer += _t(f"\n\nMaar even terug naar je aanvraag — {_amf(missing[0], session.current_intent, lang=_lang())}",
                                     f"\n\nBut back to your request — {_amf(missing[0], session.current_intent, lang=_lang())}")
                return answer
        else:
            # IDLE: determine user role from recent history
            from app.ai.qa import answer_general_question
            _role = _detect_user_role(session, conversation_history)
            answer = await answer_general_question(message, conversation_history, user_role=_role)
            return answer

    elif classification.intent == "PAYMENT_CONFIRMATION":
        # Look up the buyer's most recent reservation to send seller info
        try:
            from sqlalchemy import select
            from app.models.reservation import Reservation, ReservationStatus
            from app.models.buy_request import BuyRequest
            from app.crud.sell_offers import get_sell_offer

            # Find PAID reservations for this buyer
            paid_query = (
                select(Reservation)
                .join(BuyRequest, Reservation.buy_request_id == BuyRequest.id)
                .where(
                    BuyRequest.phone == phone,
                    Reservation.status == ReservationStatus.PAID,
                )
                .order_by(Reservation.updated_at.desc())
                .limit(1)
            )
            result = await db.execute(paid_query)
            paid_reservation = result.scalar_one_or_none()

            if paid_reservation:
                offer = await get_sell_offer(db, paid_reservation.sell_offer_id)
                if offer:
                    from app.message_templates.templates import payment_received_message
                    return payment_received_message(
                        seller_name=f"{offer.first_name} {offer.last_name or ''}".strip() or "Verkoper",
                        seller_phone=offer.phone,
                    )

            # Check if there is a PENDING reservation (payment not yet confirmed by Stripe)
            pending_query = (
                select(Reservation)
                .join(BuyRequest, Reservation.buy_request_id == BuyRequest.id)
                .where(
                    BuyRequest.phone == phone,
                    Reservation.status == ReservationStatus.PENDING,
                )
                .order_by(Reservation.created_at.desc())
                .limit(1)
            )
            result = await db.execute(pending_query)
            pending_reservation = result.scalar_one_or_none()

            if pending_reservation:
                return (
                    "Je betaling wordt nog verwerkt door onze betaalprovider. "
                    "Dit duurt meestal niet langer dan een paar minuten. ⏳\n\n"
                    "Zodra de betaling is bevestigd, ontvang je automatisch de contactgegevens van de verkoper!"
                )
        except Exception as e:
            logger.error(f"Error looking up payment for {phone}: {e}")

        return "Bedankt! We controleren je betaling. Je ontvangt bericht zodra deze is bevestigd. ✅"

    elif classification.intent == "STATUS_CHECK":
        return "Momentje, ik check even de status voor je..."

    # ── Batch sell: multiple listings separated by --- (works from any state) ──
    _existing_data = (session.collected_data or {})
    _multi_total = _existing_data.get("_multi_event_total", 0)
    _multi_done = _existing_data.get("_multi_event_done", 0)

    if "---" in message and (
        classification.intent == "SELL_OFFER"
        or session.current_intent == "SELL_OFFER"
    ):
        blocks = [b.strip() for b in message.split("---") if b.strip()]
        if len(blocks) >= 2:
            if _multi_total:
                # Inside multi-event flow — track progress
                return await _handle_multi_event_batch(db, phone, blocks, _multi_total, _multi_done)
            return await _handle_batch_sell(db, phone, blocks)

    # ── Smart batch sell: detect multiple events without --- separator ──
    if (
        classification.intent == "SELL_OFFER"
        or session.current_intent == "SELL_OFFER"
    ) and "---" not in message and len(message) > 40:
        # Quick heuristic: multiple lines or keywords like "en ook", "daarnaast", "plus"
        _ml = message.lower()
        _multi_hints = (
            "\n" in message.strip() and message.strip().count("\n") >= 3
            or re.search(r"\b(?:en ook|daarnaast|plus|verder nog|ook nog)\b", _ml)
            or len(re.findall(r"\b(?:tickets?|kaarten?|kaartjes?|stuks?)\b", _ml)) >= 2
            or re.search(r"\b(?:verschillende|meerdere|diverse)\s+(?:evenementen|events?|festivals?|concerten)\b", _ml)
            or re.search(r"\b\d+\s+(?:verschillende|meerdere)\s+(?:evenementen|events?)\b", _ml)
        )
        if _multi_hints:
            listings = await _split_multi_event_message(message)
            if len(listings) >= 2:
                if _multi_total:
                    # Inside multi-event flow — track progress
                    return await _handle_multi_event_batch(db, phone, listings, _multi_total, _multi_done)
                return await _handle_batch_sell(db, phone, listings)
            elif re.search(r"\b(?:verschillende|meerdere|diverse)\s+(?:evenementen|events?)\b", _ml):
                # User wants to sell for multiple events but didn't name them
                # Try to extract the count (e.g. "3 verschillende evenementen")
                count_match = re.search(r"(\d+)\s+(?:verschillende|meerdere|diverse)", _ml)
                multi_total = int(count_match.group(1)) if count_match else 0
                collected = {"_multi_event_total": multi_total, "_multi_event_done": 0}
                await update_session(db, phone, current_intent="SELL_OFFER", current_step=COLLECTING, collected_data=collected)
                count_str = f" ({multi_total} stuks)" if multi_total else ""
                return (
                    f"Helemaal goed, meerdere evenementen kan!{count_str} 🎟️\n\n"
                    "Stuur de info per evenement, gescheiden door ---\n"
                    "Bijvoorbeeld:\n\n"
                    "Thuishaven, 5 april, 3 stuks, €80 per ticket\n"
                    "---\n"
                    "Dekmantel, 1 augustus, 2 stuks, €120 per ticket\n\n"
                    "Of stuur ze één voor één, dat kan ook!"
                )

    # Route based on current state and intent
    if session.current_step == IDLE:
        return await _handle_idle(db, phone, session, classification, message, conversation_history)
    elif session.current_step == COLLECTING:
        return await _handle_collecting(db, phone, session, classification, message, conversation_history)
    elif session.current_step == CONFIRMING:
        return await _handle_confirming(db, phone, session, message, classification, conversation_history)
    else:
        return welcome_message()


async def _handle_expired_rebuy(db: AsyncSession, phone: str) -> Optional[str]:
    """Handle re-purchase of expired reservation. Returns reply or None."""
    from sqlalchemy import select
    from app.models.reservation import Reservation, ReservationStatus
    from app.models.buy_request import BuyRequest
    from datetime import datetime, timezone, timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    expired_query = (
        select(Reservation, BuyRequest)
        .join(BuyRequest, Reservation.buy_request_id == BuyRequest.id)
        .where(
            BuyRequest.phone == phone,
            Reservation.status == ReservationStatus.EXPIRED,
            Reservation.updated_at >= cutoff,
        )
        .order_by(Reservation.updated_at.desc())
        .limit(1)
    )
    result = await db.execute(expired_query)
    row = result.first()

    if not row:
        return None

    expired_reservation, buy_request = row[0], row[1]
    collected = {
        "event_name": buy_request.event_name,
        "quantity": buy_request.quantity,
        "first_name": buy_request.first_name,
        "last_name": buy_request.last_name or "",
        "phone": buy_request.phone,
        "email": buy_request.email or "",
    }
    if buy_request.event_date:
        collected["event_date"] = buy_request.event_date.strftime("%Y-%m-%d")
    if buy_request.max_price_per_ticket:
        collected["max_price"] = float(buy_request.max_price_per_ticket)
    if buy_request.ticket_type:
        collected["ticket_type"] = buy_request.ticket_type

    from decimal import Decimal
    max_price = Decimal(str(collected["max_price"])) if collected.get("max_price") else None

    from app.schemas.buy_request import BuyRequestCreate
    new_buy = await create_buy_request(db, BuyRequestCreate(
        first_name=collected.get("first_name", ""),
        last_name=collected.get("last_name", ""),
        phone=phone,
        email=collected.get("email", ""),
        event_name=collected["event_name"],
        event_date=buy_request.event_date,
        ticket_type=collected.get("ticket_type"),
        quantity=collected["quantity"],
        max_price_per_ticket=max_price,
        agreement_accepted=True,
        source="WHATSAPP",
    ))
    await db.commit()

    match_result = await auto_match_and_notify(
        db,
        buy_request_id=new_buy.id,
        event_name=collected["event_name"],
        quantity=collected["quantity"],
        max_price=max_price,
        buyer_phone=phone,
        ticket_type=collected.get("ticket_type"),
    )

    if match_result and not match_result.get("pending_confirmation"):
        return (
            f"Nice, er zijn nog tickets voor {collected['event_name']}! 🎉\n\n"
            f"Betaal de aanbetaling van €{match_result['deposit_amount']:.2f} om ze te reserveren:\n"
            f"{match_result['checkout_url']}\n\n"
            f"Je hebt {settings.RESERVATION_TIMEOUT_MINUTES} minuten om te betalen."
        )
    elif match_result and match_result.get("pending_confirmation"):
        return (
            "We hebben een mogelijke match gevonden! We checken even bij de verkoper "
            "of het nog beschikbaar is. Je hoort van ons!"
        )
    else:
        return (
            f"Helaas, de tickets voor {collected['event_name']} zijn inmiddels weg.\n\n"
            "We hebben je zoekopdracht opnieuw opgeslagen — zodra er iets beschikbaar komt, hoor je van ons!"
        )


async def _handle_idle(
    db: AsyncSession,
    phone: str,
    session,
    classification: ClassificationResult,
    raw_message: str = "",
    conversation_history: list = None,
) -> str:
    """Handle a message when user has no active conversation."""

    stripped = raw_message.strip().lower()
    _raw_stripped = raw_message.strip()
    _AFFIRM_EMOJI = {"👍", "👍🏻", "👍🏼", "👍🏽", "👍🏾", "👍🏿", "✅", "👌"}
    _DENY_EMOJI_IDLE = {"👎", "👎🏻", "👎🏼", "👎🏽", "👎🏾", "👎🏿", "❌"}
    is_affirm = stripped in ("ja", "yes", "yep", "jep") or _raw_stripped in _AFFIRM_EMOJI
    is_deny = stripped in ("nee", "no") or _raw_stripped in _DENY_EMOJI_IDLE

    # Fix #1: Context-aware "ja"/"nee" routing via _pending_action
    pending_action = (session.collected_data or {}).get("_pending_action")

    # If message starts with "nee" but has more text (like "nee ik wil kopen"),
    # consume the pending_action (treat as deny) but DON'T return the deny response —
    # let the rest of the message be processed as a new intent.
    if pending_action and not is_affirm and not is_deny and stripped.startswith("nee "):
        logger.info(f"Clearing stale _pending_action '{pending_action}' — message starts with 'nee' but has more content")
        data = dict(session.collected_data or {})
        data.pop("_pending_action", None)
        data.pop("_last_saved_id", None)
        data.pop("_last_saved_type", None)
        await update_session(db, phone, collected_data=data)
        pending_action = None  # Don't enter the pending_action block below

    if (is_affirm or is_deny) and pending_action:
        # Always clear _pending_action first — it's consumed regardless of outcome
        data = dict(session.collected_data or {})
        data.pop("_pending_action", None)
        await update_session(db, phone, collected_data=data)

        if pending_action == "seller_confirmation":
            from app.services.matching import handle_seller_confirmation
            confirmation_reply = await handle_seller_confirmation(
                db, phone, confirmed=is_affirm
            )
            if confirmation_reply:
                return confirmation_reply

        elif pending_action == "expired_rebuy":
            if is_affirm:
                return await _handle_expired_rebuy(db, phone)
            else:
                await reset_session(db, phone)
                return _t("Oké, geen probleem! Laat maar weten als je iets anders nodig hebt. 👋",
                          "OK, no problem! Let me know if you need anything else. 👋")

        elif pending_action == "more_sells":
            if is_affirm:
                from app.message_templates.templates import sell_fill_template
                await update_session(
                    db, phone,
                    current_intent="SELL_OFFER",
                    current_step=COLLECTING,
                    collected_data={},
                )
                return _t("Top! Laten we het volgende aanbod invullen. 🎟️\n\n",
                          "Great! Let's fill in the next listing. 🎟️\n\n") + sell_fill_template(lang=_lang())
            else:
                await reset_session(db, phone)
                return _t("Oké, alles is opgeslagen! Je hoort van ons zodra er kopers zijn. 👋",
                          "OK, everything is saved! We'll let you know when there are buyers. 👋")

    # Undo last save: detect regret phrases when _last_saved_id is present
    last_saved_id = (session.collected_data or {}).get("_last_saved_id")
    last_saved_type = (session.collected_data or {}).get("_last_saved_type")
    if last_saved_id and pending_action in ("undo_buy", "more_sells"):
        _undo_phrases = {"dat was fout", "wacht", "undo", "ongedaan", "annuleer dat",
                         "dat klopt niet", "fout", "verkeerd", "dat was verkeerd",
                         "nee wacht", "wacht even", "oeps", "foutje"}
        _undo_contains = ("was fout", "per ongeluk", "niet de bedoeling", "wil annuleren",
                          "maak ongedaan", "trek terug", "wil het niet meer")
        _msg = raw_message.strip().lower()
        is_undo = _msg in _undo_phrases or any(p in _msg for p in _undo_contains)
        if is_undo:
            cancel_result = await _cancel_last_saved(db, last_saved_id, last_saved_type or pending_action)
            await reset_session(db, phone)
            if cancel_result:
                return _t("↩️ Geannuleerd! Je laatste aanvraag is verwijderd. Laat maar weten als je opnieuw wilt beginnen.",
                          "↩️ Cancelled! Your last request has been removed. Let me know if you want to start over.")
            else:
                return _t("Hmm, kon het niet meer annuleren — mogelijk is er al een match gemaakt. Neem contact op met support als er iets mis is.",
                          "Hmm, couldn't cancel anymore — a match may already have been made. Contact support if something's wrong.")

    # NOTE: Legacy fallback for "ja"/"nee" without _pending_action was REMOVED.
    # All seller confirmations MUST go through the _pending_action mechanism.
    # The old code blindly queried DB for ANY pending confirmation for this phone,
    # which caused accidental confirmations when a user was both buyer and seller.

    # AI-first expired rebuy: if user expresses any kind of (re)buy intent without
    # naming a specific event, check for a recent expired reservation first.
    _rebuy_intent = False
    if classification.intent == "BUY_REQUEST":
        has_specific_event = bool((classification.entities or {}).get("event_name"))
        if not has_specific_event:
            _rebuy_intent = True
    elif classification.intent in ("GENERAL_QUESTION", "UNKNOWN"):
        # Classifier missed it — ask AI if this sounds like a rebuy
        _rebuy_intent = await _ai_detect_rebuy_intent(raw_message)
    if _rebuy_intent:
        result = await _handle_expired_rebuy(db, phone)
        if result:
            return result

    if classification.intent in ("BUY_REQUEST", "SELL_OFFER"):
        # Strip [Doorgestuurd]/[Forwarded] prefix for entity extraction
        clean_message = raw_message
        if raw_message.strip().lower().startswith("[doorgestuurd]"):
            clean_message = raw_message.strip()[len("[Doorgestuurd]"):].strip()
        elif raw_message.strip().lower().startswith("[forwarded]"):
            clean_message = raw_message.strip()[len("[Forwarded]"):].strip()

        # Parse FestiFlip listing format from forwarded messages
        # Template: "*TE KOOP 🎟️*\n🎟️ event_name (YYYY-MM-DD)\n🔢 N Stuks\n💰 €X per stuk\n..."
        listing_entities = {}
        if clean_message != raw_message:  # was forwarded
            listing_match = re.search(
                r'🎟️\s*(.+?)\s*\((\d{4}-\d{2}-\d{2})\)',
                clean_message
            )
            if listing_match:
                listing_entities["event_name"] = listing_match.group(1).strip()
                listing_entities["event_date"] = listing_match.group(2)
            qty_match = re.search(r'(\d+)\s*[Ss]tuks?', clean_message)
            if qty_match:
                listing_entities["quantity"] = int(qty_match.group(1))
            price_match = re.search(r'€\s*(\d+[.,]?\d*)\s*per\s*stuk', clean_message)
            if price_match:
                listing_entities["max_price"] = float(price_match.group(1).replace(",", "."))

        # AI entities = PRIMARY source (classifier already extracted everything)
        collected = {k: v for k, v in (classification.entities or {}).items() if v is not None}

        # Only for forwarded messages: parse the structural listing format
        for key, val in listing_entities.items():
            if val is not None:
                collected[key] = val

        # Centralized price field mapping
        collected = _map_price_field(collected, classification.intent)

        # Normalize entities (sanitize event_name, parse dates, etc.)
        raw_date = collected.get("event_date")
        collected = normalize_entities(collected)

        # AI fallback for relative dates that normalize_entities can't parse
        if raw_date and not collected.get("event_date"):
            resolved = await _ai_resolve_relative_date(str(raw_date))
            if resolved:
                collected["event_date"] = resolved

        # Unified validation
        collected = _sanitize_entities(collected, classification.intent)

        missing = validate_entities(classification.intent, collected)

        if not missing:
            # FEATURE 10: edition check before confirming
            if collected.get("event_name") and not collected.get("ticket_type"):
                try:
                    from app.crud.event_configs import should_ask_edition
                    if await should_ask_edition(db, collected["event_name"]):
                        collected["_edition_asked"] = True
                        await update_session(
                            db, phone,
                            current_intent=classification.intent,
                            current_step=COLLECTING,
                            collected_data=collected,
                        )
                        return _t(
                            f"*{collected['event_name']}* heeft meerdere edities. Welke editie zoek je?\n"
                            "(bijv. zaterdag, zondag, weekender, night, etc.)",
                            f"*{collected['event_name']}* has multiple editions. Which edition are you looking for?\n"
                            "(e.g. Saturday, Sunday, weekender, night, etc.)"
                        )
                except Exception as e:
                    logger.error(f"Edition check failed: {e}")

            # All data collected in one message – proceed to confirm
            await update_session(
                db, phone,
                current_intent=classification.intent,
                current_step=CONFIRMING,
                collected_data=collected,
            )
            return _format_confirmation(classification.intent, collected)
        else:
            # Need more data
            await update_session(
                db, phone,
                current_intent=classification.intent,
                current_step=COLLECTING,
                collected_data=collected,
            )

            # FEATURE 5: If most fields missing (user just said "kopen"/"verkopen"),
            # send form link instead of asking questions one by one.
            if len(missing) >= 3 and not collected.get("event_name"):
                from app.message_templates.templates import sell_form_link_message, buy_form_link_message
                if classification.intent == "SELL_OFFER":
                    return sell_form_link_message(lang=_lang())
                else:
                    return buy_form_link_message(lang=_lang())
            elif len(missing) >= 2:
                return _fill_template_with_data(classification.intent, collected)
            else:
                return ask_missing_field(missing[0], classification.intent)

    elif classification.intent == "BROWSE_CATALOG":
        # User wants to see what tickets are available
        from app.crud.sell_offers import get_available_offers
        event_filter = (classification.entities or {}).get("event_name")
        offers = await get_available_offers(db, event_name=event_filter, limit=20)
        
        if not offers:
            if event_filter:
                return f"Er zijn momenteel geen tickets beschikbaar voor '{event_filter}'. Wil je een zoekopdracht plaatsen zodat we je informeren als er tickets beschikbaar komen?"
            return "Er zijn momenteel geen tickets beschikbaar in ons systeem. Wil je een zoekopdracht plaatsen zodat we je informeren als er tickets beschikbaar komen?"
        
        lines = ["🎟️ *Beschikbare tickets:*\n"]
        for i, offer in enumerate(offers, 1):
            line = f"{i}. *{offer.event_name}*"
            if offer.ticket_type:
                line += f" ({offer.ticket_type})"
            line += f"\n   📦 {offer.quantity}x beschikbaar"
            line += f" · €{offer.price_per_ticket:.2f} per ticket"
            if offer.event_date:
                line += f"\n   📅 {offer.event_date.strftime('%d/%m/%y')}"
            lines.append(line)
        
        lines.append("\n💡 Wil je tickets kopen? Geef het evenement, aantal en je maximale prijs door!")
        return "\n".join(lines)

    else:
        # AI Fallback: handle greetings, random questions, etc.
        from app.ai.fallback import ai_fallback_idle
        # Pass whether user has prior history so greetings after a completed flow
        # get a short reply instead of the full welcome message
        has_history = bool(conversation_history)
        return await ai_fallback_idle(raw_message, has_history=has_history)


async def _handle_collecting(
    db: AsyncSession,
    phone: str,
    session,
    classification: ClassificationResult,
    raw_message: str,
    conversation_history: list = None,
) -> str:
    """Handle a message during data collection phase."""
    # (Global reset for "stop"/"annuleer" etc. already handled in process_message)

    # Multi-event flow: check for early exit, count change, or multiple events in one message
    existing_data = session.collected_data or {}
    multi_total = existing_data.get("_multi_event_total", 0)
    multi_done = existing_data.get("_multi_event_done", 0)

    # ── Multi-event: detect multiple events in one message ──
    if multi_total and session.current_intent == "SELL_OFFER":
        # Check if user sent multiple events at once (with or without ---)
        if "---" in raw_message:
            blocks = [b.strip() for b in raw_message.split("---") if b.strip()]
            if len(blocks) >= 2:
                return await _handle_multi_event_batch(
                    db, phone, blocks, multi_total, multi_done
                )
        elif len(raw_message) > 40:
            # Try AI splitter for messages without ---
            listings = await _split_multi_event_message(raw_message)
            if len(listings) >= 2:
                return await _handle_multi_event_batch(
                    db, phone, listings, multi_total, multi_done
                )

    if multi_total and multi_done >= 0:
        # AI-first: check if message is event data or a control message (done/count change)
        # The classifier already ran — if it found no event entities, this is likely a control msg
        ai_entities = {k: v for k, v in (classification.entities or {}).items()
                       if v is not None and k in ("event_name", "event_date", "quantity", "price_per_ticket", "max_price")}
        if not ai_entities:
            # No event data found — ask AI to interpret the control message
            multi_action = await _ai_interpret_multi_event_control(raw_message, multi_total, multi_done)
            if multi_action.get("action") == "done":
                await update_session(db, phone, current_intent=None, current_step=IDLE, collected_data={})
                if multi_done > 0:
                    return f"🎉 Top! {multi_done} evenement{'en' if multi_done > 1 else ''} opgeslagen. Je hoort van ons zodra er kopers zijn!"
                else:
                    return "Oké, geen probleem! Laat maar weten als je later tickets wil verkopen 👋"
            elif multi_action.get("action") == "change_count":
                new_total = multi_action.get("new_count", multi_total)
                if new_total <= multi_done:
                    await update_session(db, phone, current_intent=None, current_step=IDLE, collected_data={})
                    return f"🎉 Top! {multi_done} evenement{'en' if multi_done > 1 else ''} opgeslagen. Je hoort van ons zodra er kopers zijn!"
                else:
                    existing_data["_multi_event_total"] = new_total
                    await update_session(db, phone, collected_data=existing_data)
                    from app.message_templates.templates import sell_fill_template
                    remaining = new_total - multi_done
                    return f"Oké, aangepast naar {new_total} evenementen. Nog {remaining} te gaan!\n\n" + sell_fill_template()
            # action == "continue" — fall through to normal collecting

    # AI-first intent switch detection
    # Path 1: Classifier explicitly says different intent AND message has explicit intent keywords
    # Path 2: Classifier says GENERAL_QUESTION/UNKNOWN — ask AI if it's a switch
    # IMPORTANT: During COLLECTING, the classifier often guesses wrong intent from entity data alone
    # (e.g. "50€ per ticket" looks like SELL to the classifier). Only switch if user explicitly
    # expresses a different intent with keywords like kopen/verkopen.
    new_intent = None
    _msg_lower = raw_message.strip().lower()
    _EXPLICIT_BUY_KW = re.compile(r'\b(?:kopen|koop|zoek|nodig|op zoek|wil kopen|wil ik kopen|tickets?\s*kopen|wil\s+tickets?)\b')
    _EXPLICIT_SELL_KW = re.compile(r'\b(?:verkopen|verkoop|te koop|aanbieden|wil\s+verkopen|heb\s+(?:ik\s+)?tickets?)\b')
    if (
        classification.intent in ("BUY_REQUEST", "SELL_OFFER")
        and classification.intent != session.current_intent
    ):
        # Only allow switch if the message contains explicit intent keywords
        has_explicit_switch = False
        if classification.intent == "BUY_REQUEST" and _EXPLICIT_BUY_KW.search(_msg_lower):
            has_explicit_switch = True
        elif classification.intent == "SELL_OFFER" and _EXPLICIT_SELL_KW.search(_msg_lower):
            has_explicit_switch = True

        if has_explicit_switch:
            new_intent = classification.intent
        else:
            logger.info(f"Blocked intent switch {session.current_intent} → {classification.intent} (no explicit keyword in: '{raw_message[:60]}')")
    elif classification.intent in ("GENERAL_QUESTION", "UNKNOWN"):
        # Classifier missed it — ask AI specifically about intent switch
        new_intent = await _ai_detect_intent_switch(raw_message, session.current_intent)

    msg_words = set(raw_message.strip().lower().split())

    if new_intent:
        # Intent switched — only keep core fields that are genuinely valid
        old_data = session.collected_data or {}
        # Only carry over verified, non-null core fields (no internal _ fields leak)
        _CARRY_FIELDS = ("event_name", "event_date", "ticket_type", "quantity")
        existing = {k: old_data[k] for k in _CARRY_FIELDS if old_data.get(k) is not None}

        # Carry over price with mapping (max_price ↔ price_per_ticket)
        old_price = {k: old_data[k] for k in ("max_price", "price_per_ticket") if old_data.get(k) is not None}
        old_price = _map_price_field(old_price, new_intent)
        existing.update(old_price)

        # Use classifier entities from the switch message (AI already extracted them)
        switch_entities = {k: v for k, v in (classification.entities or {}).items() if v is not None}
        switch_entities = normalize_entities(switch_entities)
        switch_entities = _map_price_field(switch_entities, new_intent)

        # Merge: keep existing data (event_name, date, etc.) + new entities from this message
        for key, val in switch_entities.items():
            if val is not None:
                existing[key] = val

        missing = validate_entities(new_intent, existing)
        session.current_intent = new_intent

        prefix = "Oké! " if "nee" in msg_words or "niet" in msg_words else ""
        prefix += "We switchen naar verkopen. " if new_intent == "SELL_OFFER" else "We switchen naar kopen. "

        # Show fill template if 2+ fields still missing
        if len(missing) >= 2:
            await update_session(
                db, phone,
                current_intent=new_intent,
                current_step=COLLECTING,
                collected_data=existing,
            )
            return prefix + "\n\n" + _fill_template_with_data(new_intent, existing)
        elif missing:
            await update_session(
                db, phone,
                current_intent=new_intent,
                current_step=COLLECTING,
                collected_data=existing,
            )
            return prefix + ask_missing_field(missing[0], new_intent)
        else:
            # All data already collected — go to confirmation
            await update_session(
                db, phone,
                current_intent=new_intent,
                current_step=CONFIRMING,
                collected_data=existing,
            )
            return prefix + "\n\n" + _format_confirmation(new_intent, existing)

    # Handle bare "ja"/"ok"/"oke" in COLLECTING — user is affirming, not providing data
    _bare_affirm = raw_message.strip().lower()
    _bare_emoji = raw_message.strip()
    _COLLECTING_AFFIRM_EMOJI = {"👍", "👍🏻", "👍🏼", "👍🏽", "👍🏾", "👍🏿", "✅", "👌"}
    if _bare_affirm in ("ja", "yes", "ok", "oke", "oké", "okay", "jep", "jaa", "yep") or _bare_emoji in _COLLECTING_AFFIRM_EMOJI:
        existing = session.collected_data or {}
        missing = validate_entities(session.current_intent, existing)
        if missing:
            # Still missing fields — "ja" doesn't answer the pending question, re-ask
            return ask_missing_field(missing[0], session.current_intent)
        # All required fields filled — show confirmation with explicit transition
        # so the user understands WHY they're seeing the summary
        await update_session(db, phone, current_step=CONFIRMING, collected_data=existing)
        return _t("Alles compleet! Even checken:\n\n", "All set! Let's double-check:\n\n") + _format_confirmation(session.current_intent, existing)

    prefix = ""
    # AI-first: classifier extracts ALL entities in one call
    new_entities = {k: v for k, v in (classification.entities or {}).items() if v is not None}

    # Thin fallback: for very short inputs ("3", "€80") where classifier might not extract well
    if not new_entities or len(raw_message.strip()) <= 10:
        simple_extracted = await _smart_extract_from_response(session, raw_message, conversation_history)
        if simple_extracted:
            for key, val in simple_extracted.items():
                if val is not None and not new_entities.get(key):
                    new_entities[key] = val

    # AI-first: detect event name corrections from natural language
    if not new_entities.get("event_name") and session.collected_data.get("event_name"):
        corrected_name = await _ai_extract_event_correction(raw_message, session.collected_data["event_name"])
        if corrected_name:
            new_entities["event_name"] = corrected_name

    # Centralized price field mapping (session intent, not classifier intent)
    new_entities = _map_price_field(new_entities, session.current_intent)

    # Normalize extracted data (e.g. parse dates)
    raw_date = new_entities.get("event_date")
    new_entities = normalize_entities(new_entities)

    # AI fallback for relative dates that normalize_entities can't parse
    if raw_date and not new_entities.get("event_date"):
        resolved = await _ai_resolve_relative_date(str(raw_date))
        if resolved:
            new_entities["event_date"] = resolved

    # Merge with existing collected data
    existing = session.collected_data or {}
    merged = {k: v for k, v in existing.items() if v is not None}
    for key, value in new_entities.items():
        if value is not None:
            merged[key] = value

    # Unified validation
    merged = _sanitize_entities(merged, session.current_intent)

    # Check what's still missing
    missing = validate_entities(session.current_intent, merged)



    if not missing:
        # FEATURE 10: If this event requires an edition question and we don't have ticket_type yet
        if merged.get("event_name") and not merged.get("ticket_type") and not merged.get("_edition_asked"):
            try:
                from app.crud.event_configs import should_ask_edition
                if await should_ask_edition(db, merged["event_name"]):
                    merged["_edition_asked"] = True
                    await update_session(db, phone, collected_data=merged, current_intent=session.current_intent)
                    return _t(
                        f"*{merged['event_name']}* heeft meerdere edities. Welke editie zoek je?\n"
                        "(bijv. zaterdag, zondag, weekender, night, etc.)",
                        f"*{merged['event_name']}* has multiple editions. Which edition are you looking for?\n"
                        "(e.g. Saturday, Sunday, weekender, night, etc.)"
                    )
            except Exception as e:
                logger.error(f"Edition check failed: {e}")

        # All data collected
        await update_session(
            db, phone,
            current_step=CONFIRMING,
            collected_data=merged,
            current_intent=session.current_intent,
        )
        return prefix + _format_confirmation(session.current_intent, merged)
    else:
        # Still need more data
        await update_session(
            db, phone,
            collected_data=merged,
            current_intent=session.current_intent,
        )
        next_question = ask_missing_field(missing[0], session.current_intent)

        # Smart check: did we extract anything useful from this message?
        old_data = session.collected_data or {}
        new_data_extracted = any(
            k for k in merged
            if not k.startswith("_") and merged.get(k) != old_data.get(k)
        )

        if new_entities or new_data_extracted:
            # We got something useful, just ask for the next missing field
            return prefix + next_question
        else:
            # User said something we can't parse — call AI fallback
            from app.ai.fallback import ai_fallback
            return await ai_fallback(
                raw_message=raw_message,
                intent=session.current_intent,
                collected_data=merged,
                missing_fields=missing,
                redirect_question=next_question,
                conversation_history=conversation_history,
            )


async def _handle_confirming(
    db: AsyncSession,
    phone: str,
    session,
    raw_message: str,
    classification: ClassificationResult = None,
    conversation_history: list = None,
) -> str:
    """Handle confirmation response."""
    msg = raw_message.strip().lower()

    # Dutch affirmative phrases
    confirm_words = {
        "ja", "yes", "ok", "oke", "oké", "okay",
        "akkoord", "bevestig", "klopt", "correct",
        "goed", "is goed", "oke is goed", "prima",
        "top", "doen", "zeker", "klopt helemaal",
        "dat klopt", "confirmed", "yep", "jep", "jaa",
        "zeker weten", "doe maar", "absoluut", "helemaal",
        "tuurlijk", "natuurlijk", "ja klopt", "ja is goed",
        "perfect", "precies", "exact", "helemaal goed",
        "laten we gaan", "dat klopt ja", "bevestigen",
        "go", "sure", "yes please", "sowieso", "uiteraard",
        "komt goed", "is prima", "mooi", "lekker",
        "deal", "doen we", "ga maar", "fire",
        "that's correct", "looks good", "all good", "right",
        "absolutely", "of course", "let's go", "confirm",
        "that's right", "sounds good", "good to go",
    }
    _confirm_prefixes = ("ja ", "ok ", "oke ", "goed ", "yes ", "klopt ", "zeker ", "doe ")
    _CONFIRM_EMOJI = {"👍", "👍🏻", "👍🏼", "👍🏽", "👍🏾", "👍🏿", "✅", "👌", "🤝", "💪", "🙌", "✔️", "☑️", "🔥"}

    # Denial words and prefixes — check BEFORE confirm to avoid "klopt niet" matching "klopt " prefix
    _DENY_WORDS = {
        "nee", "no", "fout", "niet klopt", "opnieuw",
        "klopt niet", "dat klopt niet", "dit is fout", "verkeerd",
        "dat is niet goed", "niet correct", "kan niet kloppen",
        "that's wrong", "not correct", "incorrect", "start over",
        "dit klopt niet", "niet goed", "is fout", "onjuist",
        "nee hoor", "absoluut niet", "zeker niet", "nope",
        "neen", "dit is verkeerd", "dat is fout", "niet juist",
    }
    _DENY_PREFIXES = ("nee ", "niet ", "fout ", "verkeerd ", "klopt niet", "no ", "not ", "wrong ")
    _DENY_EMOJI = {"👎", "👎🏻", "👎🏼", "👎🏽", "👎🏾", "👎🏿", "❌", "🚫", "✋", "🛑"}

    # Strip message to raw emoji for matching (handles "👍" with skin tone modifiers)
    _msg_stripped = raw_message.strip()
    is_deny = msg in _DENY_WORDS or any(msg.startswith(w) for w in _DENY_PREFIXES) or _msg_stripped in _DENY_EMOJI

    # Confirm check — only if not already a denial
    is_confirm = False
    if not is_deny:
        is_confirm = msg in confirm_words or any(msg.startswith(w) for w in _confirm_prefixes) or _msg_stripped in _CONFIRM_EMOJI

    # AI fallback: if not obviously confirm/deny, ask AI before falling through
    if not is_confirm and not is_deny:
        is_confirm = await _ai_is_confirmation(msg)

    if is_confirm:
        # Save to database
        data = session.collected_data or {}
        data["phone"] = phone

        # Safety check: validate data is complete before saving
        missing = validate_entities(session.current_intent, data)
        if missing:
            logger.warning(f"CONFIRMING with incomplete data for {phone}: missing={missing}")
            await update_session(db, phone, current_step=COLLECTING, collected_data=data)
            return _t("Hmm, er missen nog wat gegevens. ", "Hmm, some data is still missing. ") + ask_missing_field(missing[0], session.current_intent)

        # FIX 2: Check price against admin-configured min/max for this event
        try:
            from app.crud.event_configs import find_matching_config
            from datetime import date as _date_type
            _evt_date = None
            if data.get("event_date"):
                try:
                    _evt_date = _date_type.fromisoformat(str(data["event_date"]))
                except (ValueError, TypeError):
                    pass
            price_rule = await find_matching_config(db, data.get("event_name", ""), _evt_date)
            if price_rule:
                _price = float(data.get("price_per_ticket") or data.get("max_price") or 0)
                if _price > 0:
                    if price_rule.min_price is not None and _price < float(price_rule.min_price):
                        await update_session(db, phone, current_step=COLLECTING, collected_data=data)
                        return _t(
                            f"⚠️ De prijs €{_price:.2f} is te laag voor dit evenement. "
                            f"De minimumprijs is €{float(price_rule.min_price):.2f} per ticket.\n\n"
                            "Pas je prijs aan en probeer het opnieuw.",
                            f"⚠️ The price €{_price:.2f} is too low for this event. "
                            f"The minimum price is €{float(price_rule.min_price):.2f} per ticket.\n\n"
                            "Adjust your price and try again."
                        )
                    if price_rule.max_price is not None and _price > float(price_rule.max_price):
                        await update_session(db, phone, current_step=COLLECTING, collected_data=data)
                        return _t(
                            f"⚠️ De prijs €{_price:.2f} is te hoog voor dit evenement. "
                            f"De maximumprijs is €{float(price_rule.max_price):.2f} per ticket.\n\n"
                            "Pas je prijs aan en probeer het opnieuw.",
                            f"⚠️ The price €{_price:.2f} is too high for this event. "
                            f"The maximum price is €{float(price_rule.max_price):.2f} per ticket.\n\n"
                            "Adjust your price and try again."
                        )
        except Exception as e:
            logger.error(f"Price rule check failed: {e}")

        if session.current_intent == "BUY_REQUEST":
            result = await _save_buy_request(db, data)
            # Store undo reference before resetting — user can say "dat was fout" to cancel
            await update_session(
                db, phone,
                current_intent=None,
                current_step=IDLE,
                collected_data={"_pending_action": "undo_buy", "_last_saved_id": result.id},
            )

            # Try to auto-match and create reservation with Stripe link
            from decimal import Decimal
            max_price = Decimal(str(data["max_price"])) if data.get("max_price") else None
            match_result = await auto_match_and_notify(
                db,
                buy_request_id=result.id,
                event_name=data.get("event_name", ""),
                quantity=data.get("quantity", 1),
                max_price=max_price,
                buyer_phone=phone,
                ticket_type=data.get("ticket_type"),
                event_date=data.get("event_date"),
            )
            if match_result:
                if match_result.get("pending_confirmation"):
                    return _t(
                        "Opgeslagen! ✅\n\n"
                        "We hebben al een mogelijke match gevonden — we checken even bij de verkoper of het nog beschikbaar is. "
                        "Je hoort van ons!",
                        "Saved! ✅\n\n"
                        "We already found a possible match — we're checking with the seller if it's still available. "
                        "We'll let you know!"
                    )
                evt = data.get('event_name', '')
                amt = match_result['deposit_amount']
                url = match_result['checkout_url']
                return _t(
                    f"Opgeslagen! ✅\n\nNice, er zijn tickets beschikbaar voor {evt}! 🎉\n\n"
                    f"Betaal de aanbetaling van €{amt:.2f} om ze te reserveren:\n{url}\n\n"
                    f"Na betaling krijg je het nummer van de verkoper.",
                    f"Saved! ✅\n\nNice, tickets are available for {evt}! 🎉\n\n"
                    f"Pay the deposit of €{amt:.2f} to reserve them:\n{url}\n\n"
                    f"After payment you'll get the seller's number."
                )
            # No match found -> Broadcast to subscribers
            try:
                from app.services.broadcast import broadcast_buy_request
                await broadcast_buy_request(
                    event_name=data.get("event_name", ""),
                    event_date=data.get("event_date", ""),
                    quantity=data.get("quantity", 1),
                    requester_phone=phone,
                )
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Search broadcast failed: {e}")

            # Send group notification via Whapi (independent of broadcast)
            try:
                from app.services.whapi import send_group_notification
                from app.message_templates.templates import buy_request_group_broadcast
                await send_group_notification(
                    buy_request_group_broadcast(
                        event_name=data.get('event_name', ''),
                        event_date=data.get('event_date', ''),
                        quantity=data.get('quantity', 1),
                        max_price=data.get('max_price', 'N/A'),
                    )
                )
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Whapi group notification failed: {e}")

            return _t("Opgeslagen! ✅ We hebben het doorgezet naar ons netwerk. Zodra er iets beschikbaar is, hoor je van ons!",
                      "Saved! ✅ We've shared your request with our network. We'll let you know when something's available!")

        elif session.current_intent == "SELL_OFFER":
            new_offer = await _save_sell_offer(db, data)

            # Track multi-event progress
            multi_total = data.get("_multi_event_total", 0)
            multi_done = data.get("_multi_event_done", 0) + 1

            # 1. Broadcast new listing to subscribers
            try:
                from app.services.broadcast import broadcast_new_listing
                from decimal import Decimal
                price = Decimal(str(data.get("price_per_ticket", 0)))
                await broadcast_new_listing(
                    event_name=data.get("event_name", ""),
                    quantity=data.get("quantity", 1),
                    price_per_ticket=price,
                    seller_phone=phone,
                )
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Broadcast failed: {e}")

            # 2. Process Waitlist (Notify waiting buyers)
            try:
                from app.services.matching import process_waitlist
                await process_waitlist(db, new_offer)
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Waitlist processing failed: {e}")

            # Send group notification via queue (FIFO cooldown per event)
            try:
                from app.services.group_queue import enqueue_group_post
                from app.message_templates.templates import sell_offer_group_broadcast
                from datetime import date as _dt
                _evt_date = None
                if data.get("event_date"):
                    try: _evt_date = _dt.fromisoformat(str(data["event_date"]))
                    except (ValueError, TypeError): pass
                await enqueue_group_post(
                    db, sell_offer_id=new_offer.id,
                    event_name=data.get('event_name', ''),
                    event_date=_evt_date,
                    message_body=sell_offer_group_broadcast(
                        event_name=data.get('event_name', ''),
                        event_date=data.get('event_date', ''),
                        quantity=data.get('quantity', 1),
                        price_per_ticket=data.get('price_per_ticket', 'N/A'),
                        ticket_type=data.get('ticket_type', ''),
                    ),
                )
            except Exception as e:
                logger.error(f"Group queue failed: {e}")

            # Multi-event flow: short confirmation for mid-flow, full details on last/single
            if multi_total and multi_done < multi_total:
                # Mid-flow: short confirmation, auto-start next event
                remaining = multi_total - multi_done
                evt = data.get("event_name", "?")
                qty = data.get("quantity", 1)
                price = data.get("price_per_ticket", 0)
                from app.message_templates.templates import sell_fill_template
                await update_session(
                    db, phone,
                    current_intent="SELL_OFFER",
                    current_step=COLLECTING,
                    collected_data={"_multi_event_total": multi_total, "_multi_event_done": multi_done},
                )
                return (
                    f"✅ *{evt}* opgeslagen! ({qty}x €{price})\n\n"
                    f"📋 Evenement {multi_done}/{multi_total} — nog {remaining} te gaan.\n\n"
                    + sell_fill_template()
                )
            elif multi_total and multi_done >= multi_total:
                # Last event in multi-flow: full confirmation
                confirmation = (
                    "✅ Je aanbod is opgeslagen!\n\n"
                    + seller_confirmation_message(
                        price_per_ticket=float(data.get("price_per_ticket", 0)),
                        quantity=int(data.get("quantity", 1)),
                    )
                )
                await update_session(
                    db, phone,
                    current_intent=None,
                    current_step=IDLE,
                    collected_data={},
                )
                return (
                    confirmation
                    + f"\n\n─────────────────\n"
                    f"🎉 Alle {multi_total} evenementen zijn opgeslagen! Je hoort van ons zodra er kopers zijn."
                )
            else:
                # Single event flow — full confirmation + "more sells?" prompt
                confirmation = (
                    "✅ Je aanbod is opgeslagen!\n\n"
                    + seller_confirmation_message(
                        price_per_ticket=float(data.get("price_per_ticket", 0)),
                        quantity=int(data.get("quantity", 1)),
                    )
                )
                await update_session(
                    db, phone,
                    current_intent=None,
                    current_step=IDLE,
                    collected_data={"_pending_action": "more_sells", "_last_saved_id": new_offer.id, "_last_saved_type": "sell"},
                )
                return (
                    confirmation
                    + "\n\n─────────────────\n"
                    "🎟️ Heb je nog meer tickets te verkopen? Typ *ja* voor een nieuw formulier."
                )

        await reset_session(db, phone)
        return "✅ Opgeslagen!"

    elif is_deny:
        await update_session(db, phone, current_step=COLLECTING, collected_data={})
        return _t("Oké, we beginnen opnieuw. ", "OK, starting over. ") + ask_missing_field("event_name", session.current_intent)

    else:
        # AI-first intent switch during CONFIRMING (e.g. "nee ik wil eigenlijk verkopen")
        switch_intent = None
        if (
            classification.intent in ("BUY_REQUEST", "SELL_OFFER")
            and classification.intent != session.current_intent
        ):
            switch_intent = classification.intent
        elif classification.intent in ("GENERAL_QUESTION", "UNKNOWN"):
            switch_intent = await _ai_detect_intent_switch(raw_message, session.current_intent)

        if switch_intent:
            new_intent = switch_intent
            old_data = session.collected_data or {}
            # Carry over core fields + map price
            _CARRY_FIELDS = ("event_name", "event_date", "ticket_type", "quantity")
            existing = {k: old_data[k] for k in _CARRY_FIELDS if old_data.get(k) is not None}
            old_price = {k: old_data[k] for k in ("max_price", "price_per_ticket") if old_data.get(k) is not None}
            old_price = _map_price_field(old_price, new_intent)
            existing.update(old_price)

            # Merge classifier entities from the switch message
            switch_entities = {k: v for k, v in (classification.entities or {}).items() if v is not None}
            switch_entities = normalize_entities(switch_entities)
            switch_entities = _map_price_field(switch_entities, new_intent)
            for key, val in switch_entities.items():
                if val is not None:
                    existing[key] = val

            existing = _sanitize_entities(existing, new_intent)
            missing = validate_entities(new_intent, existing)

            prefix = "Oké! We switchen naar "
            prefix += "verkopen. " if new_intent == "SELL_OFFER" else "kopen. "

            if not missing:
                await update_session(db, phone, current_intent=new_intent, current_step=CONFIRMING, collected_data=existing)
                return prefix + "\n\n" + _format_confirmation(new_intent, existing)
            else:
                await update_session(db, phone, current_intent=new_intent, current_step=COLLECTING, collected_data=existing)
                if len(missing) >= 2:
                    return prefix + "\n\n" + _fill_template_with_data(new_intent, existing)
                return prefix + ask_missing_field(missing[0], new_intent)

        # Unified correction extraction: classifier first, then AI correction extractor.
        # If both find values, MERGE them (AI correction is more context-aware for ambiguous cases).
        _CORRECTION_FIELDS = ("event_name", "event_date", "ticket_type", "quantity",
                              "price_per_ticket", "max_price")
        classifier_entities = {k: v for k, v in (classification.entities or {}).items()
                               if v is not None and k in _CORRECTION_FIELDS}
        classifier_entities = _map_price_field(classifier_entities, session.current_intent)

        # Always run AI correction extractor (unless circuit breaker is tripped)
        # to catch "verander de prijs naar 80" where classifier sees GENERAL_QUESTION + no entities
        ai_correction = await _ai_extract_correction(
            raw_message, session.current_intent, session.collected_data or {}
        )
        ai_correction = _map_price_field(ai_correction, session.current_intent)

        # Merge: classifier entities take precedence (they come from full classification),
        # but AI correction fills gaps the classifier missed
        updates = {**ai_correction, **classifier_entities}

        # Sanitize corrections
        updates = _sanitize_entities(updates, session.current_intent)

        if updates:
            # Normalize any extracted date before saving
            if "event_date" in updates:
                raw_date = updates["event_date"]
                date_normalized = normalize_entities({"event_date": raw_date})
                if date_normalized.get("event_date"):
                    updates["event_date"] = date_normalized["event_date"]
                else:
                    # AI fallback for relative dates
                    resolved = await _ai_resolve_relative_date(str(raw_date))
                    if resolved:
                        updates["event_date"] = resolved
                    else:
                        updates.pop("event_date")  # Can't parse — don't save garbage

            # User is correcting/updating data — OVERWRITE (not merge) so corrections take effect
            data = dict(session.collected_data or {})  # Make a COPY so SQLAlchemy detects the change
            logger.info(f"CONFIRMING correction for {phone}: updates={updates}")
            data.update(updates)  # Overwrite existing values with the user's corrections

            await update_session(
                db, phone,
                current_step=CONFIRMING,
                collected_data=data,
            )

            return _format_confirmation(session.current_intent, data)

        # No data updates detected — use AI fallback
        from app.ai.fallback import ai_fallback_confirming
        return await ai_fallback_confirming(msg, session.current_intent, session.collected_data or {}, conversation_history)


def _detect_user_role(session, conversation_history: list = None) -> Optional[str]:
    """Detect if the user was recently a buyer or seller based on session and history."""
    # Check session data for clues
    cd = session.collected_data or {}
    if cd.get("_pending_action") in ("more_sells", "undo_sell"):
        return "seller"
    if cd.get("_pending_action") in ("undo_buy",):
        return "buyer"
    if cd.get("_last_saved_type") == "sell":
        return "seller"
    # Check recent conversation for sell/buy keywords from the bot
    if conversation_history:
        recent = " ".join(m.get("content", "") for m in conversation_history[-4:]).lower()
        if "opgeslagen" in recent and ("verkop" in recent or "aanbod" in recent or "per stuk" in recent):
            return "seller"
        if "opgeslagen" in recent and ("kop" in recent or "zoek" in recent):
            return "buyer"
    return None


def _format_confirmation(intent: str, data: dict) -> str:
    """Format a confirmation message with collected data."""
    en = _lang() == "en"
    lines = [("Let me confirm, is this correct?\n" if en else "Even checken, klopt dit?\n")]

    if data.get("event_name"):
        evt = data['event_name']
        if data.get("ticket_type"):
            evt += f" ({data['ticket_type']})"
        lines.append(f"🎟️ {evt}")

    if data.get("event_date"):
        from app.message_templates.templates import format_date
        lines.append(f"📅 {format_date(data['event_date'])}")
    if data.get("quantity"):
        lines.append(f"🔢 {data['quantity']}x")

    if intent == "BUY_REQUEST" and data.get("max_price"):
        lines.append(f"💰 Max €{data['max_price']} per ticket")
    elif intent == "SELL_OFFER" and data.get("price_per_ticket"):
        lines.append(f"💰 €{data['price_per_ticket']} per ticket")

    lines.append("\n" + ("Correct? Type yes or no." if en else "Klopt? Typ ja of nee."))
    return "\n".join(lines)


async def _smart_extract_from_response(session, message: str, conversation_history: list = None) -> dict:
    """Use AI-powered extraction to parse user responses.

    Uses fast regex for obvious inputs (free, instant), then falls back
    to GPT-4o-mini for natural language inputs.

    Fix #4: Extracts the primary missing field via AI (which also returns
    bonus fields), then tries fast regex for remaining missing fields.
    This way multi-field responses like "Dekmantel, 3 tickets" aren't lost.
    """
    from app.ai.smart_extractor import ai_extract_value, _try_fast_extract

    data = session.collected_data or {}
    intent = session.current_intent

    # Special check: ticket_type if this is a multi-day festival
    if data.get("_is_multi_day") and data.get("_ticket_types") and not data.get("ticket_type"):
        return await ai_extract_value(
            message=message,
            expected_field="ticket_type",
            intent=intent,
            collected_data=data,
            conversation_history=conversation_history,
        )

    # Use the same required fields as validate_entities (single source of truth)
    missing = validate_entities(intent, data)
    if not missing:
        return {}

    # Extract the primary missing field (uses AI if regex fails)
    all_extracted = await ai_extract_value(
        message=message,
        expected_field=missing[0],
        intent=intent,
        collected_data=data,
        conversation_history=conversation_history,
    )

    # Try fast regex for remaining missing fields (free, no API call)
    # BUT: skip if message is a bare number/short value — it was already consumed by primary extraction.
    # This prevents "3" (intended as quantity) from also being extracted as max_price.
    _msg_stripped = message.strip()
    _is_bare_value = bool(re.match(r'^[\d€,.]+$', _msg_stripped)) or len(_msg_stripped) <= 5
    if not _is_bare_value:
        for field in missing[1:]:
            if field not in all_extracted:
                fast = _try_fast_extract(message, field)
                if fast:
                    all_extracted.update(fast)

    return all_extracted


async def _cancel_last_saved(db: AsyncSession, record_id: int, saved_type: str) -> bool:
    """Cancel a just-saved buy request or sell offer. Returns True if cancelled."""
    from sqlalchemy import select
    try:
        if saved_type in ("undo_buy", "buy"):
            from app.models.buy_request import BuyRequest, BuyStatus
            result = await db.execute(
                select(BuyRequest).where(BuyRequest.id == record_id)
            )
            record = result.scalar_one_or_none()
            if record and record.status == BuyStatus.WAITING:
                record.status = BuyStatus.EXPIRED
                await db.flush()
                logger.info(f"Cancelled buy request {record_id}")
                return True
            # Already matched — can't undo
            return False
        else:
            from app.models.sell_offer import SellOffer, OfferStatus
            result = await db.execute(
                select(SellOffer).where(SellOffer.id == record_id)
            )
            record = result.scalar_one_or_none()
            if record and record.status == OfferStatus.AVAILABLE:
                record.status = OfferStatus.CANCELLED
                await db.flush()
                logger.info(f"Cancelled sell offer {record_id}")
                return True
            # Already reserved/sold — can't undo
            return False
    except Exception as e:
        logger.error(f"Undo cancel failed for {saved_type} {record_id}: {e}")
        return False


async def _save_buy_request(db: AsyncSession, data: dict):
    """Save completed buy request to database."""
    # Safety: reject invalid data that somehow passed validation
    max_price = data.get("max_price")
    if max_price is not None and float(max_price) <= 0:
        raise ValueError(f"Invalid max_price: {max_price}")
    qty = data.get("quantity", 1)
    if int(qty) <= 0:
        raise ValueError(f"Invalid quantity: {qty}")

    # Use WhatsApp push_name if no explicit name was provided
    _name = data.get("first_name") or data.get("_push_name") or "WhatsApp User"
    request_data = BuyRequestCreate(
        first_name=_name,
        last_name=data.get("last_name"),
        phone=data["phone"],
        event_name=data.get("event_name", ""),
        event_date=data.get("event_date"),
        ticket_type=data.get("ticket_type"),
        quantity=int(qty),
        max_price_per_ticket=max_price,
        source="WHATSAPP",
    )
    return await create_buy_request(db, request_data)


async def _save_sell_offer(db: AsyncSession, data: dict):
    """Save completed sell offer to database."""
    # Safety: reject invalid price/quantity that somehow passed validation
    price = data.get("price_per_ticket")
    if price is None or float(price) <= 0:
        raise ValueError(f"Invalid price_per_ticket: {price}")
    qty = data.get("quantity", 1)
    if int(qty) <= 0:
        raise ValueError(f"Invalid quantity: {qty}")

    # Use WhatsApp push_name if no explicit name was provided
    _name = data.get("first_name") or data.get("_push_name") or "WhatsApp Seller"
    offer_data = SellOfferCreate(
        first_name=_name,
        last_name=data.get("last_name"),
        phone=data["phone"],
        event_name=data.get("event_name", ""),
        event_date=data.get("event_date"),
        ticket_type=data.get("ticket_type"),
        quantity=int(qty),
        price_per_ticket=float(price),
    )
    return await create_sell_offer(db, offer_data)
