"""
Full Business Flow Test — Tests every documented automation flow.

Flow tested:
1. Seller submits a sell offer (2 tickets for Lowlands 2025 @ €80 each)
2. Buyer submits a buy request (2 tickets for Lowlands 2025)
3. Matching engine finds the offer
4. Reservation is created (7.5% deposit, 60-min timeout, Stripe session)
5. Stripe Checkout → payment → webhook → seller contact released to buyer

This script calls the services directly (not via WhatsApp) to test the
core business logic end-to-end on the running server.
"""

import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main():
    from app.database import async_session
    from app.models.sell_offer import SellOffer, OfferStatus
    from app.models.buy_request import BuyRequest, BuyStatus
    from app.services.matching import find_matching_offers
    from app.services.reservation import create_new_reservation, complete_reservation
    from app.services.deposit import calculate_deposit
    from decimal import Decimal
    from datetime import datetime, timezone

    passed = 0
    failed = 0
    total = 0

    def check(name, condition, detail=""):
        nonlocal passed, failed, total
        total += 1
        if condition:
            passed += 1
            print(f"  ✅ {name}" + (f" — {detail}" if detail else ""))
        else:
            failed += 1
            print(f"  ❌ {name}" + (f" — {detail}" if detail else ""))

    print("=" * 60)
    print("🎪 FESTIFLIP FULL BUSINESS FLOW TEST")
    print("=" * 60)

    async with async_session() as db:
        # ──────────────────────────────────────────────
        # FLOW 1: DEPOSIT CALCULATION
        # ──────────────────────────────────────────────
        print("\n📊 FLOW 1: Deposit Calculation")
        print("-" * 40)

        # Test 7.5% rule: €80 * 2 * 0.075 = €12
        dep = calculate_deposit(Decimal("80"), 2)
        check("7.5% deposit for 2 × €80", dep.deposit_amount == Decimal("12.00"),
              f"€{dep.deposit_amount}")
        check("Remaining amount", dep.remaining_amount == Decimal("148.00"),
              f"€{dep.remaining_amount}")
        check("Minimum not applied", dep.minimum_applied == False)

        # Test minimum €5 rule: €20 * 1 * 0.075 = €1.50 → min €5
        dep2 = calculate_deposit(Decimal("20"), 1)
        check("€5 minimum for cheap ticket (€20)", dep2.deposit_amount == Decimal("5.00"),
              f"€{dep2.deposit_amount}")
        check("Minimum applied flag", dep2.minimum_applied == True)

        # ──────────────────────────────────────────────
        # FLOW 2: SELLER LISTS TICKETS
        # ──────────────────────────────────────────────
        print("\n🎫 FLOW 2: Seller Lists Tickets")
        print("-" * 40)

        seller = SellOffer(
            first_name="Jan",
            last_name="de Vries",
            phone="+31612345678",
            email="jan@example.com",
            event_name="Lowlands 2025",
            event_date=datetime(2025, 8, 15, tzinfo=timezone.utc),
            quantity=2,
            price_per_ticket=Decimal("80.00"),
            total_price=Decimal("160.00"),
            sale_type="REGULAR",
            status=OfferStatus.AVAILABLE,
            agreement_accepted=True,
        )
        db.add(seller)
        await db.flush()

        check("Sell offer created", seller.id is not None, f"ID={seller.id}")
        check("Status is AVAILABLE", seller.status == OfferStatus.AVAILABLE)
        check("Correct price", seller.price_per_ticket == Decimal("80.00"))
        check("Correct quantity", seller.quantity == 2)

        # ──────────────────────────────────────────────
        # FLOW 3: BUYER REQUESTS TICKETS
        # ──────────────────────────────────────────────
        print("\n🛒 FLOW 3: Buyer Requests Tickets")
        print("-" * 40)

        buyer = BuyRequest(
            first_name="Emma",
            last_name="Bakker",
            phone="+31698765432",
            email="emma@example.com",
            event_name="Lowlands 2025",
            quantity=2,
            max_price_per_ticket=Decimal("100.00"),
            source="WHATSAPP",
            status=BuyStatus.WAITING,
            agreement_accepted=True,
        )
        db.add(buyer)
        await db.flush()

        check("Buy request created", buyer.id is not None, f"ID={buyer.id}")
        check("Status is WAITING", buyer.status == BuyStatus.WAITING)
        check("Source is WHATSAPP", buyer.source == "WHATSAPP")

        # ──────────────────────────────────────────────
        # FLOW 4: MATCHING ENGINE
        # ──────────────────────────────────────────────
        print("\n🔍 FLOW 4: Buy ↔ Sell Matching")
        print("-" * 40)

        matches = await find_matching_offers(
            db,
            event_name="Lowlands",
            quantity=2,
            max_price=Decimal("100.00")
        )

        check("Found matching offers", len(matches) > 0, f"{len(matches)} match(es)")
        if matches:
            best = matches[0]
            check("Best match is our seller", best.id == seller.id)
            check("Price within budget", best.price_per_ticket <= Decimal("100.00"),
                  f"€{best.price_per_ticket}")

        # ──────────────────────────────────────────────
        # FLOW 5: RESERVATION + STRIPE SESSION
        # ──────────────────────────────────────────────
        print("\n🔒 FLOW 5: Reservation + Stripe Deposit")
        print("-" * 40)

        try:
            result = await create_new_reservation(
                db,
                buy_request_id=buyer.id,
                sell_offer_id=seller.id,
                quantity=2,
            )

            check("Reservation created", result is not None)
            check("Deposit = €12", result["deposit_amount"] == 12.0,
                  f"€{result['deposit_amount']}")
            check("Remaining = €148", result["remaining_amount"] == 148.0,
                  f"€{result['remaining_amount']}")
            check("Stripe checkout URL", result["checkout_url"].startswith("https://"),
                  result["checkout_url"][:60] + "...")
            check("Has expiry time", result["expires_at"] is not None)

            reservation_id = result["reservation_id"]

            # Re-fetch offer to check status
            await db.refresh(seller)
            check("Offer status → RESERVED", seller.status == OfferStatus.RESERVED)

            await db.refresh(buyer)
            check("Buy request → MATCHED", buyer.status == BuyStatus.MATCHED)

            print(f"\n  💳 Checkout URL: {result['checkout_url'][:80]}...")
            print(f"  ⏱️  Expires at: {result['expires_at']}")

        except Exception as e:
            check("Reservation creation", False, str(e))
            reservation_id = None

        # ──────────────────────────────────────────────
        # FLOW 6: SIMULATE PAYMENT COMPLETION (webhook)
        # ──────────────────────────────────────────────
        print("\n💰 FLOW 6: Payment Completion (webhook sim)")
        print("-" * 40)

        if reservation_id:
            try:
                processed = await complete_reservation(
                    db,
                    reservation_id=reservation_id,
                    stripe_payment_intent_id="pi_test_full_flow_001",
                    webhook_event_id="evt_test_full_flow_001",
                )

                check("Payment processed", processed == True)

                # Re-fetch to verify state changes
                await db.refresh(seller)
                check("Offer status → SOLD", seller.status == OfferStatus.SOLD)

                # Check idempotency
                duplicate = await complete_reservation(
                    db,
                    reservation_id=reservation_id,
                    stripe_payment_intent_id="pi_test_full_flow_001",
                    webhook_event_id="evt_test_full_flow_001",
                )
                check("Duplicate webhook rejected", duplicate == False,
                      "Idempotency works!")

            except Exception as e:
                check("Payment completion", False, str(e))
        else:
            print("  ⏭️  Skipped (no reservation)")

        # ──────────────────────────────────────────────
        # FLOW 7: AI INTENT CLASSIFICATION
        # ──────────────────────────────────────────────
        print("\n🤖 FLOW 7: AI Intent Classification")
        print("-" * 40)

        from app.ai.classifier import classify_message

        test_messages = [
            ("Ik wil 2 tickets kopen voor Lowlands 2025", "BUY_REQUEST"),
            ("Ik verkoop 3 kaarten voor Mysteryland, €75 per stuk", "SELL_OFFER"),
            ("Wat is de status van mijn bestelling?", "STATUS_CHECK"),
            ("Hallo", "GREETING"),
        ]

        for msg, expected_intent in test_messages:
            result = await classify_message(msg)
            check(f"'{msg[:40]}...'",
                  result.intent == expected_intent,
                  f"→ {result.intent} (conf={result.confidence:.0%})")

        # ──────────────────────────────────────────────
        # FLOW 8: ADMIN DASHBOARD (via HTTP)
        # ──────────────────────────────────────────────
        print("\n📊 FLOW 8: Admin Dashboard Access")
        print("-" * 40)

        import httpx
        async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
            pages = [
                ("/admin/", "Dashboard"),
                ("/admin/listings", "Listings"),
                ("/admin/reservations", "Reservations"),
                ("/admin/payments", "Payments"),
                ("/admin/webhooks", "Webhook logs"),
            ]
            for path, name in pages:
                r = await client.get(path)
                check(f"{name} page loads", r.status_code == 200)

            # CSV export
            r = await client.get("/admin/export/sell_offers")
            check("CSV export works", r.status_code == 200 and "text/csv" in r.headers.get("content-type", ""))

        # ──────────────────────────────────────────────
        # SUMMARY
        # ──────────────────────────────────────────────
        print("\n" + "=" * 60)
        print(f"🏁 RESULTS: {passed}/{total} passed, {failed} failed")
        if failed == 0:
            print("🎉 ALL BUSINESS FLOWS WORKING CORRECTLY!")
        else:
            print(f"⚠️  {failed} test(s) need attention")
        print("=" * 60)

        # Rollback test data to keep DB clean
        await db.rollback()
        print("\n🧹 Test data rolled back (DB unchanged)")


if __name__ == "__main__":
    asyncio.run(main())
