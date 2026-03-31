"""CHAOS stress test: Break the bot like Rens does.

Simulates the most chaotic, unpredictable real-world usage patterns:
- Typos, slang, mixed languages
- Mid-flow intent switches
- Contradictions and corrections
- Multi-event chaos
- Random "ja" and "nee" at wrong times
- Gibberish mixed with real data
- Rapid-fire messages
- Reset mid-flow then continue
- Conversational sentences that look like event names
"""

import asyncio
import sys
import re

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"

passed = 0
failed = 0
errors = []


async def send(db, phone, message):
    from app.ai.state_machine import process_message
    reply = await process_message(db, phone, message)
    print(f"    {YELLOW}→ {message[:80]}{RESET}")
    print(f"    {CYAN}← {reply[:120]}{RESET}")
    return reply


async def reset_user(db, phone):
    from app.crud.chat_sessions import reset_session
    await reset_session(db, phone)
    await db.commit()


async def get_session(db, phone):
    from app.crud.chat_sessions import get_or_create_session
    return await get_or_create_session(db, phone)


def check(test_name, condition, detail=""):
    global passed, failed, errors
    if condition:
        print(f"  {GREEN}✓{RESET} {test_name}")
        passed += 1
    else:
        msg = f"  FAIL: '{test_name}'"
        if detail:
            msg += f" — {detail}"
        print(f"  {RED}✗{RESET} {test_name}")
        print(f"    {RED}{msg}{RESET}")
        errors.append(msg)
        failed += 1


def reply_has(reply, *phrases):
    """Check reply contains all phrases (case-insensitive)."""
    return all(p.lower() in reply.lower() for p in phrases)


def reply_not(reply, *phrases):
    """Check reply does NOT contain any phrase."""
    return not any(p.lower() in reply.lower() for p in phrases)


async def main():
    global passed, failed

    from app.database import async_session
    PHONE = "+31TEST_RENS_CHAOS"

    # ═══════════════════════════════════════════════════════════
    # 1. CONVERSATIONAL GARBAGE AS EVENT NAMES
    # The #1 Rens bug: Dutch sentences stored as event_name
    # ═══════════════════════════════════════════════════════════
    print(f"\n{BOLD}{CYAN}{'═'*60}")
    print(f"  1. CONVERSATIONAL GARBAGE AS EVENT NAMES")
    print(f"{'═'*60}{RESET}")

    async with async_session() as db:
        # 1.1: The flagship Rens bug
        print(f"\n{BOLD}--- 1.1 'nee maar k ben verkoper he' ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik zoek tickets")
        await send(db, PHONE, "nee maar k ben verkoper he")
        session = await get_session(db, PHONE)
        en = str((session.collected_data or {}).get("event_name", "")).lower()
        check("NOT stored as event", "verkoper" not in en and "nee maar" not in en, f"event_name='{en}'")
        await db.commit()

        # 1.2: Long conversational sentence
        print(f"\n{BOLD}--- 1.2 'echt 5 evenementen...' ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik wil verkopen")
        await send(db, PHONE, "echt 5 evenementen kunnen we dit ff snel in een keer regelen")
        session = await get_session(db, PHONE)
        en = str((session.collected_data or {}).get("event_name", "")).lower()
        check("NOT stored as event", "evenementen" not in en and "regelen" not in en, f"event_name='{en}'")
        await db.commit()

        # 1.3: Question as event name
        print(f"\n{BOLD}--- 1.3 'hoe werkt de betaling eigenlijk?' ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik wil tickets kopen")
        reply = await send(db, PHONE, "hoe werkt de betaling eigenlijk?")
        session = await get_session(db, PHONE)
        en = str((session.collected_data or {}).get("event_name", "")).lower()
        check("Question NOT stored as event", "betaling" not in en, f"event_name='{en}'")
        await db.commit()

        # 1.4: Complaint as event name
        print(f"\n{BOLD}--- 1.4 'dit is echt kut, waarom duurt het zo lang' ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik wil tickets verkopen")
        reply = await send(db, PHONE, "dit is echt kut, waarom duurt het zo lang")
        session = await get_session(db, PHONE)
        en = str((session.collected_data or {}).get("event_name", "")).lower()
        check("Complaint NOT stored as event", "kut" not in en and "duurt" not in en, f"event_name='{en}'")
        await db.commit()

        # 1.5: "ja" alone should NOT become event name
        print(f"\n{BOLD}--- 1.5 'ja' should NOT become event_name ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik wil kopen")
        await send(db, PHONE, "ja")
        session = await get_session(db, PHONE)
        en = str((session.collected_data or {}).get("event_name", "")).lower()
        check("'ja' not stored as event", en != "ja", f"event_name='{en}'")
        await db.commit()

    # ═══════════════════════════════════════════════════════════
    # 2. MULTI-FIELD SINGLE MESSAGE (the scaleup030 bug)
    # User provides ALL data at once during COLLECTING
    # ═══════════════════════════════════════════════════════════
    print(f"\n{BOLD}{CYAN}{'═'*60}")
    print(f"  2. MULTI-FIELD SINGLE MESSAGE")
    print(f"{'═'*60}{RESET}")

    async with async_session() as db:
        # 2.1: All fields in one message during COLLECTING
        print(f"\n{BOLD}--- 2.1 All fields in one message ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik wil tickets verkopen")
        reply = await send(db, PHONE, "event is scaleup030, het is op 3 mei, 2 stuks, mogen weg voor 30 euro per stuk")
        check("Goes to confirmation", reply_has(reply, "klopt"), f"reply={reply[:100]}")
        check("Has event name", reply_has(reply, "scaleup030"), f"reply={reply[:100]}")
        check("Has quantity", reply_has(reply, "2x"), f"reply={reply[:100]}")
        check("Has price", reply_has(reply, "30"), f"reply={reply[:100]}")
        await db.commit()

        # 2.2: Comma-separated natural language
        print(f"\n{BOLD}--- 2.2 Comma-sep natural language ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik wil verkopen")
        reply = await send(db, PHONE, "thuishaven, 5 april, 3 stuks, 80 euro per ticket")
        check("Goes to confirmation", reply_has(reply, "klopt"), f"reply={reply[:100]}")
        check("Has thuishaven", reply_has(reply, "thuishaven"), f"reply={reply[:100]}")
        await db.commit()

        # 2.3: Template-style with labels
        print(f"\n{BOLD}--- 2.3 Template response ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik wil tickets kopen")
        reply = await send(db, PHONE, (
            "Evenement: Dekmantel\n"
            "Datum: 1 augustus\n"
            "Aantal: 4\n"
            "Max prijs per ticket: €120"
        ))
        check("Goes to confirmation", reply_has(reply, "klopt"), f"reply={reply[:100]}")
        check("Has Dekmantel", reply_has(reply, "dekmantel"), f"reply={reply[:100]}")
        await db.commit()

    # ═══════════════════════════════════════════════════════════
    # 3. "JA" AFTER RESET — STALE ACTION BUG
    # ═══════════════════════════════════════════════════════════
    print(f"\n{BOLD}{CYAN}{'═'*60}")
    print(f"  3. 'JA' AFTER RESET — STALE ACTIONS")
    print(f"{'═'*60}{RESET}")

    async with async_session() as db:
        # 3.1: Reset then "ja"
        print(f"\n{BOLD}--- 3.1 'ja' after full reset ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik wil tickets verkopen")
        await send(db, PHONE, "Dekmantel, 1 aug, 2 stuks, €80")
        await send(db, PHONE, "ja")  # confirm sell
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ja")
        check("No stale action", reply_not(reply, "betaal", "checkout", "stripe", "€"), f"reply={reply[:150]}")
        await db.commit()

        # 3.2: "stop" then "ja" immediately
        print(f"\n{BOLD}--- 3.2 'stop' then 'ja' ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik wil verkopen")
        await send(db, PHONE, "stop")
        reply = await send(db, PHONE, "ja")
        check("No stale action after stop", reply_not(reply, "betaal", "checkout", "stripe"), f"reply={reply[:150]}")
        await db.commit()

    # ═══════════════════════════════════════════════════════════
    # 4. MID-FLOW INTENT SWITCHES
    # Start buying, switch to selling mid-conversation
    # ═══════════════════════════════════════════════════════════
    print(f"\n{BOLD}{CYAN}{'═'*60}")
    print(f"  4. MID-FLOW INTENT SWITCHES")
    print(f"{'═'*60}{RESET}")

    async with async_session() as db:
        # 4.1: Buy → Sell mid-flow
        print(f"\n{BOLD}--- 4.1 Buy → Sell switch ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik zoek tickets voor Lowlands")
        reply = await send(db, PHONE, "wacht, ik wil eigenlijk verkopen")
        session = await get_session(db, PHONE)
        check("Switched to SELL", session.current_intent == "SELL_OFFER", f"intent={session.current_intent}")
        await db.commit()

        # 4.2: Sell → Buy with "nee maar k ben koper"
        print(f"\n{BOLD}--- 4.2 Sell → 'nee maar k ben koper' ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik wil verkopen")
        reply = await send(db, PHONE, "nee wacht, ik wil kopen eigenlijk")
        session = await get_session(db, PHONE)
        check("Switched to BUY", session.current_intent == "BUY_REQUEST", f"intent={session.current_intent}")
        await db.commit()

    # ═══════════════════════════════════════════════════════════
    # 5. MULTI-EVENT CHAOS
    # ═══════════════════════════════════════════════════════════
    print(f"\n{BOLD}{CYAN}{'═'*60}")
    print(f"  5. MULTI-EVENT CHAOS")
    print(f"{'═'*60}{RESET}")

    async with async_session() as db:
        # 5.1: Multi-event detection
        print(f"\n{BOLD}--- 5.1 '3 verschillende evenementen' detected ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "k wil graag 20 tickets verkoepn voor 3 verschillende evenementen")
        check("Multi-event detected", reply_has(reply, "meerdere") or reply_has(reply, "---"), f"reply={reply[:100]}")
        session = await get_session(db, PHONE)
        cd = session.collected_data or {}
        check("Tracks multi_event_total", cd.get("_multi_event_total") == 3, f"total={cd.get('_multi_event_total')}")
        await db.commit()

        # 5.2: Complete event 1, check short confirmation
        print(f"\n{BOLD}--- 5.2 Event 1/3: short confirmation ---{RESET}")
        reply = await send(db, PHONE, "scaleup030, 3 mei, 2 stuks, 30 euro per stuk")
        # Should go to confirmation
        if reply_has(reply, "klopt"):
            reply = await send(db, PHONE, "ja")
            check("Short confirmation (no full breakdown)", reply_not(reply, "De stappen zijn als volgt"), f"reply={reply[:150]}")
            check("Shows progress", reply_has(reply, "1/3") or reply_has(reply, "1 van 3"), f"reply={reply[:150]}")
        else:
            check("Goes to confirmation after all fields", False, f"reply={reply[:150]}")
        await db.commit()

        # 5.3: "klaar" after event 1 — early exit
        print(f"\n{BOLD}--- 5.3 Early exit with 'klaar' ---{RESET}")
        reply = await send(db, PHONE, "klaar")
        check("Early exit accepted", reply_has(reply, "opgeslagen"), f"reply={reply[:100]}")
        session = await get_session(db, PHONE)
        check("Session reset to IDLE", session.current_step == "IDLE", f"step={session.current_step}")
        await db.commit()

    async with async_session() as db:
        # 5.4: Multi-event with count change
        print(f"\n{BOLD}--- 5.4 Count change: 'maar 2 evenementen' ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "k wil tickets verkopen voor 5 verschillende evenementen")
        await send(db, PHONE, "festival X, 1 juni, 3 stuks, 50 euro")
        await send(db, PHONE, "ja")
        reply = await send(db, PHONE, "maar 2 evenementen")
        check("Count changed", reply_has(reply, "2") or reply_has(reply, "aangepast"), f"reply={reply[:100]}")
        await db.commit()

    # ═══════════════════════════════════════════════════════════
    # 5B. MULTI-EVENT CANCELLATION (B3 fix)
    # ═══════════════════════════════════════════════════════════
    print(f"\n{BOLD}{CYAN}{'═'*60}")
    print(f"  5B. MULTI-EVENT CANCELLATION (B3)")
    print(f"{'═'*60}{RESET}")

    async with async_session() as db:
        # 5B.1: "ik wil niet meer" during multi-event — global reset
        print(f"\n{BOLD}--- 5B.1 'ik wil niet meer' cancels multi-event ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik wil tickets verkopen voor 3 evenementen")
        await send(db, PHONE, "scaleup030, 3 mei, 2 stuks, 30 euro per stuk")
        await send(db, PHONE, "ja")
        # Now 1/3 done — cancel
        reply = await send(db, PHONE, "ik wil niet meer")
        session = await get_session(db, PHONE)
        check("'ik wil niet meer' → exits flow", session.current_step == "IDLE", f"step={session.current_step}")
        check("Reset response", reply_has(reply, "opnieuw") or reply_has(reply, "opgeslagen") or reply_has(reply, "geen probleem"), f"reply={reply[:120]}")
        await db.commit()

    async with async_session() as db:
        # 5B.2: "laat maar" during multi-event — global reset
        print(f"\n{BOLD}--- 5B.2 'laat maar' cancels multi-event ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik wil tickets verkopen voor 2 evenementen")
        reply = await send(db, PHONE, "laat maar")
        session = await get_session(db, PHONE)
        check("'laat maar' → IDLE", session.current_step == "IDLE", f"step={session.current_step}")
        await db.commit()

    async with async_session() as db:
        # 5B.3: "dit is verkeerd" during multi-event — AI control
        print(f"\n{BOLD}--- 5B.3 'dit is verkeerd' during multi-event ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik wil tickets verkopen voor 3 evenementen")
        await send(db, PHONE, "festival X, 1 juni, 3 stuks, 50 euro")
        await send(db, PHONE, "ja")
        reply = await send(db, PHONE, "dit is verkeerd")
        session = await get_session(db, PHONE)
        check("'dit is verkeerd' → exits flow", session.current_step == "IDLE", f"step={session.current_step}")
        await db.commit()

    async with async_session() as db:
        # 5B.4: "nee" during multi-event — should stop, not continue
        print(f"\n{BOLD}--- 5B.4 'nee' stops multi-event ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik wil tickets verkopen voor 3 evenementen")
        await send(db, PHONE, "Thuishaven, 5 april, 2 tickets, 40 euro")
        await send(db, PHONE, "ja")
        reply = await send(db, PHONE, "nee")
        session = await get_session(db, PHONE)
        check("'nee' → exits multi-event", session.current_step == "IDLE", f"step={session.current_step}")
        await db.commit()

    async with async_session() as db:
        # 5B.5: "vergeet het" — global reset catches it
        print(f"\n{BOLD}--- 5B.5 'vergeet het' cancels ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik wil tickets verkopen voor 4 evenementen")
        reply = await send(db, PHONE, "vergeet het")
        session = await get_session(db, PHONE)
        check("'vergeet het' → IDLE", session.current_step == "IDLE", f"step={session.current_step}")
        await db.commit()

    # ═══════════════════════════════════════════════════════════
    # 6. TYPOS, SLANG & BROKEN DUTCH
    # Real Rens messages with typos
    # ═══════════════════════════════════════════════════════════
    print(f"\n{BOLD}{CYAN}{'═'*60}")
    print(f"  6. TYPOS, SLANG & BROKEN DUTCH")
    print(f"{'═'*60}{RESET}")

    async with async_session() as db:
        # 6.1: "verkoepn" (typo for verkopen)
        print(f"\n{BOLD}--- 6.1 'verkoepn' typo ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ik wil tickets verkoepn")
        session = await get_session(db, PHONE)
        check("Typo 'verkoepn' → SELL", session.current_intent == "SELL_OFFER", f"intent={session.current_intent}")
        await db.commit()

        # 6.2: Slang pricing "mogen weg voor 30 piek"
        print(f"\n{BOLD}--- 6.2 Slang pricing ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik wil verkopen")
        reply = await send(db, PHONE, "Lowlands, 20 juni, 2 tickets, mogen weg voor 30 euro per stuk")
        check("Slang price parsed", reply_has(reply, "30") and reply_has(reply, "klopt"), f"reply={reply[:100]}")
        await db.commit()

        # 6.3: "80 per stuk" without euro symbol
        print(f"\n{BOLD}--- 6.3 '80 per stuk' no € symbol ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ik wil 2 tickets voor Dekmantel verkopen, 80 per stuk, 1 augustus")
        check("Price 80 parsed", reply_has(reply, "80"), f"reply={reply[:100]}")
        await db.commit()

    # ═══════════════════════════════════════════════════════════
    # 7. RAPID-FIRE CONTRADICTIONS
    # Say one thing, immediately contradict
    # ═══════════════════════════════════════════════════════════
    print(f"\n{BOLD}{CYAN}{'═'*60}")
    print(f"  7. RAPID-FIRE CONTRADICTIONS")
    print(f"{'═'*60}{RESET}")

    async with async_session() as db:
        # 7.1: Confirm then immediately say "nee"
        print(f"\n{BOLD}--- 7.1 Confirm then 'nee, opnieuw' ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik wil 2 tickets voor Dekmantel verkopen, €80, 1 aug")
        reply = await send(db, PHONE, "ja")
        # Should be saved
        reply = await send(db, PHONE, "wacht nee dat was fout")
        # Bot should handle this gracefully (not crash)
        check("Handles post-confirm correction gracefully", len(reply) > 5, f"reply={reply[:100]}")
        await db.commit()

        # 7.2: Give event name, then say "nee dat is niet het evenement"
        print(f"\n{BOLD}--- 7.2 Correct event name ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik zoek tickets")
        await send(db, PHONE, "Lowlands")
        reply = await send(db, PHONE, "nee, Dekmantel is het evenement")
        session = await get_session(db, PHONE)
        en = str((session.collected_data or {}).get("event_name", "")).lower()
        check("Corrected to Dekmantel", "dekmantel" in en, f"event_name='{en}'")
        await db.commit()

    # ── B5: Event name correction — all phrasings ──
    async with async_session() as db:
        print(f"\n{BOLD}--- 7.3 'het evenement is Thuishaven' (reversed order) ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik zoek tickets")
        await send(db, PHONE, "Lowlands")
        reply = await send(db, PHONE, "het evenement is Thuishaven")
        session = await get_session(db, PHONE)
        en = str((session.collected_data or {}).get("event_name", "")).lower()
        check("Reversed: 'het evenement is X'", "thuishaven" in en, f"event_name='{en}'")
        await db.commit()

    async with async_session() as db:
        print(f"\n{BOLD}--- 7.4 'ik bedoel Dekmantel' ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik wil kopen")
        await send(db, PHONE, "Lowlands")
        reply = await send(db, PHONE, "ik bedoel Dekmantel")
        session = await get_session(db, PHONE)
        en = str((session.collected_data or {}).get("event_name", "")).lower()
        check("'ik bedoel X' corrects event", "dekmantel" in en, f"event_name='{en}'")
        await db.commit()

    async with async_session() as db:
        print(f"\n{BOLD}--- 7.5 'nee het heet DGTL' ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik zoek tickets")
        await send(db, PHONE, "Lowlands")
        reply = await send(db, PHONE, "nee het heet DGTL")
        session = await get_session(db, PHONE)
        en = str((session.collected_data or {}).get("event_name", "")).lower()
        check("'nee het heet X' corrects event", "dgtl" in en, f"event_name='{en}'")
        await db.commit()

    async with async_session() as db:
        print(f"\n{BOLD}--- 7.6 'de naam is Soenda' ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik wil kopen")
        await send(db, PHONE, "Lowlands")
        reply = await send(db, PHONE, "de naam is Soenda")
        session = await get_session(db, PHONE)
        en = str((session.collected_data or {}).get("event_name", "")).lower()
        check("'de naam is X' corrects event", "soenda" in en, f"event_name='{en}'")
        await db.commit()

    # ═══════════════════════════════════════════════════════════
    # 8. PRICE & QUANTITY EDGE CASES
    # ═══════════════════════════════════════════════════════════
    print(f"\n{BOLD}{CYAN}{'═'*60}")
    print(f"  8. PRICE & QUANTITY EDGE CASES")
    print(f"{'═'*60}{RESET}")

    async with async_session() as db:
        # 8.1: "min. 50eur"
        print(f"\n{BOLD}--- 8.1 'min. 50eur' ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik wil verkopen")
        reply = await send(db, PHONE, "thuishaven, 5 april, 3 stuks, min. 50eur")
        session = await get_session(db, PHONE)
        cd = session.collected_data or {}
        price = cd.get("price_per_ticket") or cd.get("max_price") or 0
        check("'min. 50eur' → price 50", float(price) == 50.0, f"price={price}")
        await db.commit()

        # 8.2: "80,-" as price
        print(f"\n{BOLD}--- 8.2 '80,-' as price ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ik wil 2 Lowlands tickets kopen, max 80,-")
        session = await get_session(db, PHONE)
        cd = session.collected_data or {}
        price = cd.get("max_price") or cd.get("price_per_ticket") or 0
        check("'80,-' → price 80", float(price) == 80.0, f"price={price}")
        await db.commit()

        # 8.3: Negative quantity
        print(f"\n{BOLD}--- 8.3 Negative quantity rejected ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik wil -5 tickets voor Lowlands verkopen")
        session = await get_session(db, PHONE)
        cd = session.collected_data or {}
        qty = cd.get("quantity")
        check("Negative qty rejected", qty is None or (isinstance(qty, int) and qty > 0), f"qty={qty}")
        await db.commit()

        # 8.4: "een kaartje" — ambiguous article, NOT quantity=1
        print(f"\n{BOLD}--- 8.4 'een kaartje' = article, not qty=1 ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ik zoek een kaartje voor Lowlands")
        session = await get_session(db, PHONE)
        cd = session.collected_data or {}
        qty = cd.get("quantity")
        check("'een kaartje' → qty=null (not 1)", qty is None, f"qty={qty}")
        await db.commit()

    # ═══════════════════════════════════════════════════════════
    # 9. DATE EDGE CASES
    # ═══════════════════════════════════════════════════════════
    print(f"\n{BOLD}{CYAN}{'═'*60}")
    print(f"  9. DATE EDGE CASES")
    print(f"{'═'*60}{RESET}")

    async with async_session() as db:
        # 9.1: "volgende week donderdag"
        print(f"\n{BOLD}--- 9.1 Relative date ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik zoek 2 tickets voor Lowlands, max €100")
        reply = await send(db, PHONE, "volgende week donderdag")
        session = await get_session(db, PHONE)
        cd = session.collected_data or {}
        date_val = cd.get("event_date", "")
        check("Relative date parsed to YYYY-MM-DD", bool(re.match(r"\d{4}-\d{2}-\d{2}", str(date_val))), f"date={date_val}")
        await db.commit()

        # 9.2: No date mentioned → should be null
        print(f"\n{BOLD}--- 9.2 No date → null ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ik zoek 3 tickets voor Dekmantel, max €80")
        session = await get_session(db, PHONE)
        cd = session.collected_data or {}
        # Date should still be asked for (missing)
        check("Date not auto-filled", reply_has(reply, "datum") or reply_has(reply, "wanneer") or cd.get("event_date") is None, f"date={cd.get('event_date')}")
        await db.commit()

    # ═══════════════════════════════════════════════════════════
    # 10. FULL HAPPY PATH — SELL FLOW
    # Complete sell from start to finish, verify everything
    # ═══════════════════════════════════════════════════════════
    print(f"\n{BOLD}{CYAN}{'═'*60}")
    print(f"  10. FULL HAPPY PATH — SELL")
    print(f"{'═'*60}{RESET}")

    async with async_session() as db:
        print(f"\n{BOLD}--- 10.1 Complete sell flow ---{RESET}")
        await reset_user(db, PHONE)
        r1 = await send(db, PHONE, "hoi ik wil tickets verkopen")
        check("Step 1: asks for info", reply_has(r1, "evenement") or reply_has(r1, "info") or reply_has(r1, "stuur"), f"reply={r1[:80]}")

        r2 = await send(db, PHONE, "Dekmantel, 1 augustus, 2 stuks, €120 per ticket")
        check("Step 2: goes to confirm", reply_has(r2, "klopt"), f"reply={r2[:80]}")
        check("Step 2: has event", reply_has(r2, "dekmantel"), f"reply={r2[:80]}")
        check("Step 2: has price", reply_has(r2, "120"), f"reply={r2[:80]}")

        r3 = await send(db, PHONE, "ja")
        check("Step 3: saved", reply_has(r3, "opgeslagen"), f"reply={r3[:80]}")
        check("Step 3: shows commission", reply_has(r3, "commissie") or reply_has(r3, "FestiFlip"), f"reply={r3[:80]}")
        await db.commit()

    # ═══════════════════════════════════════════════════════════
    # 11. FULL HAPPY PATH — BUY FLOW
    # ═══════════════════════════════════════════════════════════
    print(f"\n{BOLD}{CYAN}{'═'*60}")
    print(f"  11. FULL HAPPY PATH — BUY")
    print(f"{'═'*60}{RESET}")

    async with async_session() as db:
        print(f"\n{BOLD}--- 11.1 Complete buy flow ---{RESET}")
        await reset_user(db, PHONE)
        r1 = await send(db, PHONE, "ik zoek 2 tickets voor Lowlands, max €90, 18 juli")
        check("All-in-one → confirm", reply_has(r1, "klopt"), f"reply={r1[:80]}")

        r2 = await send(db, PHONE, "ja")
        check("Saved", reply_has(r2, "opgeslagen"), f"reply={r2[:80]}")
        await db.commit()

    # ═══════════════════════════════════════════════════════════
    # 12. GIBBERISH & EDGE CASES
    # ═══════════════════════════════════════════════════════════
    print(f"\n{BOLD}{CYAN}{'═'*60}")
    print(f"  12. GIBBERISH & EDGE CASES")
    print(f"{'═'*60}{RESET}")

    async with async_session() as db:
        # 12.1: Pure gibberish
        print(f"\n{BOLD}--- 12.1 Pure gibberish ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "asdfghjkl qwerty")
        check("Doesn't crash", len(reply) > 0, f"reply={reply[:80]}")
        await db.commit()

        # 12.2: Emoji-only message
        print(f"\n{BOLD}--- 12.2 Emoji only ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "🎟️🎟️🎟️")
        check("Doesn't crash on emojis", len(reply) > 0, f"reply={reply[:80]}")
        await db.commit()

        # 12.3: Empty-ish message
        print(f"\n{BOLD}--- 12.3 Single character ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, ".")
        check("Doesn't crash on '.'", len(reply) > 0, f"reply={reply[:80]}")
        await db.commit()

        # 12.4: Very long message (500+ chars)
        print(f"\n{BOLD}--- 12.4 Very long message ---{RESET}")
        await reset_user(db, PHONE)
        long_msg = "ik wil tickets kopen voor " + "een heel lang evenement " * 25
        reply = await send(db, PHONE, long_msg)
        check("Doesn't crash on long msg", len(reply) > 0, f"reply={reply[:80]}")
        await db.commit()

        # 12.5: Number only during IDLE
        print(f"\n{BOLD}--- 12.5 '42' in IDLE ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "42")
        check("Handles bare number in IDLE", len(reply) > 0, f"reply={reply[:80]}")
        await db.commit()

    # ═══════════════════════════════════════════════════════════
    # 13. CORRECTIONS DURING CONFIRMING
    # ═══════════════════════════════════════════════════════════
    print(f"\n{BOLD}{CYAN}{'═'*60}")
    print(f"  13. CORRECTIONS DURING CONFIRMING")
    print(f"{'═'*60}{RESET}")

    async with async_session() as db:
        # 13.1: Price correction during confirmation
        print(f"\n{BOLD}--- 13.1 Price correction ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik wil 2 Dekmantel tickets verkopen, €80, 1 aug")
        reply = await send(db, PHONE, "de prijs moet 90 euro zijn")
        session = await get_session(db, PHONE)
        cd = session.collected_data or {}
        price = cd.get("price_per_ticket", 0)
        check("Price corrected to 90", float(price) == 90.0, f"price={price}")
        await db.commit()

        # 13.2: Quantity correction
        print(f"\n{BOLD}--- 13.2 Quantity correction ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik wil 2 Lowlands tickets kopen, max €80, 18 juli")
        reply = await send(db, PHONE, "eigenlijk zijn het er 4")
        session = await get_session(db, PHONE)
        cd = session.collected_data or {}
        qty = cd.get("quantity", 0)
        check("Qty corrected to 4", int(qty) == 4, f"qty={qty}")
        await db.commit()

    # ── C1: Confirmation with non-standard phrases ──
    async with async_session() as db:
        print(f"\n{BOLD}--- 13.3 'doe maar' confirms (C1) ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik wil 2 Dekmantel tickets verkopen, €80, 1 aug")
        reply = await send(db, PHONE, "doe maar")
        check("'doe maar' confirms", reply_has(reply, "opgeslagen"), f"reply={reply[:120]}")
        await db.commit()

    async with async_session() as db:
        print(f"\n{BOLD}--- 13.4 'zeker weten' confirms (C1) ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik zoek 2 tickets voor Lowlands, max €90, 18 juli")
        reply = await send(db, PHONE, "zeker weten")
        check("'zeker weten' confirms", reply_has(reply, "opgeslagen"), f"reply={reply[:120]}")
        await db.commit()

    async with async_session() as db:
        print(f"\n{BOLD}--- 13.5 'laten we gaan' confirms (C1) ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik wil 2 Dekmantel tickets verkopen, €80, 1 aug")
        reply = await send(db, PHONE, "laten we gaan")
        check("'laten we gaan' confirms", reply_has(reply, "opgeslagen"), f"reply={reply[:120]}")
        await db.commit()

    async with async_session() as db:
        print(f"\n{BOLD}--- 13.6 'tuurlijk, sla maar op' confirms via AI (C1) ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik zoek 2 tickets voor Lowlands, max €90, 18 juli")
        reply = await send(db, PHONE, "tuurlijk, sla maar op")
        check("'tuurlijk sla maar op' confirms", reply_has(reply, "opgeslagen"), f"reply={reply[:120]}")
        await db.commit()

    # ── C2: Denial with non-standard phrases ──
    async with async_session() as db:
        print(f"\n{BOLD}--- 13.7 'klopt niet' denies (C2) ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik wil 2 Dekmantel tickets verkopen, €80, 1 aug")
        reply = await send(db, PHONE, "klopt niet")
        check("'klopt niet' restarts", reply_has(reply, "opnieuw") or reply_has(reply, "evenement"), f"reply={reply[:120]}")
        session = await get_session(db, PHONE)
        check("Back to COLLECTING", session.current_step == "COLLECTING", f"step={session.current_step}")
        await db.commit()

    async with async_session() as db:
        print(f"\n{BOLD}--- 13.8 'dat klopt niet' denies (C2) ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik zoek 2 tickets voor Lowlands, max €90, 18 juli")
        reply = await send(db, PHONE, "dat klopt niet")
        check("'dat klopt niet' restarts", reply_has(reply, "opnieuw") or reply_has(reply, "evenement"), f"reply={reply[:120]}")
        await db.commit()

    async with async_session() as db:
        print(f"\n{BOLD}--- 13.9 'dit is fout' denies (C2) ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik wil 2 Dekmantel tickets verkopen, €80, 1 aug")
        reply = await send(db, PHONE, "dit is fout")
        check("'dit is fout' restarts", reply_has(reply, "opnieuw") or reply_has(reply, "evenement"), f"reply={reply[:120]}")
        await db.commit()

    async with async_session() as db:
        print(f"\n{BOLD}--- 13.10 'nee dat is niet goed' denies (C2) ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik zoek 2 tickets voor Lowlands, max €90, 18 juli")
        reply = await send(db, PHONE, "nee dat is niet goed")
        check("'nee dat is niet goed' restarts", reply_has(reply, "opnieuw") or reply_has(reply, "evenement"), f"reply={reply[:120]}")
        await db.commit()

    # ═══════════════════════════════════════════════════════════
    # 14. FORWARDED MESSAGES
    # ═══════════════════════════════════════════════════════════
    print(f"\n{BOLD}{CYAN}{'═'*60}")
    print(f"  14. FORWARDED MESSAGES")
    print(f"{'═'*60}{RESET}")

    async with async_session() as db:
        # 14.1: Forwarded FestiFlip listing
        print(f"\n{BOLD}--- 14.1 Forwarded listing ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, (
            "[Doorgestuurd] *TE KOOP 🎟️*\n"
            "🎟️ thuishaven lammers (2026-06-07)\n"
            "🔢 4 Stuks\n"
            "💰 €80.0 per stuk\n"
            "Bericht FestiFlip als je geïnteresseerd bent!"
        ))
        session = await get_session(db, PHONE)
        cd = session.collected_data or {}
        check("Forwarded → BUY intent", session.current_intent == "BUY_REQUEST", f"intent={session.current_intent}")
        check("Event extracted", "thuishaven" in str(cd.get("event_name", "")).lower(), f"event={cd.get('event_name')}")
        await db.commit()

    # ═══════════════════════════════════════════════════════════
    # 15. RAPID STATE CHANGES
    # ═══════════════════════════════════════════════════════════
    print(f"\n{BOLD}{CYAN}{'═'*60}")
    print(f"  15. RAPID STATE CHANGES")
    print(f"{'═'*60}{RESET}")

    async with async_session() as db:
        # 15.1: Start sell → reset → start buy → provide all data
        print(f"\n{BOLD}--- 15.1 Sell → reset → Buy complete ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik wil verkopen")
        await send(db, PHONE, "Dekmantel, 1 aug")
        await send(db, PHONE, "stop")
        reply = await send(db, PHONE, "ik zoek 2 tickets voor Lowlands, max €90, 18 juli")
        check("Clean restart to BUY", reply_has(reply, "klopt") or reply_has(reply, "lowlands"), f"reply={reply[:100]}")
        session = await get_session(db, PHONE)
        check("Intent is BUY", session.current_intent == "BUY_REQUEST", f"intent={session.current_intent}")
        # Old sell data should NOT leak
        cd = session.collected_data or {}
        check("No Dekmantel leak", "dekmantel" not in str(cd.get("event_name", "")).lower(), f"event={cd.get('event_name')}")
        await db.commit()

        # 15.2: Double reset
        print(f"\n{BOLD}--- 15.2 Double reset ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "stop")
        reply = await send(db, PHONE, "reset")
        check("Double reset doesn't crash", len(reply) > 0)
        await db.commit()

    # ═══════════════════════════════════════════════════════════
    # 16. UNDO AFTER CONFIRMATION (C5)
    # ═══════════════════════════════════════════════════════════
    print(f"\n{BOLD}{CYAN}{'═'*60}")
    print(f"  16. UNDO AFTER CONFIRMATION (C5)")
    print(f"{'═'*60}{RESET}")

    async with async_session() as db:
        # 16.1: Undo buy request
        print(f"\n{BOLD}--- 16.1 Undo buy: 'dat was fout' ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik wil tickets kopen")
        await send(db, PHONE, "Lowlands, 2 stuks, max 90 euro")
        reply = await send(db, PHONE, "ja")
        check("Buy saved", reply_has(reply, "opgeslagen"), f"reply={reply[:100]}")
        reply = await send(db, PHONE, "wacht dat was fout")
        check("Undo acknowledged", reply_has(reply, "annul") or reply_has(reply, "verwijder"), f"reply={reply[:120]}")
        session = await get_session(db, PHONE)
        check("Session reset after undo", session.current_step == "IDLE", f"step={session.current_step}")
        await db.commit()

    async with async_session() as db:
        # 16.2: Undo sell offer
        print(f"\n{BOLD}--- 16.2 Undo sell: 'per ongeluk bevestigd' ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik wil tickets verkopen")
        await send(db, PHONE, "Dekmantel, 1 augustus, 2 stuks, 80 euro per stuk")
        reply = await send(db, PHONE, "ja")
        check("Sell saved", reply_has(reply, "opgeslagen"), f"reply={reply[:100]}")
        reply = await send(db, PHONE, "dat was per ongeluk, wil annuleren")
        check("Sell undo acknowledged", reply_has(reply, "annul") or reply_has(reply, "verwijder"), f"reply={reply[:120]}")
        await db.commit()

    async with async_session() as db:
        # 16.3: Normal flow after save — no undo trigger
        print(f"\n{BOLD}--- 16.3 Normal message after save (no undo) ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik wil tickets kopen")
        await send(db, PHONE, "Lowlands, 2 stuks, max 90 euro")
        await send(db, PHONE, "ja")
        reply = await send(db, PHONE, "hoi")
        check("Normal msg doesn't undo", reply_not(reply, "annul", "verwijder"), f"reply={reply[:120]}")
        await db.commit()

    # ═══════════════════════════════════════════════════════════
    # RESULTS
    # ═══════════════════════════════════════════════════════════
    print(f"\n{BOLD}{'═'*60}")
    color = GREEN if failed == 0 else RED
    print(f"  RENS CHAOS TEST: {color}{passed} passed{RESET}, {color}{failed} failed{RESET}")
    print(f"{'═'*60}{RESET}")

    if errors:
        print(f"\n{RED}All failures:{RESET}")
        for e in errors:
            print(f"  {RED}{e}{RESET}")

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    asyncio.run(main())
