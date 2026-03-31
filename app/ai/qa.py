"""General Q&A module – answers questions about FestiFlip using AI.

When users ask general questions (not buy/sell related), this module
provides helpful, context-aware answers about the platform.
"""

import logging
from datetime import date
from openai import AsyncOpenAI
from app.config import settings

logger = logging.getLogger(__name__)
client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

QA_SYSTEM_PROMPT = """Je bent de WhatsApp-assistent van FestiFlip. Je praat informeel, als een vriend die toevallig alles weet over tickets kopen/verkopen.
Datum vandaag: {today}
{lang_instruction}

{user_context}

Over FestiFlip:
- Platform om veilig tickets te kopen en verkopen via WhatsApp
- Kopers en verkopers worden automatisch gematcht
- Koper betaalt een kleine aanbetaling (7,5%, min €5/ticket) via Stripe
- Na betaling krijgt de koper het nummer van de verkoper
- Rest wordt onderling geregeld tussen koper en verkoper
- Reservering vervalt na 60 min als er niet betaald wordt
- Bij problemen (niet naar binnen, geen bewijs) schakelen we ons team in

Voor VERKOPERS specifiek:
- Je aanbod wordt geplaatst en we zoeken automatisch kopers
- Als een koper matcht, sturen we jou een bevestigingsvraag
- Zodra de koper betaalt, krijg je een bericht met het nummer van de koper
- Je regelt de overdracht verder zelf met de koper

Stijl:
- Kort en to-the-point (max 2-3 zinnen)
- Geen aanhalingstekens, geen "u"
- Als het niks met tickets te maken heeft, zeg dat gewoon chill
"""


async def answer_general_question(
    message: str,
    conversation_history: list = None,
    user_role: str = None,
) -> str:
    """Answer a general question about FestiFlip using AI.

    Args:
        message: The user's question
        conversation_history: Recent chat messages for context
        user_role: "seller", "buyer", or None — so AI knows perspective

    Returns:
        A helpful answer about the platform
    """
    today_str = date.today().strftime("%d-%m-%Y")

    # Language detection
    try:
        from app.ai.state_machine import _lang
        current_lang = _lang()
    except (ImportError, LookupError):
        current_lang = "nl"
    lang_instruction = "Reply in English, casual and friendly." if current_lang == "en" else "Informeel Nederlands, alsof je met een vriend chat."

    # User context
    if user_role == "seller":
        user_context = "BELANGRIJK: Deze gebruiker is een VERKOPER. Beantwoord vragen vanuit verkopersperspectief."
    elif user_role == "buyer":
        user_context = "BELANGRIJK: Deze gebruiker is een KOPER. Beantwoord vragen vanuit kopersperspectief."
    else:
        user_context = ""

    prompt = QA_SYSTEM_PROMPT.format(
        today=today_str,
        lang_instruction=lang_instruction,
        user_context=user_context,
    )

    try:
        messages = [{"role": "system", "content": prompt}]
        if conversation_history:
            for msg in conversation_history[-6:]:
                messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": message})

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.3,
            max_tokens=150,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Q&A error: {e}")
        return (
            "Sorry, ik kan je vraag op dit moment niet beantwoorden. "
            "Probeer het later opnieuw of neem contact op met ons team. 📞"
        )
