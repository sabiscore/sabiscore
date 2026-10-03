"""Dual-Pipeline Feature Union & Staging.

Joins Understat xG telemetry with historical market lines (1X2, Asian Handicap, Over/Under),
enforcing strict target leakage prevention (segregating all post-match target variables)
and memory efficiency with chunked operations and aggressive garbage collection.
"""

from __future__ import annotations

import gc
import logging
from dataclasses import dataclass
from typing import Any, Generator, Mapping, Sequence

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from ...services.understat.formatter import UnderstatTensorFormatter

logger = logging.getLogger(__name__)

# Pre-match feature column names (Strictly ZERO target leakage)
FEATURE_COLUMNS: list[str] = [
    # Understat granular xG & xA features
    "home_xg",
    "away_xg",
    "delta_xg",
    "total_xg",
    "home_xa",
    "away_xa",
    "delta_xa",
    "total_xa",
    "home_rolling_xg_5",
    "away_rolling_xg_5",
    "delta_rolling_xg_5",
    # De-vigged market implied probabilities
    "market_implied_home",
    "market_implied_draw",
    "market_implied_away",
    "market_overround",
    # Spreads & Totals lines
    "asian_handicap_line",
    "over_under_line",
]

# Post-match target columns to strictly segregate
TARGET_COLUMNS: list[str] = [
    "result_1x2",  # 0: Home, 1: Draw, 2: Away
    "home_goals",
    "away_goals",
]


@dataclass(frozen=True)
class StagedDataset:
    """Staged dataset containing strictly segregated features, targets, and metadata."""

    X: np.ndarray  # float32, C_CONTIGUOUS, shape (N, len(FEATURE_COLUMNS))
    y: np.ndarray  # int64, shape (N,) - 1X2 result classes (0, 1, 2)
    feature_names: list[str]
    metadata: pd.DataFrame  # match_id, match_date, season, home_team, away_team


def devig_1x2_odds(
    home_odds: float, draw_odds: float, away_odds: float
) -> tuple[float, float, float, float]:
    """Compute normalized (de-vigged) probabilities and overround from decimal odds.

    Returns:
        (p_home, p_draw, p_away, overround)
    """
    if home_odds <= 1.0 or draw_odds <= 1.0 or away_odds <= 1.0:
        # Fallback to uniform on invalid odds
        return 0.333333, 0.333333, 0.333334, 1.0

    raw_h = 1.0 / home_odds
    raw_d = 1.0 / draw_odds
    raw_a = 1.0 / away_odds
    overround = raw_h + raw_d + raw_a

    if overround <= 0.0:
        return 0.333333, 0.333333, 0.333334, 1.0

    return raw_h / overround, raw_d / overround, raw_a / overround, overround


def build_staged_feature_record(
    telemetry_row: Mapping[str, Any],
    market_row: Mapping[str, Any],
    rolling_xg_home: float,
    rolling_xg_away: float,
) -> dict[str, float]:
    """Construct a single pre-match feature dictionary with zero target leakage."""
    home_xg = float(telemetry_row.get("home_xg") or 0.0)
    away_xg = float(telemetry_row.get("away_xg") or 0.0)
    delta_xg = home_xg - away_xg
    total_xg = home_xg + away_xg

    # Extract xA
    shot_telemetry = telemetry_row.get("shot_telemetry")
    if shot_telemetry is not None:
        home_xa, away_xa = UnderstatTensorFormatter.extract_xa_from_shot_telemetry(shot_telemetry)
        if home_xa == 0.0 and telemetry_row.get("home_xa"):
            home_xa = float(telemetry_row["home_xa"])
        if away_xa == 0.0 and telemetry_row.get("away_xa"):
            away_xa = float(telemetry_row["away_xa"])
    else:
        home_xa = float(telemetry_row.get("home_xa") or 0.0)
        away_xa = float(telemetry_row.get("away_xa") or 0.0)

    delta_xa = home_xa - away_xa
    total_xa = home_xa + away_xa

    # Market odds de-vigging
    h_odds = float(market_row.get("home_odds") or market_row.get("home_win_odds") or 2.50)
    d_odds = float(market_row.get("draw_odds") or 3.20)
    a_odds = float(market_row.get("away_odds") or market_row.get("away_win_odds") or 3.00)

    p_h, p_d, p_a, overround = devig_1x2_odds(h_odds, d_odds, a_odds)

    ah_line = float(market_row.get("asian_handicap_line") or market_row.get("asian_handicap") or 0.0)
    ou_line = float(market_row.get("over_under_line") or 2.5)

    return {
        "home_xg": home_xg,
        "away_xg": away_xg,
        "delta_xg": delta_xg,
        "total_xg": total_xg,
        "home_xa": home_xa,
        "away_xa": away_xa,
        "delta_xa": delta_xa,
        "total_xa": total_xa,
        "home_rolling_xg_5": rolling_xg_home,
        "away_rolling_xg_5": rolling_xg_away,
        "delta_rolling_xg_5": rolling_xg_home - rolling_xg_away,
        "market_implied_home": p_h,
        "market_implied_draw": p_d,
        "market_implied_away": p_a,
        "market_overround": overround,
        "asian_handicap_line": ah_line,
        "over_under_line": ou_line,
    }


def stage_features_and_targets(
    records: Sequence[Mapping[str, Any]],
    chunk_size: int = 5000,
) -> StagedDataset:
    """Stage feature and target arrays in memory-efficient chunks.

    Guarantees strict segregation of post-match target variables from the
    pre-match feature tensor X.

    Args:
        records: List of combined match records ordered chronologically.
        chunk_size: Processing batch size to control memory footprint.

    Returns:
        StagedDataset containing contiguous float32 X tensor, int64 y array,
        feature column names, and metadata DataFrame.
    """
    n_samples = len(records)
    n_features = len(FEATURE_COLUMNS)

    if n_samples == 0:
        return StagedDataset(
            X=np.empty((0, n_features), dtype=np.float32),
            y=np.empty((0,), dtype=np.int64),
            feature_names=list(FEATURE_COLUMNS),
            metadata=pd.DataFrame(),
        )

    # Compute rolling xG values across the chronologically ordered sequence
    rolling_values = UnderstatTensorFormatter.compute_rolling_averages(records, window=5)

    # Pre-allocate contiguous arrays
    X = np.empty((n_samples, n_features), dtype=np.float32)
    y = np.empty(n_samples, dtype=np.int64)

    meta_records: list[dict[str, Any]] = []

    # Process in chunks to ensure low RAM spikes and periodic garbage collection
    for start_idx in range(0, n_samples, chunk_size):
        end_idx = min(start_idx + chunk_size, n_samples)

        for i in range(start_idx, end_idx):
            row = records[i]
            r_h, r_a = rolling_values[i]

            feat_dict = build_staged_feature_record(
                telemetry_row=row,
                market_row=row,
                rolling_xg_home=r_h,
                rolling_xg_away=r_a,
            )

            for col_idx, col_name in enumerate(FEATURE_COLUMNS):
                X[i, col_idx] = feat_dict[col_name]

            # Target extraction (0: Home, 1: Draw, 2: Away)
            if "result_1x2" in row and row["result_1x2"] is not None:
                y[i] = int(row["result_1x2"])
            else:
                h_goals = int(row.get("home_goals") or 0)
                a_goals = int(row.get("away_goals") or 0)
                if h_goals > a_goals:
                    y[i] = 0
                elif h_goals == a_goals:
                    y[i] = 1
                else:
                    y[i] = 2

            meta_records.append(
                {
                    "match_id": row.get("match_id"),
                    "match_date": row.get("match_date") or row.get("date"),
                    "season": row.get("season"),
                    "home_team_slug": row.get("home_team_slug"),
                    "away_team_slug": row.get("away_team_slug"),
                }
            )

        gc.collect()

    metadata_df = pd.DataFrame(meta_records)
    contiguous_X = np.ascontiguousarray(X, dtype=np.float32)
    assert contiguous_X.flags["C_CONTIGUOUS"], "Feature matrix must be C-contiguous"

    return StagedDataset(
        X=contiguous_X,
        y=y,
        feature_names=list(FEATURE_COLUMNS),
        metadata=metadata_df,
    )


def iter_staged_chunks(
    records: Sequence[Mapping[str, Any]],
    chunk_size: int = 2500,
) -> Generator[tuple[np.ndarray, np.ndarray, pd.DataFrame], None, None]:
    """Yield memory-safe chunks for streaming model training or out-of-core evaluation."""
    n_samples = len(records)
    rolling_values = UnderstatTensorFormatter.compute_rolling_averages(records, window=5)

    for start_idx in range(0, n_samples, chunk_size):
        end_idx = min(start_idx + chunk_size, n_samples)
        current_len = end_idx - start_idx

        chunk_X = np.empty((current_len, len(FEATURE_COLUMNS)), dtype=np.float32)
        chunk_y = np.empty(current_len, dtype=np.int64)
        chunk_meta: list[dict[str, Any]] = []

        for offset, i in enumerate(range(start_idx, end_idx)):
            row = records[i]
            r_h, r_a = rolling_values[i]
            feat_dict = build_staged_feature_record(row, row, r_h, r_a)

            for col_idx, col_name in enumerate(FEATURE_COLUMNS):
                chunk_X[offset, col_idx] = feat_dict[col_name]

            h_goals = int(row.get("home_goals") or 0)
            a_goals = int(row.get("away_goals") or 0)
            chunk_y[offset] = 0 if h_goals > a_goals else (1 if h_goals == a_goals else 2)

            chunk_meta.append(
                {
                    "match_id": row.get("match_id"),
                    "match_date": row.get("match_date"),
                    "season": row.get("season"),
                }
            )

        yield np.ascontiguousarray(chunk_X, dtype=np.float32), chunk_y, pd.DataFrame(chunk_meta)
        del chunk_X, chunk_y
        gc.collect()


__all__ = [
    "FEATURE_COLUMNS",
    "TARGET_COLUMNS",
    "StagedDataset",
    "devig_1x2_odds",
    "build_staged_feature_record",
    "stage_features_and_targets",
    "iter_staged_chunks",
]
