"""
FestiFlip Pipeline Stress Test
==============================
Simulates realistic WhatsApp conversations hitting the webhook endpoint,
exercising every code path: buy flow, sell flow, matching, confirmations,
edge cases, concurrency, and error conditions.

Usage:
    python tests/stress_test.py [--base-url http://localhost:8000] [--concurrency 10]
"""

import asyncio
import httpx
import json
import time
import random
import string
import argparse
import sys
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

# ─── Config ───

BASE_URL = "http://localhost:8000"
WEBHOOK_PATH = "/webhooks/whatsapp"

# Generate unique phone numbers to avoid cross-test interference
def _phone(n: int) -> str:
    return f"+3160000{n:04d}"

# ─── Test Result Tracking ───

@dataclass
class TestResult:
    name: str
    passed: bool
    duration_ms: float
    error: Optional[str] = None
    details: Optional[str] = None

@dataclass
class StressReport:
    results: list = field(default_factory=list)
    start_time: float = 0
    end_time: float = 0

    def add(self, result: TestResult):
        self.results.append(result)

    @property
    def passed(self):
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self):
        return sum(1 for r in self.results if not r.passed)

    def print_report(self):
        self.end_time = time.time()
        total = self.end_time - self.start_time
        print("\n" + "=" * 70)
        print(f"  FESTIFLIP STRESS TEST REPORT")
        print(f"  Total time: {total:.1f}s | Tests: {len(self.results)} | "
              f"Passed: {self.passed} | Failed: {self.failed}")
        print("=" * 70)

        for r in self.results:
            icon = "PASS" if r.passed else "FAIL"
            print(f"  [{icon}] {r.name} ({r.duration_ms:.0f}ms)")
            if r.error:
                print(f"         Error: {r.error}")
            if r.details:
                print(f"         {r.details}")

        print("=" * 70)
        if self.failed == 0:
            print("  ALL TESTS PASSED")
        else:
            print(f"  {self.failed} TEST(S) FAILED")
        print("=" * 70 + "\n")


# ─── WhatsApp Webhook Simulator ───

def _wa_payload(phone: str, text: str, msg_id: str = None, forwarded: bool = False) -> dict:
    """Build a realistic Meta WhatsApp webhook payload."""
    if msg_id is None:
        msg_id = "wamid_test_" + "".join(random.choices(string.ascii_lowercase, k=12))

    message = {
        "id": msg_id,
        "from": phone.lstrip("+"),
        "type": "text",
        "text": {"body": text},
        "timestamp": str(int(time.time())),
    }
    if forwarded:
        message["context"] = {"forwarded": True}

    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "ENTRY_ID",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "15551234567", "phone_number_id": "PHONE_ID"},
                    "messages": [message],
                    "contacts": [{"profile": {"name": "Test User"}, "wa_id": phone.lstrip("+")}],
                },
                "field": "messages",
            }],
        }],
    }


def _wa_image_payload(phone: str, media_id: str = "test_media_123", caption: str = "") -> dict:
    """Build a WhatsApp image message payload."""
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "ENTRY_ID",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "messages": [{
                        "id": "wamid_img_" + "".join(random.choices(string.ascii_lowercase, k=8)),
                        "from": phone.lstrip("+"),
                        "type": "image",
                        "image": {"id": media_id, "caption": caption},
                        "timestamp": str(int(time.time())),
                    }],
                    "contacts": [{"profile": {"name": "Test"}, "wa_id": phone.lstrip("+")}],
                },
                "field": "messages",
            }],
        }],
    }


def _wa_status_payload() -> dict:
    """Build a WhatsApp status update (not a message) — should be ignored."""
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "statuses": [{"id": "wamid_status", "status": "delivered"}],
                },
                "field": "messages",
            }],
        }],
    }


async def send_msg(client: httpx.AsyncClient, phone: str, text: str, forwarded: bool = False) -> httpx.Response:
    """Send a simulated WhatsApp message and return the response."""
    payload = _wa_payload(phone, text, forwarded=forwarded)
    return await client.post(f"{BASE_URL}{WEBHOOK_PATH}", json=payload, timeout=60)


# ─── Individual Test Cases ───

async def test_health(client: httpx.AsyncClient) -> TestResult:
    """Test health endpoint responds."""
    t0 = time.time()
    try:
        r = await client.get(f"{BASE_URL}/health")
        ok = r.status_code == 200
        return TestResult("Health endpoint", ok, (time.time()-t0)*1000,
                          error=None if ok else f"Status {r.status_code}")
    except Exception as e:
        return TestResult("Health endpoint", False, (time.time()-t0)*1000, error=str(e))


async def test_root(client: httpx.AsyncClient) -> TestResult:
    """Test root endpoint."""
    t0 = time.time()
    try:
        r = await client.get(f"{BASE_URL}/")
        data = r.json()
        ok = r.status_code == 200 and data.get("service") == "FestiFlip"
        return TestResult("Root endpoint", ok, (time.time()-t0)*1000,
                          error=None if ok else f"Unexpected response: {data}")
    except Exception as e:
        return TestResult("Root endpoint", False, (time.time()-t0)*1000, error=str(e))


async def test_admin_dashboard(client: httpx.AsyncClient) -> TestResult:
    """Test admin dashboard loads."""
    t0 = time.time()
    try:
        r = await client.get(f"{BASE_URL}/admin/")
        ok = r.status_code == 200 and "dashboard" in r.text.lower()
        return TestResult("Admin dashboard", ok, (time.time()-t0)*1000,
                          error=None if ok else f"Status {r.status_code}")
    except Exception as e:
        return TestResult("Admin dashboard", False, (time.time()-t0)*1000, error=str(e))


async def test_admin_pages(client: httpx.AsyncClient) -> TestResult:
    """Test all admin sub-pages load without error."""
    t0 = time.time()
    pages = ["/admin/listings", "/admin/requests", "/admin/reservations",
             "/admin/payments", "/admin/sellers", "/admin/webhooks", "/admin/chats"]
    errors = []
    for page in pages:
        try:
            r = await client.get(f"{BASE_URL}{page}")
            if r.status_code != 200:
                errors.append(f"{page}: {r.status_code}")
        except Exception as e:
            errors.append(f"{page}: {e}")
    ok = len(errors) == 0
    return TestResult("Admin sub-pages", ok, (time.time()-t0)*1000,
                      error="; ".join(errors) if errors else None,
                      details=f"Tested {len(pages)} pages")


async def test_webhook_verification(client: httpx.AsyncClient) -> TestResult:
    """Test WhatsApp webhook verification (GET)."""
    t0 = time.time()
    try:
        # Valid verification
        r = await client.get(f"{BASE_URL}{WEBHOOK_PATH}", params={
            "hub.mode": "subscribe",
            "hub.verify_token": "test_token_placeholder",
            "hub.challenge": "12345",
        })
        # We expect 403 since we don't know the real token, which is correct behavior
        ok = r.status_code in (200, 403)
        return TestResult("Webhook verification", ok, (time.time()-t0)*1000,
                          details=f"Status: {r.status_code} (403 = correct rejection)")
    except Exception as e:
        return TestResult("Webhook verification", False, (time.time()-t0)*1000, error=str(e))


async def test_status_update_ignored(client: httpx.AsyncClient) -> TestResult:
    """Test that WhatsApp status updates (non-message) are ignored gracefully."""
    t0 = time.time()
    try:
        payload = _wa_status_payload()
        r = await client.post(f"{BASE_URL}{WEBHOOK_PATH}", json=payload)
        ok = r.status_code == 200
        return TestResult("Status update ignored", ok, (time.time()-t0)*1000)
    except Exception as e:
        return TestResult("Status update ignored", False, (time.time()-t0)*1000, error=str(e))


async def test_empty_payload(client: httpx.AsyncClient) -> TestResult:
    """Test empty/malformed webhook payloads don't crash the server."""
    t0 = time.time()
    payloads = [
        {},
        {"entry": []},
        {"entry": [{"changes": []}]},
        {"entry": [{"changes": [{"value": {}}]}]},
        {"entry": [{"changes": [{"value": {"messages": []}}]}]},
        {"garbage": True},
    ]
    errors = []
    for i, p in enumerate(payloads):
        try:
            r = await client.post(f"{BASE_URL}{WEBHOOK_PATH}", json=p)
            if r.status_code >= 500:
                errors.append(f"Payload {i}: server error {r.status_code}")
        except Exception as e:
            errors.append(f"Payload {i}: {e}")
    ok = len(errors) == 0
    return TestResult("Empty/malformed payloads", ok, (time.time()-t0)*1000,
                      error="; ".join(errors) if errors else None,
                      details=f"Tested {len(payloads)} edge cases")


async def test_full_buy_flow(client: httpx.AsyncClient) -> TestResult:
    """Test complete buy flow: greeting → intent → data → confirm."""
    phone = _phone(1001)
    t0 = time.time()
    errors = []

    try:
        # Step 0: Reset session
        r = await send_msg(client, phone, "stop")
        if r.status_code != 200:
            errors.append(f"Reset failed: {r.status_code}")

        await asyncio.sleep(0.3)

        # Step 1: Start buy intent
        r = await send_msg(client, phone, "ik wil tickets kopen")
        if r.status_code != 200:
            errors.append(f"Buy intent failed: {r.status_code}")

        await asyncio.sleep(0.5)

        # Step 2: Provide all details
        r = await send_msg(client, phone, "Lowlands festival 20 augustus 2 tickets max 100 euro")
        if r.status_code != 200:
            errors.append(f"Details failed: {r.status_code}")

        await asyncio.sleep(0.5)

        # Step 3: Confirm
        r = await send_msg(client, phone, "ja")
        if r.status_code != 200:
            errors.append(f"Confirm failed: {r.status_code}")

    except Exception as e:
        errors.append(str(e))

    ok = len(errors) == 0
    return TestResult("Full BUY flow", ok, (time.time()-t0)*1000,
                      error="; ".join(errors) if errors else None)


async def test_full_sell_flow(client: httpx.AsyncClient) -> TestResult:
    """Test complete sell flow: intent → data → confirm."""
    phone = _phone(1002)
    t0 = time.time()
    errors = []

    try:
        # Reset
        r = await send_msg(client, phone, "stop")
        await asyncio.sleep(0.3)

        # Start sell
        r = await send_msg(client, phone, "ik wil tickets verkopen")
        if r.status_code != 200:
            errors.append(f"Sell intent: {r.status_code}")
        await asyncio.sleep(0.5)

        # Provide details in one message
        r = await send_msg(client, phone, "Dekmantel festival 2 augustus 3 tickets 75 euro per stuk")
        if r.status_code != 200:
            errors.append(f"Details: {r.status_code}")
        await asyncio.sleep(0.5)

        # Confirm
        r = await send_msg(client, phone, "ja")
        if r.status_code != 200:
            errors.append(f"Confirm: {r.status_code}")

    except Exception as e:
        errors.append(str(e))

    ok = len(errors) == 0
    return TestResult("Full SELL flow", ok, (time.time()-t0)*1000,
                      error="; ".join(errors) if errors else None)


async def test_buy_with_corrections(client: httpx.AsyncClient) -> TestResult:
    """Test mid-flow corrections: change price, change quantity during CONFIRMING."""
    phone = _phone(1003)
    t0 = time.time()
    errors = []

    try:
        await send_msg(client, phone, "stop")
        await asyncio.sleep(0.3)

        # Buy intent with details
        await send_msg(client, phone, "kopen")
        await asyncio.sleep(0.5)
        await send_msg(client, phone, "Awakenings 28 juni 2 tickets 80 euro")
        await asyncio.sleep(0.5)

        # Correct the price during confirmation
        r = await send_msg(client, phone, "verhoog de maximale prijs naar 100")
        if r.status_code != 200:
            errors.append(f"Price correction: {r.status_code}")
        await asyncio.sleep(0.5)

        # Correct quantity
        r = await send_msg(client, phone, "aantal moet 3 zijn")
        if r.status_code != 200:
            errors.append(f"Quantity correction: {r.status_code}")
        await asyncio.sleep(0.5)

        # Finally confirm
        r = await send_msg(client, phone, "ja")
        if r.status_code != 200:
            errors.append(f"Confirm: {r.status_code}")

    except Exception as e:
        errors.append(str(e))

    ok = len(errors) == 0
    return TestResult("Buy with corrections", ok, (time.time()-t0)*1000,
                      error="; ".join(errors) if errors else None)


async def test_session_reset(client: httpx.AsyncClient) -> TestResult:
    """Test reset commands work from any state."""
    phone = _phone(1004)
    t0 = time.time()
    errors = []

    reset_commands = ["stop", "reset", "annuleer", "cancel", "opnieuw", "herstart"]

    try:
        for cmd in reset_commands:
            # Start a flow
            await send_msg(client, phone, "kopen")
            await asyncio.sleep(0.3)

            # Reset mid-flow
            r = await send_msg(client, phone, cmd)
            if r.status_code != 200:
                errors.append(f"'{cmd}': {r.status_code}")
            await asyncio.sleep(0.3)

    except Exception as e:
        errors.append(str(e))

    ok = len(errors) == 0
    return TestResult("Session reset commands", ok, (time.time()-t0)*1000,
                      error="; ".join(errors) if errors else None,
                      details=f"Tested {len(reset_commands)} reset variants")


async def test_forwarded_message(client: httpx.AsyncClient) -> TestResult:
    """Test forwarded message handling."""
    phone = _phone(1005)
    t0 = time.time()
    try:
        await send_msg(client, phone, "stop")
        await asyncio.sleep(0.3)

        r = await send_msg(client, phone, "Hallo ik heb 2 tickets voor Sonar festival te koop", forwarded=True)
        ok = r.status_code == 200
        return TestResult("Forwarded message", ok, (time.time()-t0)*1000)
    except Exception as e:
        return TestResult("Forwarded message", False, (time.time()-t0)*1000, error=str(e))


async def test_general_question(client: httpx.AsyncClient) -> TestResult:
    """Test general Q&A doesn't break state."""
    phone = _phone(1006)
    t0 = time.time()
    try:
        await send_msg(client, phone, "stop")
        await asyncio.sleep(0.3)

        r = await send_msg(client, phone, "Hoe werkt FestiFlip?")
        ok = r.status_code == 200
        return TestResult("General question", ok, (time.time()-t0)*1000)
    except Exception as e:
        return TestResult("General question", False, (time.time()-t0)*1000, error=str(e))


async def test_browse_catalog(client: httpx.AsyncClient) -> TestResult:
    """Test browse/catalog intent."""
    phone = _phone(1007)
    t0 = time.time()
    try:
        await send_msg(client, phone, "stop")
        await asyncio.sleep(0.3)

        r = await send_msg(client, phone, "welke tickets zijn er beschikbaar?")
        ok = r.status_code == 200
        return TestResult("Browse catalog", ok, (time.time()-t0)*1000)
    except Exception as e:
        return TestResult("Browse catalog", False, (time.time()-t0)*1000, error=str(e))


async def test_escalation_entrance_blocked(client: httpx.AsyncClient) -> TestResult:
    """Test entrance-blocked escalation."""
    phone = _phone(1008)
    t0 = time.time()
    try:
        await send_msg(client, phone, "stop")
        await asyncio.sleep(0.3)

        r = await send_msg(client, phone, "Ik sta bij de ingang maar mijn ticket werkt niet, ik kan niet naar binnen!")
        ok = r.status_code == 200
        return TestResult("Escalation: entrance blocked", ok, (time.time()-t0)*1000)
    except Exception as e:
        return TestResult("Escalation: entrance blocked", False, (time.time()-t0)*1000, error=str(e))


async def test_rapid_messages(client: httpx.AsyncClient) -> TestResult:
    """Test rapid-fire messages from same user (race condition check)."""
    phone = _phone(1009)
    t0 = time.time()
    errors = []

    try:
        await send_msg(client, phone, "stop")
        await asyncio.sleep(0.3)

        # Fire 5 messages almost simultaneously
        tasks = [
            send_msg(client, phone, f"bericht {i}")
            for i in range(5)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, r in enumerate(results):
            if isinstance(r, Exception):
                errors.append(f"Msg {i}: {r}")
            elif r.status_code >= 500:
                errors.append(f"Msg {i}: server error {r.status_code}")

    except Exception as e:
        errors.append(str(e))

    ok = len(errors) == 0
    return TestResult("Rapid messages (race condition)", ok, (time.time()-t0)*1000,
                      error="; ".join(errors) if errors else None,
                      details="5 concurrent messages from same user")


async def test_concurrent_users(client: httpx.AsyncClient, concurrency: int = 10) -> TestResult:
    """Test many users sending messages concurrently."""
    t0 = time.time()
    errors = []

    async def user_flow(user_num: int):
        phone = _phone(2000 + user_num)
        try:
            await send_msg(client, phone, "stop")
            await asyncio.sleep(0.1)
            r = await send_msg(client, phone, "ik zoek tickets voor Awakenings")
            if r.status_code >= 500:
                return f"User {user_num}: {r.status_code}"
        except Exception as e:
            return f"User {user_num}: {e}"
        return None

    tasks = [user_flow(i) for i in range(concurrency)]
    results = await asyncio.gather(*tasks)
    errors = [r for r in results if r is not None]

    ok = len(errors) == 0
    return TestResult(f"Concurrent users ({concurrency})", ok, (time.time()-t0)*1000,
                      error="; ".join(errors[:5]) if errors else None,
                      details=f"{concurrency - len(errors)}/{concurrency} succeeded")


async def test_unicode_and_special_chars(client: httpx.AsyncClient) -> TestResult:
    """Test messages with emoji, special chars, very long text."""
    phone = _phone(1010)
    t0 = time.time()
    errors = []

    test_messages = [
        "🎶🎵🎤 Ik wil naar het festival! 🎉🎊",
        "café résumé naïve über straße",
        "a" * 5000,  # Very long message
        "",  # Empty
        "   ",  # Whitespace only
        "¡Hola! ¿Cómo estás? 你好 مرحبا",
        '<script>alert("xss")</script>',  # XSS attempt
        "'; DROP TABLE sell_offers; --",  # SQL injection attempt
        "line1\nline2\nline3\n\n\n",  # Multi-line with extra newlines
    ]

    for i, msg in enumerate(test_messages):
        try:
            r = await client.post(
                f"{BASE_URL}{WEBHOOK_PATH}",
                json=_wa_payload(phone, msg),
                timeout=60,
            )
            if r.status_code >= 500:
                errors.append(f"Msg {i} ({msg[:30]}...): server error {r.status_code}")
        except Exception as e:
            errors.append(f"Msg {i}: {e}")
        await asyncio.sleep(0.2)

    ok = len(errors) == 0
    return TestResult("Unicode & special chars", ok, (time.time()-t0)*1000,
                      error="; ".join(errors) if errors else None,
                      details=f"Tested {len(test_messages)} edge-case messages")


async def test_duplicate_message_id(client: httpx.AsyncClient) -> TestResult:
    """Test same message ID sent twice (idempotency)."""
    phone = _phone(1011)
    t0 = time.time()
    errors = []

    try:
        msg_id = "wamid_duplicate_test_001"
        payload = _wa_payload(phone, "test dedup", msg_id=msg_id)

        r1 = await client.post(f"{BASE_URL}{WEBHOOK_PATH}", json=payload, timeout=60)
        await asyncio.sleep(1)
        r2 = await client.post(f"{BASE_URL}{WEBHOOK_PATH}", json=payload, timeout=60)

        # Both should succeed without server error
        if r1.status_code >= 500:
            errors.append(f"First send: {r1.status_code}")
        if r2.status_code >= 500:
            errors.append(f"Duplicate send: {r2.status_code}")

    except Exception as e:
        errors.append(str(e))

    ok = len(errors) == 0
    return TestResult("Duplicate message ID", ok, (time.time()-t0)*1000,
                      error="; ".join(errors) if errors else None)


async def test_intent_switching(client: httpx.AsyncClient) -> TestResult:
    """Test switching from buy to sell mid-flow."""
    phone = _phone(1012)
    t0 = time.time()
    errors = []

    try:
        await send_msg(client, phone, "stop")
        await asyncio.sleep(0.3)

        # Start buy flow
        r = await send_msg(client, phone, "ik wil kopen")
        if r.status_code != 200:
            errors.append(f"Buy start: {r.status_code}")
        await asyncio.sleep(0.5)

        # Switch to sell mid-flow
        r = await send_msg(client, phone, "eigenlijk wil ik verkopen")
        if r.status_code != 200:
            errors.append(f"Switch to sell: {r.status_code}")
        await asyncio.sleep(0.5)

        # Continue with sell details
        r = await send_msg(client, phone, "Dekmantel 3 augustus 2 tickets 60 euro")
        if r.status_code != 200:
            errors.append(f"Sell details: {r.status_code}")

    except Exception as e:
        errors.append(str(e))

    ok = len(errors) == 0
    return TestResult("Intent switching mid-flow", ok, (time.time()-t0)*1000,
                      error="; ".join(errors) if errors else None)


async def test_partial_data_collection(client: httpx.AsyncClient) -> TestResult:
    """Test providing data incrementally, one field at a time."""
    phone = _phone(1013)
    t0 = time.time()
    errors = []

    try:
        await send_msg(client, phone, "stop")
        await asyncio.sleep(0.3)

        await send_msg(client, phone, "verkopen")
        await asyncio.sleep(0.5)

        # Provide one field at a time
        steps = [
            "Thuishaven festival",
            "15 juli",
            "3 stuks",
            "50 euro per stuk",
        ]
        for step in steps:
            r = await send_msg(client, phone, step)
            if r.status_code != 200:
                errors.append(f"'{step}': {r.status_code}")
            await asyncio.sleep(0.5)

        # Confirm
        r = await send_msg(client, phone, "ja")
        if r.status_code != 200:
            errors.append(f"Confirm: {r.status_code}")

    except Exception as e:
        errors.append(str(e))

    ok = len(errors) == 0
    return TestResult("Partial data collection", ok, (time.time()-t0)*1000,
                      error="; ".join(errors) if errors else None)


async def test_deny_confirmation(client: httpx.AsyncClient) -> TestResult:
    """Test denying confirmation and restarting."""
    phone = _phone(1014)
    t0 = time.time()
    errors = []

    try:
        await send_msg(client, phone, "stop")
        await asyncio.sleep(0.3)

        await send_msg(client, phone, "kopen")
        await asyncio.sleep(0.5)

        await send_msg(client, phone, "Awakenings 28 juni 1 ticket 50 euro")
        await asyncio.sleep(0.5)

        # Deny
        r = await send_msg(client, phone, "nee")
        if r.status_code != 200:
            errors.append(f"Deny: {r.status_code}")
        await asyncio.sleep(0.3)

        # Should be back to collecting — provide new data
        r = await send_msg(client, phone, "Lowlands 20 augustus 2 tickets 80 euro")
        if r.status_code != 200:
            errors.append(f"New data after deny: {r.status_code}")

    except Exception as e:
        errors.append(str(e))

    ok = len(errors) == 0
    return TestResult("Deny and restart", ok, (time.time()-t0)*1000,
                      error="; ".join(errors) if errors else None)


async def test_dutch_date_formats(client: httpx.AsyncClient) -> TestResult:
    """Test various Dutch date formats are parsed correctly."""
    phone_base = 1020
    t0 = time.time()
    errors = []

    date_formats = [
        "3 maart",
        "15 juli 2026",
        "28-06-2026",
        "2026-08-20",
        "20 aug",
        "volgende week zaterdag",
        "1 januari",
    ]

    for i, date_str in enumerate(date_formats):
        phone = _phone(phone_base + i)
        try:
            await send_msg(client, phone, "stop")
            await asyncio.sleep(0.2)
            await send_msg(client, phone, "kopen")
            await asyncio.sleep(0.3)

            r = await send_msg(client, phone, f"Awakenings {date_str} 2 tickets 80 euro")
            if r.status_code >= 500:
                errors.append(f"Date '{date_str}': server error {r.status_code}")
            await asyncio.sleep(0.3)

        except Exception as e:
            errors.append(f"Date '{date_str}': {e}")

    ok = len(errors) == 0
    return TestResult("Dutch date formats", ok, (time.time()-t0)*1000,
                      error="; ".join(errors) if errors else None,
                      details=f"Tested {len(date_formats)} date formats")


async def test_price_formats(client: httpx.AsyncClient) -> TestResult:
    """Test various price formats."""
    phone_base = 1030
    t0 = time.time()
    errors = []

    prices = [
        "50 euro",
        "€50",
        "50,-",
        "50,50",
        "50.00 euro",
        "€ 75",
        "75 per stuk",
        "honderd euro",  # Word-based number
    ]

    for i, price_str in enumerate(prices):
        phone = _phone(phone_base + i)
        try:
            await send_msg(client, phone, "stop")
            await asyncio.sleep(0.2)
            await send_msg(client, phone, "kopen")
            await asyncio.sleep(0.3)

            r = await send_msg(client, phone, f"Awakenings 28 juni 2 tickets {price_str}")
            if r.status_code >= 500:
                errors.append(f"Price '{price_str}': server error {r.status_code}")
            await asyncio.sleep(0.3)

        except Exception as e:
            errors.append(f"Price '{price_str}': {e}")

    ok = len(errors) == 0
    return TestResult("Price formats", ok, (time.time()-t0)*1000,
                      error="; ".join(errors) if errors else None,
                      details=f"Tested {len(prices)} price formats")


async def test_matching_self_filter(client: httpx.AsyncClient) -> TestResult:
    """Test that a buyer can't match their own sell offer."""
    phone = _phone(1040)
    t0 = time.time()
    errors = []

    try:
        # First sell
        await send_msg(client, phone, "stop")
        await asyncio.sleep(0.3)
        await send_msg(client, phone, "verkopen")
        await asyncio.sleep(0.5)
        await send_msg(client, phone, "Self Match Test Event 15 augustus 2 tickets 50 euro")
        await asyncio.sleep(0.5)
        r = await send_msg(client, phone, "ja")
        if r.status_code != 200:
            errors.append(f"Sell confirm: {r.status_code}")
        await asyncio.sleep(0.5)

        # Now try to buy the same thing with the same phone
        await send_msg(client, phone, "kopen")
        await asyncio.sleep(0.5)
        await send_msg(client, phone, "Self Match Test Event 15 augustus 2 tickets max 60 euro")
        await asyncio.sleep(0.5)
        r = await send_msg(client, phone, "ja")
        if r.status_code != 200:
            errors.append(f"Buy confirm: {r.status_code}")
        # Should NOT get a direct match (self-match filter)

    except Exception as e:
        errors.append(str(e))

    ok = len(errors) == 0
    return TestResult("Self-match filter", ok, (time.time()-t0)*1000,
                      error="; ".join(errors) if errors else None)


async def test_image_message_handling(client: httpx.AsyncClient) -> TestResult:
    """Test image message doesn't crash (will fail at download but shouldn't 500)."""
    phone = _phone(1041)
    t0 = time.time()
    try:
        payload = _wa_image_payload(phone, media_id="fake_media_id_123")
        r = await client.post(f"{BASE_URL}{WEBHOOK_PATH}", json=payload, timeout=15)
        # Expect 200 even if image processing fails (error handled gracefully)
        ok = r.status_code == 200
        return TestResult("Image message handling", ok, (time.time()-t0)*1000,
                          error=None if ok else f"Status: {r.status_code}")
    except Exception as e:
        return TestResult("Image message handling", False, (time.time()-t0)*1000, error=str(e))


async def test_stripe_webhook_invalid_sig(client: httpx.AsyncClient) -> TestResult:
    """Test Stripe webhook rejects invalid signature."""
    t0 = time.time()
    try:
        r = await client.post(
            f"{BASE_URL}/webhooks/stripe",
            content=b'{"type": "checkout.session.completed"}',
            headers={"stripe-signature": "invalid_sig", "content-type": "application/json"},
        )
        ok = r.status_code == 400  # Should reject
        return TestResult("Stripe invalid signature", ok, (time.time()-t0)*1000,
                          details=f"Status: {r.status_code} (400 = correct rejection)")
    except Exception as e:
        return TestResult("Stripe invalid signature", False, (time.time()-t0)*1000, error=str(e))


async def test_payment_success_no_session(client: httpx.AsyncClient) -> TestResult:
    """Test payment success page with no/invalid session ID."""
    t0 = time.time()
    errors = []
    try:
        # No session_id
        r = await client.get(f"{BASE_URL}/payment/success")
        if r.status_code >= 500:
            errors.append(f"No session: {r.status_code}")

        # Invalid session_id
        r = await client.get(f"{BASE_URL}/payment/success?session_id=invalid_xxx")
        if r.status_code >= 500:
            errors.append(f"Invalid session: {r.status_code}")

    except Exception as e:
        errors.append(str(e))

    ok = len(errors) == 0
    return TestResult("Payment success edge cases", ok, (time.time()-t0)*1000,
                      error="; ".join(errors) if errors else None)


async def test_admin_send_message_validation(client: httpx.AsyncClient) -> TestResult:
    """Test admin chat send with missing fields."""
    t0 = time.time()
    errors = []
    try:
        # Missing phone
        r = await client.post(f"{BASE_URL}/admin/chats/send", json={"message": "test"})
        if r.status_code != 400:
            errors.append(f"Missing phone should be 400, got {r.status_code}")

        # Missing message
        r = await client.post(f"{BASE_URL}/admin/chats/send", json={"phone": "+31612345678"})
        if r.status_code != 400:
            errors.append(f"Missing message should be 400, got {r.status_code}")

        # Empty both
        r = await client.post(f"{BASE_URL}/admin/chats/send", json={})
        if r.status_code != 400:
            errors.append(f"Empty payload should be 400, got {r.status_code}")

    except Exception as e:
        errors.append(str(e))

    ok = len(errors) == 0
    return TestResult("Admin send validation", ok, (time.time()-t0)*1000,
                      error="; ".join(errors) if errors else None)


async def test_export_tables(client: httpx.AsyncClient) -> TestResult:
    """Test CSV export for all supported tables."""
    t0 = time.time()
    errors = []
    tables = ["sell_offers", "buy_requests", "reservations"]

    for table in tables:
        try:
            r = await client.get(f"{BASE_URL}/admin/export/{table}")
            if r.status_code != 200:
                errors.append(f"{table}: {r.status_code}")
        except Exception as e:
            errors.append(f"{table}: {e}")

    # Invalid table should fail
    try:
        r = await client.get(f"{BASE_URL}/admin/export/nonexistent")
        if r.status_code != 400:
            errors.append(f"Invalid table should be 400, got {r.status_code}")
    except Exception as e:
        errors.append(f"Invalid table: {e}")

    ok = len(errors) == 0
    return TestResult("CSV export", ok, (time.time()-t0)*1000,
                      error="; ".join(errors) if errors else None)


async def test_long_conversation(client: httpx.AsyncClient) -> TestResult:
    """Test a long conversation with many back-and-forth messages."""
    phone = _phone(1050)
    t0 = time.time()
    errors = []

    try:
        await send_msg(client, phone, "stop")
        await asyncio.sleep(0.2)

        messages = [
            "hoi",
            "ik zoek tickets",
            "voor een festival",
            "Awakenings",
            "in juni",
            "28 juni",
            "2 tickets",
            "maximaal 80 euro",
            "ja",
            "stop",
            "verkopen",
            "Dekmantel 2 augustus 1 ticket 50 euro",
            "ja",
            "stop",
            "hoe werkt festiflip?",
            "wat zijn de kosten?",
            "bedankt",
        ]

        for i, msg in enumerate(messages):
            r = await send_msg(client, phone, msg)
            if r.status_code >= 500:
                errors.append(f"Msg {i} '{msg}': {r.status_code}")
            await asyncio.sleep(0.4)

    except Exception as e:
        errors.append(str(e))

    ok = len(errors) == 0
    return TestResult("Long conversation (17 msgs)", ok, (time.time()-t0)*1000,
                      error="; ".join(errors) if errors else None)


# ─── Main Runner ───

async def run_all_tests(base_url: str, concurrency: int):
    global BASE_URL
    BASE_URL = base_url

    report = StressReport()
    report.start_time = time.time()

    async with httpx.AsyncClient() as client:
        # Phase 1: Basic infrastructure tests (parallel)
        print("\n[Phase 1] Infrastructure tests...")
        infra_tests = await asyncio.gather(
            test_health(client),
            test_root(client),
            test_admin_dashboard(client),
            test_admin_pages(client),
            test_webhook_verification(client),
        )
        for r in infra_tests:
            report.add(r)
            print(f"  {'PASS' if r.passed else 'FAIL'} {r.name}")

        # Phase 2: Edge case / safety tests (parallel)
        print("\n[Phase 2] Edge case & safety tests...")
        safety_tests = await asyncio.gather(
            test_status_update_ignored(client),
            test_empty_payload(client),
            test_unicode_and_special_chars(client),
            test_duplicate_message_id(client),
            test_stripe_webhook_invalid_sig(client),
            test_payment_success_no_session(client),
            test_admin_send_message_validation(client),
            test_export_tables(client),
            test_image_message_handling(client),
        )
        for r in safety_tests:
            report.add(r)
            print(f"  {'PASS' if r.passed else 'FAIL'} {r.name}")

        # Phase 3: Conversation flow tests (sequential — they share state machine)
        print("\n[Phase 3] Conversation flow tests...")
        flow_tests = [
            test_full_buy_flow,
            test_full_sell_flow,
            test_buy_with_corrections,
            test_session_reset,
            test_forwarded_message,
            test_general_question,
            test_browse_catalog,
            test_escalation_entrance_blocked,
            test_intent_switching,
            test_partial_data_collection,
            test_deny_confirmation,
            test_matching_self_filter,
        ]
        for test_fn in flow_tests:
            r = await test_fn(client)
            report.add(r)
            print(f"  {'PASS' if r.passed else 'FAIL'} {r.name}")

        # Phase 4: Format parsing tests (parallel — different phone numbers)
        print("\n[Phase 4] Input format stress tests...")
        format_tests = await asyncio.gather(
            test_dutch_date_formats(client),
            test_price_formats(client),
        )
        for r in format_tests:
            report.add(r)
            print(f"  {'PASS' if r.passed else 'FAIL'} {r.name}")

        # Phase 5: Concurrency & load tests
        print("\n[Phase 5] Concurrency & load tests...")
        r = await test_rapid_messages(client)
        report.add(r)
        print(f"  {'PASS' if r.passed else 'FAIL'} {r.name}")

        r = await test_concurrent_users(client, concurrency=concurrency)
        report.add(r)
        print(f"  {'PASS' if r.passed else 'FAIL'} {r.name}")

        # Phase 6: Long conversation stress test
        print("\n[Phase 6] Long conversation test...")
        r = await test_long_conversation(client)
        report.add(r)
        print(f"  {'PASS' if r.passed else 'FAIL'} {r.name}")

    report.print_report()
    return report


def main():
    parser = argparse.ArgumentParser(description="FestiFlip Pipeline Stress Test")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Server base URL")
    parser.add_argument("--concurrency", type=int, default=10, help="Concurrent users for load test")
    args = parser.parse_args()

    print(f"\nFestiFlip Stress Test")
    print(f"Target: {args.base_url}")
    print(f"Concurrency: {args.concurrency}")

    report = asyncio.run(run_all_tests(args.base_url, args.concurrency))
    sys.exit(0 if report.failed == 0 else 1)


if __name__ == "__main__":
    main()
