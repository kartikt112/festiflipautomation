"""Tests for entity extraction and validation."""

import pytest
from app.ai.extractor import validate_entities, normalize_entities, merge_collected_data


class TestValidateEntities:
    def test_buy_request_complete(self):
        entities = {"event_name": "Lowlands", "event_date": "2026-08-15", "quantity": 2, "max_price": 100}
        missing = validate_entities("BUY_REQUEST", entities)
        assert missing == []

    def test_buy_request_missing_event(self):
        entities = {"quantity": 2}
        missing = validate_entities("BUY_REQUEST", entities)
        assert "event_name" in missing

    def test_sell_offer_complete(self):
        entities = {"event_name": "Lowlands", "event_date": "2026-08-15", "quantity": 2, "price_per_ticket": 80}
        missing = validate_entities("SELL_OFFER", entities)
        assert missing == []

    def test_sell_offer_missing_price(self):
        entities = {"event_name": "Lowlands", "quantity": 2}
        missing = validate_entities("SELL_OFFER", entities)
        assert "price_per_ticket" in missing


class TestNormalizeEntities:
    def test_normalize_quantity(self):
        result = normalize_entities({"quantity": "3"})
        assert result["quantity"] == 3

    def test_normalize_price(self):
        result = normalize_entities({"price_per_ticket": "89.50"})
        assert result["price_per_ticket"] == 89.50


class TestMergeData:
    def test_merge_new_fields(self):
        existing = {"event_name": "Lowlands"}
        new = {"quantity": 2, "max_price": 100}
        result = merge_collected_data(existing, new)
        assert result == {"event_name": "Lowlands", "quantity": 2, "max_price": 100}

    def test_no_overwrite(self):
        existing = {"event_name": "Lowlands"}
        new = {"event_name": "Pinkpop"}
        result = merge_collected_data(existing, new)
        assert result["event_name"] == "Lowlands"
