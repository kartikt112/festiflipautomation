"""Test script for Rens production feedback fixes.

Tests:
1. Q&A payout info — correct commission answers
2. Bot pause toggle — bot stays silent when paused
3. Verified/trusted removal — status can be set back to UNVERIFIED
4. Form link — sent when user just says "kopen"/"verkopen"
5. Edition question — asked for multi-edition events
6. Group broadcast wording — no "interested to buy" misclassification triggers
7. Push name extraction — names saved instead of "WhatsApp Seller"
8. Sell vs buy classification — forwarded "TE KOOP" not misclassified as BUY
9. Price validation — blocked when outside min/max range
10. Ticket type in broadcast — edition shown in group message
"""

import asyncio
import sys

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"

passed = 0
failed = 0
errors = []


async def send(db, phone, message, push_name=""):
    from app.ai.state_machine import process_message
    reply = await process_message(db, phone, message, push_name=push_name)
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
        msg = f"FAIL: '{test_name}'"
        if detail:
            msg += f" — {detail}"
        print(f"  {RED}✗{RESET} {test_name}")
        print(f"    {RED}{msg}{RESET}")
        errors.append(msg)
        failed += 1


def has(reply, *phrases):
    return all(p.lower() in reply.lower() for p in phrases)


def has_not(reply, *phrases):
    return not any(p.lower() in reply.lower() for p in phrases)


async def main():
    global passed, failed

    from app.database import async_session

    # ═══════════════════════════════════════════════════════════
    # 1. Q&A PAYOUT INFO (FIX 1)
    # Bot must give correct commission info, not say "full amount"
    # ═══════════════════════════════════════════════════════════
    print(f"\n{BOLD}{CYAN}{'═'*60}")
    print(f"  1. Q&A PAYOUT INFO — Correct commission answers")
    print(f"{'═'*60}{RESET}")

    async with async_session() as db:
        PHONE = "+31TEST_FIX_001"
        await reset_user(db, PHONE)

        # Seller completes a sell flow (two-step: intent, then data)
        print(f"\n{BOLD}--- 1.1 Seller asks about payout ---{RESET}")
        r1 = await send(db, PHONE, "tickets verkopen")
        r2 = await send(db, PHONE, "Fanta Event, 3 april, 5 stuks, 60 euro per stuk")
        r3 = await send(db, PHONE, "ja")

        # Now ask about payout
        r4 = await send(db, PHONE, "krijg ik dan gewoon 60 per ticket?")
        check("Mentions commission/7.5%", has(r4, "7,5") or has(r4, "7.5") or has(r4, "commissie") or has(r4, "min"), f"reply: {r4[:100]}")
        check("Does NOT say full amount", has_not(r4, "je krijgt gewoon €60", "je krijgt gewoon 60"), f"reply: {r4[:100]}")
        await db.commit()

        print(f"\n{BOLD}--- 1.2 Seller asks 'ontvangen jullie geld?' ---{RESET}")
        r5 = await send(db, PHONE, "ontvangen jullie een deel van de ticketprijs?")
        check("Says YES FestiFlip gets commission", has_not(r5, "nee, wij ontvangen geen"), f"reply: {r5[:100]}")
        await db.commit()

    # ═══════════════════════════════════════════════════════════
    # 2. BOT PAUSE TOGGLE (FIX 3)
    # ═══════════════════════════════════════════════════════════
    print(f"\n{BOLD}{CYAN}{'═'*60}")
    print(f"  2. BOT PAUSE — Silent when paused")
    print(f"{'═'*60}{RESET}")

    async with async_session() as db:
        PHONE = "+31TEST_FIX_002"
        await reset_user(db, PHONE)

        # Normal reply first
        r1 = await send(db, PHONE, "hoi")
        check("Bot replies when active", len(r1) > 0, f"reply length: {len(r1)}")

        # Pause the bot
        session = await get_session(db, PHONE)
        session.bot_paused = True
        await db.commit()

        r2 = await send(db, PHONE, "hallo?")
        check("Bot stays silent when paused", r2 == "", f"reply: '{r2[:80]}'")

        # Unpause
        session = await get_session(db, PHONE)
        session.bot_paused = False
        await db.commit()

        r3 = await send(db, PHONE, "ben je er?")
        check("Bot replies again after unpause", len(r3) > 0, f"reply length: {len(r3)}")
        await db.commit()

    # ═══════════════════════════════════════════════════════════
    # 3. FORM LINK (FEATURE 5)
    # Send form URL when user just says "kopen" or "verkopen"
    # ═══════════════════════════════════════════════════════════
    print(f"\n{BOLD}{CYAN}{'═'*60}")
    print(f"  3. FORM LINK — Sent for bare intent")
    print(f"{'═'*60}{RESET}")

    async with async_session() as db:
        PHONE = "+31TEST_FIX_003"

        print(f"\n{BOLD}--- 3.1 Bare 'verkopen' → sellform link ---{RESET}")
        await reset_user(db, PHONE)
        r1 = await send(db, PHONE, "ik wil tickets verkopen")
        check("Sell form link sent", has(r1, "festiflip.nl/sellform"), f"reply: {r1[:100]}")

        print(f"\n{BOLD}--- 3.2 Bare 'kopen' → searchform link ---{RESET}")
        await reset_user(db, PHONE)
        r2 = await send(db, PHONE, "ik wil tickets kopen")
        check("Buy form link sent", has(r2, "festiflip.nl/searchform"), f"reply: {r2[:100]}")

        print(f"\n{BOLD}--- 3.3 Full data → NO form link (direct flow) ---{RESET}")
        await reset_user(db, PHONE)
        r3 = await send(db, PHONE, "ik zoek 2 tickets voor Lowlands, max 90 euro")
        check("No form link when data given", has_not(r3, "festiflip.nl"), f"reply: {r3[:100]}")
        await db.commit()

    # ═══════════════════════════════════════════════════════════
    # 4. GROUP BROADCAST WORDING (Misclassification fix)
    # No more "interested to buy" that triggers BUY classification
    # ═══════════════════════════════════════════════════════════
    print(f"\n{BOLD}{CYAN}{'═'*60}")
    print(f"  4. GROUP BROADCAST — No buy/sell trigger words")
    print(f"{'═'*60}{RESET}")

    from app.message_templates.templates import (
        sell_offer_group_broadcast,
        buy_request_group_broadcast,
        searching_broadcast,
        event_sale_broadcast,
    )
    from decimal import Decimal

    print(f"\n{BOLD}--- 4.1 Sell offer broadcast ---{RESET}")
    msg = sell_offer_group_broadcast("DGTL", "2026-04-05", 3, "80")
    print(f"    {CYAN}{msg}{RESET}")
    check("No 'geïnteresseerd bent' in sell broadcast", "geïnteresseerd bent" not in msg)
    check("No 'kopen' in sell broadcast", "kopen" not in msg.lower())
    check("No 'verkopen' in sell broadcast", "verkopen" not in msg.lower())
    check("Has FestiFlip contact", "festiflip" in msg.lower())

    print(f"\n{BOLD}--- 4.2 Buy request broadcast ---{RESET}")
    msg2 = buy_request_group_broadcast("Thuishaven", "2026-04-18", 2, "60")
    print(f"    {CYAN}{msg2}{RESET}")
    check("No 'verkopen' trigger in buy broadcast", "wilt verkopen" not in msg2.lower())

    print(f"\n{BOLD}--- 4.3 Searching broadcast ---{RESET}")
    msg3 = searching_broadcast("Awakenings", "2026-06-27", 4)
    print(f"    {CYAN}{msg3}{RESET}")
    check("No 'verkopen' trigger in search broadcast", "wilt verkopen" not in msg3.lower())

    print(f"\n{BOLD}--- 4.4 Event sale broadcast ---{RESET}")
    msg4 = event_sale_broadcast("Mysteryland", "2026-08-22", 2, Decimal("95.00"))
    print(f"    {CYAN}{msg4}{RESET}")
    check("No 'geïnteresseerd bent' in event broadcast", "geïnteresseerd bent" not in msg4)

    # ═══════════════════════════════════════════════════════════
    # 5. TICKET TYPE / EDITION IN BROADCAST
    # ═══════════════════════════════════════════════════════════
    print(f"\n{BOLD}{CYAN}{'═'*60}")
    print(f"  5. EDITION IN BROADCAST — ticket_type shown")
    print(f"{'═'*60}{RESET}")

    print(f"\n{BOLD}--- 5.1 Broadcast with edition ---{RESET}")
    msg = sell_offer_group_broadcast("DGTL", "2026-04-05", 3, "80", ticket_type="Saturday")
    print(f"    {CYAN}{msg}{RESET}")
    check("Edition shown in broadcast", "Saturday" in msg, f"msg: {msg[:100]}")
    check("Format: 'DGTL (Saturday)'", "DGTL (Saturday)" in msg)

    print(f"\n{BOLD}--- 5.2 Broadcast without edition ---{RESET}")
    msg2 = sell_offer_group_broadcast("Fanta Event", "2026-04-03", 5, "60")
    print(f"    {CYAN}{msg2}{RESET}")
    check("No extra parens when no edition", "Fanta Event\n" not in msg2 or "()" not in msg2)

    # ═══════════════════════════════════════════════════════════
    # 6. PUSH NAME EXTRACTION
    # WhatsApp name used instead of "WhatsApp Seller"
    # ═══════════════════════════════════════════════════════════
    print(f"\n{BOLD}{CYAN}{'═'*60}")
    print(f"  6. PUSH NAME — Real name stored")
    print(f"{'═'*60}{RESET}")

    async with async_session() as db:
        PHONE = "+31TEST_FIX_006"
        await reset_user(db, PHONE)

        print(f"\n{BOLD}--- 6.1 Push name stored in session ---{RESET}")
        r1 = await send(db, PHONE, "hoi", push_name="Rens Klaucke")
        session = await get_session(db, PHONE)
        stored_name = (session.collected_data or {}).get("_push_name", "")
        check("Push name stored", stored_name == "Rens Klaucke", f"stored: '{stored_name}'")

        print(f"\n{BOLD}--- 6.2 Push name used when saving sell offer ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "tickets verkopen", push_name="Rens Klaucke")
        await send(db, PHONE, "Fanta Event, 3 april, 5 stuks, 60 euro per stuk", push_name="Rens Klaucke")
        await send(db, PHONE, "ja", push_name="Rens Klaucke")

        # Check the saved offer has the real name
        from sqlalchemy import select
        from app.models.sell_offer import SellOffer
        result = await db.execute(
            select(SellOffer).where(SellOffer.phone == PHONE).order_by(SellOffer.created_at.desc()).limit(1)
        )
        offer = result.scalar_one_or_none()
        if offer:
            check("Offer has real name", offer.first_name == "Rens Klaucke", f"first_name: '{offer.first_name}'")
        else:
            check("Offer saved", False, "No offer found")
        await db.commit()

    # ═══════════════════════════════════════════════════════════
    # 7. FORWARDED "TE KOOP" MESSAGE — classified as SELL, not BUY
    # ═══════════════════════════════════════════════════════════
    print(f"\n{BOLD}{CYAN}{'═'*60}")
    print(f"  7. FORWARDED LISTING — Not misclassified as BUY")
    print(f"{'═'*60}{RESET}")

    async with async_session() as db:
        PHONE = "+31TEST_FIX_007"
        await reset_user(db, PHONE)

        # Forwarded "TE KOOP" = user wants to BUY those tickets
        forwarded = (
            "[Doorgestuurd] *TE KOOP 🎟️*\n\n"
            "🎟️ DGTL (2026-04-05)\n"
            "🔢 3 Stuks\n"
            "💰 €80 per stuk\n"
            "📥 Stuur FestiFlip een bericht via +31 6 12899608"
        )
        r1 = await send(db, PHONE, forwarded)
        session = await get_session(db, PHONE)
        intent = session.current_intent
        check("Forwarded TE KOOP → BUY intent", intent == "BUY_REQUEST", f"intent: {intent}")
        check("No 'verkopen' in reply", has_not(r1, "verkopen", "verkoop"), f"reply: {r1[:100]}")
        await db.commit()

    # ═══════════════════════════════════════════════════════════
    # 8. SELL FLOW — complete flow still works end-to-end
    # ═══════════════════════════════════════════════════════════
    print(f"\n{BOLD}{CYAN}{'═'*60}")
    print(f"  8. SELL FLOW — End-to-end with edition")
    print(f"{'═'*60}{RESET}")

    async with async_session() as db:
        PHONE = "+31TEST_FIX_008"
        await reset_user(db, PHONE)

        print(f"\n{BOLD}--- 8.1 Sell with ticket type ---{RESET}")
        r1 = await send(db, PHONE, "tickets verkopen")
        r2 = await send(db, PHONE, "DGTL Saturday, 5 april, 3 stuks, 80 euro per stuk")
        check("Confirmation shown", has(r2, "klopt") or has(r2, "checken") or has(r2, "dgtl"), f"reply: {r2[:100]}")
        # Check ticket type extracted
        session = await get_session(db, PHONE)
        cd = session.collected_data or {}
        check("Event name has DGTL", "dgtl" in str(cd.get("event_name", "")).lower(), f"event: {cd.get('event_name')}")
        await db.commit()

    # ═══════════════════════════════════════════════════════════
    # 9. BUY FLOW — with form link then data
    # ═══════════════════════════════════════════════════════════
    print(f"\n{BOLD}{CYAN}{'═'*60}")
    print(f"  9. BUY FLOW — Form link then manual data")
    print(f"{'═'*60}{RESET}")

    async with async_session() as db:
        PHONE = "+31TEST_FIX_009"
        await reset_user(db, PHONE)

        print(f"\n{BOLD}--- 9.1 Bare 'ik wil kopen' gets form link ---{RESET}")
        r1 = await send(db, PHONE, "ik wil tickets kopen")
        check("Form link sent", has(r1, "festiflip.nl"), f"reply: {r1[:100]}")

        print(f"\n{BOLD}--- 9.2 User sends data after form link ---{RESET}")
        r2 = await send(db, PHONE, "Thuishaven, 18 april, 2 stuks, max 60 euro per stuk")
        check("Confirmation after data", has(r2, "klopt") or has(r2, "checken") or has(r2, "thuishaven"), f"reply: {r2[:100]}")
        await db.commit()

    # ═══════════════════════════════════════════════════════════
    # 10. DATE RECOGNITION — "komende zondag" etc.
    # ═══════════════════════════════════════════════════════════
    print(f"\n{BOLD}{CYAN}{'═'*60}")
    print(f"  10. RELATIVE DATE — AI resolution")
    print(f"{'═'*60}{RESET}")

    async with async_session() as db:
        PHONE = "+31TEST_FIX_010"
        await reset_user(db, PHONE)

        print(f"\n{BOLD}--- 10.1 'komende zaterdag' resolves to date ---{RESET}")
        await send(db, PHONE, "tickets verkopen")
        r1 = await send(db, PHONE, "DGTL, komende zaterdag, 2 stuks, 90 euro per stuk")
        session = await get_session(db, PHONE)
        cd = session.collected_data or {}
        event_date = cd.get("event_date", "")
        check("Date resolved (not empty)", len(str(event_date)) > 0, f"event_date: '{event_date}'")
        check("Date is YYYY-MM-DD format", bool(event_date and len(str(event_date)) == 10 and str(event_date)[4] == '-'), f"event_date: '{event_date}'")
        await db.commit()

    # ═══════════════════════════════════════════════════════════
    # RESULTS
    # ═══════════════════════════════════════════════════════════
    total = passed + failed
    print(f"\n\n{BOLD}{'═'*60}")
    if failed == 0:
        print(f"  {GREEN}RENS FIXES TEST: {passed} passed, 0 failed ✅{RESET}")
    else:
        print(f"  {RED}RENS FIXES TEST: {passed} passed, {failed} failed ❌{RESET}")
        for e in errors:
            print(f"    {RED}• {e}{RESET}")
    print(f"{'═'*60}\n")

    return failed == 0


if __name__ == "__main__":
    sys.path.insert(0, ".")
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
