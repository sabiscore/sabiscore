"""Tests for PredictionEngine (backend/src/models/prediction.py).

Coverage:
  PE-1  PredictionResult is a frozen dataclass (immutable)
  PE-2  to_dict() returns all required keys with correct types (incl. Phase D fields)
  PE-3  _fallback_result returns uniform 0.333/0.334 probabilities, confidence=0
  PE-4  Probabilities always sum to 1.0 when model returns valid proba (v5 bundle)
  PE-5  Feature schema mismatch: shorter vector fails closed to fallback, never zero-padded
  PE-6  Feature schema mismatch: longer vector fails closed, never truncates
  PE-7  Valid probability simplexes are preserved without repair
  PE-8  calculate_value_bets returns empty list when no outcome has edge >= min_edge_pct
  PE-9  calculate_value_bets identifies a high-edge outcome correctly
  PE-10 calculate_value_bets sets clv_pct=None when closing_odds not supplied
  PE-11 calculate_value_bets computes clv_pct when closing_odds provided
  PE-12 calculate_value_bets sorts bets by edge descending
  PE-13 prime_cache stores an _ArtifactBundle; clear_cache empties it
  PE-14 predict() falls back gracefully when model directory is empty
  PE-15 _run_inference handles two-class model (binary) correctly (v5 bundle)
  PE-16 _wrap_artifact: v5 direct model → bundle with direct_model set
  PE-17 _wrap_artifact: v6 dict artifact → bundle with models_dict set
  PE-18 _wrap_artifact: invalid artifact (no predict_proba, no models key) → None
  PE-19 calibration applied when FittedCalibrator present and _CAL_AVAILABLE=True
  PE-20 overlay applied when overlay.alpha > 0
  PE-21 overlay NOT applied when overlay.alpha == 0
  PE-22 _ensemble_predict_dict averages multiple base-learner outputs
  PE-23 _ensemble_predict_dict fails closed when no model returns valid 3-class proba
  PE-24 calibration_applied=False and overlay_applied=False by default
  PE-25 v6 bundle inference path (models_dict) returns a valid 3-class simplex
"""
from __future__ import annotations

from dataclasses import fields
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.models.prediction import PredictionEngine, PredictionResult, _ArtifactBundle


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_v5_bundle(proba=(0.50, 0.25, 0.25), n_features=58) -> _ArtifactBundle:
    """v5-style bundle: direct sklearn model, no calibrator or overlay."""
    model = MagicMock()
    model.n_features_in_ = n_features
    model.predict_proba = MagicMock(return_value=np.array([list(proba)]))
    return _ArtifactBundle(
        direct_model=model,
        models_dict=None,
        calibrator=None,
        overlay=None,
        feature_columns=None,
        model_version="v5_phase7",
        generation="v5_phase7-test",
        feature_schema_version=f"phase7_{n_features}",
        manifest_sha256="test-manifest",
    )


def _make_v6_bundle(
    proba=(0.50, 0.25, 0.25),
    n_features=58,
    calibrator=None,
    overlay=None,
    feature_columns=None,
) -> _ArtifactBundle:
    """v6-style bundle: dict of named base learners."""
    model = MagicMock()
    model.n_features_in_ = n_features
    model.predict_proba = MagicMock(return_value=np.array([list(proba)]))
    return _ArtifactBundle(
        direct_model=None,
        models_dict={"rf": model},
        calibrator=calibrator,
        overlay=overlay,
        feature_columns=feature_columns,
        model_version="v6_phase8",
        generation="v6_phase8-test",
        feature_schema_version=f"phase8_{n_features}",
        manifest_sha256="test-manifest",
    )


FEATURES_58 = np.random.rand(58).astype(np.float32)
FEATURES_86 = np.random.rand(86).astype(np.float32)
FEATURES_30 = np.random.rand(30).astype(np.float32)


# ── PE-1 ──────────────────────────────────────────────────────────────────────

def test_prediction_result_is_frozen():
    """PE-1: PredictionResult cannot be mutated after construction."""
    result = PredictionResult(
        home_win=0.5, draw=0.25, away_win=0.25,
        confidence=0.17, model_dim=58,
        model_version="v6_phase8", calibration_method="isotonic",
    )
    with pytest.raises((AttributeError, TypeError)):
        result.home_win = 0.9  # type: ignore[misc]


# ── PE-2 ──────────────────────────────────────────────────────────────────────

def test_to_dict_has_all_keys():
    """PE-2: to_dict() includes all dataclass fields including Phase D additions."""
    result = PredictionResult(
        home_win=0.5, draw=0.25, away_win=0.25,
        confidence=0.17, model_dim=58,
        model_version="v6_phase8", calibration_method="isotonic",
    )
    d = result.to_dict()
    expected_keys = {f.name for f in fields(PredictionResult)}
    assert expected_keys == set(d.keys())
    assert isinstance(d["home_win"], float)
    assert isinstance(d["model_dim"], int)
    # Phase D fields must be present
    assert "calibration_applied" in d
    assert "overlay_applied" in d


# ── PE-3 ──────────────────────────────────────────────────────────────────────

def test_fallback_result_uniform():
    """PE-3: Fallback gives ~1/3 probs and confidence 0."""
    r = PredictionEngine._fallback_result(input_dim=58)
    assert r.confidence == 0.0
    assert r.model_version == "fallback"
    total = r.home_win + r.draw + r.away_win
    assert abs(total - 1.0) < 1e-6


# ── PE-4 ──────────────────────────────────────────────────────────────────────

def test_inference_probs_sum_to_one():
    """PE-4: Probabilities returned from a 3-class v5 bundle sum to 1.0."""
    engine = PredictionEngine()
    bundle = _make_v5_bundle((0.6, 0.2, 0.2))
    result = engine._run_inference(bundle, FEATURES_58, "EPL")
    total = result.home_win + result.draw + result.away_win
    assert abs(total - 1.0) < 1e-5


# ── PE-5 ──────────────────────────────────────────────────────────────────────

def test_short_vector_fails_closed_not_padded(caplog):
    """PE-5: A 30-dim vector against a 58-dim model fails closed to the fallback
    result instead of zero-padding the missing 28 slots (INV-10) — the model is
    never called, and the result is tagged model_version="fallback", the
    established signal full_analysis.py/upcoming_match_service.py already check
    to treat a result as diagnostic-only rather than a real prediction."""
    import logging
    engine = PredictionEngine()
    bundle = _make_v5_bundle(n_features=58)
    with caplog.at_level(logging.ERROR, logger="src.models.prediction"):
        result = engine._run_inference(bundle, FEATURES_30, "EPL")
    bundle.direct_model.predict_proba.assert_not_called()
    assert result.model_version == "fallback"
    assert any("SCHEMA_MISMATCH" in r.message for r in caplog.records)


# ── PE-6 ──────────────────────────────────────────────────────────────────────

def test_long_vector_fails_closed_instead_of_truncating(caplog):
    """PE-6: A wider vector cannot be silently truncated into an older schema."""
    import logging
    engine = PredictionEngine()
    bundle = _make_v5_bundle(n_features=58)
    with caplog.at_level(logging.ERROR, logger="src.models.prediction"):
        result = engine._run_inference(bundle, FEATURES_86, "EPL")
    bundle.direct_model.predict_proba.assert_not_called()
    assert result.model_version == "fallback"
    assert result.model_dim == 86
    assert any("SCHEMA_MISMATCH" in r.message for r in caplog.records)


# ── PE-7 ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("proba", [
    (1.0, 0.0, 0.0),
    (0.33, 0.33, 0.34),
    (0.0, 0.0, 1.0),
])
def test_probs_in_unit_interval(proba):
    """PE-7: Valid model probabilities are preserved within [0, 1]."""
    engine = PredictionEngine()
    bundle = _make_v5_bundle(proba)
    result = engine._run_inference(bundle, FEATURES_58, "EPL")
    assert 0.0 <= result.home_win <= 1.0
    assert 0.0 <= result.draw <= 1.0
    assert 0.0 <= result.away_win <= 1.0


# ── PE-8 ──────────────────────────────────────────────────────────────────────

def test_value_bets_empty_when_no_edge():
    """PE-8: No value bets returned when all edges are below min_edge_pct."""
    preds = {"home_win": 0.40, "draw": 0.30, "away_win": 0.30}
    odds = {"home_win": 2.0, "draw": 2.5, "away_win": 2.5}
    bets = PredictionEngine.calculate_value_bets(preds, odds, min_edge_pct=3.0)
    assert bets == []


# ── PE-9 ──────────────────────────────────────────────────────────────────────

def test_value_bets_identifies_high_edge():
    """PE-9: A genuine edge outcome appears in the value bets list."""
    preds = {"home_win": 0.65, "draw": 0.20, "away_win": 0.15}
    odds = {"home_win": 3.0, "draw": 4.0, "away_win": 8.0}
    bets = PredictionEngine.calculate_value_bets(preds, odds, min_edge_pct=3.0)
    assert len(bets) >= 1
    assert bets[0]["outcome"] == "home_win"
    assert bets[0]["edge_pct"] > 3.0


# ── PE-10 ─────────────────────────────────────────────────────────────────────

def test_clv_pct_null_without_closing_odds():
    """PE-10: clv_pct is None when closing_odds are absent (B-contract)."""
    preds = {"home_win": 0.65, "draw": 0.20, "away_win": 0.15}
    odds = {"home_win": 3.0, "draw": 4.0, "away_win": 8.0}
    bets = PredictionEngine.calculate_value_bets(preds, odds, closing_odds=None)
    for bet in bets:
        assert bet["clv_pct"] is None


# ── PE-11 ─────────────────────────────────────────────────────────────────────

def test_clv_pct_computed_with_closing_odds():
    """PE-11: clv_pct is computed when closing_odds supplied."""
    preds = {"home_win": 0.65, "draw": 0.20, "away_win": 0.15}
    odds = {"home_win": 3.0, "draw": 4.0, "away_win": 8.0}
    closing_odds = {"home_win": 2.5, "draw": 4.5, "away_win": 9.0}
    bets = PredictionEngine.calculate_value_bets(preds, odds, closing_odds=closing_odds)
    home_bets = [b for b in bets if b["outcome"] == "home_win"]
    assert home_bets, "Expected home_win in value bets"
    clv = home_bets[0]["clv_pct"]
    assert clv is not None
    assert abs(clv - 25.0) < 0.1


# ── PE-12 ─────────────────────────────────────────────────────────────────────

def test_value_bets_sorted_by_edge_descending():
    """PE-12: Multiple value bets are ordered by edge_pct highest first."""
    preds = {"home_win": 0.70, "draw": 0.15, "away_win": 0.15}
    odds = {"home_win": 3.5, "draw": 5.0, "away_win": 9.0}
    bets = PredictionEngine.calculate_value_bets(preds, odds, min_edge_pct=1.0)
    edges = [b["edge_pct"] for b in bets]
    assert edges == sorted(edges, reverse=True)


# ── PE-13 ─────────────────────────────────────────────────────────────────────

def test_prime_and_clear_cache():
    """PE-13: prime_cache wraps model into _ArtifactBundle; clear_cache empties it."""
    mock_model = MagicMock()
    mock_model.predict_proba = MagicMock(return_value=np.array([[0.5, 0.25, 0.25]]))
    PredictionEngine.clear_cache()
    PredictionEngine.prime_cache("EPL", mock_model)
    assert "epl" in PredictionEngine._model_cache
    stored = PredictionEngine._model_cache["epl"]
    assert isinstance(stored, _ArtifactBundle)
    # The mock model should be reachable via the bundle
    assert stored.direct_model is mock_model or (
        stored.models_dict is not None and mock_model in stored.models_dict.values()
    )
    PredictionEngine.clear_cache()
    assert PredictionEngine._model_cache == {}


# ── PE-14 ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_predict_returns_fallback_when_no_model(tmp_path):
    """PE-14: predict() returns fallback probabilities when model directory is empty."""
    PredictionEngine.clear_cache()
    with patch("src.models.prediction.settings") as mock_settings:
        mock_settings.phase7_models_path = tmp_path / "empty_phase7"
        mock_settings.models_path = tmp_path / "empty_models"
        (tmp_path / "empty_phase7").mkdir()
        (tmp_path / "empty_models").mkdir()
        engine = PredictionEngine()
        result = await engine.predict(FEATURES_58, league="EPL")
    assert result.confidence == 0.0
    assert result.model_version == "fallback"
    assert abs(result.home_win + result.draw + result.away_win - 1.0) < 1e-5
    PredictionEngine.clear_cache()


# ── PE-15 ─────────────────────────────────────────────────────────────────────

def test_binary_model_handled_correctly():
    """PE-15: A two-class v5 bundle output is unpacked as (away, home) binary."""
    engine = PredictionEngine()
    model = MagicMock()
    model.n_features_in_ = 58
    model.predict_proba = MagicMock(return_value=np.array([[0.30, 0.70]]))
    bundle = _ArtifactBundle(
        direct_model=model,
        models_dict=None,
        calibrator=None,
        overlay=None,
        feature_columns=None,
    )
    result = engine._run_inference(bundle, FEATURES_58, "EPL")
    assert result.draw == 0.0
    assert abs(result.home_win - 0.70) < 1e-4
    assert abs(result.away_win - 0.30) < 1e-4


# ── PE-16 ─────────────────────────────────────────────────────────────────────

def test_wrap_artifact_v5_direct_model():
    """PE-16: _wrap_artifact returns bundle with direct_model for v5 sklearn models."""
    model = MagicMock()
    model.predict_proba = MagicMock(return_value=np.array([[0.5, 0.25, 0.25]]))
    bundle = PredictionEngine._wrap_artifact(model, "epl", "<test>")
    assert bundle is not None
    assert isinstance(bundle, _ArtifactBundle)
    assert bundle.direct_model is model
    assert bundle.models_dict is None
    assert bundle.calibrator is None
    assert bundle.overlay is None


def test_wrap_artifact_preserves_manifest_provenance():
    model = MagicMock()
    model.predict_proba = MagicMock(return_value=np.array([[0.5, 0.25, 0.25]]))
    bundle = PredictionEngine._wrap_artifact(
        model,
        "epl",
        "<test>",
        provenance={
            "model_version": "v5_phase7",
            "generation": "v5_phase7-20260808",
            "feature_schema_version": "phase7_68",
            "manifest_sha256": "abc123",
            "certification_state": "UNVERIFIED",
            "artifact_sha256": "def456",
            "coverage": "dedicated",
        },
    )
    assert bundle is not None
    assert bundle.model_version == "v5_phase7"
    assert bundle.generation == "v5_phase7-20260808"
    assert bundle.feature_schema_version == "phase7_68"
    assert bundle.manifest_sha256 == "abc123"
    assert bundle.artifact_sha256 == "def456"


# ── PE-17 ─────────────────────────────────────────────────────────────────────

def test_wrap_artifact_v6_dict_artifact():
    """PE-17: _wrap_artifact returns bundle with models_dict for v6 dict artifacts."""
    sub_model = MagicMock()
    sub_model.predict_proba = MagicMock(return_value=np.array([[0.5, 0.25, 0.25]]))
    raw = {
        "models": {"rf": sub_model},
        "calibrator": MagicMock(),
        "bivariate_poisson_overlay": MagicMock(),
        "feature_columns": ["feat_a", "feat_b"],
    }
    bundle = PredictionEngine._wrap_artifact(raw, "epl", "<test>")
    assert bundle is not None
    assert isinstance(bundle, _ArtifactBundle)
    assert bundle.direct_model is None
    assert "rf" in bundle.models_dict
    assert bundle.calibrator is raw["calibrator"]
    assert bundle.overlay is raw["bivariate_poisson_overlay"]
    assert bundle.feature_columns == ["feat_a", "feat_b"]


# ── PE-18 ─────────────────────────────────────────────────────────────────────

def test_wrap_artifact_invalid_returns_none():
    """PE-18: _wrap_artifact returns None for artifacts that are neither dict nor predict_proba."""
    assert PredictionEngine._wrap_artifact("not_a_model", "epl", "<test>") is None
    assert PredictionEngine._wrap_artifact(42, "epl", "<test>") is None
    assert PredictionEngine._wrap_artifact({"no_models_key": True}, "epl", "<test>") is None


# ── PE-19 ─────────────────────────────────────────────────────────────────────

def test_calibration_applied_when_calibrator_present():
    """PE-19: calibration_applied=True and calibration_method set when FittedCalibrator present."""
    mock_calibrator = MagicMock()
    mock_calibrator.method = "isotonic"
    mock_calibrator.calibrators = MagicMock()
    mock_calibrator.ece_after = {"mean": 0.03}

    bundle = _make_v6_bundle((0.6, 0.2, 0.2), calibrator=mock_calibrator)
    calibrated_proba = np.array([[0.55, 0.22, 0.23]])

    with patch("src.models.prediction._CAL_AVAILABLE", True), \
         patch("src.models.prediction._apply_calibrator", return_value=calibrated_proba):
        engine = PredictionEngine()
        result = engine._run_inference(bundle, FEATURES_58, "EPL")

    assert result.calibration_applied is True
    assert result.calibration_method == "isotonic"
    total = result.home_win + result.draw + result.away_win
    assert abs(total - 1.0) < 1e-5


# ── PE-20 ─────────────────────────────────────────────────────────────────────

def test_overlay_applied_when_alpha_nonzero():
    """PE-20: overlay_applied=True when overlay.alpha > 0."""
    mock_overlay = MagicMock()
    mock_overlay.alpha = 0.3
    mock_overlay.apply = MagicMock(return_value=np.array([[0.58, 0.23, 0.19]]))

    bundle = _make_v6_bundle((0.6, 0.2, 0.2), overlay=mock_overlay)
    engine = PredictionEngine()
    result = engine._run_inference(bundle, FEATURES_58, "EPL")

    assert result.overlay_applied is True
    mock_overlay.apply.assert_called_once()


# ── PE-21 ─────────────────────────────────────────────────────────────────────

def test_overlay_not_applied_when_alpha_zero():
    """PE-21: overlay_applied=False when overlay.alpha == 0 (inactive overlay)."""
    mock_overlay = MagicMock()
    mock_overlay.alpha = 0.0
    mock_overlay.apply = MagicMock(return_value=np.array([[0.6, 0.2, 0.2]]))

    bundle = _make_v6_bundle((0.6, 0.2, 0.2), overlay=mock_overlay)
    engine = PredictionEngine()
    result = engine._run_inference(bundle, FEATURES_58, "EPL")

    assert result.overlay_applied is False
    mock_overlay.apply.assert_not_called()


# ── PE-22 ─────────────────────────────────────────────────────────────────────

def test_ensemble_predict_dict_averages_models():
    """PE-22: _ensemble_predict_dict computes equal-weight average across base learners."""
    m1 = MagicMock()
    m1.predict_proba = MagicMock(return_value=np.array([[0.6, 0.2, 0.2]]))
    m2 = MagicMock()
    m2.predict_proba = MagicMock(return_value=np.array([[0.4, 0.3, 0.3]]))

    result = PredictionEngine._ensemble_predict_dict({"rf": m1, "xgb": m2}, FEATURES_58.reshape(1, -1))
    expected = np.array([[0.5, 0.25, 0.25]])
    np.testing.assert_allclose(result, expected, atol=1e-5)


# ── PE-23 ─────────────────────────────────────────────────────────────────────

def test_ensemble_predict_dict_fails_closed_when_no_valid_proba():
    """PE-23: no valid base learner output is never repaired or fabricated."""
    m = MagicMock()
    m.predict_proba = MagicMock(return_value=np.array([[0.5, 0.5]]))  # only 2 classes

    with pytest.raises(ValueError, match="no base learner"):
        PredictionEngine._ensemble_predict_dict({"m": m}, FEATURES_58.reshape(1, -1))


@pytest.mark.parametrize(
    "proba",
    [
        (0.60, 0.30, 0.30),
        (0.60, 0.50, -0.10),
        (float("nan"), 0.50, 0.50),
    ],
)
def test_invalid_model_probability_simplex_fails_closed(proba):
    """Invalid model output becomes an explicitly tagged diagnostic fallback."""
    result = PredictionEngine()._run_inference(
        _make_v5_bundle(proba),
        FEATURES_58,
        "EPL",
    )
    assert result.model_version == "fallback"
    assert result.confidence == 0.0


# ── PE-24 ─────────────────────────────────────────────────────────────────────

def test_prediction_result_defaults_no_calibration():
    """PE-24: PredictionResult.calibration_applied and overlay_applied default to False."""
    r = PredictionResult(
        home_win=0.5, draw=0.25, away_win=0.25,
        confidence=0.17, model_dim=58,
        model_version="v5_phase7", calibration_method="raw",
    )
    assert r.calibration_applied is False
    assert r.overlay_applied is False


# ── PE-25 ─────────────────────────────────────────────────────────────────────

def test_v6_bundle_inference_returns_valid_proba():
    """PE-25: v6 bundle (models_dict path) returns a valid 3-class simplex."""
    bundle = _make_v6_bundle((0.55, 0.25, 0.20), n_features=86)
    engine = PredictionEngine()
    result = engine._run_inference(bundle, FEATURES_86, "EPL")

    assert result.model_version == "v6_phase8"
    assert result.calibration_applied is False
    assert result.overlay_applied is False
    total = result.home_win + result.draw + result.away_win
    assert abs(total - 1.0) < 1e-5
