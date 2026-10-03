"""Comprehensive Unit and Integration Tests for Stacked ML Ensemble Pipeline."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from src.api.endpoints.predict_live import (
    LivePredictionResponse,
    PredictMatchRequest,
    ProbabilitySimplex,
    compute_kelly_recommendation,
    fetch_rolling_xg_from_redis,
    predict_live_match,
)
from src.models.stacked.calibration_evaluation import (
    CalibrationDeltaReport,
    compute_brier_score,
    compute_ece,
    compute_rps,
    evaluate_predictions,
    generate_calibration_delta_report,
)
from src.models.stacked.data_staging import (
    FEATURE_COLUMNS,
    TARGET_COLUMNS,
    StagedDataset,
    devig_1x2_odds,
    iter_staged_chunks,
    stage_features_and_targets,
)
from src.models.stacked.ensemble import StackedMatchEnsemble


# ---------------------------------------------------------------------------
# Synthetic Dataset Generator
# ---------------------------------------------------------------------------


def _generate_synthetic_matches(n_matches: int = 120) -> list[dict]:
    records = []
    teams = ["inter_milan", "ac_milan", "juventus", "as_roma", "napoli", "lazio"]

    for i in range(n_matches):
        h_idx = i % len(teams)
        a_idx = (i + 1) % len(teams)
        h_team = teams[h_idx]
        a_team = teams[a_idx]

        h_xg = round(float(np.random.uniform(0.5, 3.0)), 2)
        a_xg = round(float(np.random.uniform(0.3, 2.5)), 2)

        # Simulate goals based loosely on xG with noise
        h_goals = int(np.random.poisson(max(0.2, h_xg)))
        a_goals = int(np.random.poisson(max(0.2, a_xg)))
        res_1x2 = 0 if h_goals > a_goals else (1 if h_goals == a_goals else 2)

        h_odds = round(float(np.random.uniform(1.5, 4.0)), 2)
        d_odds = round(float(np.random.uniform(2.8, 3.8)), 2)
        a_odds = round(float(np.random.uniform(1.8, 4.5)), 2)

        records.append(
            {
                "match_id": 1000 + i,
                "date": f"2024-{(i % 9) + 1:02d}-{(i % 25) + 1:02d}",
                "season": "2024" if i < 60 else ("2025" if i < 100 else "2026"),
                "home_team_slug": h_team,
                "away_team_slug": a_team,
                "home_xg": h_xg,
                "away_xg": a_xg,
                "home_xa": round(h_xg * 0.7, 2),
                "away_xa": round(a_xg * 0.7, 2),
                "home_odds": h_odds,
                "draw_odds": d_odds,
                "away_odds": a_odds,
                "asian_handicap_line": -0.5,
                "over_under_line": 2.5,
                "home_goals": h_goals,
                "away_goals": a_goals,
                "result_1x2": res_1x2,
                "shot_telemetry": None,
            }
        )
    return records


# ---------------------------------------------------------------------------
# Task 1: Dual-Pipeline Feature Union & Target Segregation Tests
# ---------------------------------------------------------------------------


def test_feature_staging_zero_target_leakage() -> None:
    """Verify that NO post-match target variables exist in the feature tensor X."""
    records = _generate_synthetic_matches(50)
    dataset = stage_features_and_targets(records, chunk_size=20)

    assert isinstance(dataset, StagedDataset)
    assert dataset.X.dtype == np.float32
    assert dataset.X.flags["C_CONTIGUOUS"]
    assert dataset.X.shape == (50, len(FEATURE_COLUMNS))
    assert dataset.y.shape == (50,)

    # Verify target columns are not in feature names
    for target in TARGET_COLUMNS:
        assert target not in dataset.feature_names, f"Target leakage detected: {target} in features!"

    # Verify no NaN or Inf in feature matrix
    assert np.all(np.isfinite(dataset.X)), "Feature matrix contains NaN or Inf values!"


def test_devig_1x2_odds_simplex() -> None:
    """Verify de-vigged implied probabilities sum to 1.0."""
    p_h, p_d, p_a, overround = devig_1x2_odds(2.0, 3.2, 3.8)
    assert overround > 1.0
    total = p_h + p_d + p_a
    assert abs(total - 1.0) < 1e-6
    assert 0 < p_h < 1 and 0 < p_d < 1 and 0 < p_a < 1


def test_iter_staged_chunks_memory_safe() -> None:
    """Verify chunked streaming iterator produces matching dimensions and cleans memory."""
    records = _generate_synthetic_matches(30)
    chunks = list(iter_staged_chunks(records, chunk_size=10))

    assert len(chunks) == 3
    total_samples = 0
    for chunk_X, chunk_y, chunk_meta in chunks:
        assert chunk_X.dtype == np.float32
        assert chunk_X.flags["C_CONTIGUOUS"]
        assert len(chunk_X) == len(chunk_y) == len(chunk_meta)
        total_samples += len(chunk_X)
    assert total_samples == 30


# ---------------------------------------------------------------------------
# Task 2: Walk-Forward Validation & Stacked Ensemble Training Tests
# ---------------------------------------------------------------------------


def test_stacked_ensemble_walk_forward_training() -> None:
    """Verify chronological walk-forward training, meta-learner fit, and predict_proba simplex."""
    records = _generate_synthetic_matches(100)
    dataset = stage_features_and_targets(records)

    ensemble = StackedMatchEnsemble()
    result = ensemble.train_walk_forward(dataset, num_splits=3, num_boost_round=15)

    assert ensemble.is_fitted
    assert len(result.fold_losses) == 3
    assert len(result.fold_accuracy) == 3
    assert ensemble.meta_learner is not None

    # Test predict_proba on holdout sample
    holdout_X = dataset.X[-10:]
    probs = ensemble.predict_proba(holdout_X)

    assert isinstance(probs, np.ndarray)
    assert probs.dtype == np.float32
    assert probs.flags["C_CONTIGUOUS"]
    assert probs.shape == (10, 3)

    # Invariant: Every row must strictly form a valid probability simplex (sum to 1 within 1e-6)
    row_sums = probs.sum(axis=1)
    np.testing.assert_allclose(row_sums, 1.0, atol=1e-5)
    assert np.all(probs >= 0.0) and np.all(probs <= 1.0)


# ---------------------------------------------------------------------------
# Task 3: Probability Calibration Evaluation Tests
# ---------------------------------------------------------------------------


def test_calibration_metrics_formulas() -> None:
    """Validate RPS, Brier Score, and 10-bin ECE mathematical logic."""
    # Synthetic ground truth: 0, 1, 2
    y_true = np.array([0, 1, 2], dtype=np.int64)
    # Perfect predictions
    perfect_probs = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float32,
    )

    rps = compute_rps(y_true, perfect_probs)
    brier = compute_brier_score(y_true, perfect_probs)
    ece_mean, ece_h, ece_d, ece_a = compute_ece(y_true, perfect_probs, n_bins=10)

    assert rps == 0.0, "Perfect prediction must have RPS = 0"
    assert brier == 0.0, "Perfect prediction must have Brier = 0"
    assert ece_mean == 0.0, "Perfect prediction must have ECE = 0"


def test_calibration_delta_report_generation() -> None:
    """Verify calibration delta report generation and ECE < 5% gate check."""
    np.random.seed(42)
    n = 1000

    # True calibrated probability distribution
    calibrated_probs = np.random.dirichlet([2.0, 1.2, 1.0], size=n).astype(np.float32)
    # Ground truth sampled from true probabilities
    y_true = np.array([np.random.choice([0, 1, 2], p=calibrated_probs[i]) for i in range(n)], dtype=np.int64)

    # Uncalibrated baseline with distorted probabilities and high miscalibration
    distorted = calibrated_probs**2.5
    baseline_probs = (distorted / distorted.sum(axis=1, keepdims=True)).astype(np.float32)

    report = generate_calibration_delta_report(y_true, baseline_probs, calibrated_probs)

    assert isinstance(report, CalibrationDeltaReport)
    assert report.ensemble_metrics.ece_mean < report.baseline_metrics.ece_mean
    assert report.ensemble_metrics.brier_score < report.baseline_metrics.brier_score
    assert report.ensemble_metrics.rps < report.baseline_metrics.rps
    assert report.passes_ece_gate is True  # ECE < 0.05
    assert "CALIBRATION DELTA REPORT" in report.formatted_report


# ---------------------------------------------------------------------------
# Task 4: FastAPI Live Inference & Kelly Staking Tests
# ---------------------------------------------------------------------------


def test_fractional_kelly_recommendation() -> None:
    """Verify Quarter-Kelly computation and 5% hard cap enforcement."""
    # Strong home edge: Model 60%, Fair 45%, Odds 2.0 (net odds b = 1.0)
    # EV = 0.6 * 2.0 - 1.0 = +0.20
    # Raw Kelly = (0.6 * 1 - 0.4) / 1 = 0.20
    # Quarter Kelly = 0.25 * 0.20 = 0.05
    rec = compute_kelly_recommendation(
        p_model=(0.60, 0.25, 0.15),
        odds=(2.0, 3.4, 4.0),
        devig_probs=(0.45, 0.30, 0.25),
    )

    assert rec.action == "ACTIONABLE"
    assert rec.best_bet == "home"
    assert rec.edge > 0.042
    assert rec.expected_value > 0.0
    assert 0.0 < rec.kelly_fraction <= 0.05
    assert rec.stake_capped is True  # hits 5% cap


def test_fractional_kelly_no_bet_on_negative_ev() -> None:
    """Verify NO_BET and 0.0 stake when expected value is non-positive."""
    rec = compute_kelly_recommendation(
        p_model=(0.30, 0.30, 0.40),
        odds=(2.0, 3.0, 2.0),
        devig_probs=(0.40, 0.30, 0.30),
    )
    assert rec.action == "NO_BET"
    assert rec.kelly_fraction == 0.0


@pytest.mark.asyncio
async def test_fetch_rolling_xg_from_redis_concurrent() -> None:
    """Verify concurrent Redis rolling xG lookup with asyncio.gather."""
    mock_redis = MagicMock()
    mock_redis.get = AsyncMock(side_effect=["1.85", "1.10"])

    with patch("src.api.endpoints.predict_live.get_redis_client") as mock_get_client:
        mock_client_wrapper = MagicMock()
        mock_client_wrapper.get_client = AsyncMock(return_value=mock_redis)
        mock_get_client.return_value = mock_client_wrapper

        h_val, a_val, source = await fetch_rolling_xg_from_redis("inter_milan", "ac_milan")

        assert h_val == 1.85
        assert a_val == 1.10
        assert source == "redis_cache"


@pytest.mark.asyncio
async def test_predict_live_match_endpoint_full_pipeline() -> None:
    """Test full POST /api/v1/predict/match endpoint returns Next.js 15 compliant schema."""
    req = PredictMatchRequest(
        match_id="11662",
        home_team="Inter",
        away_team="AC Milan",
        competition="SERIE_A",
        home_odds=2.10,
        draw_odds=3.30,
        away_odds=3.60,
    )

    # Mock Redis lookup
    with patch(
        "src.api.endpoints.predict_live.fetch_rolling_xg_from_redis",
        new=AsyncMock(return_value=(1.95, 1.20, "mock_redis")),
    ):
        response: LivePredictionResponse = await predict_live_match(req)

        assert isinstance(response, LivePredictionResponse)
        assert response.match_id == "11662"
        assert response.home_team == "Inter"
        assert response.away_team == "AC Milan"

        # Verify Next.js 15 probability simplex invariant
        total_p = response.probabilities.home + response.probabilities.draw + response.probabilities.away
        assert abs(total_p - 1.0) < 1e-4

        # Verify market and recommendation
        assert response.market.home_odds == 2.10
        assert response.recommendation.kelly_fraction <= 0.05
        assert response.telemetry.rolling_xg_home == 1.95
        assert response.telemetry.rolling_xg_away == 1.20
        assert response.telemetry.delta_rolling_xg == 0.75
