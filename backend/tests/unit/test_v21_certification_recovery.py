from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "backend"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

try:
    from backend.serving.feature_bridge import FeatureBridge, FeatureBridgeRejected
    import backend.serving.feature_bridge as feature_bridge_module
    from backend.scripts.v21_market_protocol import (
        PROTOCOL,
        compare_cohorts,
        evaluate_market_rows,
        protocol_sha256,
        validate_calibration_split,
        validate_market_independent_feature_names,
    )
    from backend.workers.c6_live_collector import C6LiveCollector, LIVE_CAPTURE_TRIGGER
except ModuleNotFoundError:
    from serving.feature_bridge import FeatureBridge, FeatureBridgeRejected
    import serving.feature_bridge as feature_bridge_module
    from scripts.v21_market_protocol import (
        PROTOCOL,
        compare_cohorts,
        evaluate_market_rows,
        protocol_sha256,
        validate_calibration_split,
        validate_market_independent_feature_names,
    )
    from workers.c6_live_collector import C6LiveCollector, LIVE_CAPTURE_TRIGGER



def test_feature_bridge_requires_semantic_lineage_and_freshness():
    bridge = FeatureBridge(schema_id="apex_v1_89")
    assert bridge.feature_dim == 89
    with pytest.raises(FeatureBridgeRejected, match="market-derived"):
        bridge.validate(
            features={"wrong": 1.0},
            feature_schema_id="apex_v1_89",
            schema_hash=bridge.schema_hash,
            feature_evidence={},
            feature_cutoff="2026-10-01T12:00:00Z",
        )


def test_feature_bridge_rejects_unproven_parent_vector():
    bridge = FeatureBridge(schema_id="apex_v1_89")
    with pytest.raises(FeatureBridgeRejected, match="no semantic evidence"):
        bridge.get_serving_features("fixture-1", [0.0] * 89)


def test_feature_bridge_checks_semantics_lineage_freshness_and_cutoff(monkeypatch):
    contract = {
        "feature_contract_sha256": "declared-test-contract-hash",
        "features": [
            {
                "feature_name": "elo_difference",
                "semantic_definition": "home Elo minus away Elo",
                "unit": "rating_points",
                "serving_source": "elo:fixture_snapshot",
            }
        ],
    }
    monkeypatch.setattr(
        feature_bridge_module, "build_feature_contract", lambda _: contract
    )
    bridge = FeatureBridge(schema_id="test_market_independent")
    assert bridge.schema_hash == contract["feature_contract_sha256"]
    cutoff = "2026-10-01T10:00:15Z"
    evidence = {
        "elo_difference": {
            "feature_name": "elo_difference",
            "source": "elo:fixture_snapshot",
            "semantics": "home Elo minus away Elo",
            "unit": "rating_points",
            "feature_timestamp": "2026-10-01T10:00:00Z",
            "effective_at": "2026-10-01T09:59:00Z",
            "max_age_seconds": 30,
        }
    }
    result = bridge.validate(
        features={"elo_difference": 12.5},
        feature_schema_id="test_market_independent",
        schema_hash=bridge.schema_hash,
        feature_evidence=evidence,
        feature_cutoff=cutoff,
    )
    assert result.values == (12.5,)

    wrong_lineage = {"elo_difference": {**evidence["elo_difference"], "source": "other"}}
    with pytest.raises(FeatureBridgeRejected, match="lineage mismatch"):
        bridge.validate(
            features={"elo_difference": 12.5},
            feature_schema_id="test_market_independent",
            schema_hash=bridge.schema_hash,
            feature_evidence=wrong_lineage,
            feature_cutoff=cutoff,
        )

    stale = {
        "elo_difference": {
            **evidence["elo_difference"],
            "feature_timestamp": "2026-10-01T09:59:00Z",
        }
    }
    with pytest.raises(FeatureBridgeRejected, match="stale"):
        bridge.validate(
            features={"elo_difference": 12.5},
            feature_schema_id="test_market_independent",
            schema_hash=bridge.schema_hash,
            feature_evidence=stale,
            feature_cutoff=cutoff,
        )

    lookahead = {
        "elo_difference": {
            **evidence["elo_difference"],
            "feature_timestamp": "2026-10-01T10:00:16Z",
        }
    }
    with pytest.raises(FeatureBridgeRejected, match="point-in-time cutoff"):
        bridge.validate(
            features={"elo_difference": 12.5},
            feature_schema_id="test_market_independent",
            schema_hash=bridge.schema_hash,
            feature_evidence=lookahead,
            feature_cutoff=cutoff,
        )


def test_canonical_inference_calls_candidate_bridge_without_replacing_incumbent():
    source = (ROOT / "backend/src/api/endpoints/full_analysis.py").read_text(encoding="utf-8")
    assert "FeatureBridge(schema_id=\"apex_v1_89\")" in source
    assert '"status": "WITHHELD"' in source
    assert "PredictionEngine()" in source


def test_c6_collector_is_persistent_and_marks_live_trigger():
    collector = C6LiveCollector()
    assert collector.target == 200
    assert LIVE_CAPTURE_TRIGGER == "interactive_full_analysis"
    assert inspect.iscoroutinefunction(collector.capture_pre_kickoff_predictions)
    assert inspect.iscoroutinefunction(collector.settle_predictions)
    assert not hasattr(collector, "settled_count")


def test_c6_is_bound_to_fastapi_lifecycle_capture_and_settlement_loops():
    source = (ROOT / "backend/src/api/main.py").read_text(encoding="utf-8")
    assert "_background_settlement_sync(app.state.c6_collector)" in source
    assert "c6_collector.capture_pre_kickoff_predictions" in source


def test_candidate_m_rejects_market_features():
    with pytest.raises(ValueError, match="market-derived"):
        validate_market_independent_feature_names(["elo_difference", "odds_drift_home"])
    assert validate_market_independent_feature_names(["elo_difference", "home_weighted_ppg"])


def test_calibration_population_must_be_disjoint_from_test_and_c6():
    validate_calibration_split(
        calibration_fixture_ids=["cal-1"], test_fixture_ids=["test-1"], c6_fixture_ids=["c6-1"]
    )
    with pytest.raises(ValueError, match="overlap"):
        validate_calibration_split(
            calibration_fixture_ids=["c6-1"], test_fixture_ids=["test-1"], c6_fixture_ids=["c6-1"]
        )


def test_opening_and_closing_market_comparisons_require_identical_cohorts():
    result = compare_cohorts(
        candidate_fixture_ids=["a", "b"], candidate_outcomes=[0, 2],
        market_fixture_ids=["a", "b"], market_outcomes=[0, 2],
        candidate_rps=0.19, market_rps=0.20, benchmark="closing_market",
    )
    assert result["gate_7"] == "PASS"
    assert result["market_blend_used_for_certification"] is False
    with pytest.raises(ValueError, match="cohorts/outcomes differ"):
        compare_cohorts(
            candidate_fixture_ids=["a"], candidate_outcomes=[0],
            market_fixture_ids=["b"], market_outcomes=[0],
            candidate_rps=0.19, market_rps=0.20, benchmark="closing_market",
        )


def test_market_evaluator_reports_opening_and_closing_separately():
    report = evaluate_market_rows([
        {
            "fixture_id": "f1",
            "outcome": 0,
            "candidate_m_probabilities": [0.6, 0.2, 0.2],
            "opening_market_probabilities": [0.5, 0.25, 0.25],
            "closing_market_probabilities": [0.55, 0.25, 0.20],
        }
    ])
    assert report["fixture_count"] == 1
    assert report["opening_market_rps"] != report["closing_market_rps"]
    assert report["market_blend_used_for_certification"] is False


def test_frozen_protocol_has_no_market_blend_certification_and_hash_is_stable():
    assert PROTOCOL["frozen"] is True
    assert PROTOCOL["gate_7"]["market_blend_is_certification_input"] is False
    assert len(protocol_sha256()) == 64


def test_existing_active_generation_remains_fail_closed():
    manifest = json.loads((ROOT / "backend/models/active_generation.json").read_text(encoding="utf-8"))
    assert manifest["promotion_state"] == "ACTIVE_FAIL_CLOSED"
    assert manifest["certification_state"] == "UNVERIFIED"


# Named runners keep the V21 41–60 matrix auditable. A passing check can confirm
# that a gate is correctly represented as blocked; it never means the empirical
# certification gate itself passed.
def test_gate_41_bridge_callsite():
    test_canonical_inference_calls_candidate_bridge_without_replacing_incumbent()


def test_gate_42_semantic_contract_blocks_candidate():
    report = json.loads((ROOT / "reports/research/v21-feature-integration.json").read_text())
    assert report["status"] == "BLOCKED"
    assert report["undeclared_semantic_contract_count"] > 0


def test_gate_43_freshness_is_required():
    bridge = FeatureBridge(schema_id="apex_v1_89")
    assert "max_age_seconds" in (ROOT / "backend/serving/feature_bridge.py").read_text()
    assert bridge.feature_dim == 89


def test_gate_44_capture_is_lifecycle_bound():
    test_c6_is_bound_to_fastapi_lifecycle_capture_and_settlement_loops()


def test_gate_45_settlement_is_lifecycle_bound():
    test_c6_is_bound_to_fastapi_lifecycle_capture_and_settlement_loops()


def test_gate_46_capture_is_idempotent_and_pre_kickoff():
    source = (ROOT / "backend/src/services/prediction_log_service.py").read_text()
    assert "require_scheduled_pre_kickoff" in source
    assert "capture.input_hash" in source


def test_gate_47_settlement_sample_comes_from_persisted_rows():
    source = (ROOT / "backend/workers/c6_live_collector.py").read_text()
    assert "get_clv_records" in source and "get_settled_predictions" in source
    assert "capture_trigger=LIVE_CAPTURE_TRIGGER" in source
    assert "settled_count" not in source


def test_gate_48_replay_does_not_count_as_live_c6():
    report = json.loads((ROOT / "reports/research/v21-c6-live-status.json").read_text())
    assert report["replay_n"] is None
    assert report["replay_included_in_live_n"] is False
    assert report["capture_trigger"] == LIVE_CAPTURE_TRIGGER


def test_gate_49_provider_integrity_is_not_overstated():
    report = json.loads((ROOT / "reports/evidence/v21-historical-market-provider.json").read_text())
    assert report["status"] == "UNVERIFIED"


def test_gate_50_pit_closing_quotes_are_pre_kickoff():
    source = (ROOT / "backend/src/repositories/fixtures.py").read_text()
    assert "MarketSnapshot.captured_at < Match.match_date" in source


def test_gate_51_comparison_requires_matching_cohorts():
    test_opening_and_closing_market_comparisons_require_identical_cohorts()


def test_gate_52_opening_and_closing_benchmarks_are_separate():
    report = evaluate_market_rows([{
        "fixture_id": "f1", "outcome": 1,
        "candidate_m_probabilities": [0.2, 0.6, 0.2],
        "opening_market_probabilities": [0.3, 0.4, 0.3],
        "closing_market_probabilities": [0.25, 0.5, 0.25],
    }])
    assert report["opening_is_separate_from_closing"] is True


def test_gate_53_market_blend_is_research_only():
    assert PROTOCOL["gate_7"]["market_blend_is_certification_input"] is False


def test_gate_54_candidate_m_has_no_market_inputs():
    test_candidate_m_rejects_market_features()


def test_gate_55_candidate_evaluation_is_not_inferred_from_artifact_presence():
    report = json.loads((ROOT / "reports/research/v21-market-evaluation.json").read_text())
    assert report["status"] == "BLOCKED_NO_V21_EMPIRICAL_COHORT_ARTIFACT"
    assert report["candidate_m"]["rps"] is None


def test_gate_56_calibration_split_is_independent():
    test_calibration_population_must_be_disjoint_from_test_and_c6()


def test_gate_57_regime_metrics_remain_unverified_until_run():
    report = json.loads((ROOT / "reports/research/v21-regime-performance.json").read_text())
    assert report["status"] == "NOT_RUN_NO_V21_OUT_OF_SAMPLE_PREDICTIONS"


def test_gate_58_shadow_validation_is_not_claimed_without_observations():
    report = json.loads((ROOT / "reports/research/v21-model-certification.json").read_text())
    assert report["gates"]["gate_58"] == "UNVERIFIED"


def test_gate_59_prediction_provenance_tracks_bridge_blocker():
    report = json.loads((ROOT / "reports/research/v21-feature-integration.json").read_text())
    assert report["live_bridge_callsite"].endswith("full_analysis.py")
    assert report["status"] == "BLOCKED"


def test_gate_60_canary_is_blocked_without_empirical_certification():
    report = json.loads((ROOT / "reports/release/v21-promotion-attestation.json").read_text())
    assert report["decision"] == "CERTIFICATION_BLOCKED"
    assert report["gate_7_v21_state"] == "NOT_RUN"


@pytest.mark.asyncio
async def test_clv_capture_tick_with_c6_collector(monkeypatch):
    from src.api.main import _clv_capture_tick

    mock_collector = MagicMock()
    mock_collector.capture_pre_kickoff_predictions = AsyncMock(
        return_value={"captured": 5}
    )
    mock_provider = MagicMock()
    mock_odds = MagicMock()

    monkeypatch.setattr(
        "src.services.clv_capture_service.run_clv_capture_pass", AsyncMock()
    )

    await _clv_capture_tick(
        provider=mock_provider,
        odds_service=mock_odds,
        c6_collector=mock_collector,
    )
    assert mock_collector.last_capture == {"captured": 5}
    mock_collector.capture_pre_kickoff_predictions.assert_awaited_once_with(
        odds_service=mock_odds
    )


@pytest.mark.asyncio
async def test_clv_capture_tick_handles_collector_exception(monkeypatch):
    from src.api.main import _clv_capture_tick

    mock_collector = MagicMock()
    mock_collector.capture_pre_kickoff_predictions = AsyncMock(
        side_effect=RuntimeError("collector err")
    )
    monkeypatch.setattr(
        "src.services.clv_capture_service.run_clv_capture_pass",
        AsyncMock(side_effect=RuntimeError("clv err")),
    )

    # Should safely swallow exceptions and not crash
    await _clv_capture_tick(
        provider=None, odds_service=None, c6_collector=mock_collector
    )


@pytest.mark.asyncio
async def test_background_settlement_sync_with_c6_collector(monkeypatch):
    from src.api.main import _background_settlement_sync, _FIXTURE_SYNC_COMPLETED

    _FIXTURE_SYNC_COMPLETED.set()
    mock_collector = MagicMock()
    mock_collector.settle_predictions = AsyncMock(
        return_value={"status": "OK", "live_n": 42}
    )
    monkeypatch.setattr(
        "src.services.settlement_service.run_settlement_pass", AsyncMock()
    )
    monkeypatch.setattr(
        "src.services.provider_evidence_service.run_provider_evidence_retention",
        AsyncMock(),
    )

    tick_count = 0

    async def fake_sleep(sec):
        nonlocal tick_count
        tick_count += 1
        if tick_count > 1:
            raise asyncio.CancelledError()

    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await _background_settlement_sync(c6_collector=mock_collector)

    assert mock_collector.last_telemetry == {"status": "OK", "live_n": 42}


@pytest.mark.asyncio
async def test_background_settlement_sync_handles_exception(monkeypatch):
    from src.api.main import _background_settlement_sync, _FIXTURE_SYNC_COMPLETED

    _FIXTURE_SYNC_COMPLETED.set()
    mock_collector = MagicMock()
    mock_collector.settle_predictions = AsyncMock(
        side_effect=RuntimeError("c6 telemetry failed")
    )
    monkeypatch.setattr(
        "src.services.settlement_service.run_settlement_pass",
        AsyncMock(side_effect=RuntimeError("settle failed")),
    )
    monkeypatch.setattr(
        "src.services.provider_evidence_service.run_provider_evidence_retention",
        AsyncMock(),
    )

    tick_count = 0

    async def fake_sleep(sec):
        nonlocal tick_count
        tick_count += 1
        if tick_count > 1:
            raise asyncio.CancelledError()

    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await _background_settlement_sync(c6_collector=mock_collector)


@pytest.mark.asyncio
async def test_background_clv_capture(monkeypatch):
    from src.api.main import _background_clv_capture

    mock_tick = AsyncMock()
    monkeypatch.setattr("src.api.main._clv_capture_tick", mock_tick)

    tick_count = 0

    async def fake_sleep(sec):
        nonlocal tick_count
        tick_count += 1
        if tick_count > 1:
            raise asyncio.CancelledError()

    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await _background_clv_capture(provider=None, odds_service=None, c6_collector=None)

    assert mock_tick.await_count == 1


@pytest.mark.asyncio
async def test_lifespan_initializes_c6_collector_and_cleans_up(monkeypatch):
    from fastapi import FastAPI
    from src.api.main import lifespan

    app = FastAPI()
    monkeypatch.setattr("src.api.main.verify_database_connection", MagicMock())
    monkeypatch.setattr("src.api.main.init_db", AsyncMock())
    monkeypatch.setattr("src.api.main.close_db", AsyncMock())
    monkeypatch.setattr("src.api.main._background_fixture_sync", AsyncMock())
    monkeypatch.setattr("src.api.main._background_settlement_sync", AsyncMock())
    monkeypatch.setattr("src.api.main._background_clv_capture", AsyncMock())
    monkeypatch.setattr("src.api.main._startup_load_models_strict", MagicMock())

    async with lifespan(app):
        assert hasattr(app.state, "c6_collector")
        assert app.state.c6_collector.last_capture == {"outcome": "never_run"}
        assert app.state.c6_collector.last_telemetry["status"] == "INSUFFICIENT_SAMPLE"
        assert app.state.c6_collector.last_telemetry["target"] == 200
        assert app.state.settlement_task is not None
        assert app.state.clv_capture_task is not None


@pytest.mark.asyncio
async def test_full_analysis_candidate_feature_bridge_branches(monkeypatch):
    from types import SimpleNamespace
    from src.api.endpoints import full_analysis as fa_endpoint

    class DummyProjector:
        def __init__(self, **_kwargs):
            pass

        async def build_live_feature_vector(self, **_kwargs):
            raise ValueError("fixture unavailable")

    class DummyPredictionEngine:
        async def predict(self, **_kwargs):
            return SimpleNamespace(
                to_dict=lambda: {
                    "home_win": 0.333,
                    "draw": 0.333,
                    "away_win": 0.334,
                    "model_version": "dummy",
                    "calibration_method": "raw",
                }
            )

    monkeypatch.setattr(fa_endpoint, "UpcomingMatchFeatureProjector", DummyProjector)
    monkeypatch.setattr(fa_endpoint, "PredictionEngine", DummyPredictionEngine)
    monkeypatch.setattr(fa_endpoint, "cache", None)

    # Branch 1: FeatureBridge admits candidate features
    class AdmittingBridge:
        def __init__(self, schema_id="apex_v1_89"):
            self.schema_id = schema_id
            self.schema_hash = "fake-sha"
            self.feature_order = ["elo_diff"]

        def validate(self, **_kwargs):
            return SimpleNamespace(
                schema_id=self.schema_id,
                schema_hash=self.schema_hash,
                values=(1.0,),
                provenance={"elo_diff": "test"},
            )

    monkeypatch.setattr(fa_endpoint, "FeatureBridge", AdmittingBridge)
    payload1 = await fa_endpoint.get_full_analysis("f1", league="EPL", db=object())
    assert payload1["feature_integration"]["status"] == "ADMITTED"
    assert payload1["feature_integration"]["schema_id"] == "apex_v1_89"
    assert payload1["feature_integration"]["feature_count"] == 1

    # Branch 2: FeatureBridge raises generic unexpected Exception
    class CrashingBridge:
        def __init__(self, schema_id="apex_v1_89"):
            self.feature_order = ["elo_diff"]

        def validate(self, **_kwargs):
            raise RuntimeError("Unexpected bridge crash")

    monkeypatch.setattr(fa_endpoint, "FeatureBridge", CrashingBridge)
    payload2 = await fa_endpoint.get_full_analysis("f2", league="EPL", db=object())
    assert payload2["feature_integration"]["status"] == "WITHHELD"
    assert payload2["feature_integration"]["reason"] == "candidate_feature_bridge_error"


