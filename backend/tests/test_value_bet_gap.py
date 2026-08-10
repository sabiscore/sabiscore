"""Tests for value-bet data_gap signalling — Gap 1 coverage."""

from __future__ import annotations


from src.api.endpoints.value_bets import ValueBetListResponse, ValueBetFilter


# ── Schema tests (no DB needed) ──────────────────────────────────────────────

def test_value_bet_list_response_schema_has_data_gap():
    """ValueBetListResponse must expose a data_gap boolean field."""
    assert "data_gap" in ValueBetListResponse.model_fields


def test_value_bet_list_response_data_gap_defaults_false():
    """data_gap must default to False (no gap assumed unless detected)."""
    response = ValueBetListResponse(items=[], total=0)
    assert response.data_gap is False


def test_value_bet_list_response_data_gap_true():
    """data_gap=True must be constructible and serialise correctly."""
    response = ValueBetListResponse(items=[], total=0, data_gap=True)
    assert response.data_gap is True
    payload = response.model_dump()
    assert payload["data_gap"] is True


def test_value_bet_list_response_serialisable():
    """ValueBetListResponse with empty items must be JSON-safe."""
    import json
    response = ValueBetListResponse(items=[], total=0, data_gap=True)
    json.dumps(response.model_dump(mode="json"))


def test_value_bet_list_response_total_matches_items():
    """total field must reflect the count of items."""
    response = ValueBetListResponse(items=[], total=0, data_gap=False)
    assert response.total == 0


def test_value_bet_filter_schema():
    """ValueBetFilter must accept default values without raising."""
    f = ValueBetFilter()
    assert f.min_edge >= 0
    assert 0 <= f.min_confidence <= 1
    assert f.max_results >= 1


def test_value_bet_list_response_with_gap_true_and_empty_items():
    """Canonical DATA_GAP state: data_gap=True, items=[], total=0."""
    response = ValueBetListResponse(items=[], total=0, data_gap=True)
    assert response.items == []
    assert response.total == 0
    assert response.data_gap is True


def test_value_bet_list_response_with_gap_false_and_empty_items():
    """Legitimate empty state: data_gap=False, items=[], total=0."""
    response = ValueBetListResponse(items=[], total=0, data_gap=False)
    assert response.items == []
    assert response.total == 0
    assert response.data_gap is False
