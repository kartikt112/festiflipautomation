"""Tests for message templates."""

from decimal import Decimal
from app.message_templates.templates import (
    availability_message,
    deposit_payment_message,
    payment_received_message,
    reservation_expired_message,
    seller_confirmation_message,
    event_sale_broadcast,
    searching_broadcast,
    ask_missing_field,
)


class TestTemplates:
    def test_availability_message(self):
        msg = availability_message(3)
        assert "3 stuk(s) beschikbaar" in msg

    def test_deposit_payment_message(self):
        msg = deposit_payment_message(
            Decimal("10.00"), Decimal("110.00"), "https://stripe.com/pay/xyz"
        )
        assert "€10.00" in msg
        assert "€110.00" in msg
        assert "https://stripe.com/pay/xyz" in msg
        assert "Ticket aanbetaling" in msg

    def test_payment_received_has_seller_info(self):
        msg = payment_received_message("Jan Visser", "+31612345678")
        assert "Betaling ontvangen ✅" in msg
        assert "Jan Visser" in msg
        assert "+31612345678" in msg

    def test_seller_confirmation(self):
        msg = seller_confirmation_message()
        assert "7,5%" in msg
        assert "€5" in msg
        assert "verkoper" in msg

    def test_broadcast_no_seat_numbers(self):
        msg = event_sale_broadcast(
            "Lowlands", "15-08-2025", 2, Decimal("100.00"),
            section="Vak A", seat_info=""
        )
        assert "Lowlands" in msg
        assert "€100.00" in msg
        assert "Vak A" in msg

    def test_searching_broadcast(self):
        msg = searching_broadcast("Pinkpop", "20-06-2025", 4)
        assert "OP ZOEK" in msg
        assert "Pinkpop" in msg

    def test_ask_missing_field(self):
        msg = ask_missing_field("event_name")
        assert "evenement" in msg.lower()
