"""Odds normalisation and market-efficiency feature helpers.

Pure functions — no network I/O, no cache, no external state. Safe to call
from ``PredictionService``, training scripts, or backtests without adding
latency or new dependencies.

Relationship to ``features/market.py``
---------------------------------------
``backend/src/features/market.py::market_movement_features`` is the existing
*production* Phase 8 feature (feeds the canonical Phase 8 model frame) and uses
``{"home", "draw", "away"}`` keys with opening/closing odds only.

This module is a **separate, additive, Phase 9-candidate** layer that:

- Uses the request-schema key convention ``{"home_win", "draw", "away_win"}``
  (matches ``MatchPredictionRequest.odds``).
- Computes EV, edge, CLV, and vig-aware ("sharp") probabilities — none of
  which exist in the Phase 8 production feature set.
- Is consumed only via ``features/phase9_xg_market_features.py`` and only
  ever written to ``metadata`` (never to the model feature frame) while
  ``PHASE9_SHADOW_ONLY=true``.

There is intentionally no name collision with ``market.py`` — the two
modules can coexist indefinitely.

Drift convention
----------------
We use *log-ratio* drift rather than simple price difference::

    drift = ln(current_price / opening_price)

Log-ratio is scale-invariant (a 2.0 → 2.2 move is the same magnitude as
4.0 → 4.4), additive over time intervals, and sign-symmetric around zero.
A positive drift means the market lengthened (probability shortened); negative
means the market shortened (probability lengthened).

CLV (Closing Line Value)
------------------------
CLV is only defined *post-match* once closing prices are available. Do not
label pre-match EV as CLV. Store ``closing_odds`` from a closing snapshot
captured no earlier than ~60 s before kick-off.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Mapping

MARKETS_1X2: tuple[str, ...] = ("home_win", "draw", "away_win")

# Minimum valid decimal odds.  Anything <= 1.0 is invalid.
_MIN_VALID_PRICE: float = 1.0001


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OddsMarketSnapshot:
    """Immutable point-in-time odds record for one bookmaker's 1X2 market."""

    bookmaker: str
    captured_at: datetime
    odds: Mapping[str, float]
    is_closing: bool = False

    @classmethod
    def now(
        cls,
        bookmaker: str,
        odds: Mapping[str, float],
        *,
        is_closing: bool = False,
    ) -> "OddsMarketSnapshot":
        return cls(
            bookmaker=bookmaker,
            captured_at=datetime.now(UTC),
            odds=odds,
            is_closing=is_closing,
        )


# ---------------------------------------------------------------------------
# Core normalisers
# ---------------------------------------------------------------------------


def normalize_decimal_odds(odds: Mapping[str, float]) -> dict[str, float]:
    """Return only the valid decimal prices from a 1X2 odds mapping.

    Invalid entries (non-numeric, <= 1, NaN, inf) are silently dropped so
    downstream functions never divide by zero or produce nonsense. Keys
    outside ``MARKETS_1X2`` (e.g. BTTS / over-under markets) are ignored.
    """
    normalised: dict[str, float] = {}
    for market in MARKETS_1X2:
        raw = odds.get(market)
        try:
            price = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if math.isfinite(price) and price > _MIN_VALID_PRICE:
            normalised[market] = price
    return normalised


def is_complete_market(odds: Mapping[str, float]) -> bool:
    """True only when all three 1X2 outcomes have valid decimal prices.

    The overround / margin concept is only well-defined over a *complete*
    market. A partial market (e.g. only ``home_win`` priced) yields a
    meaningless — and potentially negative — "margin", so callers that
    classify sharpness should gate on this.
    """
    return len(normalize_decimal_odds(odds)) == len(MARKETS_1X2)


def bookmaker_margin(odds: Mapping[str, float]) -> float:
    """Bookmaker overround (margin) — higher means more vig.

    A fair book has margin = 0.0; a typical ~5% bookmaker book returns ~0.05.

    Note: the margin is only meaningful over a *complete* 1X2 market. For a
    partial market this returns the partial overround (which can be negative
    when fewer than three outcomes are priced) — use ``is_complete_market``
    to guard any decision that depends on the margin being well-defined.
    """
    clean = normalize_decimal_odds(odds)
    if not clean:
        return 0.0
    return sum(1.0 / p for p in clean.values()) - 1.0


# ---------------------------------------------------------------------------
# Implied-probability methods
# ---------------------------------------------------------------------------


def implied_probabilities(
    odds: Mapping[str, float],
    *,
    remove_vig: bool = True,
) -> dict[str, float]:
    """Convert decimal odds to implied probabilities.

    With ``remove_vig=True`` (default) this is simple proportional
    normalisation (each raw implied probability divided by the overround
    total).  This is fast and appropriate for most use-cases.

    See ``power_method_probs`` for a sharper (margin-proportional) approach.
    """
    clean = normalize_decimal_odds(odds)
    raw = {m: 1.0 / p for m, p in clean.items()}
    total = sum(raw.values())
    if remove_vig and total > 0.0:
        return {m: p / total for m, p in raw.items()}
    return raw


def power_method_probs(odds: Mapping[str, float]) -> dict[str, float]:
    """Remove vig using the power / margin-proportional method.

    Solves for *k* such that ``sum (1/o_i)^(1/k) = 1`` via binary search.
    The power method allocates margin proportionally to the raw implied
    probabilities rather than uniformly, which better approximates the
    sharp-line distribution for asymmetric markets (e.g. heavy favourites).

    Falls back to simple normalisation when the market is already fair or
    the binary-search bounds fail to converge.
    """
    clean = normalize_decimal_odds(odds)
    if not clean:
        return {}
    raw = {m: 1.0 / p for m, p in clean.items()}
    total_raw = sum(raw.values())
    if total_raw <= 1.0 + 1e-9:
        # Already fair (or close enough) — normalise directly.
        return {m: p / total_raw for m, p in raw.items()}

    lo, hi = 0.1, 10.0
    for _ in range(60):
        mid = (lo + hi) / 2.0
        total = sum(p ** (1.0 / mid) for p in raw.values())
        # total(mid) is monotonically increasing in mid for raw values in
        # (0, 1): as mid grows, the exponent 1/mid shrinks toward 0 and
        # p**(1/mid) -> 1 for every outcome, so total -> len(raw). When
        # total overshoots 1 the root lies at a *smaller* mid, so narrow
        # the upper bound; otherwise narrow the lower bound.
        if total > 1.0:
            hi = mid
        else:
            lo = mid

    k = (lo + hi) / 2.0
    probs = {m: p ** (1.0 / k) for m, p in raw.items()}
    # Normalise to guard against tiny floating-point residuals.
    t = sum(probs.values())
    return {m: v / t for m, v in probs.items()} if t > 0.0 else probs


# ---------------------------------------------------------------------------
# Market-efficiency feature builder
# ---------------------------------------------------------------------------


def compute_market_features(
    *,
    model_probabilities: Mapping[str, float],
    opening_odds: Mapping[str, float] | None = None,
    current_odds: Mapping[str, float] | None = None,
    closing_odds: Mapping[str, float] | None = None,
) -> dict[str, float | None]:
    """Compute a comprehensive set of market-efficiency features.

    All features are ``None`` when the required data is absent, ensuring
    safe serialisation to JSON/metadata without crashing on partial inputs.

    Feature glossary
    ----------------
    ``market_prob_{outcome}``
        Vig-removed implied probability from current odds.
    ``ev_{outcome}``
        Expected value if model probability is correct:
        ``model_prob x current_price - 1``.
    ``edge_{outcome}``
        Raw probability edge: ``model_prob - market_prob``.
    ``odds_drift_{outcome}``
        Log-ratio drift from opening to current: ``ln(current / opening)``.
        Positive -> price lengthened (market drifted away from this outcome).
    ``clv_{outcome}``
        Closing Line Value: ``model_prob - closing_implied_prob``.
        Only defined post-match; ``None`` until closing odds supplied.
    ``max_ev``
        Highest EV across all outcomes — proxy for best value opportunity.
    ``max_edge``
        Largest raw probability edge across all outcomes.
    ``max_abs_odds_drift``
        Largest absolute log-ratio drift — proxy for market movement.
    """
    current = normalize_decimal_odds(current_odds or {})
    opening = normalize_decimal_odds(opening_odds or {})
    closing = normalize_decimal_odds(closing_odds or {})

    current_implied = implied_probabilities(current) if current else {}
    implied_probabilities(opening) if opening else {}
    closing_implied = implied_probabilities(closing) if closing else {}

    features: dict[str, float | None] = {}

    for market in MARKETS_1X2:
        model_prob = float(model_probabilities.get(market) or 0.0)
        price = current.get(market)

        features[f"market_prob_{market}"] = current_implied.get(market)
        features[f"ev_{market}"] = (model_prob * price - 1.0) if price else None
        features[f"edge_{market}"] = (
            model_prob - current_implied[market]
            if market in current_implied
            else None
        )

        # Log-ratio drift: scale-invariant, additive over time.
        if market in current and market in opening:
            try:
                features[f"odds_drift_{market}"] = math.log(
                    current[market] / opening[market]
                )
            except (ValueError, ZeroDivisionError):
                features[f"odds_drift_{market}"] = None
        else:
            features[f"odds_drift_{market}"] = None

        # CLV: only meaningful post-match with true closing odds.
        features[f"clv_{market}"] = (
            model_prob - closing_implied[market]
            if market in closing_implied
            else None
        )

    # ------------------------------------------------------------------
    # Aggregate signals
    # ------------------------------------------------------------------
    ev_vals = [v for k, v in features.items() if k.startswith("ev_") and v is not None]
    features["max_ev"] = max(ev_vals) if ev_vals else None

    edge_vals = [v for k, v in features.items() if k.startswith("edge_") and v is not None]
    features["max_edge"] = max(edge_vals) if edge_vals else None

    drift_vals = [
        abs(v)
        for k, v in features.items()
        if k.startswith("odds_drift_") and v is not None
    ]
    features["max_abs_odds_drift"] = max(drift_vals) if drift_vals else None

    # Legacy alias preserved for backward compatibility with Phase 8 consumers.
    features["max_model_edge"] = features["max_edge"]

    return features
