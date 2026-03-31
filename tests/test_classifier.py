"""Tests for Dutch keyword intent classifier."""

import pytest
from app.ai.rules import (
    classify_by_rules,
    BUY_REQUEST, SELL_OFFER, STATUS_CHECK,
    PAYMENT_CONFIRMATION, SUPPORT, UNKNOWN,
)


class TestDutchKeywordClassifier:
    """Test rule-based classification with Dutch messages."""

    def test_buy_intent_zoek(self):
        intent, conf = classify_by_rules("Ik zoek 2 tickets voor Lowlands")
        assert intent == BUY_REQUEST
        assert conf > 0.4

    def test_buy_intent_kopen(self):
        intent, conf = classify_by_rules("Wil kopen 3 tickets")
        assert intent == BUY_REQUEST

    def test_buy_intent_nodig(self):
        intent, conf = classify_by_rules("Ik heb tickets nodig voor het festival")
        assert intent == BUY_REQUEST

    def test_sell_intent_verkoop(self):
        intent, conf = classify_by_rules("Ik verkoop mijn ticket voor Lowlands")
        assert intent == SELL_OFFER

    def test_sell_intent_te_koop(self):
        intent, conf = classify_by_rules("2 tickets te koop voor concert")
        assert intent == SELL_OFFER

    def test_sell_intent_beschikbaar(self):
        intent, conf = classify_by_rules("Heb nog tickets beschikbaar")
        assert intent == SELL_OFFER

    def test_status_check(self):
        intent, conf = classify_by_rules("Hoe staat het met mijn bestelling?")
        assert intent == STATUS_CHECK

    def test_payment_confirmation(self):
        intent, conf = classify_by_rules("Ik heb zojuist betaald via tikkie")
        assert intent == PAYMENT_CONFIRMATION

    def test_support_dispute(self):
        intent, conf = classify_by_rules("Ik heb een probleem, ticket niet ontvangen")
        assert intent == SUPPORT

    def test_unknown_message(self):
        intent, conf = classify_by_rules("Hallo")
        assert intent == UNKNOWN
        assert conf == 0.0

    def test_empty_message(self):
        intent, conf = classify_by_rules("")
        assert intent == UNKNOWN
        assert conf == 0.0
