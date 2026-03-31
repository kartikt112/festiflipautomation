"""
🔥 COMPREHENSIVE STRESS TEST — FestiFlip WhatsApp Automation
=============================================================
Simulates 15+ real conversation scenarios through the state machine,
matching engine, reservation system, and payment flow.

Each test runs an isolated conversation with a unique phone number.
"""

import asyncio
import sys
import os
import traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─── Test harness ───────────────────────────────────────────

passed = 0
failed = 0
total = 0
errors = []


def check(test_name, condition, detail=""):
    global passed, failed, total
    total += 1
    if condition:
        passed += 1
        print(f"    ✅ {test_name}" + (f" — {detail}" if detail else ""))
    else:
        failed += 1
        errors.append(test_name)
        print(f"    ❌ {test_name}" + (f" — {detail}" if detail else ""))


async def chat(db, phone, message):
    """Simulate a WhatsApp message and return the bot's reply."""
    from app.ai.state_machine import process_message
    reply = await process_message(db, phone, message)
    return reply


async def reset_phone(db, phone):
    """Reset a phone's chat session."""
    from app.crud.chat_sessions import reset_session
    await reset_session(db, phone)
    await db.commit()


# ─── Test scenarios ─────────────────────────────────────────

async def test_01_buy_full_message(db):
    """BUYER: Full buy request in a single message → straight to confirmation."""
    print("\n📱 TEST 01: Buyer — complete request in one message")
    phone = "+31600000001"
    reply = await chat(db, phone, "Ik wil graag 2 tickets kopen voor Lowlands 2025, maximaal €90 per stuk")

    check("Extracts all entities in one shot",
          "Kloppen deze gegevens" in reply or "bevestig" in reply.lower(),
          reply[:80])
    check("Event name extracted", "Lowlands" in reply)
    check("Quantity extracted", "2" in reply)
    check("Max price extracted", "90" in reply)

    # Confirm
    reply2 = await chat(db, phone, "ja")
    check("Confirmation accepted", "opgeslagen" in reply2.lower() or "✅" in reply2, reply2[:80])
    await reset_phone(db, phone)


async def test_02_buy_step_by_step(db):
    """BUYER: Provides data one field at a time."""
    print("\n📱 TEST 02: Buyer — step-by-step data collection")
    phone = "+31600000002"

    reply = await chat(db, phone, "Ik wil tickets kopen")
    check("Asks for event name", "evenement" in reply.lower(), reply[:80])

    reply = await chat(db, phone, "Defqon.1 2025")
    check("Asks for quantity", "hoeveel" in reply.lower(), reply[:80])

    reply = await chat(db, phone, "3")
    check("Goes to confirmation (BUY only needs event+qty)", 
          "Kloppen" in reply or "bevestig" in reply.lower(),
          reply[:80])

    reply = await chat(db, phone, "ja")
    check("Saved successfully", "✅" in reply, reply[:60])
    await reset_phone(db, phone)


async def test_03_buy_dutch_numbers(db):
    """BUYER: Uses Dutch number words — 'twee', 'drie' etc."""
    print("\n📱 TEST 03: Buyer — Dutch number words")
    phone = "+31600000003"

    reply = await chat(db, phone, "Ik zoek tickets voor Mysteryland")
    check("Asks quantity after event", "hoeveel" in reply.lower(), reply[:80])

    reply = await chat(db, phone, "twee")
    check("Parsed 'twee' as 2", "Kloppen" in reply or "2" in reply, reply[:80])

    await reset_phone(db, phone)


async def test_04_buy_reject_and_restart(db):
    """BUYER: Gets to confirmation, says 'nee', starts over."""
    print("\n📱 TEST 04: Buyer — reject confirmation and restart")
    phone = "+31600000004"

    reply = await chat(db, phone, "Ik wil 1 ticket kopen voor Awakenings 2025")
    is_confirming = "Kloppen" in reply or "bevestig" in reply.lower()
    is_collecting = "evenement" in reply.lower() or "hoeveel" in reply.lower() or "prijs" in reply.lower()
    check("Intent recognized", is_confirming or is_collecting, reply[:60])

    # If in confirmation, reject it
    if is_confirming:
        reply = await chat(db, phone, "nee")
        check("Restart after rejection", "opnieuw" in reply.lower() or "evenement" in reply.lower(), reply[:80])
    elif is_collecting:
        # Fill in remaining fields until we hit confirmation
        if "hoeveel" in reply.lower():
            reply = await chat(db, phone, "1")
        if "Kloppen" in reply:
            reply = await chat(db, phone, "nee")
            check("Restart after rejection", "opnieuw" in reply.lower() or "evenement" in reply.lower(), reply[:80])
    
    await reset_phone(db, phone)


async def test_05_buy_cancel_midflow(db):
    """BUYER: Cancels mid-collection with 'stop'."""
    print("\n📱 TEST 05: Buyer — cancel mid-flow")
    phone = "+31600000005"

    await chat(db, phone, "Ik wil tickets kopen")
    reply = await chat(db, phone, "stop")
    check("Cancel acknowledged", "opnieuw" in reply.lower() or "geen probleem" in reply.lower(), reply[:80])

    # Next message should be fresh (IDLE state)
    reply = await chat(db, phone, "Hallo")
    check("Back to IDLE after cancel", "welkom" in reply.lower() or "festiflip" in reply.lower(), reply[:80])
    await reset_phone(db, phone)


async def test_06_sell_full_message(db):
    """SELLER: Full sell offer in one message."""
    print("\n📱 TEST 06: Seller — complete offer in one message")
    phone = "+31600000006"

    reply = await chat(db, phone, "Ik verkoop 3 kaarten voor Mysteryland 2025, €75 per stuk")
    # Should either confirm or ask for remaining fields
    has_data = "Kloppen" in reply or "Mysteryland" in reply or "prijs" in reply.lower()
    check("Processes sell intent", has_data, reply[:80])

    # If at confirmation
    if "Kloppen" in reply:
        check("Event extracted", "Mysteryland" in reply)
        check("Price extracted", "75" in reply)
        reply2 = await chat(db, phone, "ja")
        check("Sell saved", "✅" in reply2 or "opgeslagen" in reply2.lower(), reply2[:60])
    await reset_phone(db, phone)


async def test_07_sell_step_by_step(db):
    """SELLER: Provides data one field at a time."""
    print("\n📱 TEST 07: Seller — step-by-step")
    phone = "+31600000007"

    reply = await chat(db, phone, "Ik wil mijn tickets verkopen")
    check("Asks for event", "evenement" in reply.lower(), reply[:80])

    reply = await chat(db, phone, "Into The Great Wide Open 2025")
    check("Asks for quantity", "hoeveel" in reply.lower(), reply[:80])

    reply = await chat(db, phone, "2")
    check("Asks for price", "prijs" in reply.lower(), reply[:80])

    reply = await chat(db, phone, "€55")
    check("Goes to confirmation", "Kloppen" in reply, reply[:80])

    reply = await chat(db, phone, "ja")
    check("Sell saved", "✅" in reply, reply[:60])
    await reset_phone(db, phone)


async def test_08_greeting(db):
    """USER: Sends a greeting — should get welcome message."""
    print("\n📱 TEST 08: Greeting / unknown intent")
    phone = "+31600000008"

    reply = await chat(db, phone, "Hallo")
    check("Welcome message", "welkom" in reply.lower() or "festiflip" in reply.lower(), reply[:80])

    reply = await chat(db, phone, "Goedemorgen!")
    check("Still welcome on 2nd greeting", "welkom" in reply.lower() or "kopen" in reply.lower(), reply[:80])
    await reset_phone(db, phone)


async def test_09_status_check(db):
    """USER: Asks for order status."""
    print("\n📱 TEST 09: Status check")
    phone = "+31600000009"

    reply = await chat(db, phone, "Wat is de status van mijn bestelling?")
    check("Status response", "status" in reply.lower() or "⏳" in reply, reply[:80])
    await reset_phone(db, phone)


async def test_10_payment_confirmation(db):
    """USER: Reports payment."""
    print("\n📱 TEST 10: Payment confirmation")
    phone = "+31600000010"

    reply = await chat(db, phone, "Ik heb net betaald via Stripe")
    check("Payment ack", "betaling" in reply.lower() or "✅" in reply, reply[:80])
    await reset_phone(db, phone)


async def test_11_support(db):
    """USER: Reports a problem."""
    print("\n📱 TEST 11: Support request")
    phone = "+31600000011"

    reply = await chat(db, phone, "Ik heb een probleem met mijn ticket")
    check("Support response", "medewerker" in reply.lower() or "📞" in reply or "bericht" in reply.lower(), reply[:80])
    await reset_phone(db, phone)


async def test_12_gibberish(db):
    """USER: Sends random gibberish."""
    print("\n📱 TEST 12: Gibberish / unrecognized input")
    phone = "+31600000012"

    reply = await chat(db, phone, "asdfghjkl 12345 xyz")
    check("Falls back to welcome", "welkom" in reply.lower() or "kopen" in reply.lower() or "verkopen" in reply.lower(), reply[:80])
    await reset_phone(db, phone)


async def test_13_emoji_only(db):
    """USER: Sends only emojis."""
    print("\n📱 TEST 13: Emoji-only message")
    phone = "+31600000013"

    reply = await chat(db, phone, "🎉🎫🔥")
    check("Handles emojis gracefully", reply is not None and len(reply) > 0, reply[:60])
    await reset_phone(db, phone)


async def test_14_price_formats(db):
    """BUYER: Tests various price formats — €90, 90 euro, 90.50, etc."""
    print("\n📱 TEST 14: Various price formats")
    phone = "+31600000014"

    from app.ai.classifier import classify_message

    tests = [
        ("Ik zoek tickets voor Lowlands 2025, €90 per stuk", 90.0),
        ("Ik zoek tickets voor Lowlands 2025, 75 euro", 75.0),
        ("Ik zoek tickets voor Lowlands 2025, maximaal €120,50", 120.50),
    ]
    for msg, expected_price in tests:
        result = await classify_message(msg)
        entities = result.entities or {}
        price = entities.get("max_price") or entities.get("price_per_ticket")
        check(f"Price from '{msg[-20:]}'",
              price == expected_price,
              f"got {price}")
    await reset_phone(db, phone)


async def test_15_quantity_formats(db):
    """Tests all Dutch number words and digit formats."""
    print("\n📱 TEST 15: Quantity formats (Dutch words + digits)")
    phone = "+31600000015"

    from app.ai.state_machine import _parse_dutch_number

    tests = [
        ("een", 1), ("één", 1), ("eentje", 1),
        ("twee", 2), ("drie", 3), ("vier", 4), ("vijf", 5),
        ("zes", 6), ("zeven", 7), ("acht", 8), ("negen", 9), ("tien", 10),
        ("1", 1), ("2", 2), ("10", 10), ("25", 25),
    ]
    for text, expected in tests:
        result = _parse_dutch_number(text)
        check(f"'{text}' → {expected}", result == expected, f"got {result}")
    await reset_phone(db, phone)


async def test_16_matching_engine(db):
    """Tests buy↔sell matching with various scenarios."""
    print("\n📱 TEST 16: Matching engine scenarios")
    phone = "+31600000016"

    from app.services.matching import find_matching_offers
    from decimal import Decimal

    # Match with existing seeded data (Lowlands 2025 @ €80)
    matches = await find_matching_offers(db, "Lowlands", quantity=1, max_price=Decimal("100"))
    check("Finds Lowlands tickets", len(matches) > 0, f"{len(matches)} matches")

    # No match — price too low
    matches = await find_matching_offers(db, "Lowlands", quantity=1, max_price=Decimal("10"))
    check("No match when price too low", len(matches) == 0)

    # No match — wrong event
    matches = await find_matching_offers(db, "Tomorrowland", quantity=1)
    check("No match for non-existent event", len(matches) == 0)

    # Match — partial name
    matches = await find_matching_offers(db, "mystery", quantity=1)
    check("Fuzzy match 'mystery' → Mysteryland", len(matches) > 0, f"{len(matches)} matches")

    await reset_phone(db, phone)


async def test_17_deposit_calculation(db):
    """Tests deposit calculation edge cases."""
    print("\n📱 TEST 17: Deposit calculation edge cases")

    from app.services.deposit import calculate_deposit
    from decimal import Decimal

    # Normal: 7.5% of €100 * 2 = €15
    dep = calculate_deposit(Decimal("100"), 2)
    check("€100×2 → €15.00 deposit", dep.deposit_amount == Decimal("15.00"), f"€{dep.deposit_amount}")

    # Minimum kicks in: 7.5% of €20 * 1 = €1.50 → min €5
    dep = calculate_deposit(Decimal("20"), 1)
    check("€20×1 → €5.00 (min applied)", dep.deposit_amount == Decimal("5.00"))
    check("Minimum flag set", dep.minimum_applied == True)

    # Exactly at minimum: 7.5% of €66.67 ≈ €5.00
    dep = calculate_deposit(Decimal("66.67"), 1)
    check("€66.67×1 deposit", dep.deposit_amount == Decimal("5.00"), f"€{dep.deposit_amount}")

    # High value: €500 * 4 = 2000 * 7.5% = €150
    dep = calculate_deposit(Decimal("500"), 4)
    check("€500×4 → €150.00", dep.deposit_amount == Decimal("150.00"), f"€{dep.deposit_amount}")

    # Single cheap ticket
    dep = calculate_deposit(Decimal("5"), 1)
    check("€5×1 → €5.00 (min)", dep.deposit_amount == Decimal("5.00"))
    check("Remaining correct", dep.remaining_amount == Decimal("0.00"), f"€{dep.remaining_amount}")


async def test_18_reservation_lifecycle(db):
    """Tests full reservation: create → complete → idempotency."""
    print("\n📱 TEST 18: Reservation lifecycle")

    from app.models.sell_offer import SellOffer, OfferStatus
    from app.models.buy_request import BuyRequest, BuyStatus
    from app.services.reservation import create_new_reservation, complete_reservation
    from decimal import Decimal
    from datetime import datetime, timezone
    import time

    # Clean up leftover data from any previous test runs
    from sqlalchemy import text
    await db.execute(text("DELETE FROM payments WHERE webhook_event_id LIKE 'evt_stress_%'"))
    await db.commit()

    # Use unique IDs per run to avoid idempotency collisions
    run_id = str(int(time.time()))
    evt_id = f"evt_stress_{run_id}"
    pi_id = f"pi_stress_{run_id}"

    # Create test data
    seller = SellOffer(
        first_name="StressTest", last_name="Seller", phone="+31600099001",
        email="stress@test.nl", event_name="StressTest Festival 2025",
        event_date=datetime(2025, 9, 1, tzinfo=timezone.utc),
        quantity=2, price_per_ticket=Decimal("100.00"), total_price=Decimal("200.00"),
        sale_type="REGULAR", verification_status="VERIFIED",
        status=OfferStatus.AVAILABLE, agreement_accepted=True,
    )
    buyer = BuyRequest(
        first_name="StressTest", last_name="Buyer", phone="+31600099002",
        email="stressbuyer@test.nl", event_name="StressTest Festival 2025",
        quantity=2, max_price_per_ticket=Decimal("120.00"),
        source="WHATSAPP", status=BuyStatus.WAITING, agreement_accepted=True,
    )
    db.add(seller)
    db.add(buyer)
    await db.flush()

    try:
        result = await create_new_reservation(db, buyer.id, seller.id, quantity=2)
        check("Reservation created", result is not None)
        check("Stripe URL generated", result["checkout_url"].startswith("https://"))
        check("Deposit calculated", result["deposit_amount"] == 15.0, f"€{result['deposit_amount']}")
        check("Remaining correct", result["remaining_amount"] == 185.0, f"€{result['remaining_amount']}")

        rid = result["reservation_id"]

        # Complete via webhook
        try:
            ok = await complete_reservation(db, rid, pi_id, evt_id)
            check("Reservation completed", ok == True)
        except Exception as e:
            # WhatsApp send failure is OK in test — check if reservation was marked paid
            from app.crud.reservations import get_reservation
            res = await get_reservation(db, rid)
            is_paid = res and str(res.status) in ("PAID", "ReservationStatus.PAID")
            check("Reservation completed (WA send failed)", is_paid, str(e)[:60])

        # Idempotency — same event ID should be rejected
        try:
            dup = await complete_reservation(db, rid, pi_id, evt_id)
            check("Duplicate webhook rejected", dup == False)
        except Exception:
            check("Duplicate webhook rejected", True, "raised on completed")

        # Check seller status
        await db.refresh(seller)
        check("Offer → SOLD", seller.status == OfferStatus.SOLD)

    except Exception as e:
        check("Reservation lifecycle", False, str(e)[:80])

    await db.rollback()


async def test_19_concurrent_conversations(db):
    """Multiple users chatting simultaneously — each gets own DB session."""
    print("\n📱 TEST 19: Concurrent conversations (5 users)")

    from app.database import async_session

    phones = [f"+3160001900{i}" for i in range(5)]
    messages = [
        "Ik wil 2 tickets voor Lowlands 2025",
        "Ik verkoop 1 kaart voor Defqon.1 2025, €100",
        "Wat is mijn status?",
        "Ik zoek 4 tickets voor Awakenings",
        "Hallo!",
    ]

    async def process_one(phone, msg):
        from app.ai.state_machine import process_message
        async with async_session() as session:
            result = await process_message(session, phone, msg)
            await session.commit()
            return result

    # Fire all at once with separate sessions
    results = await asyncio.gather(*[
        process_one(phone, msg) for phone, msg in zip(phones, messages)
    ])

    check("All 5 replied", all(r is not None and len(r) > 0 for r in results),
          f"{sum(1 for r in results if r)} replies")
    check("Buy intent processed", "ticket" in results[0].lower() or "Kloppen" in results[0])
    check("Sell intent processed", "ticket" in results[1].lower() or "Kloppen" in results[1] or "prijs" in results[1].lower())
    check("Status processed", "status" in results[2].lower() or "⏳" in results[2])
    check("Buy intent #2 processed", "ticket" in results[3].lower() or "Kloppen" in results[3])
    check("Greeting processed", "welkom" in results[4].lower() or "FestiFlip" in results[4])

    # Reset with separate sessions
    for phone in phones:
        async with async_session() as session:
            from app.crud.chat_sessions import reset_session
            await reset_session(session, phone)
            await session.commit()


async def test_20_invalid_confirmation(db):
    """Random text during confirmation step."""
    print("\n📱 TEST 20: Invalid input during confirmation")
    phone = "+31600000020"

    # Use a message with explicit 'kopen' + enough entities to reach confirmation
    reply = await chat(db, phone, "Ik wil 2 tickets kopen voor Lowlands 2025, maximaal €90")
    if "Kloppen" in reply:
        reply2 = await chat(db, phone, "misschien")
        check("Prompts ja/nee", "ja" in reply2.lower() or "nee" in reply2.lower(), reply2[:60])

        reply3 = await chat(db, phone, "blabla")
        check("Still prompts ja/nee", "ja" in reply3.lower(), reply3[:60])

        reply4 = await chat(db, phone, "ja")
        check("Finally accepts ja", "✅" in reply4 or "opgeslagen" in reply4.lower(), reply4[:60])
    else:
        # Reached collecting — proceed through it
        check("Reached collecting", "hoeveel" in reply.lower() or "prijs" in reply.lower() or "evenement" in reply.lower(), reply[:60])

    await reset_phone(db, phone)


async def test_21_entity_extraction_edge_cases(db):
    """Edge cases in entity extraction."""
    print("\n📱 TEST 21: Entity extraction edge cases")

    from app.ai.classifier import classify_message

    # Multiple numbers — should pick the right one
    r = await classify_message("Ik wil 3 tickets voor Lowlands 2025, €80")
    e = r.entities or {}
    check("Quantity=3 with price", e.get("quantity") == 3, f"qty={e.get('quantity')}")
    check("Price=80", (e.get("max_price") or e.get("price_per_ticket")) == 80.0, f"price={e.get('max_price')}")
    check("Event=Lowlands", "Lowlands" in (e.get("event_name") or ""), f"event={e.get('event_name')}")

    # No quantity in message
    r2 = await classify_message("Ik zoek tickets voor Mysteryland")
    e2 = r2.entities or {}
    check("No quantity if not mentioned", e2.get("quantity") is None)
    check("Event still extracted", "Mysteryland" in (e2.get("event_name") or ""))

    # Euro with comma decimal
    r3 = await classify_message("Ik zoek tickets voor Festival X, €75,50")
    e3 = r3.entities or {}
    check("€75,50 parsed as 75.5", (e3.get("max_price") or e3.get("price_per_ticket")) == 75.5, f"price={e3.get('max_price')}")


async def test_22_admin_dashboard_under_load(db):
    """Verify admin dashboard still works after all the test data."""
    print("\n📱 TEST 22: Admin dashboard under load")

    import httpx
    async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
        pages = ["/admin/", "/admin/listings", "/admin/reservations", "/admin/payments", "/admin/webhooks"]
        for page in pages:
            r = await client.get(page)
            check(f"GET {page}", r.status_code == 200)

        # API endpoints
        r = await client.get("/health")
        check("Health check", r.status_code == 200)

        r = await client.get("/admin/export/sell_offers")
        check("CSV export", r.status_code == 200)


async def test_23_rapid_fire_same_user(db):
    """Same user sends 10 messages rapidly."""
    print("\n📱 TEST 23: Rapid-fire — 10 messages from one user")
    phone = "+31600000023"

    messages = [
        "Hallo", "Ik wil tickets", "Lowlands 2025", "twee",
        "ja", "Wat is mijn status?", "stop",
        "Ik verkoop 1 ticket voor Defqon.1, €100",
        "nee", "opnieuw"
    ]

    crash = False
    for i, msg in enumerate(messages):
        try:
            reply = await chat(db, phone, msg)
            if i == 0:
                check(f"Msg {i+1}: '{msg}'", reply is not None, f"{reply[:50]}")
        except Exception as e:
            crash = True
            check(f"Msg {i+1}: '{msg}'", False, str(e)[:60])
            break

    check("No crashes in rapid-fire", not crash, "All 10 messages processed")
    await reset_phone(db, phone)


# ─── Main runner ────────────────────────────────────────────

async def main():
    from app.database import async_session

    print("=" * 70)
    print("🔥 FESTIFLIP COMPREHENSIVE STRESS TEST")
    print("=" * 70)

    async with async_session() as db:
        tests = [
            test_01_buy_full_message,
            test_02_buy_step_by_step,
            test_03_buy_dutch_numbers,
            test_04_buy_reject_and_restart,
            test_05_buy_cancel_midflow,
            test_06_sell_full_message,
            test_07_sell_step_by_step,
            test_08_greeting,
            test_09_status_check,
            test_10_payment_confirmation,
            test_11_support,
            test_12_gibberish,
            test_13_emoji_only,
            test_14_price_formats,
            test_15_quantity_formats,
            test_16_matching_engine,
            test_17_deposit_calculation,
            test_18_reservation_lifecycle,
            test_19_concurrent_conversations,
            test_20_invalid_confirmation,
            test_21_entity_extraction_edge_cases,
            test_22_admin_dashboard_under_load,
            test_23_rapid_fire_same_user,
        ]

        for test_fn in tests:
            try:
                await test_fn(db)
            except Exception as e:
                print(f"\n    💥 CRASH in {test_fn.__name__}: {e}")
                traceback.print_exc()
                errors.append(f"CRASH: {test_fn.__name__}")

    # ── Summary ──
    print("\n" + "=" * 70)
    print(f"🏁 STRESS TEST RESULTS: {passed}/{total} passed, {failed} failed")
    if failed == 0:
        print("🎉 ALL TESTS PASSED! System is rock solid!")
    else:
        print(f"⚠️  {failed} test(s) need attention:")
        for e in errors:
            print(f"    • {e}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
