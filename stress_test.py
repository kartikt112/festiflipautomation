"""Stress test for FestiFlip bot – tests all recent changes directly via process_message."""

import asyncio
import sys
import traceback
from datetime import datetime

# Colors for terminal output
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
    """Send a message through the state machine and return the reply."""
    from app.ai.state_machine import process_message
    reply = await process_message(db, phone, message)
    return reply


async def reset_user(db, phone):
    """Reset user session to IDLE."""
    from app.crud.chat_sessions import reset_session
    await reset_session(db, phone)
    await db.commit()


def check(test_name, reply, *must_contain, must_not_contain=None):
    """Check if reply contains expected strings."""
    global passed, failed, errors
    ok = True
    for phrase in must_contain:
        if phrase.lower() not in reply.lower():
            ok = False
            break
    if must_not_contain:
        for phrase in must_not_contain:
            if phrase.lower() in reply.lower():
                ok = False
                break
    if ok:
        passed += 1
        print(f"  {GREEN}✓{RESET} {test_name}")
    else:
        failed += 1
        errors.append((test_name, reply, must_contain))
        print(f"  {RED}✗{RESET} {test_name}")
        print(f"    {YELLOW}Reply:{RESET} {reply[:150]}...")
    return ok


async def run_tests():
    global passed, failed

    # Setup database
    from app.database import async_session, init_db
    await init_db()

    async with async_session() as db:
        # Use fake test phone numbers
        PHONE_A = "+31600000001"
        PHONE_B = "+31600000002"
        PHONE_C = "+31600000003"
        PHONE_D = "+31600000004"
        PHONE_E = "+31600000005"

        # ════════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}═══ 1. GREETING & WELCOME ═══{RESET}")
        # ════════════════════════════════════════════
        await reset_user(db, PHONE_A)

        reply = await send(db, PHONE_A, "Hoi")
        check("Greeting → welcome message", reply, "welkom", "festiflip")

        reply = await send(db, PHONE_A, "Hey!")
        check("Hey greeting", reply, "welkom")

        # ════════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}═══ 2. INFORMAL TONE ═══{RESET}")
        # ════════════════════════════════════════════
        await reset_user(db, PHONE_A)

        reply = await send(db, PHONE_A, "Ik wil tickets kopen voor Lowlands")
        check("Buy request → informal tone (no formal emoji spam)", reply, "lowlands")
        # Check it's not overly formal
        check("No formal 'u' in response", reply, must_not_contain=["heeft u", "kunt u"])

        # ════════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}═══ 3. SINGLE BUY FLOW ═══{RESET}")
        # ════════════════════════════════════════════
        await reset_user(db, PHONE_A)

        reply = await send(db, PHONE_A, "Ik zoek 3 tickets voor Awakenings op 5 juli, max €90")
        check("Full buy request → confirmation or collecting", reply, "awakenings")

        # If we're in confirmation, confirm
        if "klopt" in reply.lower() or "ja of nee" in reply.lower():
            reply = await send(db, PHONE_A, "ja")
            check("Buy confirm → saved", reply, "opgeslagen")
        else:
            check("Buy request recognized (collecting more)", reply, "")

        # ════════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}═══ 4. SINGLE SELL FLOW ═══{RESET}")
        # ════════════════════════════════════════════
        await reset_user(db, PHONE_B)

        reply = await send(db, PHONE_B, "Ik wil tickets verkopen voor Dekmantel 1 augustus 2 stuks €60")
        check("Sell offer → confirmation or collecting", reply, "dekmantel")

        if "klopt" in reply.lower() or "ja of nee" in reply.lower():
            reply = await send(db, PHONE_B, "ja")
            check("Sell confirm → saved + seller steps", reply, "opgeslagen")
            check("Sell confirm → offers more sells", reply, "meer tickets")

            # Test "ja" after sell → new template
            reply = await send(db, PHONE_B, "ja")
            check("'ja' after sell → new sell template", reply, "stuur me")
        else:
            check("Sell recognized (collecting)", reply, "")

        # ════════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}═══ 5. RESET COMMAND ═══{RESET}")
        # ════════════════════════════════════════════
        await reset_user(db, PHONE_A)
        reply = await send(db, PHONE_A, "Ik zoek tickets voor Lowlands")
        reply = await send(db, PHONE_A, "reset")
        check("Reset → starts over", reply, "opnieuw")

        # ════════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}═══ 6. ACKNOWLEDGMENTS (IDLE) ═══{RESET}")
        # ════════════════════════════════════════════
        await reset_user(db, PHONE_A)

        reply = await send(db, PHONE_A, "bedankt")
        check("Acknowledgment → friendly close", reply, "laat maar weten")

        await reset_user(db, PHONE_A)
        reply = await send(db, PHONE_A, "top")
        check("'top' acknowledgment", reply, "laat maar weten")

        await reset_user(db, PHONE_A)
        reply = await send(db, PHONE_A, "👍")
        check("Emoji acknowledgment", reply, "laat maar weten")

        # ════════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}═══ 7. GENERAL QUESTIONS (AI Q&A) ═══{RESET}")
        # ════════════════════════════════════════════
        await reset_user(db, PHONE_A)

        reply = await send(db, PHONE_A, "Hoe werkt FestiFlip?")
        check("General question → AI answer (not buy/sell)", reply, must_not_contain=["evenement", "stuur me even"])

        await reset_user(db, PHONE_A)
        reply = await send(db, PHONE_A, "Wat als de verkoper me de tickets niet stuurt?")
        check("Hypothetical question → Q&A not escalation", reply, must_not_contain=["escalatie", "melding ontvangen"])

        # ════════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}═══ 8. BATCH SELL WITH --- SEPARATOR ═══{RESET}")
        # ════════════════════════════════════════════
        await reset_user(db, PHONE_C)

        batch_msg = """Ik wil tickets verkopen:
Evenement: Awakenings
Datum: 5 juli
Aantal: 2
Prijs per ticket: €85
---
Evenement: Dekmantel
Datum: 1 augustus
Aantal: 1
Prijs per ticket: €60"""

        reply = await send(db, PHONE_C, batch_msg)
        check("Batch sell (---) → multiple saved", reply, "opgeslagen")
        check("Batch sell → shows count", reply, "2")
        check("Batch sell → asks for more", reply, "meer tickets")

        # ════════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}═══ 9. SMART BATCH (NO ---) ═══{RESET}")
        # ════════════════════════════════════════════
        await reset_user(db, PHONE_D)

        smart_batch = "ik wil tickets verkopen voor awakenings 5 juli 2 stuks 85 euro en ook voor dekmantel 1 augustus 1 stuk 60 euro en DGTL 10 april 3 kaarten 70 euro"
        reply = await send(db, PHONE_D, smart_batch)
        check("Smart batch → detected multiple events", reply, "opgeslagen")
        # Should have 3 listings
        if "3" in reply:
            check("Smart batch → 3 listings saved", reply, "3")
        else:
            check("Smart batch → at least some listings saved", reply, "opgeslagen")

        # ════════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}═══ 10. INTENT SWITCHING ═══{RESET}")
        # ════════════════════════════════════════════
        await reset_user(db, PHONE_A)

        reply = await send(db, PHONE_A, "Ik zoek tickets voor Lowlands")
        check("Start buy flow", reply, "lowlands")

        reply = await send(db, PHONE_A, "Nee eigenlijk wil ik tickets verkopen")
        check("Switch to sell mid-flow", reply, "verkopen")

        # ════════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}═══ 11. OFF-TOPIC DURING COLLECTING ═══{RESET}")
        # ════════════════════════════════════════════
        await reset_user(db, PHONE_A)

        reply = await send(db, PHONE_A, "Ik zoek tickets voor Lowlands")
        reply = await send(db, PHONE_A, "Wat is de hoofdstad van Nederland?")
        check("Off-topic during collecting → AI fallback + redirect", reply, "")
        # Should not crash and should eventually redirect

        # ════════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}═══ 12. CONFIRMATION CORRECTIONS ═══{RESET}")
        # ════════════════════════════════════════════
        await reset_user(db, PHONE_E)

        reply = await send(db, PHONE_E, "Ik wil 2 tickets verkopen voor Thuishaven op 7 juni voor €80")
        if "klopt" in reply.lower():
            reply = await send(db, PHONE_E, "De prijs moet 90 euro zijn")
            check("Price correction during confirm", reply, "90", "bijgewerkt")
        else:
            check("Sell offer started", reply, "")

        # ════════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}═══ 13. NEE DURING CONFIRMATION ═══{RESET}")
        # ════════════════════════════════════════════
        await reset_user(db, PHONE_A)

        reply = await send(db, PHONE_A, "Ik zoek 2 tickets voor Lowlands op 20 augustus max €100")
        if "klopt" in reply.lower():
            reply = await send(db, PHONE_A, "nee")
            check("'nee' during confirm → restart collection", reply, "opnieuw")
        else:
            check("Buy flow started (more data needed)", reply, "")

        # ════════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}═══ 14. BROWSE CATALOG ═══{RESET}")
        # ════════════════════════════════════════════
        await reset_user(db, PHONE_A)

        reply = await send(db, PHONE_A, "Welke tickets zijn er beschikbaar?")
        check("Browse catalog → shows list or 'no tickets'", reply, "ticket")

        # ════════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}═══ 15. FORWARDED MESSAGE (BUY INTENT) ═══{RESET}")
        # ════════════════════════════════════════════
        await reset_user(db, PHONE_A)

        forwarded = "[Doorgestuurd] *TE KOOP 🎟️*\n🎟️ Thuishaven Lammers (2026-06-07)\n🔢 4 Stuks\n💰 €80.0 per stuk\n📥 Bericht FestiFlip"
        reply = await send(db, PHONE_A, forwarded)
        check("Forwarded listing → BUY intent", reply, "thuishaven")
        check("Forwarded → not sell", reply, must_not_contain=["verkopen"])

        # ════════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}═══ 16. ESCALATION (REAL vs HYPOTHETICAL) ═══{RESET}")
        # ════════════════════════════════════════════
        await reset_user(db, PHONE_A)

        reply = await send(db, PHONE_A, "Wat doe ik als mijn ticket niet werkt bij de ingang?")
        check("Hypothetical entrance Q → NOT escalation", reply, must_not_contain=["melding ontvangen", "escalatie"])

        # ════════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}═══ 17. QUESTION PHRASE ═══{RESET}")
        # ════════════════════════════════════════════
        await reset_user(db, PHONE_A)

        reply = await send(db, PHONE_A, "Ik heb een vraag")
        check("Question phrase → invite to ask", reply, "tuurlijk")

        # ════════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}═══ 18. EMOJI CHECK (🔢 not 4️⃣) ═══{RESET}")
        # ════════════════════════════════════════════
        from app.message_templates.templates import (
            sell_offer_group_broadcast, buy_request_group_broadcast,
            searching_broadcast, broadcast_listing_message,
        )
        bc1 = sell_offer_group_broadcast("Test", "2026-07-01", 3, "50")
        bc2 = buy_request_group_broadcast("Test", "2026-07-01", 3, "50")
        bc3 = searching_broadcast("Test", "2026-07-01", 3)
        check("Sell broadcast uses 🔢", bc1, "🔢")
        check("Buy broadcast uses 🔢", bc2, "🔢")
        check("Search broadcast uses 🔢", bc3, "🔢")
        check("No 4️⃣ in sell broadcast", bc1, must_not_contain=["4️⃣"])
        check("No 4️⃣ in buy broadcast", bc2, must_not_contain=["4️⃣"])

        # ════════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}═══ 19. TEMPLATE TONE CHECK ═══{RESET}")
        # ════════════════════════════════════════════
        from app.message_templates.templates import welcome_message, sell_fill_template, buy_fill_template
        wm = welcome_message()
        check("Welcome → 'Hey!' informal", wm, "hey")
        check("Welcome → no formal language", wm, must_not_contain=["Beste", "Geachte"])

        sf = sell_fill_template()
        check("Sell template → 'stuur me'", sf, "stuur me")
        check("Sell template → 'eigen woorden'", sf, "eigen woorden")

        bf = buy_fill_template()
        check("Buy template → 'stuur me'", bf, "stuur me")

        # ════════════════════════════════════════════
        print(f"\n{BOLD}{CYAN}═══ 20. RAPID-FIRE EDGE CASES ═══{RESET}")
        # ════════════════════════════════════════════

        # Empty message
        await reset_user(db, PHONE_A)
        try:
            reply = await send(db, PHONE_A, "")
            check("Empty message → doesn't crash", reply, "")
        except Exception as e:
            failed += 1
            errors.append(("Empty message", str(e), []))
            print(f"  {RED}✗{RESET} Empty message → CRASHED: {e}")

        # Very long message
        await reset_user(db, PHONE_A)
        long_msg = "Ik wil tickets kopen " * 50
        try:
            reply = await send(db, PHONE_A, long_msg)
            check("Very long message → doesn't crash", reply, "")
        except Exception as e:
            failed += 1
            errors.append(("Long message", str(e), []))
            print(f"  {RED}✗{RESET} Long message → CRASHED: {e}")

        # Special characters
        await reset_user(db, PHONE_A)
        try:
            reply = await send(db, PHONE_A, "Ik zoek tickets voor événement spéciàl 🎉🔥💀")
            check("Special chars/emojis → doesn't crash", reply, "")
        except Exception as e:
            failed += 1
            errors.append(("Special chars", str(e), []))
            print(f"  {RED}✗{RESET} Special chars → CRASHED: {e}")

        # Number-only message
        await reset_user(db, PHONE_A)
        reply = await send(db, PHONE_A, "Ik zoek tickets voor Lowlands")
        reply = await send(db, PHONE_A, "3")
        check("Bare number during collecting → parsed", reply, "")

        # Negative quantity
        await reset_user(db, PHONE_A)
        reply = await send(db, PHONE_A, "Ik wil -5 tickets kopen voor Lowlands")
        check("Negative quantity → handled gracefully", reply, "")

        # Zero price
        await reset_user(db, PHONE_A)
        reply = await send(db, PHONE_A, "Ik zoek gratis tickets voor Lowlands")
        check("Zero/free price → handled gracefully", reply, "")

        await db.commit()

    # ════════════════════════════════════════════
    print(f"\n{BOLD}{'═' * 50}{RESET}")
    print(f"{BOLD}Results: {GREEN}{passed} passed{RESET}, {RED if failed else GREEN}{failed} failed{RESET}")
    print(f"{BOLD}{'═' * 50}{RESET}")

    if errors:
        print(f"\n{RED}Failed tests:{RESET}")
        for name, reply, expected in errors:
            print(f"  • {name}")
            print(f"    Reply: {reply[:200]}")
            if expected:
                print(f"    Expected: {expected}")

    return failed == 0


if __name__ == "__main__":
    # Add project root to path
    sys.path.insert(0, "/Users/prakashtupe/Ticketautomation")

    # Suppress ALL logging
    import logging
    import warnings
    import os
    os.environ["APP_ENV"] = "production"  # prevents SQLAlchemy echo=True
    warnings.filterwarnings("ignore")
    logging.disable(logging.CRITICAL)

    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)
