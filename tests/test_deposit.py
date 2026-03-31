"""Tests for deposit calculation logic."""

import pytest
from decimal import Decimal
from app.services.deposit import calculate_deposit


class TestDepositCalculation:
    """Test the 7.5% commission with €5 minimum per ticket."""

    def test_standard_deposit(self):
        """€100 ticket → 7.5% = €7.50 (above minimum)."""
        result = calculate_deposit(Decimal("100"), 1)
        assert result.deposit_amount == Decimal("7.50")
        assert result.remaining_amount == Decimal("92.50")
        assert result.minimum_applied is False

    def test_minimum_applies(self):
        """€60 ticket → 7.5% = €4.50 < €5 minimum → deposit = €5."""
        result = calculate_deposit(Decimal("60"), 1)
        assert result.deposit_amount == Decimal("5.00")
        assert result.remaining_amount == Decimal("55.00")
        assert result.minimum_applied is True

    def test_multiple_tickets_minimum(self):
        """2 × €60 → 7.5% = €9.00, minimum = €10 → deposit = €10."""
        result = calculate_deposit(Decimal("60"), 2)
        assert result.deposit_amount == Decimal("10.00")
        assert result.remaining_amount == Decimal("110.00")
        assert result.minimum_applied is True
        assert result.total_price == Decimal("120.00")

    def test_multiple_tickets_standard(self):
        """2 × €100 → 7.5% = €15 > €10 minimum → deposit = €15."""
        result = calculate_deposit(Decimal("100"), 2)
        assert result.deposit_amount == Decimal("15.00")
        assert result.remaining_amount == Decimal("185.00")
        assert result.minimum_applied is False

    def test_exact_minimum_boundary(self):
        """€66.67 → 7.5% ≈ €5.00, exactly at minimum."""
        result = calculate_deposit(Decimal("66.67"), 1)
        assert result.deposit_amount >= Decimal("5.00")

    def test_high_price_ticket(self):
        """€500 ticket → 7.5% = €37.50."""
        result = calculate_deposit(Decimal("500"), 1)
        assert result.deposit_amount == Decimal("37.50")
        assert result.minimum_applied is False

    def test_total_adds_up(self):
        """Deposit + remaining must always equal total price."""
        for price in [30, 50, 60, 66.67, 100, 200, 500]:
            for qty in [1, 2, 3, 5]:
                result = calculate_deposit(Decimal(str(price)), qty)
                assert result.deposit_amount + result.remaining_amount == result.total_price
