"""Candidate-M / Candidate-MA feature staging.

Stages point-in-time (PIT) safe training matrices from chronologically ordered
Understat telemetry joined (optionally) to historical market quotes.

Contract (V21.1):

* **Candidate-M** contains market-independent predictors only. Today that is the
  rolling five-match xG family computed strictly from matches that finished
  *before* the fixture. The fixture's own xG/xA/shots are post-match evidence
  and are never part of its own pre-match vector.
* **Candidate-MA** (``include_market=True``) additionally carries de-vigged
  market features. It is labelled ``MARKET-AWARE RESEARCH`` and is never an
  independent-alpha / Candidate-M artifact.
* Missing evidence is never replaced by a plausible value. A row that lacks the
  required history, market provenance, odds, or outcome is **excluded** and the
  exclusion (with a reason code) is recorded on the dataset.
"""

from __future__ import annotations

import gc
import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Generator, Mapping, Sequence

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from ...services.understat.formatter import UnderstatTensorFormatter

logger = logging.getLogger(__name__)

ROLLING_WINDOW: int = 5

# ---------------------------------------------------------------------------
# Feature registries
# ---------------------------------------------------------------------------

#: Market-independent, strictly pre-match predictors.
CANDIDATE_M_FEATURE_COLUMNS: list[str] = [
    "home_rolling_xg_5",
    "away_rolling_xg_5",
    "delta_rolling_xg_5",
]

#: Market-derived columns. Allowed only in the MARKET-AWARE RESEARCH feature set.
CANDIDATE_MA_MARKET_COLUMNS: list[str] = [
    "market_implied_home",
    "market_implied_draw",
    "market_implied_away",
    "market_overround",
    "asian_handicap_line",
    "over_under_line",
]

CANDIDATE_MA_FEATURE_COLUMNS: list[str] = [
    *CANDIDATE_M_FEATURE_COLUMNS,
    *CANDIDATE_MA_MARKET_COLUMNS,
]

#: Default feature list: Candidate-M (market independent).
FEATURE_COLUMNS: list[str] = list(CANDIDATE_M_FEATURE_COLUMNS)

FEATURE_SET_CANDIDATE_M = "CANDIDATE_M"
FEATURE_SET_CANDIDATE_MA = "MARKET-AWARE RESEARCH"

#: Substrings that make a column market-derived (case-insensitive).
MARKET_CONTAMINATION_TOKENS: tuple[str, ...] = (
    "market",
    "odds",
    "implied",
    "devig",
    "closing",
    "opening",
    "bookmaker",
    "drift",
    "favorite",
    "entropy",
    "overround",
    "handicap",
    "over_under",
)

# Post-match target columns to strictly segregate
TARGET_COLUMNS: list[str] = [
    "result_1x2",  # 0: Home, 1: Draw, 2: Away
    "home_goals",
    "away_goals",
]

# Exclusion reason codes
REASON_INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
REASON_MARKET_UNAVAILABLE = "MARKET_UNAVAILABLE"
REASON_MARKET_PROVENANCE_MISSING = "MARKET_PROVENANCE_MISSING"
REASON_TARGET_UNAVAILABLE = "TARGET_UNAVAILABLE"


class InsufficientEvidenceError(ValueError):
    """Required evidence is unavailable; the row must be excluded, never filled."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


class MarketContaminationError(ValueError):
    """A market-derived column was found in the Candidate-M feature list."""


def find_market_contaminated_columns(columns: Sequence[str]) -> list[str]:
    """Return every column whose name carries a market-derived token."""
    return [
        col
        for col in columns
        if any(token in col.lower() for token in MARKET_CONTAMINATION_TOKENS)
    ]


def assert_candidate_m_purity(columns: Sequence[str]) -> None:
    """Fail closed if ``columns`` contains any market-derived feature."""
    bad = find_market_contaminated_columns(columns)
    if bad:
        raise MarketContaminationError(
            f"Candidate-M must be market independent; contaminated columns: {bad}"
        )


def feature_list_sha256(columns: Sequence[str]) -> str:
    """Deterministic SHA-256 of the ordered feature list."""
    payload = json.dumps(list(columns), separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# Import-time guard: the registered Candidate-M list can never silently regress.
assert_candidate_m_purity(CANDIDATE_M_FEATURE_COLUMNS)


@dataclass(frozen=True)
class StagedDataset:
    """Staged dataset containing strictly segregated features, targets, and metadata."""

    X: np.ndarray  # float32, C_CONTIGUOUS, shape (N, len(feature_names))
    y: np.ndarray  # int64, shape (N,) - 1X2 result classes (0, 1, 2)
    feature_names: list[str]
    metadata: pd.DataFrame  # match_id, match_date, season, home_team, away_team
    feature_set: str = FEATURE_SET_CANDIDATE_M
    #: (match_id, reason_code) for every input row excluded for missing evidence.
    excluded: tuple[tuple[Any, str], ...] = field(default_factory=tuple)

    @property
    def excluded_count(self) -> int:
        return len(self.excluded)

    @property
    def feature_list_sha256(self) -> str:
        return feature_list_sha256(self.feature_names)


def devig_1x2_odds(
    home_odds: float, draw_odds: float, away_odds: float
) -> tuple[float, float, float, float]:
    """Compute normalized (de-vigged) probabilities and overround from decimal odds.

    Raises:
        ValueError: when any price is not a valid decimal quote (> 1.0). There is
            no uniform-probability fallback: invalid prices are unavailable
            evidence, not a neutral market.

    Returns:
        (p_home, p_draw, p_away, overround)
    """
    if home_odds <= 1.0 or draw_odds <= 1.0 or away_odds <= 1.0:
        raise ValueError("Decimal odds must all be > 1.0 to de-vig a 1X2 market")

    raw_h = 1.0 / home_odds
    raw_d = 1.0 / draw_odds
    raw_a = 1.0 / away_odds
    overround = raw_h + raw_d + raw_a
    return raw_h / overround, raw_d / overround, raw_a / overround, overround


def _first_present(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None:
            return value
    return None


def _market_features(row: Mapping[str, Any]) -> dict[str, float]:
    """Build market-aware research features from a single bookmaker snapshot."""
    if not row.get("market_timestamp") or not row.get("bookmaker"):
        raise InsufficientEvidenceError(
            REASON_MARKET_PROVENANCE_MISSING,
            "market_timestamp and bookmaker are required for market-aware features",
        )

    h = _first_present(row, "home_odds", "home_win_odds")
    d = _first_present(row, "draw_odds")
    a = _first_present(row, "away_odds", "away_win_odds")
    ah = _first_present(row, "asian_handicap_line", "asian_handicap")
    ou = _first_present(row, "over_under_line")
    if h is None or d is None or a is None or ah is None or ou is None:
        raise InsufficientEvidenceError(
            REASON_MARKET_UNAVAILABLE, "1X2 prices and spread/total lines are required"
        )

    try:
        p_h, p_d, p_a, overround = devig_1x2_odds(float(h), float(d), float(a))
    except ValueError as exc:
        raise InsufficientEvidenceError(REASON_MARKET_UNAVAILABLE, str(exc)) from exc

    return {
        "market_implied_home": p_h,
        "market_implied_draw": p_d,
        "market_implied_away": p_a,
        "market_overround": overround,
        "asian_handicap_line": float(ah),
        "over_under_line": float(ou),
    }


def build_staged_feature_record(
    row: Mapping[str, Any],
    rolling_xg_home: float | None,
    rolling_xg_away: float | None,
    *,
    include_market: bool = False,
) -> dict[str, float]:
    """Construct one pre-match feature dictionary with zero target/post-match leakage.

    ``row`` is only consulted for *market* evidence (when ``include_market``);
    its own xG/xA/shot telemetry is deliberately ignored.

    Raises:
        InsufficientEvidenceError: rolling history or (optionally) market evidence
            is unavailable.
    """
    if rolling_xg_home is None or rolling_xg_away is None:
        raise InsufficientEvidenceError(
            REASON_INSUFFICIENT_HISTORY,
            f"fewer than {ROLLING_WINDOW} prior completed matches",
        )

    features: dict[str, float] = {
        "home_rolling_xg_5": float(rolling_xg_home),
        "away_rolling_xg_5": float(rolling_xg_away),
        "delta_rolling_xg_5": float(rolling_xg_home) - float(rolling_xg_away),
    }
    if include_market:
        features.update(_market_features(row))
    return features


def _extract_target(row: Mapping[str, Any]) -> int:
    """Return the 1X2 outcome class or raise; a missing score is never a 0-0 draw."""
    result = row.get("result_1x2")
    if result is not None:
        return int(result)
    h_goals = row.get("home_goals")
    a_goals = row.get("away_goals")
    if h_goals is None or a_goals is None:
        raise InsufficientEvidenceError(
            REASON_TARGET_UNAVAILABLE, "no settled result for the fixture"
        )
    if int(h_goals) > int(a_goals):
        return 0
    if int(h_goals) == int(a_goals):
        return 1
    return 2


def _stage_rows(
    records: Sequence[Mapping[str, Any]],
    include_market: bool,
) -> tuple[list[np.ndarray], list[int], list[dict[str, Any]], list[tuple[Any, str]]]:
    columns = CANDIDATE_MA_FEATURE_COLUMNS if include_market else CANDIDATE_M_FEATURE_COLUMNS
    if not include_market:
        assert_candidate_m_purity(columns)

    rolling_values = UnderstatTensorFormatter.compute_rolling_averages(
        records, window=ROLLING_WINDOW
    )

    rows: list[np.ndarray] = []
    targets: list[int] = []
    meta: list[dict[str, Any]] = []
    excluded: list[tuple[Any, str]] = []

    for i, row in enumerate(records):
        r_h, r_a = rolling_values[i]
        try:
            feat = build_staged_feature_record(
                row, r_h, r_a, include_market=include_market
            )
            y_val = _extract_target(row)
        except InsufficientEvidenceError as exc:
            excluded.append((row.get("match_id"), exc.reason))
            continue

        rows.append(np.fromiter((feat[c] for c in columns), dtype=np.float32, count=len(columns)))
        targets.append(y_val)
        meta.append(
            {
                "match_id": row.get("match_id"),
                "match_date": row.get("match_date") or row.get("date"),
                "season": row.get("season"),
                "home_team_slug": row.get("home_team_slug"),
                "away_team_slug": row.get("away_team_slug"),
            }
        )
    return rows, targets, meta, excluded


def stage_features_and_targets(
    records: Sequence[Mapping[str, Any]],
    chunk_size: int = 5000,
    *,
    include_market: bool = False,
) -> StagedDataset:
    """Stage PIT-safe feature and target arrays.

    Rows lacking required evidence are excluded and reported in
    ``StagedDataset.excluded``; nothing is imputed.

    Args:
        records: Match records ordered chronologically (verified when the rows
            carry ``kickoff_utc``/``match_date``/``date``).
        chunk_size: Retained for API compatibility (memory-release cadence).
        include_market: Build the MARKET-AWARE RESEARCH feature set instead of
            the market-independent Candidate-M set.
    """
    columns = list(CANDIDATE_MA_FEATURE_COLUMNS if include_market else CANDIDATE_M_FEATURE_COLUMNS)
    feature_set = FEATURE_SET_CANDIDATE_MA if include_market else FEATURE_SET_CANDIDATE_M

    rows, targets, meta, excluded = _stage_rows(records, include_market)
    n = len(rows)

    if n:
        X = np.ascontiguousarray(np.vstack(rows), dtype=np.float32)
    else:
        X = np.empty((0, len(columns)), dtype=np.float32)
    y = np.asarray(targets, dtype=np.int64)
    gc.collect()

    return StagedDataset(
        X=X,
        y=y,
        feature_names=columns,
        metadata=pd.DataFrame(meta),
        feature_set=feature_set,
        excluded=tuple(excluded),
    )


def iter_staged_chunks(
    records: Sequence[Mapping[str, Any]],
    chunk_size: int = 2500,
    *,
    include_market: bool = False,
) -> Generator[tuple[np.ndarray, np.ndarray, pd.DataFrame], None, None]:
    """Yield memory-safe chunks of *valid* staged rows (excluded rows are skipped)."""
    columns = CANDIDATE_MA_FEATURE_COLUMNS if include_market else CANDIDATE_M_FEATURE_COLUMNS
    rows, targets, meta, excluded = _stage_rows(records, include_market)
    if excluded:
        logger.info("Staging excluded %d rows for missing evidence", len(excluded))

    for start in range(0, len(rows), chunk_size):
        end = min(start + chunk_size, len(rows))
        chunk_X = np.ascontiguousarray(np.vstack(rows[start:end]), dtype=np.float32)
        chunk_y = np.asarray(targets[start:end], dtype=np.int64)
        assert chunk_X.shape[1] == len(columns)
        yield chunk_X, chunk_y, pd.DataFrame(meta[start:end])
        del chunk_X, chunk_y
        gc.collect()


__all__ = [
    "CANDIDATE_M_FEATURE_COLUMNS",
    "CANDIDATE_MA_FEATURE_COLUMNS",
    "CANDIDATE_MA_MARKET_COLUMNS",
    "FEATURE_COLUMNS",
    "FEATURE_SET_CANDIDATE_M",
    "FEATURE_SET_CANDIDATE_MA",
    "MARKET_CONTAMINATION_TOKENS",
    "TARGET_COLUMNS",
    "InsufficientEvidenceError",
    "MarketContaminationError",
    "StagedDataset",
    "assert_candidate_m_purity",
    "build_staged_feature_record",
    "devig_1x2_odds",
    "feature_list_sha256",
    "find_market_contaminated_columns",
    "iter_staged_chunks",
    "stage_features_and_targets",
]
