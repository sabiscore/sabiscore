"""Tests for the stacked ML pipeline: Candidate-M/MA staging, PIT safety, ensemble, calibration.

The retired ``/predict/match`` route is intentionally not covered: it is covered
negatively in ``test_v21_1_evidence_integrity.py``.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from src.models.stacked.calibration_evaluation import (
    CalibrationDeltaReport,
    compute_brier_score,
    compute_ece,
    compute_rps,
    generate_calibration_delta_report,
)
from src.models.stacked.data_staging import (
    CANDIDATE_MA_FEATURE_COLUMNS,
    CANDIDATE_M_FEATURE_COLUMNS,
    FEATURE_COLUMNS,
    TARGET_COLUMNS,
    MarketContaminationError,
    StagedDataset,
    assert_candidate_m_purity,
    devig_1x2_odds,
    feature_list_sha256,
    find_market_contaminated_columns,
    iter_staged_chunks,
    stage_features_and_targets,
)
from src.models.stacked.ensemble import StackedMatchEnsemble

TEAMS = ["inter_milan", "ac_milan", "juventus", "as_roma", "napoli", "lazio"]


def _matches(n_matches: int = 120) -> list[dict]:
    """Deterministic chronological fixture list (test data only; no RNG)."""
    start = date(2024, 8, 1)
    records = []
    for i in range(n_matches):
        h_xg = round(0.6 + ((i * 7) % 13) / 5.0, 2)
        a_xg = round(0.4 + ((i * 5) % 11) / 5.0, 2)
        h_goals = (i * 3) % 4
        a_goals = (i * 5) % 3
        records.append(
            {
                "match_id": 1000 + i,
                "match_date": (start + timedelta(days=i)).isoformat(),
                "season": "2024" if i < 60 else ("2025" if i < 100 else "2026"),
                "home_team_slug": TEAMS[i % len(TEAMS)],
                "away_team_slug": TEAMS[(i + 1) % len(TEAMS)],
                "home_xg": h_xg,
                "away_xg": a_xg,
                "home_goals": h_goals,
                "away_goals": a_goals,
            }
        )
    return records


def _two_team_series(xgs: list[float]) -> list[dict]:
    """Team 'a' (home) vs team 'b' (away) repeatedly; both teams share xg series."""
    start = date(2025, 1, 1)
    return [
        {
            "match_id": i,
            "match_date": (start + timedelta(days=i)).isoformat(),
            "season": "2025",
            "home_team_slug": "a",
            "away_team_slug": "b",
            "home_xg": xg,
            "away_xg": xg / 2,
            "home_goals": 1,
            "away_goals": 0,
        }
        for i, xg in enumerate(xgs)
    ]


# ---------------------------------------------------------------------------
# Candidate-M purity / registry
# ---------------------------------------------------------------------------


def test_candidate_m_is_market_independent_and_excludes_own_match_telemetry() -> None:
    assert FEATURE_COLUMNS == CANDIDATE_M_FEATURE_COLUMNS
    assert find_market_contaminated_columns(CANDIDATE_M_FEATURE_COLUMNS) == []
    assert_candidate_m_purity(CANDIDATE_M_FEATURE_COLUMNS)
    for own_match in ("home_xg", "away_xg", "home_xa", "away_xa", "total_xg", "delta_xg"):
        assert own_match not in CANDIDATE_M_FEATURE_COLUMNS


def test_candidate_ma_is_flagged_as_market_contaminated() -> None:
    contaminated = find_market_contaminated_columns(CANDIDATE_MA_FEATURE_COLUMNS)
    assert "market_implied_home" in contaminated
    with pytest.raises(MarketContaminationError):
        assert_candidate_m_purity(CANDIDATE_MA_FEATURE_COLUMNS)


def test_feature_list_hash_is_deterministic_and_order_sensitive() -> None:
    assert feature_list_sha256(FEATURE_COLUMNS) == feature_list_sha256(list(FEATURE_COLUMNS))
    assert feature_list_sha256(FEATURE_COLUMNS) != feature_list_sha256(FEATURE_COLUMNS[::-1])


# ---------------------------------------------------------------------------
# PIT safety
# ---------------------------------------------------------------------------


def test_staging_zero_target_leakage_and_explicit_exclusions() -> None:
    records = _matches(50)
    dataset = stage_features_and_targets(records, chunk_size=20)

    assert isinstance(dataset, StagedDataset)
    assert dataset.X.dtype == np.float32
    assert dataset.X.flags["C_CONTIGUOUS"]
    assert dataset.feature_names == CANDIDATE_M_FEATURE_COLUMNS
    assert dataset.X.shape == (50 - dataset.excluded_count, len(FEATURE_COLUMNS))
    assert dataset.y.shape == (dataset.X.shape[0],)
    assert dataset.excluded_count > 0, "cold-start rows must be excluded, not filled"
    assert {reason for _, reason in dataset.excluded} == {"INSUFFICIENT_HISTORY"}
    for target in TARGET_COLUMNS:
        assert target not in dataset.feature_names
    assert np.all(np.isfinite(dataset.X))


def test_rolling_xg_uses_only_previous_five_completed_matches() -> None:
    xgs = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    dataset = stage_features_and_targets(_two_team_series(xgs))

    # First five matches have <5 prior observations => excluded, not substituted.
    assert [mid for mid, _ in dataset.excluded] == [0, 1, 2, 3, 4]
    rows = dict(zip(dataset.metadata["match_id"], dataset.X, strict=True))
    # match 5: mean(xg[0:5]) for team 'a' (home series) = 3.0
    assert rows[5][0] == pytest.approx(3.0)
    # team 'b' away series is xg/2 => mean(0.5..2.5) = 1.5
    assert rows[5][1] == pytest.approx(1.5)
    # match 6 window slides to matches 1..5 => mean(2..6) = 4.0
    assert rows[6][0] == pytest.approx(4.0)


def test_current_match_xg_never_enters_its_own_vector() -> None:
    base = _two_team_series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0])
    mutated = _two_team_series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0])
    mutated[5]["home_xg"] = 99.0  # change match 5's OWN post-match xG
    mutated[5]["away_xg"] = 99.0

    a = stage_features_and_targets(base)
    b = stage_features_and_targets(mutated)
    rows_a = dict(zip(a.metadata["match_id"], a.X, strict=True))
    rows_b = dict(zip(b.metadata["match_id"], b.X, strict=True))

    np.testing.assert_array_equal(rows_a[5], rows_b[5])  # own xG ignored
    assert not np.array_equal(rows_a[6], rows_b[6])  # becomes history afterwards


def test_out_of_order_records_are_rejected() -> None:
    records = _two_team_series([1.0] * 8)
    records[3], records[4] = records[4], records[3]
    with pytest.raises(ValueError, match="chronological"):
        stage_features_and_targets(records)


def test_missing_result_is_excluded_never_defaulted_to_a_draw() -> None:
    records = _two_team_series([1.0] * 8)
    records[7]["home_goals"] = None
    records[7]["away_goals"] = None
    dataset = stage_features_and_targets(records)
    assert (7, "TARGET_UNAVAILABLE") in dataset.excluded
    assert 7 not in set(dataset.metadata["match_id"])


# ---------------------------------------------------------------------------
# Candidate-MA (MARKET-AWARE RESEARCH)
# ---------------------------------------------------------------------------


def test_market_aware_requires_single_snapshot_provenance() -> None:
    records = _two_team_series([1.0] * 9)
    for r in records:
        r.update(
            home_odds=2.0, draw_odds=3.4, away_odds=3.8,
            asian_handicap_line=-0.5, over_under_line=2.5,
            market_timestamp="2025-01-01T10:00:00Z", bookmaker="bk",
        )
    del records[6]["market_timestamp"]  # provenance missing on one row

    dataset = stage_features_and_targets(records, include_market=True)
    assert dataset.feature_set == "MARKET-AWARE RESEARCH"
    assert dataset.feature_names == CANDIDATE_MA_FEATURE_COLUMNS
    assert (6, "MARKET_PROVENANCE_MISSING") in dataset.excluded


def test_market_aware_without_odds_is_excluded_not_defaulted() -> None:
    records = _two_team_series([1.0] * 8)
    for r in records:
        r.update(market_timestamp="2025-01-01T10:00:00Z", bookmaker="bk")
    dataset = stage_features_and_targets(records, include_market=True)
    assert dataset.X.shape[0] == 0
    assert {reason for _, reason in dataset.excluded} >= {"MARKET_UNAVAILABLE"}


def test_devig_simplex_and_invalid_odds_fail_closed() -> None:
    p_h, p_d, p_a, overround = devig_1x2_odds(2.0, 3.2, 3.8)
    assert overround > 1.0
    assert abs(p_h + p_d + p_a - 1.0) < 1e-9
    with pytest.raises(ValueError):
        devig_1x2_odds(1.0, 3.0, 3.0)  # no uniform-probability fallback


def test_iter_staged_chunks_yields_only_valid_rows() -> None:
    records = _matches(60)
    expected = stage_features_and_targets(records).X.shape[0]
    chunks = list(iter_staged_chunks(records, chunk_size=10))
    total = 0
    for chunk_X, chunk_y, chunk_meta in chunks:
        assert chunk_X.dtype == np.float32
        assert chunk_X.flags["C_CONTIGUOUS"]
        assert len(chunk_X) == len(chunk_y) == len(chunk_meta)
        total += len(chunk_X)
    assert total == expected


# ---------------------------------------------------------------------------
# Walk-forward ensemble training on staged (PIT-safe) data
# ---------------------------------------------------------------------------


def test_stacked_ensemble_walk_forward_training() -> None:
    dataset = stage_features_and_targets(_matches(120))
    assert dataset.X.shape[0] >= 50

    ensemble = StackedMatchEnsemble()
    result = ensemble.train_walk_forward(dataset, num_splits=3, num_boost_round=15)

    assert ensemble.is_fitted
    assert len(result.fold_losses) == 3
    assert ensemble.feature_names == CANDIDATE_M_FEATURE_COLUMNS

    probs = ensemble.predict_proba(dataset.X[-10:])
    assert probs.dtype == np.float32
    assert probs.shape == (10, 3)
    np.testing.assert_allclose(probs.sum(axis=1), 1.0, atol=1e-5)
    assert np.all(probs >= 0.0) and np.all(probs <= 1.0)


def test_unfitted_ensemble_refuses_to_predict() -> None:
    with pytest.raises(RuntimeError):
        StackedMatchEnsemble().predict_proba(np.zeros((1, len(FEATURE_COLUMNS)), dtype=np.float32))


# ---------------------------------------------------------------------------
# Calibration metrics
# ---------------------------------------------------------------------------


def test_calibration_metrics_formulas() -> None:
    y_true = np.array([0, 1, 2], dtype=np.int64)
    perfect = np.eye(3, dtype=np.float32)

    assert compute_rps(y_true, perfect) == 0.0
    assert compute_brier_score(y_true, perfect) == 0.0
    ece_mean, _, _, _ = compute_ece(y_true, perfect, n_bins=10)
    assert ece_mean == 0.0


def test_calibration_delta_report_generation() -> None:
    rng = np.random.default_rng(42)  # test-only evaluation fixture
    n = 1000
    calibrated = rng.dirichlet([2.0, 1.2, 1.0], size=n).astype(np.float32)
    y_true = np.array([rng.choice([0, 1, 2], p=calibrated[i]) for i in range(n)], dtype=np.int64)
    distorted = calibrated**2.5
    baseline = (distorted / distorted.sum(axis=1, keepdims=True)).astype(np.float32)

    report = generate_calibration_delta_report(y_true, baseline, calibrated)

    assert isinstance(report, CalibrationDeltaReport)
    assert report.ensemble_metrics.ece_mean < report.baseline_metrics.ece_mean
    assert report.ensemble_metrics.brier_score < report.baseline_metrics.brier_score
    assert report.ensemble_metrics.rps < report.baseline_metrics.rps
    assert report.passes_ece_gate is True
    assert "CALIBRATION DELTA REPORT" in report.formatted_report
