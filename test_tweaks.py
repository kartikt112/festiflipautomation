"""Test script for the 5 production tweaks.

1. Sell broadcast: no TE KOOP, number emoji, cap at 4
2. Session timeout: 2h
3. Max price hidden from confirmation
4. Proof request after sell save
5. Form link on intent switch
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


async def send(db, phone, message):
    from app.ai.state_machine import process_message
    reply = await process_message(db, phone, message)
    print(f"    {YELLOW}→ {message[:80]}{RESET}")
    print(f"    {CYAN}← {reply[:140]}{RESET}")
    return reply


async def reset_user(db, phone):
    from app.crud.chat_sessions import reset_session
    await reset_session(db, phone)
    await db.commit()


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
    # 1. SELL BROADCAST TEMPLATE
    # ═══════════════════════════════════════════════════════════
    print(f"\n{BOLD}{CYAN}{'═'*60}")
    print(f"  1. SELL BROADCAST — No TE KOOP, number emoji, cap at 4")
    print(f"{'═'*60}{RESET}")

    from app.message_templates.templates import sell_offer_group_broadcast

    print(f"\n{BOLD}--- 1.1 Broadcast with 2 tickets ---{RESET}")
    msg = sell_offer_group_broadcast("Joy", "2026-04-27", 2, "30")
    print(f"    {CYAN}{msg}{RESET}")
    check("No 'TE KOOP' in broadcast", "TE KOOP" not in msg)
    check("Has 2️⃣ emoji", "2️⃣" in msg)
    check("Shows '2 Stuks'", "2 Stuks" in msg)

    print(f"\n{BOLD}--- 1.2 Broadcast with 4 tickets ---{RESET}")
    msg2 = sell_offer_group_broadcast("DGTL", "2026-04-05", 4, "80")
    print(f"    {CYAN}{msg2}{RESET}")
    check("Has 4️⃣ emoji", "4️⃣" in msg2)

    print(f"\n{BOLD}--- 1.3 Broadcast with 1 ticket ---{RESET}")
    msg3 = sell_offer_group_broadcast("Awakenings", "2026-06-27", 1, "95")
    print(f"    {CYAN}{msg3}{RESET}")
    check("Has 1️⃣ emoji", "1️⃣" in msg3)
    check("Shows '1 Stuks'", "1 Stuks" in msg3)

    print(f"\n{BOLD}--- 1.4 Broadcast with 7 tickets (capped to 4) ---{RESET}")
    msg4 = sell_offer_group_broadcast("Thuishaven", "2026-05-10", 7, "60")
    print(f"    {CYAN}{msg4}{RESET}")
    check("Capped at 4: shows '4 Stuks'", "4 Stuks" in msg4)
    check("Has 4️⃣ emoji (capped)", "4️⃣" in msg4)
    check("Does NOT show '7 Stuks'", "7 Stuks" not in msg4)

    print(f"\n{BOLD}--- 1.5 Broadcast with 10 tickets (capped to 4) ---{RESET}")
    msg5 = sell_offer_group_broadcast("Mysteryland", "2026-08-22", 10, "120")
    print(f"    {CYAN}{msg5}{RESET}")
    check("Capped at 4 for 10 tickets", "4 Stuks" in msg5)

    print(f"\n{BOLD}--- 1.6 Broadcast with edition ---{RESET}")
    msg6 = sell_offer_group_broadcast("DGTL", "2026-04-05", 3, "80", ticket_type="Saturday")
    print(f"    {CYAN}{msg6}{RESET}")
    check("Edition shown", "DGTL (Saturday)" in msg6)
    check("Has 3️⃣ emoji", "3️⃣" in msg6)

    # ═══════════════════════════════════════════════════════════
    # 2. BUY BROADCAST — no max price
    # ═══════════════════════════════════════════════════════════
    print(f"\n{BOLD}{CYAN}{'═'*60}")
    print(f"  2. BUY BROADCAST — Max price removed")
    print(f"{'═'*60}{RESET}")

    from app.message_templates.templates import buy_request_group_broadcast

    print(f"\n{BOLD}--- 2.1 Buy broadcast has no max price ---{RESET}")
    bmsg = buy_request_group_broadcast("Thuishaven", "2026-04-18", 2, "60")
    print(f"    {CYAN}{bmsg}{RESET}")
    check("No 'Max prijs' in buy broadcast", "max prijs" not in bmsg.lower())
    check("No '€60' in buy broadcast", "€60" not in bmsg)
    check("Has number emoji", "2️⃣" in bmsg)

    # ═══════════════════════════════════════════════════════════
    # 3. CONFIRMATION — no max price shown
    # ═══════════════════════════════════════════════════════════
    print(f"\n{BOLD}{CYAN}{'═'*60}")
    print(f"  3. CONFIRMATION — No max price in buy confirmation")
    print(f"{'═'*60}{RESET}")

    async with async_session() as db:
        PHONE = "+31TEST_TWEAK_03"
        await reset_user(db, PHONE)

        print(f"\n{BOLD}--- 3.1 Buy flow confirmation ---{RESET}")
        await send(db, PHONE, "ik wil tickets kopen")
        r = await send(db, PHONE, "Thuishaven, 18 april, 2 stuks, max 60 euro")
        check("No 'Max €60' in confirmation", has_not(r, "Max €60", "max €60"), f"reply: {r[:120]}")
        check("Confirmation still shows event", has(r, "thuishaven") or has(r, "klopt"), f"reply: {r[:120]}")
        await db.commit()

    # ═══════════════════════════════════════════════════════════
    # 4. PROOF REQUEST — after sell save
    # ═══════════════════════════════════════════════════════════
    print(f"\n{BOLD}{CYAN}{'═'*60}")
    print(f"  4. PROOF REQUEST — Asked after sell offer saved")
    print(f"{'═'*60}{RESET}")

    async with async_session() as db:
        PHONE = "+31TEST_TWEAK_04"
        await reset_user(db, PHONE)

        print(f"\n{BOLD}--- 4.1 Complete sell flow ---{RESET}")
        await send(db, PHONE, "ik wil tickets verkopen")  # gets form link
        await send(db, PHONE, "Evenement: Joy Festival\nDatum: 27 april\nAantal: 4\nPrijs per ticket: 30 euro")
        r = await send(db, PHONE, "ja")  # confirm
        check("Proof request in response", has(r, "screenshot") or has(r, "bewijs") or has(r, "foto"), f"reply: {r[:150]}")
        await db.commit()

    # ═══════════════════════════════════════════════════════════
    # 5. FORM LINK ON INTENT SWITCH
    # ═══════════════════════════════════════════════════════════
    print(f"\n{BOLD}{CYAN}{'═'*60}")
    print(f"  5. FORM LINK ON SWITCH — Correct form sent")
    print(f"{'═'*60}{RESET}")

    async with async_session() as db:
        PHONE = "+31TEST_TWEAK_05"

        print(f"\n{BOLD}--- 5.1 Start sell, switch to buy ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik wil tickets verkopen")
        r = await send(db, PHONE, "nee ik wil kopen")
        check("Buy form link on switch", has(r, "searchform") or has(r, "kopen"), f"reply: {r[:120]}")
        check("No sell form after switch", has_not(r, "sellform"), f"reply: {r[:120]}")
        await db.commit()

        print(f"\n{BOLD}--- 5.2 Start buy, switch to sell ---{RESET}")
        await reset_user(db, PHONE)
        await send(db, PHONE, "ik wil tickets kopen")
        r2 = await send(db, PHONE, "nee ik wil verkopen")
        check("Sell form link on switch", has(r2, "sellform") or has(r2, "verkopen"), f"reply: {r2[:120]}")
        check("No buy form after switch", has_not(r2, "searchform"), f"reply: {r2[:120]}")
        await db.commit()

    # ═══════════════════════════════════════════════════════════
    # 6. SESSION TIMEOUT = 2h
    # ═══════════════════════════════════════════════════════════
    print(f"\n{BOLD}{CYAN}{'═'*60}")
    print(f"  6. SESSION TIMEOUT — Set to 2 hours")
    print(f"{'═'*60}{RESET}")

    from app.ai.state_machine import SESSION_TIMEOUT_HOURS
    check("Timeout is 2 hours", SESSION_TIMEOUT_HOURS == 2, f"actual: {SESSION_TIMEOUT_HOURS}h")

    # ═══════════════════════════════════════════════════════════
    # RESULTS
    # ═══════════════════════════════════════════════════════════
    print(f"\n\n{BOLD}{'═'*60}")
    if failed == 0:
        print(f"  {GREEN}TWEAKS TEST: {passed} passed, 0 failed ✅{RESET}")
    else:
        print(f"  {RED}TWEAKS TEST: {passed} passed, {failed} failed ❌{RESET}")
        for e in errors:
            print(f"    {RED}• {e}{RESET}")
    print(f"{'═'*60}\n")
    return failed == 0


if __name__ == "__main__":
    sys.path.insert(0, ".")
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
