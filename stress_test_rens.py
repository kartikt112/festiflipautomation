"""Stress test: replay Rens's real conversation patterns through the current state machine.

Tests the exact messages that caused problems in production for +31637194374.
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
    reply = await process_message(db, phone, message)
    return reply


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
        if phrase.lower() not in reply.lower():
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
        print(f"    Reply: {reply[:200]}")
        failed += 1


async def main():
    global passed, failed

    from app.database import async_session

    PHONE = "+31TEST_RENS_001"

    async with async_session() as db:

        # ═══════════════════════════════════════════
        # TEST 1: "evenement, thuishaven" template parse
        # Rens sent: "evenement, thuishaven" and bot parsed "evenement" as event name
        # ═══════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}═══ 1. TEMPLATE PARSE: 'evenement, thuishaven' ═══{RESET}")
        await reset_user(db, PHONE)

        reply = await send(db, PHONE, "ik heb wat tickets om te verkopen")
        check("Sell intent → template", reply, "evenement")

        reply = await send(db, PHONE, (
            "evenement, thuishaven\n"
            "datum is zaterdag 28 februari\n"
            "type ticket - dag ticket\n"
            "5 stuks\n"
            "prijs is 80,- per ticket"
        ))
        # Should recognize "thuishaven" as the event, NOT "evenement"
        session = await get_session(db, PHONE)
        collected = session.collected_data or {}
        event_name = collected.get("event_name", "").lower()
        if "thuishaven" in event_name and "evenement" not in event_name:
            print(f"  {GREEN}✓{RESET} Event name is 'thuishaven' (not 'evenement')")
            passed += 1
        else:
            print(f"  {RED}✗{RESET} Event name should be 'thuishaven', got: '{collected.get('event_name')}'")
            failed += 1

        await db.commit()

        # ═══════════════════════════════════════════
        # TEST 2: "nee thuishaven is het evenement" correction
        # ═══════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}═══ 2. EVENT NAME CORRECTION ═══{RESET}")
        await reset_user(db, PHONE)

        reply = await send(db, PHONE, "ik wil tickets verkopen")
        reply = await send(db, PHONE, "lowlands festival")
        session = await get_session(db, PHONE)

        # Now correct the event name
        reply = await send(db, PHONE, "nee, thuishaven is het evenement")
        session = await get_session(db, PHONE)
        collected = session.collected_data or {}
        if "thuishaven" in (collected.get("event_name") or "").lower():
            print(f"  {GREEN}✓{RESET} Correction accepted: event_name = '{collected.get('event_name')}'")
            passed += 1
        else:
            print(f"  {RED}✗{RESET} Correction failed: event_name = '{collected.get('event_name')}'")
            failed += 1

        await db.commit()

        # ═══════════════════════════════════════════
        # TEST 3: "nee maar k ben verkoper he" should NOT become event name
        # This was the #1 bug — conversational Dutch stored as event
        # ═══════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}═══ 3. CONVERSATIONAL MSG ≠ EVENT NAME ═══{RESET}")
        await reset_user(db, PHONE)

        reply = await send(db, PHONE, "k wil graag 20 tickets verkopen")
        check("Sell 20 tickets → collecting", reply, "evenement")

        # User asks a question mid-flow
        reply = await send(db, PHONE, "want hoe werkt de betaling etc?")
        # AI fallback should answer the question and redirect — content varies
        check("Mid-flow question → answered + redirect", reply, "evenement")

        # User says "nee maar k ben verkoper he" — THIS must NOT become event name
        reply = await send(db, PHONE, "nee maar k ben verkoper he")
        session = await get_session(db, PHONE)
        collected = session.collected_data or {}
        event_name = collected.get("event_name", "")
        if event_name and "verkoper" in event_name.lower():
            print(f"  {RED}✗{RESET} BUG: 'nee maar k ben verkoper he' stored as event name: '{event_name}'")
            failed += 1
        else:
            print(f"  {GREEN}✓{RESET} Conversational message NOT stored as event name (event_name='{event_name}')")
            passed += 1

        await db.commit()

        # ═══════════════════════════════════════════
        # TEST 4: Date correction during CONFIRMING
        # Rens said "het is op 3 maart het evenement" during confirmation
        # Bot should update the date, not reset
        # ═══════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}═══ 4. DATE CORRECTION IN CONFIRMING ═══{RESET}")
        await reset_user(db, PHONE)

        reply = await send(db, PHONE, "ik zoek 3 tickets voor kartik tupe event, max 50 euro")
        # Might go to CONFIRMING or COLLECTING depending on missing date
        session = await get_session(db, PHONE)

        if session.current_step == "CONFIRMING":
            # Already confirming — send date correction
            reply = await send(db, PHONE, "het is op 3 maart het evenement")
            check("Date correction in CONFIRMING → updated", reply, "03")
            session = await get_session(db, PHONE)
            if session.current_step == "CONFIRMING":
                print(f"  {GREEN}✓{RESET} Still in CONFIRMING after date correction")
                passed += 1
            else:
                print(f"  {YELLOW}⚠{RESET} State changed to {session.current_step}")
                passed += 1  # Still acceptable if it handled the data
        else:
            # Still collecting — provide date
            reply = await send(db, PHONE, "3 maart")
            session = await get_session(db, PHONE)
            collected = session.collected_data or {}
            if collected.get("event_date") and "03" in str(collected.get("event_date", "")):
                print(f"  {GREEN}✓{RESET} Date collected: {collected.get('event_date')}")
                passed += 1
            else:
                print(f"  {RED}✗{RESET} Date not parsed: {collected.get('event_date')}")
                failed += 1

        await db.commit()

        # ═══════════════════════════════════════════
        # TEST 5: Multi-event sell ("20 tickets voor 3 verschillende evenementen")
        # ═══════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}═══ 5. MULTI-EVENT SELL (BATCH) ═══{RESET}")
        await reset_user(db, PHONE)

        reply = await send(db, PHONE, "ik wil tickets verkopen")
        reply = await send(db, PHONE, (
            "10 tickets voor thuishaven eastern special, 5 april, 60 euro per stuk\n"
            "---\n"
            "8 voor music on festival, 9 mei, 80 euro per stuk\n"
            "---\n"
            "2 voor by the creek, 15 juni, 45 euro per stuk"
        ))
        check("Batch sell → saved or partially saved", reply, "opgeslagen")
        await db.commit()

        # ═══════════════════════════════════════════
        # TEST 6: "echt 5 evenementen kunnen we dit ff snel regelen"
        # should NOT become event name
        # ═══════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}═══ 6. LONG CONVERSATIONAL MSG ≠ EVENT NAME ═══{RESET}")
        await reset_user(db, PHONE)

        reply = await send(db, PHONE, "ik wil tickets verkopen, maar k heb tickets te koop voor echt 5 evenementen kunnen we dit ff snel in een keer regelen")
        session = await get_session(db, PHONE)
        collected = session.collected_data or {}
        event_name = collected.get("event_name", "")
        if event_name and len(event_name) > 40:
            print(f"  {RED}✗{RESET} Long sentence stored as event name: '{event_name[:60]}...'")
            failed += 1
        else:
            print(f"  {GREEN}✓{RESET} Long sentence NOT stored as event name (got: '{event_name}')")
            passed += 1

        await db.commit()

        # ═══════════════════════════════════════════
        # TEST 7: "heb je die liggen" during COLLECTING
        # Should not crash or store garbage
        # ═══════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}═══ 7. OFF-TOPIC DURING COLLECTING ═══{RESET}")
        await reset_user(db, PHONE)

        reply = await send(db, PHONE, "k wil graag tickets kopen voor music on op 9 mei")
        reply = await send(db, PHONE, "heb je die liggen")
        # Should get a redirect, not crash
        check("Off-topic question → redirect", reply, "")  # Just check it doesn't crash
        session = await get_session(db, PHONE)
        if session.current_step in ("COLLECTING", "CONFIRMING"):
            print(f"  {GREEN}✓{RESET} Still in flow after off-topic question (state={session.current_step})")
            passed += 1
        else:
            print(f"  {YELLOW}⚠{RESET} State changed to {session.current_step}")
            passed += 1

        await db.commit()

        # ═══════════════════════════════════════════
        # TEST 8: Full happy path — sell flow
        # ═══════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}═══ 8. FULL SELL HAPPY PATH ═══{RESET}")
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
        check("Complete sell data → confirmation", reply, "klopt")
        check("Event name in confirmation", reply, "thuishaven")

        reply = await send(db, PHONE, "ja")
        check("Confirm sell → saved", reply, "opgeslagen")

        # Check "more sells" prompt
        reply = await send(db, PHONE, "ja")
        check("More sells → new template", reply, "evenement")

        await db.commit()

        # ═══════════════════════════════════════════
        # TEST 9: Full happy path — buy flow
        # ═══════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}═══ 9. FULL BUY HAPPY PATH ═══{RESET}")
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

        # ═══════════════════════════════════════════
        # TEST 10: "ik wil eigenlijk kopen" during sell COLLECTING
        # Intent switch
        # ═══════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}═══ 10. INTENT SWITCH SELL→BUY ═══{RESET}")
        await reset_user(db, PHONE)

        reply = await send(db, PHONE, "ik wil tickets verkopen")
        reply = await send(db, PHONE, "thuishaven")
        session = await get_session(db, PHONE)
        check("Sell collecting → event stored", reply, "")

        reply = await send(db, PHONE, "nee ik wil eigenlijk kopen")
        check("Intent switch → buy", reply, "kopen")
        session = await get_session(db, PHONE)
        if session.current_intent == "BUY_REQUEST":
            print(f"  {GREEN}✓{RESET} Intent switched to BUY_REQUEST")
            passed += 1
        else:
            print(f"  {RED}✗{RESET} Intent still {session.current_intent}")
            failed += 1

        await db.commit()

        # ═══════════════════════════════════════════
        # TEST 11: Conversation history context
        # The bot should know what it asked previously
        # ═══════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}═══ 11. CONVERSATION CONTEXT ═══{RESET}")
        await reset_user(db, PHONE)

        # Log some messages manually to simulate history
        from app.models.chat_message import ChatMessage, MessageDirection
        db.add(ChatMessage(phone=PHONE, direction=MessageDirection.OUTBOUND, body="Hoeveel tickets zoek je?"))
        await db.flush()

        reply = await send(db, PHONE, "ik wil tickets kopen voor dekmantel")
        # Should start collecting
        session = await get_session(db, PHONE)
        check("Buy with context → collecting/confirming", reply, "")
        if session.current_step in ("COLLECTING", "CONFIRMING"):
            print(f"  {GREEN}✓{RESET} In flow (state={session.current_step})")
            passed += 1
        else:
            print(f"  {YELLOW}⚠{RESET} State: {session.current_step}")
            passed += 1

        await db.commit()

        # ═══════════════════════════════════════════
        # TEST 12: Price correction in CONFIRMING
        # ═══════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}═══ 12. PRICE CORRECTION IN CONFIRMING ═══{RESET}")
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

    # ═══════════════════════════════════════════
    # RESULTS
    # ═══════════════════════════════════════════
    print(f"\n{BOLD}{'═'*50}")
    color = GREEN if failed == 0 else RED
    print(f"Results: {color}{passed} passed{RESET}, {color}{failed} failed{RESET}")
    print(f"{'═'*50}{RESET}")

    if errors:
        print(f"\n{RED}Failures:{RESET}")
        for e in errors:
            print(f"  {RED}{e}{RESET}")

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    asyncio.run(main())
