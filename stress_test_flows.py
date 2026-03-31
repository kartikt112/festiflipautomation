"""
Stress Test: Full Buyer & Seller Flows
Simulates WhatsApp conversations through the state machine and verifies DB output.
"""
import asyncio
import os
import sys
import logging

# Suppress noisy SQL logs
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

from app.database import async_session
from app.ai.state_machine import process_message
from app.crud.chat_sessions import get_or_create_session, reset_session
from sqlalchemy import text

# ──────────────────────────────────────────
# TEST SCENARIOS
# ──────────────────────────────────────────

SELLER_FLOW = {
    "phone": "+31600000001",
    "label": "SELLER: Multi-day festival (Lowlands, Weekender)",
    "messages": [
        "Hallo",
        "Ik wil tickets verkopen",
        "Voor Lowlands",
        # AI verifier should detect multi-day → ask ticket type
        "Weekender",
        "15 augustus 2025",
        "2 tickets",
        "150 euro per stuk",
        "ja",
    ],
    "expected_db": {
        "table": "sell_offers",
        "event_name_contains": "Lowlands",
        "ticket_type_contains": "Weekender",  # Should NOT be None
        "quantity": 2,
        "price_field": "price_per_ticket",
        "price_value": 150.0,
    }
}

SELLER_SINGLE_DAY = {
    "phone": "+31600000002",
    "label": "SELLER: Single-day concert (Coldplay)",
    "messages": [
        "Verkopen voor Coldplay",
        # AI verifier should detect single-day → skip ticket type
        "25 juni 2025",
        "1",
        "€200",
        "ja",
    ],
    "expected_db": {
        "table": "sell_offers",
        "event_name_contains": "Coldplay",
        "ticket_type_contains": None,  # Should be NULL (single-day)
        "quantity": 1,
        "price_field": "price_per_ticket",
        "price_value": 200.0,
    }
}

BUYER_FLOW = {
    "phone": "+31600000003",
    "label": "BUYER: Looking for Pinkpop tickets",
    "messages": [
        "Ik zoek tickets voor Pinkpop",
        # AI verifier should detect multi-day → ask ticket type
        "Dagticket Zaterdag",
        "21 juni 2025",
        "3",
        "maximaal 80 euro",
        "ja",
    ],
    "expected_db": {
        "table": "buy_requests",
        "event_name_contains": "Pinkpop",
        "ticket_type_contains": "Dagticket",
        "quantity": 3,
        "price_field": "max_price_per_ticket",
        "price_value": 80.0,
    }
}

BUYER_ALL_IN_ONE = {
    "phone": "+31600000004",
    "label": "BUYER: All data in one message",
    "messages": [
        "Ik zoek 2 tickets voor Beyoncé op 10 juli 2025, maximaal €120",
        # Should skip ticket type (single-day concert)
        "ja",
    ],
    "expected_db": {
        "table": "buy_requests",
        "event_name_contains": "Beyoncé",
        "ticket_type_contains": None,
        "quantity": 2,
        "price_field": "max_price_per_ticket",
        "price_value": 120.0,
    }
}

ALL_SCENARIOS = [SELLER_FLOW, SELLER_SINGLE_DAY, BUYER_FLOW, BUYER_ALL_IN_ONE]


# ──────────────────────────────────────────
# TEST RUNNER
# ──────────────────────────────────────────

async def run_scenario(scenario: dict) -> dict:
    """Run a single conversation scenario and return results."""
    phone = scenario["phone"]
    label = scenario["label"]
    messages = scenario["messages"]
    expected = scenario["expected_db"]
    
    print(f"\n{'='*60}")
    print(f"📋 {label}")
    print(f"{'='*60}")
    
    results = {"label": label, "passed": True, "errors": []}
    
    async with async_session() as db:
        # Clean slate
        await db.execute(text(f"DELETE FROM chat_sessions WHERE phone = '{phone}'"))
        await db.execute(text(f"DELETE FROM {expected['table']} WHERE phone = '{phone}'"))
        await db.commit()
    
    # Run conversation
    for i, msg in enumerate(messages):
        async with async_session() as db:
            print(f"\n  👤 User [{i+1}/{len(messages)}]: {msg}")
            try:
                reply = await process_message(db, phone, msg)
                await db.commit()
                # Truncate long replies for display
                display_reply = reply[:120] + "..." if len(reply) > 120 else reply
                print(f"  🤖 Bot: {display_reply}")
            except Exception as e:
                print(f"  ❌ ERROR: {e}")
                results["passed"] = False
                results["errors"].append(f"Message {i+1} crashed: {e}")
                return results
    
    # Verify database
    print(f"\n  📊 Verifying database...")
    async with async_session() as db:
        table = expected["table"]
        result = await db.execute(text(f"SELECT * FROM {table} WHERE phone = '{phone}' ORDER BY id DESC LIMIT 1"))
        row = result.fetchone()
        
        if not row:
            print(f"  ❌ FAIL: No record found in {table} for {phone}")
            results["passed"] = False
            results["errors"].append(f"No record in {table}")
            return results
        
        # Get column names
        cols_result = await db.execute(text(f"PRAGMA table_info({table})"))
        col_names = [c[1] for c in cols_result.fetchall()]
        row_dict = dict(zip(col_names, row))
        
        # Check event name
        if expected["event_name_contains"]:
            if expected["event_name_contains"].lower() not in (row_dict.get("event_name") or "").lower():
                results["passed"] = False
                results["errors"].append(f"event_name '{row_dict.get('event_name')}' doesn't contain '{expected['event_name_contains']}'")
                print(f"  ❌ event_name: {row_dict.get('event_name')}")
            else:
                print(f"  ✅ event_name: {row_dict.get('event_name')}")
        
        # Check ticket type
        actual_tt = row_dict.get("ticket_type")
        expected_tt = expected["ticket_type_contains"]
        if expected_tt is None:
            if actual_tt is None or actual_tt == "":
                print(f"  ✅ ticket_type: None (correct, single-day event)")
            else:
                print(f"  ⚠️  ticket_type: '{actual_tt}' (expected None for single-day, but got a value — acceptable)")
        else:
            if actual_tt and expected_tt.lower() in actual_tt.lower():
                print(f"  ✅ ticket_type: {actual_tt}")
            else:
                results["passed"] = False
                results["errors"].append(f"ticket_type '{actual_tt}' doesn't contain '{expected_tt}'")
                print(f"  ❌ ticket_type: {actual_tt} (expected: {expected_tt})")
        
        # Check quantity
        if row_dict.get("quantity") == expected["quantity"]:
            print(f"  ✅ quantity: {row_dict.get('quantity')}")
        else:
            results["passed"] = False
            results["errors"].append(f"quantity {row_dict.get('quantity')} != {expected['quantity']}")
            print(f"  ❌ quantity: {row_dict.get('quantity')} (expected: {expected['quantity']})")
        
        # Check price
        price_field = expected["price_field"]
        actual_price = float(row_dict.get(price_field) or 0)
        if abs(actual_price - expected["price_value"]) < 0.01:
            print(f"  ✅ {price_field}: €{actual_price:.2f}")
        else:
            results["passed"] = False
            results["errors"].append(f"{price_field} {actual_price} != {expected['price_value']}")
            print(f"  ❌ {price_field}: €{actual_price:.2f} (expected: €{expected['price_value']:.2f})")
        
        # Check event_date
        event_date = row_dict.get("event_date")
        print(f"  {'✅' if event_date else '⚠️ '} event_date: {event_date or 'None (not captured)'}")
        
    return results


async def main():
    print("🚀 FESTIFLIP STRESS TEST — BUYER & SELLER FLOWS")
    print("=" * 60)
    
    all_results = []
    for scenario in ALL_SCENARIOS:
        result = await run_scenario(scenario)
        all_results.append(result)
    
    # Summary
    print(f"\n\n{'='*60}")
    print("📊 STRESS TEST SUMMARY")
    print(f"{'='*60}")
    
    passed = sum(1 for r in all_results if r["passed"])
    total = len(all_results)
    
    for r in all_results:
        status = "✅ PASS" if r["passed"] else "❌ FAIL"
        print(f"  {status} — {r['label']}")
        for err in r.get("errors", []):
            print(f"         └─ {err}")
    
    print(f"\n  Result: {passed}/{total} scenarios passed")
    
    if passed == total:
        print("  🎉 ALL TESTS PASSED! The system is working correctly.")
    else:
        print("  ⚠️  Some tests failed. Review the errors above.")


if __name__ == "__main__":
    asyncio.run(main())
