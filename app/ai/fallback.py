"""AI Fallback Layer – handles off-topic or unrecognizable user messages.

When the state machine can't parse the user's reply, this module sends the
message to OpenAI with full context (current step, intent, collected data)
so the AI can answer the user's question AND gently steer them back on track.
"""

import logging
from datetime import date
from openai import AsyncOpenAI
from app.config import settings

logger = logging.getLogger(__name__)
client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

FALLBACK_SYSTEM_PROMPT = """
Je bent de WhatsApp-assistent van FestiFlip. Je praat als een behulpzame vriend — kort, chill, informeel. Geen formeel taalgebruik.
Datum vandaag: {today}
BELANGRIJK: Antwoord in het {response_lang}. {lang_instruction}

Context: de gebruiker is bezig tickets te {intent_nl}.
Wat we al weten: {collected_summary}
Wat we nog nodig hebben: {missing_summary}

De gebruiker zei iets dat niet direct een antwoord is op onze vraag.

Jouw taak:
1. Reageer kort en natuurlijk op wat ze zeiden (1 zin max, alsof je een vriend bent).
2. Breng ze dan terug naar de flow met deze vraag: {redirect_question}

Stijl:
- Kort en to-the-point. Geen onnodige zinnen.
- Geen aanhalingstekens. Max 2 zinnen totaal.
- Gebruik af en toe emoji's maar overdrijf niet.
"""


async def ai_fallback(
    raw_message: str,
    intent: str,
    collected_data: dict,
    missing_fields: list,
    redirect_question: str,
    conversation_history: list = None,
) -> str:
    """Call OpenAI to handle an off-topic message and redirect the user.

    Args:
        raw_message: The user's unrecognized message
        intent: Current intent (BUY_REQUEST / SELL_OFFER)
        collected_data: What we've collected so far
        missing_fields: List of field names still needed
        redirect_question: The exact template question to redirect to

    Returns:
        A helpful reply that answers the user + redirects them
    """
    try:
        from app.ai.state_machine import _ai_is_available
        if not _ai_is_available():
            return redirect_question
    except ImportError:
        pass
    # Build context strings
    intent_nl = "kopen" if intent == "BUY_REQUEST" else "verkopen"
    
    # Summarize collected data in Dutch
    collected_parts = []
    if collected_data.get("event_name"):
        collected_parts.append(f"Evenement: {collected_data['event_name']}")
    if collected_data.get("quantity"):
        collected_parts.append(f"Aantal: {collected_data['quantity']}")
    if collected_data.get("max_price"):
        collected_parts.append(f"Max prijs: €{collected_data['max_price']}")
    if collected_data.get("price_per_ticket"):
        collected_parts.append(f"Prijs: €{collected_data['price_per_ticket']}")
    collected_summary = ", ".join(collected_parts) if collected_parts else "nog niets"
    
    # Summarize missing fields in Dutch
    field_names_nl = {
        "event_name": "evenementnaam",
        "quantity": "aantal tickets",
        "max_price": "maximale prijs",
        "price_per_ticket": "verkoopprijs per ticket",
        "event_date": "datum",
    }
    missing_summary = ", ".join(field_names_nl.get(f, f) for f in missing_fields) if missing_fields else "niets"
    
    today_str = date.today().strftime("%d-%m-%Y")
    
    try:
        from app.ai.state_machine import _lang
        current_lang = _lang()
    except (ImportError, LookupError):
        current_lang = "nl"
    response_lang = "Engels" if current_lang == "en" else "Nederlands"
    lang_instruction = "Reply in English." if current_lang == "en" else "Informeel Nederlands, zoals je met een vriend chat."

    prompt = FALLBACK_SYSTEM_PROMPT.format(
        today=today_str,
        intent_nl=intent_nl,
        collected_summary=collected_summary,
        missing_summary=missing_summary,
        redirect_question=redirect_question,
        response_lang=response_lang,
        lang_instruction=lang_instruction,
    )

    try:
        # Build messages with conversation context
        messages = [{"role": "system", "content": prompt}]
        if conversation_history:
            for msg in conversation_history[-6:]:
                messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": raw_message})

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.7,
            max_tokens=150,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"AI fallback error: {e}")
        # If OpenAI fails, just redirect with the template question
        return redirect_question


async def ai_fallback_idle(raw_message: str, has_history: bool = False) -> str:
    """Handle messages when user has no active session.

    For greetings from NEW users, return the welcome template.
    For greetings from RETURNING users (has_history=True), respond warmly.
    For anything else, use AI to respond helpfully.
    """
    msg = raw_message.strip().lower()

    # Check for acknowledgments (after a completed flow) — respond warmly, don't restart
    acks = {"ok", "oke", "oké", "okay", "okee", "okido",
            "bedankt", "dankje", "dankjewel", "thanks", "thank you", "top", "super",
            "perfect", "goed", "fijn", "prima", "cool", "nice", "lekker", "geweldig",
            "mooi", "helemaal goed", "dank", "merci", "thnx", "thx", "ty",
            "ja", "yes", "yep", "jep",
            "👍", "👌", "🙏", "✅", "😊", "🤝"}
    if msg in acks or msg.rstrip("!.") in acks:
        return "Top! Laat maar weten als je nog iets nodig hebt 👋"

    # Check if it's a greeting
    greetings = {"hallo", "hoi", "hey", "hi", "hello", "yo", "goedemorgen",
                 "goedemiddag", "goedenavond", "dag", "heej", "hee", "heyy"}
    msg_clean = msg.rstrip("!.,?")
    if msg_clean in greetings or msg.startswith(("hallo ", "hoi ", "hey ", "hi ")):
        if has_history:
            # Returning user — short friendly reply, don't repeat the full welcome
            return "Hey! 👋 Wil je tickets kopen of verkopen?"
        from app.message_templates.templates import welcome_message
        return welcome_message()

    # Check if user says they have a question — invite them to ask it
    question_phrases = ["ik heb een vraag", "vraag over", "wil iets vragen",
                        "mag ik vragen", "kan ik vragen", "vraagje"]
    if any(phrase in msg for phrase in question_phrases):
        return "Tuurlijk, vraag maar! Ik weet alles over hoe FestiFlip werkt."
    
    # For anything else off-topic, use Q&A module
    from app.ai.qa import answer_general_question
    try:
        return await answer_general_question(raw_message)
    except Exception as e:
        logger.error(f"AI fallback idle Q&A error: {e}")
        from app.message_templates.templates import welcome_message
        return welcome_message()


async def ai_fallback_confirming(
    raw_message: str, intent: str, collected_data: dict, conversation_history: list = None
) -> str:
    """Handle unexpected messages during the confirmation step.

    The AI will try to understand if they're confirming or not, or answer
    a side question, and redirect them back.
    """
    try:
        from app.ai.state_machine import _ai_is_available
        if not _ai_is_available():
            return "Typ 'ja' om te bevestigen of 'nee' om opnieuw te beginnen."
    except ImportError:
        pass
    today_str = date.today().strftime("%d-%m-%Y")
    intent_nl = "kopen" if intent == "BUY_REQUEST" else "verkopen"
    
    # Build summary of what we're confirming
    lines = []
    if collected_data.get("event_name"):
        lines.append(f"Evenement: {collected_data['event_name']}")
    if collected_data.get("quantity"):
        lines.append(f"Aantal: {collected_data['quantity']}")
    if collected_data.get("max_price"):
        lines.append(f"Max prijs: €{collected_data['max_price']}")
    if collected_data.get("price_per_ticket"):
        lines.append(f"Prijs: €{collected_data['price_per_ticket']}")
    summary = ", ".join(lines)
    
    try:
        from app.ai.state_machine import _lang
        current_lang = _lang()
    except (ImportError, LookupError):
        current_lang = "nl"
    lang_hint = "Reply in English, casual and friendly." if current_lang == "en" else "Informeel Nederlands, geen aanhalingstekens."

    prompt = f"""
Je bent de WhatsApp-assistent van FestiFlip. Datum: {today_str}
{lang_hint}

De gebruiker wil tickets {intent_nl}. We hebben alles verzameld ({summary}) en wachten op bevestiging.
Ze zeiden net iets dat geen duidelijk ja of nee is.

Reageer kort en natuurlijk (1 zin). Vraag dan of de gegevens kloppen. Max 2 zinnen.
"""
    try:
        # Build messages with conversation context
        messages = [{"role": "system", "content": prompt}]
        if conversation_history:
            for msg in conversation_history[-6:]:
                messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": raw_message})

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.3,
            max_tokens=100,
        )
        reply = response.choices[0].message.content.strip()
        # Always end with a clear redirect to confirm/deny
        if "ja" not in reply.lower() and "nee" not in reply.lower() and "klopt" not in reply.lower():
            reply += "\n\nKlopt alles? Typ *ja* om te bevestigen of *nee* om opnieuw te beginnen."
        return reply
    except Exception as e:
        logger.error(f"AI fallback confirming error: {e}")
        return "Ik begreep dat niet helemaal. Typ *ja* om te bevestigen, *nee* om opnieuw te beginnen, of vertel me wat je wilt wijzigen."
