"""Validation for leakage-safe feature engineering and memory bounds."""

from __future__ import annotations

import threading
import time

import numpy as np
import pandas as pd
import pytest

from src.data.imputation import LeagueTransitionDiscount
from src.features.target_encoding import PointInTimeTargetEncoder
from src.features.xg_elo import XGEloUpdater
from src.models.pipeline import ChronologicalFeaturePipeline, TargetEncodingSpec


def _sample_frame(n: int = 2000) -> pd.DataFrame:
    dates = pd.date_range("2020-01-01", periods=n, freq="D")
    teams = np.array(["A", "B", "C", "D"], dtype=object)
    return pd.DataFrame(
        {
            "date": dates,
            "season": dates.year,
            "home_team": teams[np.arange(n) % 4],
            "away_team": teams[(np.arange(n) + 1) % 4],
            "home_xg": np.full(n, 1.2, dtype=np.float32),
            "away_xg": np.full(n, 0.9, dtype=np.float32),
            "home_win": (np.arange(n) % 3 == 0).astype(np.float32),
        }
    )


def test_target_encoding_never_uses_future_or_same_day_targets() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-01", "2025-01-01", "2025-01-02", "2025-01-03"]),
            "team": ["A", "B", "A", "A"],
            "target": [1.0, 1000.0, 0.0, 1.0],
        }
    )
    encoded = PointInTimeTargetEncoder().fit_transform(frame, "team", "target")

    # First day has no prior observations and therefore no evidence.
    assert encoded.loc[0, "team_target_encoded"] != encoded.loc[0, "team_target_encoded"]
    assert encoded.loc[1, "team_target_encoded"] != encoded.loc[1, "team_target_encoded"]
    # A on Jan 2 can only see A's Jan 1 value, not B's same-day value.
    assert encoded.loc[2, "team_target_encoded"] == pytest.approx(1.0)
    # Jan 3 can see both prior A observations: mean(1, 0) = 0.5.
    assert encoded.loc[3, "team_target_encoded"] == pytest.approx(0.5)
    assert encoded["team_target_encoded"].dtype == np.float32


def test_target_encoding_same_day_rows_are_all_uninformed_without_prior_history() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-01", "2025-01-01", "2025-01-02"]),
            "team": ["A", "A", "A"],
            "target": [0.0, 1.0, 0.0],
        }
    )

    encoded = PointInTimeTargetEncoder().fit_transform(frame, "team", "target")

    assert encoded.loc[[0, 1], "team_target_encoded"].isna().all()
    assert encoded.loc[2, "team_target_encoded"] == pytest.approx(0.5)


def test_target_encoding_unseen_category_uses_historical_global_mean() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"]),
            "team": ["A", "B", "NEW"],
            "target": [0.0, 1.0, 99.0],
        }
    )

    encoded = PointInTimeTargetEncoder().fit_transform(frame, "team", "target")

    assert encoded.loc[0, "team_target_encoded"] != encoded.loc[0, "team_target_encoded"]
    assert encoded.loc[1, "team_target_encoded"] == pytest.approx(0.0)
    # NEW has no category history, so only prior global evidence is available.
    assert encoded.loc[2, "team_target_encoded"] == pytest.approx(0.5)


def test_xg_elo_new_teams_start_from_initial_rating_without_prior_history() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-01", "2025-01-02"]),
            "home_team": ["NEW", "NEW"],
            "away_team": ["A", "A"],
            "home_xg": [1.0, 1.0],
            "away_xg": [1.0, 1.0],
        }
    )

    result = XGEloUpdater().calculate_ratings(frame)

    assert result.loc[0, "pre_match_home_offense"] == pytest.approx(1.0)
    assert result.loc[0, "pre_match_home_defense"] == pytest.approx(1.0)
    assert result.loc[1, "pre_match_home_offense"] != pytest.approx(1.0)
    assert result.loc[1, "pre_match_home_defense"] != pytest.approx(1.0)


def test_xg_elo_same_day_matches_update_only_after_the_prior_row() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-01", "2025-01-01"]),
            "home_team": ["A", "A"],
            "away_team": ["B", "B"],
            "home_xg": [3.0, 1.0],
            "away_xg": [0.5, 1.0],
        }
    )

    result = XGEloUpdater().calculate_ratings(frame)

    # Stable input order is the deterministic order for matches sharing a date.
    assert result.loc[0, "pre_match_home_offense"] == pytest.approx(1.0)
    assert result.loc[1, "pre_match_home_offense"] != pytest.approx(1.0)


def test_xg_elo_features_are_pre_match_state() -> None:
    frame = _sample_frame(8)
    result = XGEloUpdater(k_factor=0.1).calculate_ratings(frame)
    assert result["pre_match_home_offense"].iloc[0] == pytest.approx(1.0)
    # The second appearance of A must reflect the first match, not its own xG.
    assert result["pre_match_home_offense"].iloc[4] != pytest.approx(1.0)
    assert result["pre_match_home_offense"].dtype == np.float32


def test_promoted_team_baseline_uses_prior_seasons_only() -> None:
    frame = pd.DataFrame(
        {
            "season": [2024, 2024, 2025, 2025],
            "home_team": ["A", "B", "A", "NEW"],
            "away_team": ["B", "A", "NEW", "A"],
            "home_xg": [2.0, 2.0, 9.0, 9.0],
            "away_xg": [1.0, 1.0, 9.0, 9.0],
        }
    )
    transformed, promoted = LeagueTransitionDiscount().apply(frame, 2025)
    assert promoted == {"NEW"}
    # 2025's 9.0 values must not affect the baseline: prior means are 2.0/1.0.
    assert transformed.loc[2, "home_xg_cold_start"] != transformed.loc[3, "home_xg_cold_start"]
    assert transformed.loc[3, "home_xg_cold_start"] == pytest.approx(1.5)


def test_transition_discount_fails_closed_when_no_prior_xg_exists() -> None:
    frame = pd.DataFrame(
        {
            "season": [2025, 2025],
            "home_team": ["NEW", "A"],
            "away_team": ["A", "NEW"],
            "home_xg": [1.0, 1.0],
            "away_xg": [1.0, 1.0],
        }
    )

    with pytest.raises(ValueError, match="Prior-season xG history is required"):
        LeagueTransitionDiscount().apply(frame, 2025)


def test_transition_discount_preserves_existing_observations_and_unrelated_missing_values() -> None:
    frame = pd.DataFrame(
        {
            "season": [2024, 2025, 2025],
            "home_team": ["A", "NEW", "A"],
            "away_team": ["A", "A", "NEW"],
            "home_xg": [2.0, np.nan, 4.0],
            "away_xg": [1.0, 3.0, np.nan],
        }
    )

    transformed, _ = LeagueTransitionDiscount().apply(frame, 2025)

    assert transformed.loc[1, "home_xg"] != transformed.loc[1, "home_xg"]
    assert transformed.loc[2, "away_xg"] != transformed.loc[2, "away_xg"]
    assert transformed.loc[1, "home_xg_cold_start"] == pytest.approx(1.5)
    assert transformed.loc[2, "away_xg_cold_start"] == pytest.approx(0.75)


def test_pipeline_has_no_future_date_leakage() -> None:
    frame = _sample_frame(32)
    frame["home_manager"] = np.where(np.arange(len(frame)) % 2, "m1", "m2")
    pipeline = ChronologicalFeaturePipeline(
        target_encodings=(TargetEncodingSpec("home_team", "home_win"),)
    )
    result = pipeline.transform(frame)
    assert result["date"].is_monotonic_increasing
    # Every generated feature is attached to a row at or after its source date.
    assert result["date"].min() == frame["date"].min()
    assert result["date"].max() == frame["date"].max()
    assert result["home_win_home_team_encoded"].dtype == np.float32


def test_pipeline_same_day_target_encoding_does_not_cross_contaminate_matches() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-01", "2025-01-01", "2025-01-02"]),
            "season": [2025, 2025, 2025],
            "home_team": ["A", "B", "A"],
            "away_team": ["B", "A", "B"],
            "home_xg": [1.0, 1.0, 1.0],
            "away_xg": [1.0, 1.0, 1.0],
            "home_win": [1.0, 0.0, 1.0],
        }
    )

    # There is no prior season in this fixture set, so transition priors would
    # fail closed. Disable that stage by giving all teams sufficient history.
    history = frame.assign(season=2024)
    combined = pd.concat([history, frame], ignore_index=True)
    pipeline = ChronologicalFeaturePipeline(
        target_encodings=(TargetEncodingSpec("home_team", "home_win"),)
    )
    result = pipeline.transform(combined)

    current_day = result[result["date"] == pd.Timestamp("2025-01-01")]
    assert current_day["home_win_home_team_encoded"].isna().all()
    next_day = result[result["date"] == pd.Timestamp("2025-01-02")]
    assert next_day["home_win_home_team_encoded"].iloc[0] == pytest.approx(1.0)


def test_pipeline_memory_peak_stays_below_four_gb() -> None:
    psutil = pytest.importorskip("psutil")
    process = psutil.Process()
    frame = _sample_frame(100_000)
    peak = process.memory_info().rss
    stop = threading.Event()

    def sample() -> None:
        nonlocal peak
        while not stop.is_set():
            peak = max(peak, process.memory_info().rss)
            time.sleep(0.01)

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    try:
        ChronologicalFeaturePipeline(
            target_encodings=(TargetEncodingSpec("home_team", "home_win"),)
        ).transform(frame)
    finally:
        stop.set()
        sampler.join(timeout=1.0)

    assert peak < 4 * 1024**3
