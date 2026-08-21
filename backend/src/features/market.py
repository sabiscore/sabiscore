"""Market movement features from opening→closing odds.

5 features per matchup:
  odds_drift_home      — implied probability shift (closing − opening) for home win
  odds_drift_draw      — implied probability shift for draw
  odds_drift_away      — implied probability shift for away win
  max_abs_odds_drift   — magnitude of the largest drift across all outcomes
  sharp_money_direction — 0=home, 1=draw, 2=away (outcome with max absolute drift)

Implied probability = 1 / decimal_odds. Positive drift → market moved toward
that outcome (sharp money flowing in).

B13 compliance: if odds are unavailable, the caller should surface DATA_GAP
rather than passing zeroed odds. Zeroed odds return a feature vector of zeros.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

MARKET_FEATURE_NAMES: List[str] = [
    "odds_drift_home",
    "odds_drift_draw",
    "odds_drift_away",
    "max_abs_odds_drift",
    "sharp_money_direction",
]

_DATA_GAP_FEATURES: Dict[str, float] = {k: 0.0 for k in MARKET_FEATURE_NAMES}
_DATA_GAP_FRESHNESS: Dict[str, Optional[int]] = {k: None for k in MARKET_FEATURE_NAMES}


@dataclass(frozen=True)
class MarketDriftResult:
    """Result from compute_market_drift.

    Attributes:
        features: Dict of 5 market movement feature values.
        data_gaps: Feature names that could not be computed (empty = all live).
        per_feature_freshness_seconds: Seconds since opening snapshot was captured.
            0 means unavailable (DATA_GAP). Positive = staleness of the drift signal.
    """

    features: Dict[str, float]
    data_gaps: List[str]
    per_feature_freshness_seconds: Dict[str, Optional[int]]


def _implied(odds: float) -> float:
    """Convert decimal odds to implied probability. Returns 0.0 for invalid odds."""
    return 1.0 / odds if odds > 1.01 else 0.0


def market_movement_features(
    opening_odds: Dict[str, float],
    closing_odds: Dict[str, float],
) -> Dict[str, float]:
    """Compute market movement features from decimal opening/closing odds.

    Args:
        opening_odds: Dict with keys "home", "draw", "away" (decimal odds).
        closing_odds: Dict with keys "home", "draw", "away" (decimal odds).

    Returns:
        Dict with 5 market movement features.
    """
    outcomes = ("home", "draw", "away")
    drifts: Dict[str, float] = {}
    for out in outcomes:
        open_imp = _implied(opening_odds.get(out, 0.0))
        close_imp = _implied(closing_odds.get(out, 0.0))
        drifts[f"odds_drift_{out}"] = round(close_imp - open_imp, 4)

    abs_drifts = {k: abs(v) for k, v in drifts.items()}
    max_key = max(abs_drifts, key=abs_drifts.__getitem__)
    max_abs = abs_drifts[max_key]

    direction_map = {
        "odds_drift_home": 0.0,
        "odds_drift_draw": 1.0,
        "odds_drift_away": 2.0,
    }

    return {
        **drifts,
        "max_abs_odds_drift": round(max_abs, 4),
        "sharp_money_direction": direction_map[max_key],
    }


async def compute_market_drift(
    current_odds: Dict[str, float],
    match_id: str,
    db: "AsyncSession",
    max_staleness_hours: int = 24,
) -> MarketDriftResult:
    """Compute opening→current odds drift with staleness gate.

    Queries OddsHistory for the earliest snapshot (opening) for the given match_id,
    then computes drift against current_odds. If no opening snapshot exists or the
    snapshot is older than max_staleness_hours, returns all 5 features as DATA_GAP.

    B13: any missing live input returns DATA_GAP rather than zeros without flagging.

    Args:
        current_odds: Current market odds dict — keys "home_win", "draw", "away_win".
                      Typically the output of OddsService.get_match_odds().
        match_id:     Database match ID for the OddsHistory lookup.
        db:           Async SQLAlchemy session.
        max_staleness_hours: Threshold above which an opening snapshot is treated as
                      stale (defaults to ODDS_STALENESS_MAX_HOURS env var value).

    Returns:
        MarketDriftResult — data_gaps is empty when all 5 features are live.
    """
    _gap = MarketDriftResult(
        features=dict(_DATA_GAP_FEATURES),
        data_gaps=list(MARKET_FEATURE_NAMES),
        per_feature_freshness_seconds=dict(_DATA_GAP_FRESHNESS),
    )

    # Validate current odds before any DB work
    closing = {
        "home": current_odds.get("home_win", 0.0),
        "draw": current_odds.get("draw", 0.0),
        "away": current_odds.get("away_win", 0.0),
    }
    if not all(v > 1.01 for v in closing.values()):
        logger.debug("compute_market_drift: invalid current odds for match %s", match_id)
        return _gap

    opening_record = None
    try:
        from sqlalchemy import asc, select

        from ..db.models import OddsHistory

        query = (
            select(OddsHistory)
            .where(OddsHistory.match_id == match_id)
            .where(OddsHistory.market_type == "match_odds")
            .order_by(asc(OddsHistory.timestamp))
            .limit(1)
        )
        result = await db.execute(query)
        opening_record = result.scalar_one_or_none()
    except Exception as exc:
        logger.debug("compute_market_drift: OddsHistory query failed for %s: %s", match_id, exc)

    if opening_record is None:
        return _gap

    opening_time = opening_record.timestamp
    if opening_time is None:
        return _gap
    if opening_time.tzinfo is None:
        opening_time = opening_time.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    staleness_seconds = max(0, int((now - opening_time).total_seconds()))

    if staleness_seconds > max_staleness_hours * 3600:
        logger.debug(
            "compute_market_drift: opening snapshot stale (%ds > %dh) for match %s",
            staleness_seconds,
            max_staleness_hours,
            match_id,
        )
        return _gap

    opening = {
        "home": opening_record.home_win or 0.0,
        "draw": opening_record.draw or 0.0,
        "away": opening_record.away_win or 0.0,
    }
    if not all(v > 1.01 for v in opening.values()):
        return _gap

    features = market_movement_features(opening, closing)
    freshness = {k: staleness_seconds for k in MARKET_FEATURE_NAMES}

    return MarketDriftResult(
        features=features,
        data_gaps=[],
        per_feature_freshness_seconds=freshness,
    )
