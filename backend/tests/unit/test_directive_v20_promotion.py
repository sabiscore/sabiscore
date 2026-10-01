"""V21 recovery checks occupying the four V20 integration-gate slots."""

import inspect
from pathlib import Path

import pytest

from backend.serving.feature_bridge import FeatureBridge, FeatureBridgeRejected
from backend.scripts.v21_market_protocol import (
    PROTOCOL,
    validate_market_independent_feature_names,
)
from backend.workers.c6_live_collector import C6LiveCollector, LIVE_CAPTURE_TRIGGER


ROOT = Path(__file__).resolve().parents[3]


def test_gate_37_feature_bridge_rejects_unproven_parent_fallback():
    bridge = FeatureBridge(schema_id="apex_v1_89")
    with pytest.raises(FeatureBridgeRejected, match="no semantic evidence"):
        bridge.get_serving_features("fixture-1", [0.0] * 89)


def test_gate_38_candidate_m_excludes_market_derived_features():
    assert validate_market_independent_feature_names(
        ["elo_difference", "home_weighted_ppg"]
    )
    with pytest.raises(ValueError, match="market-derived"):
        validate_market_independent_feature_names(
            ["elo_difference", "closing_market_prob_home"]
        )
    assert PROTOCOL["candidate_tracks"]["Candidate-M"]["market_inputs_allowed"] is False


def test_gate_39_c6_settlement_uses_persisted_live_rows():
    collector = C6LiveCollector()
    assert collector.target == 200
    assert inspect.iscoroutinefunction(collector.settle_predictions)
    assert not hasattr(collector, "settled_count")
    assert not hasattr(collector, "settle_prediction")
    source = (ROOT / "backend/workers/c6_live_collector.py").read_text(
        encoding="utf-8"
    )
    assert "get_clv_records" in source
    assert "get_settled_predictions" in source
    assert "replay_n" in source


def test_gate_40_c6_writer_is_frozen_and_capture_is_pre_kickoff():
    assert LIVE_CAPTURE_TRIGGER == "interactive_full_analysis"
    assert PROTOCOL["c6"]["capture_trigger"] == LIVE_CAPTURE_TRIGGER
    capture_source = (
        ROOT / "backend/src/services/prediction_capture_service.py"
    ).read_text(encoding="utf-8")
    assert PROTOCOL["c6"]["capture_trigger"] == LIVE_CAPTURE_TRIGGER
    assert 'Match.status == "scheduled"' in capture_source
    assert "Match.match_date >= current + CAPTURE_WINDOW_START" in capture_source
    assert "Match.match_date <= current + CAPTURE_WINDOW_END" in capture_source
    assert "capture_trigger=capture_trigger" in capture_source
