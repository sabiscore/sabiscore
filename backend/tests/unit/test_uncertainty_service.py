"""Unit tests for UncertaintyService (proxy-fallback path, no BNN model needed)."""

from __future__ import annotations


import pandas as pd
import pytest

from src.services.uncertainty_service import (
    UncertaintyBreakdown,
    UncertaintyService,
    _clamp,
)


@pytest.fixture()
def svc() -> UncertaintyService:
    return UncertaintyService()


# ── _clamp helper ─────────────────────────────────────────────────────────────

def test_clamp_below_low():
    assert _clamp(-0.5, 0.0, 1.0) == 0.0


def test_clamp_above_high():
    assert _clamp(1.5, 0.0, 1.0) == 1.0


def test_clamp_within_range():
    assert _clamp(0.5, 0.0, 1.0) == 0.5


# ── UncertaintyBreakdown dataclass ────────────────────────────────────────────

def test_uncertainty_breakdown_ok_tier():
    bd = UncertaintyBreakdown(
        epistemic_unc=0.1,
        aleatoric_unc=0.2,
        concentration=3.0,
        credible_interval=(0.3, 0.7),
    )
    assert bd.confidence_tier == "OK"


def test_uncertainty_breakdown_custom_tier():
    bd = UncertaintyBreakdown(
        epistemic_unc=0.5,
        aleatoric_unc=0.3,
        concentration=2.0,
        credible_interval=(0.2, 0.6),
        confidence_tier="LOW_EVIDENCE",
    )
    assert bd.confidence_tier == "LOW_EVIDENCE"


# ── decompose_from_probabilities ──────────────────────────────────────────────

def test_decompose_returns_breakdown(svc):
    probs = {"home_win": 0.45, "draw": 0.30, "away_win": 0.25}
    bd = svc.decompose_from_probabilities(probs, confidence=0.45)
    assert isinstance(bd, UncertaintyBreakdown)
    assert 0.0 <= bd.epistemic_unc <= 1.0
    assert 0.0 <= bd.aleatoric_unc <= 1.0
    assert bd.concentration >= 1.0
    assert 0.0 <= bd.credible_interval[0] <= bd.credible_interval[1] <= 1.0


def test_decompose_high_confidence_low_epistemic(svc):
    # Use confidence=0.90 so epistemic_unc = 0.10, well below threshold of 0.15
    probs = {"home_win": 0.90, "draw": 0.07, "away_win": 0.03}
    bd = svc.decompose_from_probabilities(probs, confidence=0.90)
    assert bd.epistemic_unc < 0.5
    assert bd.confidence_tier == "OK"


def test_decompose_low_confidence_may_be_low_evidence(svc):
    probs = {"home_win": 0.35, "draw": 0.33, "away_win": 0.32}
    bd = svc.decompose_from_probabilities(probs, confidence=0.35)
    assert bd.epistemic_unc > 0.0


def test_decompose_uniform_high_entropy(svc):
    probs = {"home_win": 0.333, "draw": 0.333, "away_win": 0.334}
    bd = svc.decompose_from_probabilities(probs, confidence=0.334)
    assert bd.aleatoric_unc > 0.5


def test_decompose_certain_low_entropy(svc):
    probs = {"home_win": 0.99, "draw": 0.005, "away_win": 0.005}
    bd = svc.decompose_from_probabilities(probs, confidence=0.99)
    assert bd.aleatoric_unc < 0.5


def test_decompose_credible_interval_ordered(svc):
    probs = {"home_win": 0.55, "draw": 0.25, "away_win": 0.20}
    bd = svc.decompose_from_probabilities(probs, confidence=0.55)
    lower, upper = bd.credible_interval
    assert lower <= upper


def test_decompose_zero_confidence(svc):
    probs = {"home_win": 0.0, "draw": 0.0, "away_win": 0.0}
    bd = svc.decompose_from_probabilities(probs, confidence=0.0)
    assert bd.epistemic_unc == 1.0


def test_decompose_missing_outcome_keys(svc):
    probs = {"home_win": 0.6, "draw": 0.4}
    bd = svc.decompose_from_probabilities(probs, confidence=0.6)
    assert isinstance(bd, UncertaintyBreakdown)


# ── decompose (BNN fallback path — no model file installed in test env) ───────

def test_decompose_falls_back_when_no_bnn(svc):
    """When BNN model is absent, decompose must use proxy fallback."""
    feature_frame = pd.DataFrame({"col_a": [0.5], "col_b": [1.0]})
    probs = {"home_win": 0.50, "draw": 0.30, "away_win": 0.20}
    bd = svc.decompose(feature_frame, probs, confidence=0.50)
    assert isinstance(bd, UncertaintyBreakdown)


def test_decompose_empty_frame_uses_fallback(svc):
    probs = {"home_win": 0.45, "draw": 0.30, "away_win": 0.25}
    bd = svc.decompose(pd.DataFrame(), probs, confidence=0.45)
    assert isinstance(bd, UncertaintyBreakdown)


# ── compute_from_defaults ─────────────────────────────────────────────────────

def test_compute_from_defaults(svc):
    bd = svc.compute_from_defaults()
    assert isinstance(bd, UncertaintyBreakdown)
    assert 0.0 <= bd.epistemic_unc <= 1.0


def test_compute_from_defaults_custom_probs(svc):
    bd = svc.compute_from_defaults(home_win_prob=0.60, draw_prob=0.25, away_win_prob=0.15)
    assert bd.epistemic_unc == pytest.approx(1.0 - 0.60, abs=0.01)


# ── to_dict ────────────────────────────────────────────────────────────────────

def test_to_dict_returns_dict(svc):
    bd = UncertaintyBreakdown(
        epistemic_unc=0.2,
        aleatoric_unc=0.3,
        concentration=5.0,
        credible_interval=(0.4, 0.7),
        confidence_tier="OK",
    )
    result = svc.to_dict(bd)
    assert isinstance(result, dict)
    assert result["epistemic_unc"] == 0.2
    assert result["aleatoric_unc"] == 0.3
    assert result["concentration"] == 5.0
    assert result["credible_interval"]["lower"] == 0.4
    assert result["credible_interval"]["upper"] == 0.7
    assert result["confidence_tier"] == "OK"


def test_to_dict_low_evidence_tier(svc):
    bd = UncertaintyBreakdown(
        epistemic_unc=0.8,
        aleatoric_unc=0.6,
        concentration=1.5,
        credible_interval=(0.1, 0.9),
        confidence_tier="LOW_EVIDENCE",
    )
    result = svc.to_dict(bd)
    assert result["confidence_tier"] == "LOW_EVIDENCE"
