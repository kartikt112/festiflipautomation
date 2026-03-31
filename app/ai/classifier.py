"""Hybrid intent classifier – rule-based fast path + AI fallback."""

import json
import logging
from dataclasses import dataclass
from typing import Optional, Dict

from openai import AsyncOpenAI
from app.config import settings
from app.ai.rules import classify_by_rules, UNKNOWN, BUY_REQUEST
from app.ai.prompts import CLASSIFICATION_PROMPT, PROMPT_VERSION
from app.ai.extractor import normalize_entities

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.8

# Initialize OpenAI client
_client: Optional[AsyncOpenAI] = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


@dataclass
class ClassificationResult:
    intent: str
    entities: Dict
    confidence: float
    method: str  # "RULES" or "AI"
    prompt_version: Optional[str] = None
    raw_ai_response: Optional[dict] = None


async def classify_message(
    message: str, conversation_history: list = None
) -> ClassificationResult:
    """Classify a WhatsApp message using hybrid approach.

    1. Try rule-based first
    2. If confidence < 0.8, use AI classification
    3. Return result with method and confidence

    Args:
        message: Raw message text
        conversation_history: Recent chat messages [{"role": "user"/"assistant", "content": "..."}]

    Returns:
        ClassificationResult with intent, entities, confidence, method
    """
    # Step 1: Rule-based classification (Run for fallback/comparison)
    rule_intent, rule_confidence = classify_by_rules(message)

    # Step 0.5: Forwarded message override — forwarded listings are always BUY intent
    msg_lower = message.strip().lower()
    is_forwarded = msg_lower.startswith("[doorgestuurd]") or msg_lower.startswith("[forwarded]")

    if is_forwarded and rule_intent == BUY_REQUEST:
        # Extract entities from the forwarded listing via AI, but force BUY intent
        try:
            ai_result = await _classify_with_ai(message, conversation_history)
            entities = normalize_entities(ai_result) if ai_result else {}
            # Map seller price to buyer's max_price
            if entities.get("price_per_ticket") and not entities.get("max_price"):
                entities["max_price"] = entities.pop("price_per_ticket")
            return ClassificationResult(
                intent=BUY_REQUEST,
                entities=entities,
                confidence=0.95,
                method="RULES (Forwarded→BUY)",
                prompt_version=PROMPT_VERSION,
                raw_ai_response=ai_result,
            )
        except Exception as e:
            logger.error(f"AI extraction for forwarded message failed: {e}")
            return ClassificationResult(
                intent=BUY_REQUEST, entities={}, confidence=0.9, method="RULES (Forwarded→BUY)"
            )

    # Step 2: AI classification (PRIMARY)
    try:
        ai_result = await _classify_with_ai(message, conversation_history)
        if ai_result:
            ai_confidence = ai_result.get("confidence", 0.0)
            ai_intent = ai_result.get("intent", UNKNOWN)

            # SAFETY OVERRIDE: if user explicitly says 'verkopen'/'te koop'/'verkoop'
            # but AI returned BUY_REQUEST, forcefully correct to SELL_OFFER
            # Skip this override for forwarded messages (already handled above)
            import re
            sell_signals = re.search(
                r'\b(?:verkopen|verkoop|te koop|aanbieden|wil ik verkopen|om te verkopen)\b',
                msg_lower
            )
            buy_signals = re.search(
                r'\b(?:kopen|zoek|nodig|op zoek|wil kopen|wil ik kopen)\b',
                msg_lower
            )
            if sell_signals and ai_intent == "BUY_REQUEST" and not buy_signals:
                logger.info(f"SAFETY OVERRIDE: AI said BUY_REQUEST but message contains sell signal. Correcting to SELL_OFFER.")
                ai_intent = "SELL_OFFER"
            
            # Use AI result as primary — it extracts entities (dates/prices) which rules miss.
            return ClassificationResult(
                intent=ai_intent,
                entities=normalize_entities(ai_result),
                confidence=ai_confidence,
                method="AI",
                prompt_version=PROMPT_VERSION,
                raw_ai_response=ai_result,
            )
            
    except Exception as e:
        logger.error(f"AI classification failed: {e}")

    # Step 3: Fallback to Rules if AI failed/returned nothing
    if rule_intent != UNKNOWN and rule_confidence >= 0.4:
        return ClassificationResult(
            intent=rule_intent,
            entities={},
            confidence=rule_confidence,
            method="RULES (Fallback)",
        )
    
    # No match
    return ClassificationResult(
        intent=UNKNOWN,
        entities={},
        confidence=0.0,
        method="UNKNOWN",
    )


async def _classify_with_ai(
    message: str, conversation_history: list = None
) -> Optional[dict]:
    """Call OpenAI ChatGPT for classification and entity extraction.

    Returns parsed JSON dict or None on failure.
    """
    if not settings.OPENAI_API_KEY:
        logger.warning("OpenAI API key not configured, skipping AI classification")
        return None

    try:
        client = _get_client()

        from datetime import date
        today = date.today()
        full_prompt = CLASSIFICATION_PROMPT.format(
            message=message,
            today=today.strftime("%Y-%m-%d"),
            today_year=today.year,
        )

        # Build messages with conversation context
        messages = [
            {
                "role": "system",
                "content": "Je bent een JSON-only classificatie-assistent. Geef alleen geldig JSON terug, geen uitleg.",
            },
        ]

        # Inject recent conversation history so AI understands context
        if conversation_history:
            # Add a context separator so AI knows this is history
            messages.append({
                "role": "system",
                "content": "Hieronder volgt de recente gespreksgeschiedenis met deze gebruiker:",
            })
            for msg in conversation_history[-8:]:  # Last 8 messages max
                messages.append({
                    "role": msg["role"],
                    "content": msg["content"],
                })

        messages.append({
            "role": "user",
            "content": full_prompt,
        })

        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.1,
        )

        result = json.loads(response.choices[0].message.content)

        logger.info(f"AI classified message as: {result.get('intent')} "
                     f"(confidence: {result.get('confidence')})")
        return result

    except json.JSONDecodeError as e:
        logger.error(f"AI returned invalid JSON: {e}")
        return None
    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        return None
