"""Phase 9 candidate feature builders: hybrid xG + market efficiency.

These functions produce optional additive features. The existing canonical Phase 8 89-feature
model frame ignores them until the feature registry and model artifacts are
intentionally expanded through the walk-forward retraining gate (see
``backend/scripts/retrain_with_expanded_features.py`` and
``backend/scripts/validate_feature_expansion.py``). They are safe for
shadow-mode logging and offline ablation from day one.

Module structure
----------------
``build_hybrid_xg_features``
    Combines Phase 8 team-stats xG (``team_stats["home"]["xg_avg_5"]`` etc.,
    as produced by ``DataAggregator.fetch_team_stats`` /
    ``_create_mock_team_stats``) with optional Understat rolling xG.
    Output is deterministic, all-float, metadata-safe.

``build_value_market_features``
    Thin wrapper around ``compute_market_features`` for use in
    ``PredictionService`` after probabilities are computed.

``build_market_efficiency_report``
    Structured human-readable report for logging / enriched API metadata.
    Includes vig, sharpness, and value-bet flags per outcome. This is the
    function wired into ``PredictionService`` because it nests the raw
    ``compute_market_features`` output under ``"features"`` while adding
    bookmaker margin, sharp-line probabilities, and a `value_bets` list —
    higher shadow-mode signal for the same pure-math cost.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

import pandas as pd

from ..connectors.odds_market import (
    bookmaker_margin,
    compute_market_features,
    implied_probabilities,
    is_complete_market,
    normalize_decimal_odds,
    power_method_probs,
)

# ---------------------------------------------------------------------------
# Internal utilities
# ---------------------------------------------------------------------------


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert ``value`` to float, returning ``default`` on any failure.

    Handles ``None``, ``float('nan')``, ``float('inf')``, non-numeric strings,
    and numpy scalar types safely.
    """
    try:
        if value is None:
            return default
        result = float(value)
        if not math.isfinite(result):
            return default
        return result
    except (TypeError, ValueError):
        return default


def _latest_team_row(rollups: pd.DataFrame, team: str) -> pd.Series | None:
    """Return the most-recent rollup row for ``team`` using casefold matching.

    If a ``match_order`` column is present, rows are sorted by it before
    taking the last one — this is critical for correct temporal ordering
    when data arrives out-of-sequence.

    Casefold comparison means "Arsenal" == "arsenal" == "ARSENAL".
    """
    if rollups.empty or "team" not in rollups.columns:
        return None
    mask = rollups["team"].astype(str).str.casefold().eq(team.casefold())
    candidates = rollups[mask]
    if candidates.empty:
        return None
    if "match_order" in candidates.columns:
        candidates = candidates.sort_values("match_order")
    return candidates.iloc[-1]


def _kelly_fraction(model_prob: float, decimal_price: float) -> float:
    """Raw Kelly stake signal for a single back bet.

    ``f* = (b * p - q) / b`` where ``b = price - 1`` (net decimal odds),
    ``p = model_prob``, and ``q = 1 - p``. Clamped to ``[0.0, 1.0]`` — a
    negative Kelly (no edge) returns 0.0, and the result never exceeds the
    whole bankroll. Practitioners typically scale this down (e.g. half- or
    quarter-Kelly) to reduce variance; this returns the canonical full-Kelly
    quantity and leaves that scaling to the consumer.
    """
    b = decimal_price - 1.0
    if b <= 0.0:
        return 0.0
    p = max(0.0, min(1.0, model_prob))
    q = 1.0 - p
    f = (b * p - q) / b
    return max(0.0, min(1.0, f))


# ---------------------------------------------------------------------------
# Hybrid xG feature builder
# ---------------------------------------------------------------------------


def build_hybrid_xg_features(
    *,
    home_team: str,
    away_team: str,
    team_stats: Mapping[str, Mapping[str, Any]] | None = None,
    understat_rollups: pd.DataFrame | None = None,
) -> dict[str, float]:
    """Combine Phase 8 team-stats xG with optional Understat rolling xG.

    Priority
    --------
    When Understat rollups are available *and* contain a matching team row,
    the Understat rolling values override the team-stats scraped values for
    the ``xg_diff`` calculation only.  All raw values are always emitted so
    downstream SHAP / ablation can compare them.

    Parameters
    ----------
    home_team, away_team:
        Canonical team names (used for Understat lookup; casefold matched).
    team_stats:
        Dict keyed ``"home"`` / ``"away"``, each with at least:
        ``xg_avg_5`` (rolling mean xG for over 5 games) and
        ``xg_conceded_avg_5`` (rolling mean xG against over 5 games).
        This matches the shape returned by
        ``DataAggregator.fetch_team_stats`` / ``_create_mock_team_stats``.
    understat_rollups:
        DataFrame produced by ``UnderstatTeamXGSource.rolling_xg_features``.
        Expected columns: ``team``, ``rolling_xg_for``, ``rolling_xg_against``,
        ``rolling_xg_diff``, ``match_order``. Typically ``None`` at request
        time (offline-only source) and only populated during backfill-driven
        shadow analysis.

    Returns
    -------
    dict of str -> float
        All values are finite floats (zero-default on missing data).
        Keys are prefixed ``hybrid_`` or ``understat_`` to avoid collisions
        with existing Phase 8 feature names (``xg_avg_5``, ``xg_diff_5``, etc.
        remain untouched).
    """
    team_stats = team_stats or {}
    home_stats = dict(team_stats.get("home") or {})
    away_stats = dict(team_stats.get("away") or {})

    features: dict[str, float] = {
        "hybrid_home_xg_for_5": _safe_float(home_stats.get("xg_avg_5")),
        "hybrid_home_xg_against_5": _safe_float(home_stats.get("xg_conceded_avg_5")),
        "hybrid_away_xg_for_5": _safe_float(away_stats.get("xg_avg_5")),
        "hybrid_away_xg_against_5": _safe_float(away_stats.get("xg_conceded_avg_5")),
    }

    if understat_rollups is not None and not understat_rollups.empty:
        for side, team in (("home", home_team), ("away", away_team)):
            row = _latest_team_row(understat_rollups, team)
            if row is not None:
                features[f"understat_{side}_rolling_xg_for"] = _safe_float(
                    row.get("rolling_xg_for")
                )
                features[f"understat_{side}_rolling_xg_against"] = _safe_float(
                    row.get("rolling_xg_against")
                )
                features[f"understat_{side}_rolling_xg_diff"] = _safe_float(
                    row.get("rolling_xg_diff")
                )

    # xG differential: prefer Understat rolling diff when available.
    home_xg_diff = features.get(
        "understat_home_rolling_xg_diff",
        features["hybrid_home_xg_for_5"] - features["hybrid_home_xg_against_5"],
    )
    away_xg_diff = features.get(
        "understat_away_rolling_xg_diff",
        features["hybrid_away_xg_for_5"] - features["hybrid_away_xg_against_5"],
    )
    features["hybrid_xg_diff"] = home_xg_diff - away_xg_diff

    # Expected total goals proxy: mean of all four xG flows.
    # (home_for + away_for + home_against + away_against) / 2
    features["hybrid_total_xg_expectation"] = (
        features["hybrid_home_xg_for_5"]
        + features["hybrid_away_xg_for_5"]
        + features["hybrid_home_xg_against_5"]
        + features["hybrid_away_xg_against_5"]
    ) / 2.0

    return {key: float(val) for key, val in features.items()}


# ---------------------------------------------------------------------------
# Market value feature builder (thin wrapper for PredictionService)
# ---------------------------------------------------------------------------


def build_value_market_features(
    *,
    model_probabilities: Mapping[str, float],
    opening_odds: Mapping[str, float] | None = None,
    current_odds: Mapping[str, float] | None = None,
    closing_odds: Mapping[str, float] | None = None,
) -> dict[str, float | None]:
    """Compute market-efficiency features for use in ``PredictionService``.

    This is a direct pass-through to ``compute_market_features`` to keep
    the import chain clean and the function name self-documenting in the
    service layer. Prefer ``build_market_efficiency_report`` for the richer,
    nested shadow-mode metadata shape.
    """
    return compute_market_features(
        model_probabilities=model_probabilities,
        opening_odds=opening_odds,
        current_odds=current_odds,
        closing_odds=closing_odds,
    )


# ---------------------------------------------------------------------------
# Rich market efficiency report (for metadata / logging)
# ---------------------------------------------------------------------------


def build_market_efficiency_report(
    *,
    model_probabilities: Mapping[str, float],
    opening_odds: Mapping[str, float] | None = None,
    current_odds: Mapping[str, float] | None = None,
    closing_odds: Mapping[str, float] | None = None,
    ev_threshold: float = 0.0,
) -> dict[str, Any]:
    """Produce a structured market-efficiency report for logging / metadata.

    Extends the raw ``compute_market_features`` output with human-readable
    value-bet flags, bookmaker margin, sharp-line probability estimates, and
    full-Kelly stake sizing per value bet.

    Parameters
    ----------
    ev_threshold:
        Minimum EV to flag an outcome as a value bet (default 0 = any +EV).

    Returns
    -------
    dict
        Serialisable report dict; safe to embed directly in prediction
        metadata under ``metadata["phase9_candidate_features"]["market_efficiency"]``.
        Notable fields:

        - ``market_complete`` — whether all three 1X2 outcomes were priced.
        - ``market_sharpness`` — ``"sharp"`` / ``"standard"`` / ``"unknown"``
          (``"unknown"`` whenever the market is incomplete, so a partial-market
          margin is never misread as sharp).
        - ``value_bets`` — sorted by descending ``kelly_fraction``; each entry
          carries a full-Kelly ``kelly_fraction`` in ``[0, 1]``.
        - ``recommended_kelly_fraction`` — the top value bet's Kelly fraction,
          or ``None`` when there is no +EV outcome.
    """
    raw_features = compute_market_features(
        model_probabilities=model_probabilities,
        opening_odds=opening_odds,
        current_odds=current_odds,
        closing_odds=closing_odds,
    )

    current = normalize_decimal_odds(current_odds or {})
    sharp_probs = power_method_probs(current) if current else {}
    margin = bookmaker_margin(current) if current else 0.0
    market_implied = implied_probabilities(current) if current else {}
    complete_market = is_complete_market(current_odds or {})

    value_bets: list[dict[str, Any]] = []
    for market in ("home_win", "draw", "away_win"):
        ev = raw_features.get(f"ev_{market}")
        if ev is not None and ev > ev_threshold:
            model_prob = float(model_probabilities.get(market) or 0.0)
            price = current.get(market)
            value_bets.append(
                {
                    "outcome": market,
                    "model_prob": model_prob,
                    "market_implied_prob": market_implied.get(market),
                    "sharp_implied_prob": sharp_probs.get(market),
                    "current_price": price,
                    "ev": ev,
                    "edge": raw_features.get(f"edge_{market}"),
                    "clv": raw_features.get(f"clv_{market}"),
                    "odds_drift": raw_features.get(f"odds_drift_{market}"),
                    "kelly_fraction": (
                        _kelly_fraction(model_prob, price) if price else None
                    ),
                }
            )

    # Sort value bets by descending Kelly so the strongest opportunity leads.
    value_bets.sort(key=lambda vb: vb.get("kelly_fraction") or 0.0, reverse=True)

    # Sharpness is only well-defined over a complete 1X2 market; a partial
    # market can produce a negative "margin" that would otherwise be
    # misclassified as "sharp".
    if not complete_market:
        market_sharpness = "unknown"
    elif margin < 0.04:
        market_sharpness = "sharp"
    else:
        market_sharpness = "standard"

    return {
        "bookmaker_margin": margin,
        "market_complete": complete_market,
        "market_sharpness": market_sharpness,
        "features": raw_features,
        "value_bets": value_bets,
        "has_value": len(value_bets) > 0,
        "max_ev": raw_features.get("max_ev"),
        "max_edge": raw_features.get("max_edge"),
        "max_abs_odds_drift": raw_features.get("max_abs_odds_drift"),
        "recommended_kelly_fraction": (
            value_bets[0]["kelly_fraction"] if value_bets else None
        ),
        "clv_available": closing_odds is not None and bool(normalize_decimal_odds(closing_odds)),
    }
