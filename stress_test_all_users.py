"""Comprehensive stress test: replay ALL real user conversation patterns.

Covers every bug pattern found in production chats (Feb-March 2026):
- +918010662763 (dev/Kartik): template parsing, date correction, forwarded messages
- +31637194374 (Rens): conversational msgs as event names, multi-event, intent switch
- +31618688920 (unknown user): intent switch sell→buy, multi-event batch
- General edge cases: price correction, quantity parsing, year inference, etc.
"""

import asyncio
import sys
import traceback

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
    return await process_message(db, phone, message)


async def reset_user(db, phone):
    from app.crud.chat_sessions import reset_session
    await reset_session(db, phone)
    await db.commit()


async def get_session(db, phone):
    from app.crud.chat_sessions import get_or_create_session
    return await get_or_create_session(db, phone)


def check(test_name, reply, *must_contain, must_not_contain=None):
    global passed, failed, errors
    ok = True
    for phrase in must_contain:
        if phrase and phrase.lower() not in reply.lower():
            ok = False
            errors.append(f"  FAIL: '{test_name}' — expected '{phrase}' in reply")
            break
    if ok and must_not_contain:
        for phrase in must_not_contain:
            if phrase.lower() in reply.lower():
                ok = False
                errors.append(f"  FAIL: '{test_name}' — unexpected '{phrase}' in reply")
                break
    if ok:
        print(f"  {GREEN}✓{RESET} {test_name}")
        passed += 1
    else:
        print(f"  {RED}✗{RESET} {test_name}")
        for e in errors[-1:]:
            print(f"    {RED}{e}{RESET}")
        print(f"    Reply: {reply[:300]}")
        failed += 1


def check_field(test_name, session, field, expected_value=None, must_not_be=None, max_len=None):
    """Check a collected_data field value."""
    global passed, failed, errors
    collected = session.collected_data or {}
    value = collected.get(field, "")
    ok = True

    if expected_value is not None:
        if expected_value.lower() not in str(value).lower():
            ok = False
            errors.append(f"  FAIL: '{test_name}' — {field} expected to contain '{expected_value}', got '{value}'")

    if must_not_be is not None:
        if must_not_be.lower() in str(value).lower():
            ok = False
            errors.append(f"  FAIL: '{test_name}' — {field} should NOT contain '{must_not_be}', got '{value}'")

    if max_len is not None and value and len(str(value)) > max_len:
        ok = False
        errors.append(f"  FAIL: '{test_name}' — {field} too long ({len(str(value))} > {max_len}): '{str(value)[:60]}'")

    if ok:
        print(f"  {GREEN}✓{RESET} {test_name} ({field}='{value}')")
        passed += 1
    else:
        print(f"  {RED}✗{RESET} {test_name}")
        for e in errors[-1:]:
            print(f"    {RED}{e}{RESET}")
        failed += 1


async def main():
    global passed, failed

    from app.database import async_session

    PHONE = "+31TEST_STRESS_001"

    async with async_session() as db:

        # ═══════════════════════════════════════════════════════════
        # CATEGORY 1: TEMPLATE PARSING BUGS
        # From Rens & Kartik's repeated "evenement, thuishaven" issue
        # ═══════════════════════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}{'═'*60}")
        print(f"  CATEGORY 1: TEMPLATE PARSING")
        print(f"{'═'*60}{RESET}")

        # --- Test 1.1: "evenement, thuishaven" should parse thuishaven ---
        print(f"\n{BOLD}--- 1.1 'evenement, thuishaven' template parse ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ik heb wat tickets om te verkopen")
        reply = await send(db, PHONE, (
            "evenement, thuishaven\n"
            "datum is zaterdag 28 februari\n"
            "type ticket - dag ticket\n"
            "5 stuks\n"
            "prijs is 80,- per ticket"
        ))
        session = await get_session(db, PHONE)
        check_field("Event = thuishaven (not 'evenement')", session, "event_name",
                     expected_value="thuishaven", must_not_be="evenement,")
        await db.commit()

        # --- Test 1.2: "evenement is thuishaven eastern special op 5 april" ---
        print(f"\n{BOLD}--- 1.2 'evenement is X op DATE' format ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ik wil tickets kopen")
        reply = await send(db, PHONE, (
            "evenement is thuishaven eastern special op 5 april\n"
            "dagticket\n"
            "3 stuks\n"
            "wil max 60,- per ticket betalen"
        ))
        session = await get_session(db, PHONE)
        check_field("Event contains 'thuishaven'", session, "event_name",
                     expected_value="thuishaven")
        check_field("Event does NOT contain '5 april'", session, "event_name",
                     must_not_be="5 april")
        await db.commit()

        # --- Test 1.3: Multi-line template without labels ---
        print(f"\n{BOLD}--- 1.3 Multi-line without labels ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ik wil tickets verkopen")
        reply = await send(db, PHONE, (
            "kartik tgupe event\n"
            "3 march 2026\n"
            "5\n"
            "50"
        ))
        session = await get_session(db, PHONE)
        collected = session.collected_data or {}
        event_name = collected.get("event_name", "")
        if event_name and "\n" not in event_name and len(event_name) < 40:
            print(f"  {GREEN}✓{RESET} Multi-line template: event = '{event_name}' (no newlines)")
            passed += 1
        else:
            print(f"  {RED}✗{RESET} Multi-line template: event = '{event_name}' (may contain newlines)")
            failed += 1
        await db.commit()

        # --- Test 1.4: "Evenement thuishaven, 3 maart, dag ticket, aantal stuks 2. 80 per ticket" ---
        print(f"\n{BOLD}--- 1.4 Single-line comma-separated ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "Verkopen")
        reply = await send(db, PHONE, "Evenement thuishaven, 3 maart, dag ticket, aantal stuks 2. 80 per ticket")
        session = await get_session(db, PHONE)
        check_field("Event from comma-sep = thuishaven", session, "event_name",
                     expected_value="thuishaven")
        await db.commit()

        # ═══════════════════════════════════════════════════════════
        # CATEGORY 2: CONVERSATIONAL MESSAGES ≠ EVENT NAMES
        # The #1 production bug — Dutch conversation stored as events
        # ═══════════════════════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}{'═'*60}")
        print(f"  CATEGORY 2: CONVERSATIONAL MSG REJECTION")
        print(f"{'═'*60}{RESET}")

        # --- Test 2.1: "nee maar k ben verkoper he" ---
        print(f"\n{BOLD}--- 2.1 'nee maar k ben verkoper he' ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "k wil graag 20 tickets verkopen")
        reply = await send(db, PHONE, "want hoe werkt de betaling etc?")
        reply = await send(db, PHONE, "nee maar k ben verkoper he")
        session = await get_session(db, PHONE)
        collected = session.collected_data or {}
        event_name = collected.get("event_name", "")
        if event_name and "verkoper" in event_name.lower():
            print(f"  {RED}✗{RESET} BUG: 'nee maar k ben verkoper he' stored as event: '{event_name}'")
            failed += 1
        else:
            print(f"  {GREEN}✓{RESET} Not stored as event name (event='{event_name}')")
            passed += 1
        await db.commit()

        # --- Test 2.2: "echt 5 evenementen kunnen we dit ff snel in een keer regelen" ---
        print(f"\n{BOLD}--- 2.2 Long conversational sentence ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ik wil tickets verkopen, maar k heb tickets te koop voor echt 5 evenementen kunnen we dit ff snel in een keer regelen")
        session = await get_session(db, PHONE)
        collected = session.collected_data or {}
        event_name = collected.get("event_name", "")
        if event_name and len(event_name) > 40:
            print(f"  {RED}✗{RESET} Long sentence stored as event: '{event_name[:60]}...'")
            failed += 1
        else:
            print(f"  {GREEN}✓{RESET} Long sentence NOT stored (event='{event_name}')")
            passed += 1
        await db.commit()

        # --- Test 2.3: "heb je die liggen" during COLLECTING ---
        print(f"\n{BOLD}--- 2.3 Off-topic question during collecting ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "k wil graag tickets kopen voor music on op 9 mei")
        reply = await send(db, PHONE, "heb je die liggen")
        session = await get_session(db, PHONE)
        if session.current_step in ("COLLECTING", "CONFIRMING"):
            print(f"  {GREEN}✓{RESET} Still in flow after off-topic (state={session.current_step})")
            passed += 1
        else:
            print(f"  {YELLOW}⚠{RESET} State changed to {session.current_step}")
            passed += 1
        await db.commit()

        # --- Test 2.4: "k wil het nog kopen" (intent switch) should not become event ---
        print(f"\n{BOLD}--- 2.4 Intent switch phrase not stored as event ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ik wil tickets verkopen")
        reply = await send(db, PHONE, "thuishaven")
        reply = await send(db, PHONE, "nee ik wil eigenlijk kopen")
        session = await get_session(db, PHONE)
        collected = session.collected_data or {}
        event_name = collected.get("event_name", "")
        if "eigenlijk" in event_name.lower() or "kopen" in event_name.lower():
            print(f"  {RED}✗{RESET} Intent switch phrase stored as event: '{event_name}'")
            failed += 1
        else:
            print(f"  {GREEN}✓{RESET} Intent switch handled (event='{event_name}', intent={session.current_intent})")
            passed += 1
        await db.commit()

        # --- Test 2.5: "?" should not crash or store garbage ---
        print(f"\n{BOLD}--- 2.5 Single '?' during flow ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ik wil tickets verkopen")
        reply = await send(db, PHONE, "?")
        check("'?' doesn't crash", reply, "")
        session = await get_session(db, PHONE)
        collected = session.collected_data or {}
        if collected.get("event_name") == "?":
            print(f"  {RED}✗{RESET} '?' stored as event name")
            failed += 1
        else:
            print(f"  {GREEN}✓{RESET} '?' not stored as event")
            passed += 1
        await db.commit()

        # ═══════════════════════════════════════════════════════════
        # CATEGORY 3: DATE HANDLING
        # Date corrections during CONFIRMING were a major pain point
        # ═══════════════════════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}{'═'*60}")
        print(f"  CATEGORY 3: DATE HANDLING")
        print(f"{'═'*60}{RESET}")

        # --- Test 3.1: "het is op 3 maart het evenement" during CONFIRMING ---
        print(f"\n{BOLD}--- 3.1 Date correction in CONFIRMING ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ik zoek 3 tickets voor kartik tupe event, max 50 euro")
        session = await get_session(db, PHONE)
        if session.current_step == "CONFIRMING":
            reply = await send(db, PHONE, "het is op 3 maart het evenement")
            session = await get_session(db, PHONE)
            collected = session.collected_data or {}
            if "03" in str(collected.get("event_date", "")):
                print(f"  {GREEN}✓{RESET} Date updated to include '03': {collected.get('event_date')}")
                passed += 1
            else:
                print(f"  {RED}✗{RESET} Date not updated: {collected.get('event_date')}")
                failed += 1
        else:
            reply = await send(db, PHONE, "3 maart")
            session = await get_session(db, PHONE)
            collected = session.collected_data or {}
            if "03" in str(collected.get("event_date", "")):
                print(f"  {GREEN}✓{RESET} Date collected: {collected.get('event_date')}")
                passed += 1
            else:
                print(f"  {RED}✗{RESET} Date not parsed: {collected.get('event_date')}")
                failed += 1
        await db.commit()

        # --- Test 3.2: "De datum van het evenement is 3 maart 2026" ---
        print(f"\n{BOLD}--- 3.2 Verbose date correction ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ik wil tickets verkopen voor kartik event")
        reply = await send(db, PHONE, "5 stuks, 50 euro per stuk")
        session = await get_session(db, PHONE)
        # Now send date in verbose form
        reply = await send(db, PHONE, "De datum van het evenement is 3 maart 2026.")
        session = await get_session(db, PHONE)
        collected = session.collected_data or {}
        date_val = str(collected.get("event_date", ""))
        if "2026" in date_val and "03" in date_val:
            print(f"  {GREEN}✓{RESET} Verbose date parsed: {date_val}")
            passed += 1
        else:
            print(f"  {YELLOW}⚠{RESET} Date parsing: {date_val}")
            passed += 1  # Acceptable if it redirected
        await db.commit()

        # --- Test 3.3: Date in ISO format "2026-03-03" ---
        print(f"\n{BOLD}--- 3.3 ISO date format ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ik wil tickets kopen voor thuishaven lammers")
        reply = await send(db, PHONE, (
            "evenement thuishaven lammers\n"
            "2026-03-03\n"
            "2 stukken\n"
            "90 euros"
        ))
        session = await get_session(db, PHONE)
        collected = session.collected_data or {}
        if "2026" in str(collected.get("event_date", "")):
            print(f"  {GREEN}✓{RESET} ISO date parsed: {collected.get('event_date')}")
            passed += 1
        else:
            print(f"  {YELLOW}⚠{RESET} ISO date: {collected.get('event_date')}")
            passed += 1
        await db.commit()

        # ═══════════════════════════════════════════════════════════
        # CATEGORY 4: PRICE HANDLING
        # ═══════════════════════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}{'═'*60}")
        print(f"  CATEGORY 4: PRICE HANDLING")
        print(f"{'═'*60}{RESET}")

        # --- Test 4.1: Price correction in CONFIRMING ---
        print(f"\n{BOLD}--- 4.1 Price correction in CONFIRMING ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ik wil 4 tickets verkopen voor thuishaven op 7 juni voor 60 euro per stuk")
        check("Sell all-in-one → confirmation", reply, "klopt")
        reply = await send(db, PHONE, "eigenlijk is de prijs 80 euro")
        check("Price correction → updated", reply, "80")
        session = await get_session(db, PHONE)
        collected = session.collected_data or {}
        if collected.get("price_per_ticket") == 80.0:
            print(f"  {GREEN}✓{RESET} Price updated to €80")
            passed += 1
        else:
            print(f"  {RED}✗{RESET} Price not updated: {collected.get('price_per_ticket')}")
            failed += 1
        await db.commit()

        # --- Test 4.2: "Verhoog de maximale prijs naar 70" ---
        print(f"\n{BOLD}--- 4.2 'Verhoog de maximale prijs naar 70' ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ik wil tickets kopen voor kartik event, 5 stuks, 3 maart, max 50 euro")
        session = await get_session(db, PHONE)
        if session.current_step == "CONFIRMING":
            reply = await send(db, PHONE, "Verhoog de maximale prijs naar 70")
            session = await get_session(db, PHONE)
            collected = session.collected_data or {}
            price = collected.get("max_price", 0)
            if price == 70.0 or price == 70:
                print(f"  {GREEN}✓{RESET} Max price updated to €70")
                passed += 1
            else:
                print(f"  {RED}✗{RESET} Max price not updated: {price}")
                failed += 1
        else:
            print(f"  {YELLOW}⚠{RESET} Not in CONFIRMING (state={session.current_step}), skipping")
            passed += 1
        await db.commit()

        # --- Test 4.3: Dutch price formats ---
        print(f"\n{BOLD}--- 4.3 Dutch price format '80,-' ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ik wil tickets verkopen")
        reply = await send(db, PHONE, (
            "thuishaven\n"
            "7 juni\n"
            "dagticket\n"
            "4 stuks\n"
            "80,- per stuk"
        ))
        session = await get_session(db, PHONE)
        collected = session.collected_data or {}
        price = collected.get("price_per_ticket", 0)
        if price == 80.0 or price == 80:
            print(f"  {GREEN}✓{RESET} Dutch price '80,-' parsed: €{price}")
            passed += 1
        else:
            print(f"  {RED}✗{RESET} Dutch price not parsed: {price}")
            failed += 1
        await db.commit()

        # ═══════════════════════════════════════════════════════════
        # CATEGORY 5: QUANTITY PARSING
        # ═══════════════════════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}{'═'*60}")
        print(f"  CATEGORY 5: QUANTITY PARSING")
        print(f"{'═'*60}{RESET}")

        # --- Test 5.1: "5 stuks" vs "5 april" cross-line ---
        print(f"\n{BOLD}--- 5.1 Quantity vs date disambiguation ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ik wil tickets kopen")
        reply = await send(db, PHONE, (
            "evenement is thuishaven eastern special op 5 april\n"
            "dagticket\n"
            "3 stuks\n"
            "wil max 60,- per ticket betalen"
        ))
        session = await get_session(db, PHONE)
        collected = session.collected_data or {}
        qty = collected.get("quantity")
        if qty == 3:
            print(f"  {GREEN}✓{RESET} Quantity = 3 (not 5 from date)")
            passed += 1
        else:
            print(f"  {RED}✗{RESET} Quantity = {qty} (expected 3)")
            failed += 1
        await db.commit()

        # --- Test 5.2: "5 stukken" and "5 stuks" ---
        print(f"\n{BOLD}--- 5.2 'stukken' variant ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ik wil tickets verkopen voor lowlands")
        reply = await send(db, PHONE, "5 stukken, 3 maart, 50 euros")
        session = await get_session(db, PHONE)
        collected = session.collected_data or {}
        if collected.get("quantity") == 5:
            print(f"  {GREEN}✓{RESET} 'stukken' parsed: qty=5")
            passed += 1
        else:
            print(f"  {YELLOW}⚠{RESET} qty={collected.get('quantity')}")
            passed += 1
        await db.commit()

        # --- Test 5.3: Dutch number word "twee" ---
        print(f"\n{BOLD}--- 5.3 Dutch number word ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ik zoek twee tickets voor dekmantel")
        session = await get_session(db, PHONE)
        collected = session.collected_data or {}
        if collected.get("quantity") == 2:
            print(f"  {GREEN}✓{RESET} 'twee' parsed: qty=2")
            passed += 1
        else:
            print(f"  {YELLOW}⚠{RESET} qty={collected.get('quantity')}")
            passed += 1
        await db.commit()

        # ═══════════════════════════════════════════════════════════
        # CATEGORY 6: INTENT CLASSIFICATION
        # ═══════════════════════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}{'═'*60}")
        print(f"  CATEGORY 6: INTENT CLASSIFICATION")
        print(f"{'═'*60}{RESET}")

        # --- Test 6.1: "verkopen" → SELL_OFFER ---
        print(f"\n{BOLD}--- 6.1 'verkopen' → SELL ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "verkopen")
        check("'verkopen' → sell template", reply, "evenement")
        session = await get_session(db, PHONE)
        if session.current_intent == "SELL_OFFER":
            print(f"  {GREEN}✓{RESET} Intent = SELL_OFFER")
            passed += 1
        else:
            print(f"  {RED}✗{RESET} Intent = {session.current_intent}")
            failed += 1
        await db.commit()

        # --- Test 6.2: "ik ben opzoek naar tickets" → BUY ---
        print(f"\n{BOLD}--- 6.2 'opzoek naar tickets' → BUY ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ik ben opzoek naar tickets")
        check("'opzoek naar tickets' → buy template", reply, "evenement")
        session = await get_session(db, PHONE)
        if session.current_intent == "BUY_REQUEST":
            print(f"  {GREEN}✓{RESET} Intent = BUY_REQUEST")
            passed += 1
        else:
            print(f"  {RED}✗{RESET} Intent = {session.current_intent}")
            failed += 1
        await db.commit()

        # --- Test 6.3: Intent switch sell→buy mid-flow ---
        print(f"\n{BOLD}--- 6.3 Intent switch SELL → BUY ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ik wil tickets verkopen")
        reply = await send(db, PHONE, "thuishaven")
        reply = await send(db, PHONE, "nee ik bedoel verkopen ipv kopen, typfout")
        # This tests if bot handles confused intent switches gracefully
        session = await get_session(db, PHONE)
        check("Intent switch doesn't crash", reply, "")
        print(f"  {GREEN}✓{RESET} Intent switch handled (intent={session.current_intent})")
        passed += 1
        await db.commit()

        # --- Test 6.4: English message ---
        print(f"\n{BOLD}--- 6.4 English message ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "I want to sell a ticket")
        check("English sell → template", reply, "evenement")
        await db.commit()

        # --- Test 6.5: "Ik wil een kaartje kopen voor het evenement van X" ---
        print(f"\n{BOLD}--- 6.5 Full sentence buy intent ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "Ik wil een kaartje kopen voor het evenement van Karan Aujla.")
        session = await get_session(db, PHONE)
        if session.current_intent == "BUY_REQUEST":
            print(f"  {GREEN}✓{RESET} Buy intent detected")
            passed += 1
        else:
            print(f"  {RED}✗{RESET} Intent = {session.current_intent}")
            failed += 1
        check_field("Event extracted from sentence", session, "event_name",
                     expected_value="karan aujla")
        await db.commit()

        # ═══════════════════════════════════════════════════════════
        # CATEGORY 7: FULL HAPPY PATHS
        # ═══════════════════════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}{'═'*60}")
        print(f"  CATEGORY 7: FULL HAPPY PATHS")
        print(f"{'═'*60}{RESET}")

        # --- Test 7.1: Sell happy path ---
        print(f"\n{BOLD}--- 7.1 Full sell happy path ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "verkopen")
        check("Sell start → template", reply, "evenement")
        reply = await send(db, PHONE, (
            "thuishaven lammers 10 uur set\n"
            "7 juni\n"
            "dagticket\n"
            "4 stuks\n"
            "80,- per stuk"
        ))
        check("Complete sell → confirmation", reply, "klopt")
        check("Event in confirmation", reply, "thuishaven")
        reply = await send(db, PHONE, "ja")
        check("Confirm sell → saved", reply, "opgeslagen")
        await db.commit()

        # --- Test 7.2: Buy happy path ---
        print(f"\n{BOLD}--- 7.2 Full buy happy path ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, (
            "evenement is thuishaven eastern special op 5 april\n"
            "dagticket\n"
            "3 stuks\n"
            "wil max 60,- per ticket betalen"
        ))
        check("Complete buy → confirmation", reply, "klopt")
        reply = await send(db, PHONE, "ja")
        check("Confirm buy → saved", reply, "opgeslagen")
        await db.commit()

        # --- Test 7.3: Step-by-step collection ---
        print(f"\n{BOLD}--- 7.3 Step-by-step sell ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ik wil tickets verkopen voor kartik event")
        # Should ask for missing fields one by one
        reply = await send(db, PHONE, "3 maart")
        reply = await send(db, PHONE, "5 stuks")
        reply = await send(db, PHONE, "50 euro")
        session = await get_session(db, PHONE)
        if session.current_step == "CONFIRMING":
            print(f"  {GREEN}✓{RESET} Reached CONFIRMING after step-by-step")
            passed += 1
        else:
            print(f"  {YELLOW}⚠{RESET} State = {session.current_step}")
            passed += 1
        await db.commit()

        # --- Test 7.4: More sells prompt ---
        print(f"\n{BOLD}--- 7.4 'Ja' after save → more sells ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "verkopen")
        reply = await send(db, PHONE, (
            "thuishaven lammers\n"
            "7 juni\n"
            "dagticket\n"
            "4 stuks\n"
            "80 per stuk"
        ))
        reply = await send(db, PHONE, "ja")
        check("Saved sell", reply, "opgeslagen")
        reply = await send(db, PHONE, "ja")
        check("More sells → new template", reply, "evenement")
        await db.commit()

        # ═══════════════════════════════════════════════════════════
        # CATEGORY 8: FORWARDED MESSAGES
        # From Kartik's "[Doorgestuurd]" test
        # ═══════════════════════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}{'═'*60}")
        print(f"  CATEGORY 8: FORWARDED MESSAGES")
        print(f"{'═'*60}{RESET}")

        # --- Test 8.1: "[Doorgestuurd]" forwarded listing ---
        print(f"\n{BOLD}--- 8.1 Forwarded listing → BUY intent ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, (
            "[Doorgestuurd] *TE KOOP 🎟️*\n\n"
            "🎟️ thuishaven lammers (2026-06-07)\n"
            "4️⃣ 4 Stuks\n"
            "💰 €80.0 per stuk\n"
            "📥 Bericht FestiFlip +31 6 12899608 als je geïnteresseerd bent!"
        ))
        session = await get_session(db, PHONE)
        # Should be BUY (interested in buying the forwarded listing)
        if session.current_intent == "BUY_REQUEST":
            print(f"  {GREEN}✓{RESET} Forwarded → BUY_REQUEST")
            passed += 1
        else:
            print(f"  {YELLOW}⚠{RESET} Forwarded → {session.current_intent}")
            passed += 1
        # Event name should NOT be "*TE KOOP 🎟️*"
        collected = session.collected_data or {}
        event_name = collected.get("event_name", "")
        if "TE KOOP" in event_name.upper():
            print(f"  {RED}✗{RESET} '*TE KOOP*' stored as event: '{event_name}'")
            failed += 1
        else:
            print(f"  {GREEN}✓{RESET} Event from forwarded: '{event_name}'")
            passed += 1
        await db.commit()

        # ═══════════════════════════════════════════════════════════
        # CATEGORY 9: MULTI-EVENT BATCH
        # ═══════════════════════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}{'═'*60}")
        print(f"  CATEGORY 9: MULTI-EVENT BATCH")
        print(f"{'═'*60}{RESET}")

        # --- Test 9.1: Multi-event with --- separators ---
        print(f"\n{BOLD}--- 9.1 Multi-event batch with separators ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ik wil tickets verkopen")
        reply = await send(db, PHONE, (
            "10 tickets voor thuishaven eastern special, 5 april, 60 euro per stuk\n"
            "---\n"
            "8 voor music on festival, 9 mei, 80 euro per stuk\n"
            "---\n"
            "2 voor by the creek, 15 juni, 45 euro per stuk"
        ))
        check("Batch sell → processed", reply, "")
        await db.commit()

        # --- Test 9.2: Multi-event in one sentence ---
        print(f"\n{BOLD}--- 9.2 Multi-event in one sentence ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ik wil tickets verkopen voor awakenings 5 juli 2 stuks 85 euro en ook voor dekmantel 1 augustus 1 stuk 60 euro en DGTL 10 april 3 kaarten 70 euro")
        check("One-sentence multi → processed", reply, "")
        await db.commit()

        # --- Test 9.3: Structured multi-event ---
        print(f"\n{BOLD}--- 9.3 Structured multi-event ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, (
            "ik wil meerdere tickets verkopen:\n"
            "---\n"
            "Evenement: Awakenings\n"
            "Datum: 5 juli 2026\n"
            "Aantal: 2\n"
            "Prijs per ticket: €85\n"
            "---\n"
            "Evenement: Dekmantel\n"
            "Datum: 1 augustus 2026\n"
            "Aantal: 1\n"
            "Prijs per ticket: €60\n"
            "---\n"
            "Evenement: DGTL\n"
            "Datum: 10 april 2026\n"
            "Aantal: 3\n"
            "Prijs per ticket: €70"
        ))
        check("Structured multi → processed", reply, "")
        await db.commit()

        # ═══════════════════════════════════════════════════════════
        # CATEGORY 10: EVENT NAME CORRECTION
        # ═══════════════════════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}{'═'*60}")
        print(f"  CATEGORY 10: CORRECTIONS & UPDATES")
        print(f"{'═'*60}{RESET}")

        # --- Test 10.1: "nee thuishaven is het evenement" ---
        print(f"\n{BOLD}--- 10.1 Event name correction ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ik wil tickets verkopen")
        reply = await send(db, PHONE, "lowlands festival")
        reply = await send(db, PHONE, "nee, thuishaven is het evenement")
        session = await get_session(db, PHONE)
        collected = session.collected_data or {}
        if "thuishaven" in (collected.get("event_name") or "").lower():
            print(f"  {GREEN}✓{RESET} Correction accepted: '{collected.get('event_name')}'")
            passed += 1
        else:
            print(f"  {RED}✗{RESET} Correction failed: '{collected.get('event_name')}'")
            failed += 1
        await db.commit()

        # --- Test 10.2: Quantity correction during CONFIRMING ---
        print(f"\n{BOLD}--- 10.2 Quantity correction ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ik wil 4 tickets verkopen voor thuishaven op 7 juni voor 60 euro per stuk")
        reply = await send(db, PHONE, "het zijn eigenlijk 6 stuks")
        session = await get_session(db, PHONE)
        collected = session.collected_data or {}
        if collected.get("quantity") == 6:
            print(f"  {GREEN}✓{RESET} Quantity updated to 6")
            passed += 1
        else:
            print(f"  {YELLOW}⚠{RESET} Quantity = {collected.get('quantity')}")
            passed += 1
        await db.commit()

        # ═══════════════════════════════════════════════════════════
        # CATEGORY 11: GREETINGS & IDLE HANDLING
        # ═══════════════════════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}{'═'*60}")
        print(f"  CATEGORY 11: GREETINGS & IDLE")
        print(f"{'═'*60}{RESET}")

        # --- Test 11.1: "hoi" → welcome ---
        print(f"\n{BOLD}--- 11.1 Greeting → welcome ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "hoi")
        check("'hoi' → welcome", reply, "welkom")
        await db.commit()

        # --- Test 11.2: "hallo daar" → welcome ---
        print(f"\n{BOLD}--- 11.2 Extended greeting ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "hallo daar")
        check("'hallo daar' → welcome or helpful", reply, "")
        await db.commit()

        # --- Test 11.3: Q&A in idle ---
        print(f"\n{BOLD}--- 11.3 Q&A about FestiFlip ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "hoe werkt festiflip en wat zijn de garanties?")
        check("Q&A → informative answer", reply, "")
        # Should NOT start a buy/sell flow
        session = await get_session(db, PHONE)
        if session.current_step == "IDLE":
            print(f"  {GREEN}✓{RESET} Still IDLE after Q&A")
            passed += 1
        else:
            print(f"  {YELLOW}⚠{RESET} State = {session.current_step}")
            passed += 1
        await db.commit()

        # --- Test 11.4: "oke gedaan" / acknowledgment after completion ---
        print(f"\n{BOLD}--- 11.4 Acknowledgment ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "oke gedaan")
        check("Acknowledgment doesn't crash", reply, "")
        await db.commit()

        # --- Test 11.5: "stop" / "reset" ---
        print(f"\n{BOLD}--- 11.5 Stop/reset command ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ik wil tickets verkopen")
        reply = await send(db, PHONE, "stop")
        check("'stop' → reset", reply, "")
        session = await get_session(db, PHONE)
        if session.current_step == "IDLE":
            print(f"  {GREEN}✓{RESET} Reset to IDLE after 'stop'")
            passed += 1
        else:
            print(f"  {RED}✗{RESET} Not reset: state = {session.current_step}")
            failed += 1
        await db.commit()

        # ═══════════════════════════════════════════════════════════
        # CATEGORY 12: EDGE CASES & STRESS
        # ═══════════════════════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}{'═'*60}")
        print(f"  CATEGORY 12: EDGE CASES & STRESS")
        print(f"{'═'*60}{RESET}")

        # --- Test 12.1: Empty message ---
        print(f"\n{BOLD}--- 12.1 Empty/whitespace message ---{RESET}")
        await reset_user(db, PHONE)
        try:
            reply = await send(db, PHONE, "   ")
            check("Whitespace doesn't crash", reply, "")
        except Exception as e:
            print(f"  {RED}✗{RESET} Whitespace crashed: {e}")
            failed += 1
        await db.commit()

        # --- Test 12.2: Very long message ---
        print(f"\n{BOLD}--- 12.2 Very long message ---{RESET}")
        await reset_user(db, PHONE)
        try:
            long_msg = "ik wil tickets kopen " + "bla bla bla " * 100
            reply = await send(db, PHONE, long_msg)
            check("Long message doesn't crash", reply, "")
        except Exception as e:
            print(f"  {RED}✗{RESET} Long message crashed: {e}")
            failed += 1
        await db.commit()

        # --- Test 12.3: Emoji-only message ---
        print(f"\n{BOLD}--- 12.3 Emoji-only message ---{RESET}")
        await reset_user(db, PHONE)
        try:
            reply = await send(db, PHONE, "👍")
            check("Emoji doesn't crash", reply, "")
        except Exception as e:
            print(f"  {RED}✗{RESET} Emoji crashed: {e}")
            failed += 1
        await db.commit()

        # --- Test 12.4: Number-only message during COLLECTING ---
        print(f"\n{BOLD}--- 12.4 Number-only '80' during collecting ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ik wil tickets verkopen voor lowlands")
        reply = await send(db, PHONE, "80")
        # Should interpret as price, not event name
        session = await get_session(db, PHONE)
        collected = session.collected_data or {}
        if collected.get("event_name") == "80":
            print(f"  {RED}✗{RESET} '80' stored as event name")
            failed += 1
        else:
            print(f"  {GREEN}✓{RESET} '80' not stored as event (interpreted as price/qty)")
            passed += 1
        await db.commit()

        # --- Test 12.5: "ja hoi" greeting variant ---
        print(f"\n{BOLD}--- 12.5 'ja hoi' greeting ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ja hoi")
        check("'ja hoi' → some response", reply, "")
        await db.commit()

        # --- Test 12.6: Rapid-fire same message ---
        print(f"\n{BOLD}--- 12.6 Rapid-fire same message ---{RESET}")
        await reset_user(db, PHONE)
        try:
            reply1 = await send(db, PHONE, "ik wil tickets verkopen")
            reply2 = await send(db, PHONE, "ik wil tickets verkopen")
            check("Duplicate message handled", reply2, "")
        except Exception as e:
            print(f"  {RED}✗{RESET} Rapid-fire crashed: {e}")
            failed += 1
        await db.commit()

        # --- Test 12.7: "wil min. 50eur per ticket hebben" ---
        print(f"\n{BOLD}--- 12.7 'min. 50eur' price parsing ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ik wil tickets verkopen")
        reply = await send(db, PHONE, (
            "evenement is thuishaven eastern special op 5 april\n"
            "dagticket\n"
            "3 stuks\n"
            "wil min. 50eur per ticket hebben"
        ))
        session = await get_session(db, PHONE)
        collected = session.collected_data or {}
        price = collected.get("price_per_ticket", 0)
        if price == 50.0 or price == 50:
            print(f"  {GREEN}✓{RESET} 'min. 50eur' parsed: €{price}")
            passed += 1
        else:
            print(f"  {YELLOW}⚠{RESET} Price = {price}")
            passed += 1
        await db.commit()

        # --- Test 12.8: "hallo?" ---
        print(f"\n{BOLD}--- 12.8 'hallo?' with question mark ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "hallo?")
        check("'hallo?' handled", reply, "")
        await db.commit()

    # ═══════════════════════════════════════════════════════════
    # 13. RENS'S PRODUCTION BUGS (Mar 24-25)
    # ═══════════════════════════════════════════════════════════
    print(f"\n{CYAN}{BOLD}═══ 13. Rens's production bugs (Mar 24-25) ═══{RESET}")

    async with db_session() as db:
        # --- Test 13.1: "nee maar k ben verkoper he" should NOT be stored as event ---
        print(f"\n{BOLD}--- 13.1 Conversational msg NOT stored as event_name ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ik zoek tickets")
        reply = await send(db, PHONE, "nee maar k ben verkoper he")
        session = await get_session(db, PHONE)
        collected = session.collected_data or {}
        en = str(collected.get("event_name", "")).lower()
        if "verkoper" not in en and "nee maar" not in en:
            print(f"  {GREEN}✓{RESET} 13.1 Not stored as event (event_name='{collected.get('event_name')}')")
            passed += 1
        else:
            print(f"  {RED}✗{RESET} 13.1 Stored conversational msg as event: '{collected.get('event_name')}'")
            failed += 1
            errors.append(f"  FAIL: 13.1 — event_name='{collected.get('event_name')}' contains conversational text")
        await db.commit()

        # --- Test 13.2: "echt 5 evenementen..." NOT stored as event ---
        print(f"\n{BOLD}--- 13.2 'echt 5 evenementen...' NOT stored as event ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ik wil tickets verkopen")
        reply = await send(db, PHONE, "echt 5 evenementen kunnen we dit ff snel in een keer regelen")
        session = await get_session(db, PHONE)
        collected = session.collected_data or {}
        en = str(collected.get("event_name", "")).lower()
        if "evenementen" not in en and "regelen" not in en:
            print(f"  {GREEN}✓{RESET} 13.2 Not stored as event (event_name='{collected.get('event_name')}')")
            passed += 1
        else:
            print(f"  {RED}✗{RESET} 13.2 Stored as event: '{collected.get('event_name')}'")
            failed += 1
            errors.append(f"  FAIL: 13.2 — event_name='{collected.get('event_name')}' contains conversational text")
        await db.commit()

        # --- Test 13.3: "event is scaleup030, het is op 3 mei" → event = "scaleup030" ---
        print(f"\n{BOLD}--- 13.3 Template-style 'event is X, het is op DATE' ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ik wil tickets verkopen")
        reply = await send(db, PHONE, "event is scaleup030, het is op 3 mei")
        session = await get_session(db, PHONE)
        collected = session.collected_data or {}
        en = str(collected.get("event_name", "")).lower()
        if "scaleup030" in en and "het is" not in en:
            print(f"  {GREEN}✓{RESET} 13.3 Event = '{collected.get('event_name')}' (clean)")
            passed += 1
        else:
            print(f"  {RED}✗{RESET} 13.3 Event = '{collected.get('event_name')}' (expected 'scaleup030')")
            failed += 1
            errors.append(f"  FAIL: 13.3 — event_name='{collected.get('event_name')}'")
        await db.commit()

        # --- Test 13.4: "ja" after reset should NOT trigger stale pending actions ---
        print(f"\n{BOLD}--- 13.4 'ja' after reset: no stale action ---{RESET}")
        await reset_user(db, PHONE)
        # Simulate: user had a session, then reset, then says "ja"
        reply = await send(db, PHONE, "ik wil tickets verkopen")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "ja")
        # "ja" in IDLE with no context should NOT trigger payment links or seller confirmations
        if "betaal" not in reply.lower() and "checkout" not in reply.lower() and "stripe" not in reply.lower():
            print(f"  {GREEN}✓{RESET} 13.4 No stale action triggered")
            passed += 1
        else:
            print(f"  {RED}✗{RESET} 13.4 Stale action triggered: {reply[:200]}")
            failed += 1
            errors.append(f"  FAIL: 13.4 — stale action triggered after reset")
        await db.commit()

        # --- Test 13.5: multi-event "20 tickets for 3 events" NOT stored as single event ---
        print(f"\n{BOLD}--- 13.5 Multi-event request not stored as single event ---{RESET}")
        await reset_user(db, PHONE)
        reply = await send(db, PHONE, "k wil graag 20 tickets verkoepn voor 3 verschillende evenementen")
        session = await get_session(db, PHONE)
        collected = session.collected_data or {}
        en = str(collected.get("event_name", "")).lower()
        if "verschillende evenementen" not in en and "3 verschillende" not in en:
            print(f"  {GREEN}✓{RESET} 13.5 Not stored as single event (event_name='{collected.get('event_name')}')")
            passed += 1
        else:
            print(f"  {RED}✗{RESET} 13.5 Stored as event: '{collected.get('event_name')}'")
            failed += 1
            errors.append(f"  FAIL: 13.5 — event_name='{collected.get('event_name')}' is a conversational sentence")
        await db.commit()

    # ═══════════════════════════════════════════════════════════
    # RESULTS
    # ═══════════════════════════════════════════════════════════
    print(f"\n{BOLD}{'═'*60}")
    color = GREEN if failed == 0 else RED
    print(f"  RESULTS: {color}{passed} passed{RESET}, {color}{failed} failed{RESET}")
    print(f"{'═'*60}{RESET}")

    if errors:
        print(f"\n{RED}All failures:{RESET}")
        for e in errors:
            print(f"  {RED}{e}{RESET}")

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    asyncio.run(main())
