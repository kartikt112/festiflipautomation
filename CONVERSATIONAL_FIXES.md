# FestiFlip Conversational Flow Fixes

Complete audit of every conversational flow problem and how to fix each one.

---

## P0: Critical Flow Breaks

### Fix 1: Session Locking for Concurrent Messages
**Problem**: User sends 3 messages rapidly. All read same stale session state, only last one's data survives.
**File**: `app/ai/state_machine.py` (process_message), `app/crud/chat_sessions.py`

**Fix**: Add per-phone advisory lock before processing:
```python
# In process_message(), before any session access:
from sqlalchemy import text
await db.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"),
                 {"lock_id": hash(phone) % (2**31)})
```
This serializes all messages from the same phone number. Second message waits until first finishes.

For SQLite (dev), use an in-memory asyncio Lock per phone:
```python
import asyncio
_phone_locks: dict[str, asyncio.Lock] = {}

async def get_phone_lock(phone: str) -> asyncio.Lock:
    if phone not in _phone_locks:
        _phone_locks[phone] = asyncio.Lock()
    return _phone_locks[phone]
```

---

### Fix 2: Add Undo/Grace Period After Confirmation
**Problem**: "ja" in CONFIRMING is irreversible -- buy request created, matching runs, Stripe link generated.
**File**: `app/ai/state_machine.py` lines 1260-1429

**Fix**: After saving, set `_pending_action: "undo_last"` and add a 30-second window:
```python
# After saving buy request (line 1262):
await update_session(db, phone, current_step=IDLE,
    collected_data={"_pending_action": "undo_last", "_undo_id": result.id, "_undo_type": "buy_request"})

# In _handle_idle, add undo handler:
if pending_action == "undo_last" and is_deny:
    # Cancel the last created request/offer
    undo_id = session.collected_data.get("_undo_id")
    undo_type = session.collected_data.get("_undo_type")
    if undo_type == "buy_request":
        await cancel_buy_request(db, undo_id)  # Set status to EXPIRED
    elif undo_type == "sell_offer":
        await cancel_sell_offer(db, undo_id)  # Set status to CANCELLED
    await reset_session(db, phone)
    return "Oké, je aanvraag is geannuleerd! Wil je opnieuw beginnen?"
```

Add to the confirmation response: `"\n\n(Typ 'nee' binnen 30 seconden om te annuleren)"`

---

### Fix 3: OpenAI Circuit Breaker
**Problem**: 7+ independent OpenAI calls, partial outage creates inconsistent state.
**Files**: `app/ai/classifier.py`, `app/ai/state_machine.py`, `app/ai/fallback.py`

**Fix**: Create a shared circuit breaker:
```python
# app/ai/circuit_breaker.py
import time
import logging

logger = logging.getLogger(__name__)

class OpenAICircuitBreaker:
    def __init__(self, failure_threshold=3, recovery_time=60):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.recovery_time = recovery_time
        self.last_failure_time = 0
        self.is_open = False

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.is_open = True
            logger.warning("OpenAI circuit breaker OPEN - falling back to rules")

    def record_success(self):
        self.failure_count = 0
        self.is_open = False

    def can_call(self) -> bool:
        if not self.is_open:
            return True
        if time.time() - self.last_failure_time > self.recovery_time:
            self.is_open = False  # Half-open: try again
            return True
        return False

openai_breaker = OpenAICircuitBreaker()
```

Wrap all OpenAI calls:
```python
if not openai_breaker.can_call():
    # Use rule-based fallback
    return rule_based_result
try:
    result = await client.chat.completions.create(...)
    openai_breaker.record_success()
    return result
except Exception:
    openai_breaker.record_failure()
    raise
```

---

### Fix 4: Intent Switch Notification
**Problem**: Intent switch below 0.8 confidence is silently ignored. User thinks they switched but system keeps old intent.
**File**: `app/ai/state_machine.py` lines 1064-1125

**Fix**: When confidence is between 0.5-0.8, ASK the user instead of ignoring:
```python
if has_explicit_switch:
    if classification.confidence >= 0.8:
        # Current behavior: switch
        ...
    elif classification.confidence >= 0.5:
        # NEW: Ask for clarification
        new_intent_nl = "kopen" if classification.intent == "BUY_REQUEST" else "verkopen"
        old_intent_nl = "kopen" if session.current_intent == "BUY_REQUEST" else "verkopen"
        await update_session(db, phone, collected_data={
            **existing_data,
            "_pending_action": "intent_switch",
            "_pending_intent": classification.intent
        })
        return (f"Wil je switchen van {old_intent_nl} naar {new_intent_nl}? "
                f"Typ 'ja' om te switchen of ga verder met {old_intent_nl}.")
    # Below 0.5: ignore the switch signal (too noisy)
```

---

### Fix 5: "Ja" Ambiguity Resolution
**Problem**: "ja" in IDLE checks multiple pending actions and DB fallbacks -- can accidentally confirm wrong sale.
**File**: `app/ai/state_machine.py` lines 855-898

**Fix**: Remove the legacy DB fallback (lines 891-898). Only use `_pending_action`:
```python
# DELETE lines 891-898 (the fallback "ja"/"nee" check without _pending_action)
# This code is dangerous because it queries for ANY pending confirmation
# without the user knowing which one they're responding to.

# Instead, when creating a pending confirmation, ALWAYS set _pending_action:
# In matching.py, after sending seller confirmation message:
await update_session(db, phone, collected_data={
    "_pending_action": "seller_confirmation",
    "_pending_offer_id": offer_id,  # Track WHICH offer
    "_pending_buyer_phone": buyer_phone,
})
```

Also add context to the "ja" response -- confirm WHICH action:
```python
if pending_action == "seller_confirmation" and is_affirm:
    offer_id = session.collected_data.get("_pending_offer_id")
    # Show which offer they're confirming
    offer = await get_sell_offer(db, offer_id)
    return f"Je bevestigt dat je tickets voor {offer.event_name} nog beschikbaar zijn. ✅"
```

---

## P1: High Impact Flow Issues

### Fix 6: Session Timeout Notification
**Problem**: After 2h silence, session silently resets.
**File**: `app/ai/state_machine.py` lines 532-543

**Fix**:
```python
if now - last > timedelta(hours=SESSION_TIMEOUT_HOURS):
    logger.info(f"Session timeout for {phone}")
    old_intent = session.current_intent
    old_data = session.collected_data or {}
    await reset_session(db, phone)
    session = await get_or_create_session(db, phone)

    # NEW: Tell the user what happened
    if old_intent:
        intent_nl = "kopen" if old_intent == "BUY_REQUEST" else "verkopen"
        event = old_data.get("event_name", "")
        prefix = (f"Hey! Je was bezig met tickets {intent_nl}"
                  f"{' voor ' + event if event else ''}, "
                  f"maar het is even stil geweest. We beginnen opnieuw.\n\n")
        # Continue processing the new message normally, but prepend the notification
        # Store prefix in session to prepend to next response
        await update_session(db, phone, collected_data={"_timeout_prefix": prefix})
```

---

### Fix 7: Expand Confirmation/Denial Word Sets
**Problem**: "doe maar", "absoluut", "tuurlijk" etc. all fail confirmation.
**File**: `app/ai/state_machine.py` lines 1241-1248, 1431

**Fix**: Replace hardcoded word matching with AI-assisted confirmation detection:
```python
# Keep the fast path for common words (unchanged)
confirm_words = {"ja", "yes", "ok", "oke", ...}  # existing set
deny_words = {"nee", "no", "fout", "niet klopt", "opnieuw"}

# Add more words to both sets:
confirm_words |= {"zeker weten", "doe maar", "absoluut", "helemaal", "tuurlijk",
                  "natuurlijk", "laten we gaan", "ja klopt", "ja is goed",
                  "perfect", "precies", "exact", "ga maar", "doorgaan"}

deny_words |= {"klopt niet", "verkeerd", "dat is niet goed", "niet correct",
               "kan niet kloppen", "dit is fout", "niet goed", "onjuist",
               "dat klopt niet", "nee dat klopt niet"}

# Also check startswith for common prefixes
confirm_prefixes = ("ja ", "ok ", "oke ", "goed ", "top ", "prima ", "klopt ", "zeker ")
deny_prefixes = ("nee ", "fout ", "niet ", "verkeerd ")

if msg in confirm_words or any(msg.startswith(p) for p in confirm_prefixes):
    # confirm
elif msg in deny_words or any(msg.startswith(p) for p in deny_prefixes):
    # deny
```

---

### Fix 8: Handle Emoji Messages
**Problem**: "👍" in confirmation creates infinite loop.
**File**: `app/ai/state_machine.py` (multiple locations)

**Fix**: Add emoji mapping:
```python
# At top of state_machine.py
EMOJI_CONFIRM = {"👍", "👌", "✅", "🙏", "💪", "🤝", "😊", "🫡", "👍🏻", "👍🏽"}
EMOJI_DENY = {"👎", "❌", "🚫", "😕", "😤"}
EMOJI_UNKNOWN = {"🤔", "😅", "🤷", "🤷‍♂️", "🤷‍♀️"}

# In _handle_confirming, before confirm_words check:
if msg.strip() in EMOJI_CONFIRM:
    # Treat as confirmation
    ...
elif msg.strip() in EMOJI_DENY:
    # Treat as denial
    ...
```

---

### Fix 9: Handle Unsupported Message Types
**Problem**: Voice messages, stickers, locations, contacts all result in empty text -> confusing response.
**File**: `app/routers/whatsapp.py`

**Fix**: Before processing, check message type:
```python
# In receive_message(), after extracting message_data:
msg_type = message_data.get("type", "text")

SUPPORTED_TYPES = {"text", "image"}
UNSUPPORTED_MESSAGES = {
    "audio": "Sorry, ik kan geen spraakberichten verwerken. Typ je bericht alsjeblieft! 📝",
    "video": "Sorry, ik kan geen video's verwerken. Stuur een foto van je ticket of typ je bericht. 📝",
    "sticker": "Leuke sticker! 😄 Maar ik kan alleen tekst en foto's verwerken. Hoe kan ik je helpen?",
    "location": "Bedankt voor je locatie, maar die heb ik niet nodig. Wil je tickets kopen of verkopen?",
    "contacts": "Ik kan geen contacten verwerken. Typ je bericht alsjeblieft! 📝",
    "document": "Ik kan geen documenten verwerken. Stuur een foto van je ticket of typ je bericht. 📝",
}

if msg_type in UNSUPPORTED_MESSAGES:
    await send_text_message(phone, UNSUPPORTED_MESSAGES[msg_type])
    return {"status": "ok"}
```

---

### Fix 10: "Nee" Handling for All Pending Actions
**Problem**: "nee" to "expired_rebuy" and "more_sells" falls through with no proper response.
**File**: `app/ai/state_machine.py` lines 861-888

**Fix**:
```python
if (is_affirm or is_deny) and pending_action:
    if pending_action == "seller_confirmation":
        # ... existing handling ...

    elif pending_action == "expired_rebuy":
        if is_affirm:
            return await _handle_expired_rebuy(db, phone)
        else:  # NEW: handle "nee"
            await reset_session(db, phone)
            return "Oké, geen probleem! Wil je iets anders kopen of verkopen?"

    elif pending_action == "more_sells":
        if is_affirm:
            # ... existing handling ...
        else:  # NEW: handle "nee"
            await reset_session(db, phone)
            return "Top, je aanbiedingen zijn opgeslagen! Laat maar weten als je nog iets nodig hebt 👋"

    elif pending_action == "undo_last":
        # ... (from Fix 2 above) ...
```

---

### Fix 11: GENERAL_QUESTION Entity Data Recovery
**Problem**: Price answers phrased as statements get intercepted by Q&A handler.
**File**: `app/ai/state_machine.py` lines 589-628

**Fix**: When in COLLECTING/CONFIRMING, bias toward treating messages as data input:
```python
# Replace the existing check (lines 594-624) with:
if session.current_step in (COLLECTING, CONFIRMING):
    # Check 1: Does the classifier have entities?
    real_entities = {k: v for k, v in (classification.entities or {}).items()
                     if v is not None and k in (...)}

    # Check 2: Does the message contain numbers or prices? (very likely data input)
    has_numbers = bool(re.search(r'€?\s*\d+', raw_message))
    has_date_pattern = bool(re.search(r'\d{1,2}[\s/-]\w+|\w+\s+\d{4}', raw_message))

    # Check 3: Is the message short? (< 30 chars = likely answering a question)
    is_short_answer = len(raw_message.strip()) < 30

    if real_entities or has_numbers or has_date_pattern or is_short_answer:
        # Treat as data input, not a general question
        pass  # Fall through to state handler
    else:
        # Genuine general question - answer it but redirect
        from app.ai.qa import answer_general_question
        answer = await answer_general_question(message)
        # ... append redirect question ...
```

---

### Fix 12: Seller Confirmation Timeout
**Problem**: Buyer waits forever if seller never responds to availability check.
**File**: `app/services/matching.py`, `app/services/scheduler.py`

**Fix**: Add a 4-hour timeout on seller confirmations:
```python
# In scheduler.py, add new job:
async def expire_pending_confirmations_job():
    """Cancel seller confirmations older than 4 hours."""
    async with async_session() as db:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=4)
        expired = await db.execute(
            select(PendingConfirmation)
            .where(PendingConfirmation.created_at < cutoff)
            .where(PendingConfirmation.status == "PENDING")
        )
        for confirmation in expired.scalars():
            confirmation.status = "EXPIRED"
            # Notify buyer
            await send_text_message(
                confirmation.buyer_phone,
                f"De verkoper heeft niet gereageerd voor {confirmation.event_name}. "
                "We zoeken een andere match voor je!"
            )
            # Try to find alternative match
            await auto_match_and_notify(db, ...)
        await db.commit()
```

---

## P2: Medium Impact Improvements

### Fix 13: Multi-Event Cancel Support
**File**: `app/ai/state_machine.py` lines 1018-1062

Add explicit cancel phrases to the multi-event AI interpreter AND as hard-coded checks:
```python
# Before calling AI interpreter:
cancel_phrases = {"stop", "annuleer", "ik stop", "laat maar", "vergeet het",
                  "ik wil niet meer", "dit is verkeerd", "fout"}
if raw_message.strip().lower() in cancel_phrases:
    saved = existing_data.get("_multi_event_done", 0)
    await update_session(db, phone, current_intent=None, current_step=IDLE, collected_data={})
    if saved > 0:
        return f"Gestopt! {saved} evenement(en) zijn al opgeslagen. De rest is geannuleerd."
    return "Oké, geannuleerd! Wil je iets anders doen?"
```

---

### Fix 14: Event Name Correction via AI
**Problem**: Regex for event name correction is too narrow.
**File**: `app/ai/state_machine.py` lines 1154-1161

**Fix**: Replace regex with AI extraction (already running):
```python
# Remove the regex-based event correction (lines 1154-1161)
# Instead, rely on the classifier's entity extraction which already handles:
# "nee het heet Coldplay" -> entities: {event_name: "Coldplay"}
# The classifier is already called at line 547 and entities are at line 1140

# If classifier missed it AND the message is clearly a correction:
if not new_entities.get("event_name") and msg_lower.startswith("nee"):
    # Strip "nee" prefix and treat remainder as event name
    potential_name = re.sub(r'^nee[,.\s]*', '', raw_message.strip()).strip()
    if 3 <= len(potential_name) <= 60 and potential_name.lower() not in _REJECT_NAMES:
        new_entities["event_name"] = potential_name
```

---

### Fix 15: Verification "Ja" Loop Fix
**Problem**: After event verification returns `is_real: False`, user's "ja dat klopt" gets classified as GENERAL_QUESTION.
**File**: `app/ai/state_machine.py` lines 148-158

**Fix**: Set `_pending_action: "event_verification"` after asking the user:
```python
if not data.get("_verification_warning_sent"):
    data["_verification_warning_sent"] = True
    data["_pending_verification"] = True  # NEW flag
    return data, f"Ik kan '{data['event_name']}' niet vinden..."

# Then in _handle_collecting, check for this flag BEFORE classification:
if existing_data.get("_pending_verification"):
    if msg_lower in ("ja", "yes", "klopt", "zeker", "ja dat klopt"):
        existing_data["_verified"] = True
        existing_data.pop("_pending_verification", None)
        # Continue collecting remaining fields
        ...
    elif msg_lower in ("nee", "no"):
        existing_data.pop("event_name", None)
        existing_data.pop("_pending_verification", None)
        return "Oké, wat is het juiste evenement?"
```

---

### Fix 16: Group Chat Detection
**File**: `app/routers/whatsapp.py`

**Fix**: Check for group messages and ignore them:
```python
# In receive_message(), before processing:
# WhatsApp group messages have a different structure
metadata = message_data.get("context", {})
is_group = "@g.us" in (message_data.get("from", "") or "")

if is_group:
    logger.info(f"Ignoring group message from {phone}")
    return {"status": "ok"}  # Silently ignore
```

---

### Fix 17: Bare "Ja" Guard in COLLECTING
**Problem**: "ja" when all fields happen to be filled jumps to confirmation prematurely.
**File**: `app/ai/state_machine.py` lines 1127-1136

**Fix**: Only jump if user was explicitly asked a yes/no question:
```python
if _bare_affirm in ("ja", "yes", "ok", ...):
    existing = session.collected_data or {}

    # Only jump to confirming if we were asking a yes/no question
    # (e.g., verification, ticket type selection)
    if existing.get("_pending_verification") or existing.get("_awaiting_yn"):
        # Handle the yes/no in context
        ...
    else:
        # NOT a yes/no context - just ask the next missing field
        missing = validate_entities(session.current_intent, existing)
        if not missing:
            await update_session(db, phone, current_step=CONFIRMING, collected_data=existing)
            return _format_confirmation(session.current_intent, existing)
        return ask_missing_field(missing[0], session.current_intent)
```

---

## Implementation Order

1. **Fix 1** (session locking) - Prevents the most common data loss
2. **Fix 9** (unsupported message types) - Quick win, stops confusion
3. **Fix 7** (expand confirm/deny words) - Quick win, reduces round trips
4. **Fix 8** (emoji handling) - Quick win, breaks infinite loops
5. **Fix 10** ("nee" for all pending actions) - Quick win
6. **Fix 6** (session timeout notification) - Quick win
7. **Fix 3** (circuit breaker) - Prevents cascading failures
8. **Fix 4** (intent switch notification) - Prevents silent confusion
9. **Fix 5** ("ja" ambiguity fix) - Prevents wrong confirmations
10. **Fix 11** (GENERAL_QUESTION entity recovery) - Prevents data loss
11. **Fix 2** (undo after confirmation) - Prevents irreversible mistakes
12. **Fix 12** (seller confirmation timeout) - Prevents infinite waits
13. **Fix 13-17** (remaining P2 fixes)
