"""Market Intelligence and Provenance Layer.

CONTRACT:
- Synthesizes bookmaker odds, power-method de-vigging, expected value, probability edge,
  and complete audit provenance without duplicating mathematical primitives.
- Invariant: A positive mathematical edge NEVER automatically permits staking.
  Staking is strictly forbidden (`stake_permitted = False`) when the active model generation
  is uncertified (`active_generation_is_certified() == False`) or when market gating fails.
- Pydantic v2 protected namespace compatibility enabled.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Mapping, Optional
from pydantic import BaseModel, ConfigDict, Field

from ..connectors.odds_market import (
    MARKETS_1X2,
    bookmaker_margin,
    implied_probabilities,
    is_complete_market,
    normalize_decimal_odds,
    power_method_probs,
)
from ..models.active_generation import (
    ActiveGenerationError,
    active_feature_schema_version,
    active_generation_is_certified,
    active_model_version,
)
from ..services.betting_intelligence import (
    MIN_ACTIONABLE_EDGE,
    _expected_value,
)


class EdgeClassification(str, Enum):
    """Classification of mathematical edge against fair market probabilities."""

    POSITIVE_EDGE = "POSITIVE_EDGE"
    FAIR = "FAIR"
    NEGATIVE_EDGE = "NEGATIVE_EDGE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class MarketDecisionState(str, Enum):
    """Operational decision state for market intelligence."""

    RESEARCH_ONLY = "RESEARCH_ONLY"
    HOLD = "HOLD"
    ACTIONABLE = "ACTIONABLE"
    NO_BET = "NO_BET"
    PARTIAL = "PARTIAL"


class OutcomeMarketIntel(BaseModel):
    """Granular market pricing, fair probability, and edge for a single outcome."""

    model_config = ConfigDict(protected_namespaces=())

    outcome: str
    decimal_odds: float
    raw_implied_probability: float
    fair_market_probability: float
    model_probability: Optional[float] = None
    probability_edge: Optional[float] = None
    expected_value: Optional[float] = None
    classification: EdgeClassification = EdgeClassification.INSUFFICIENT_DATA


class MarketProvenance(BaseModel):
    """Full audit and lineage metadata for market intelligence."""

    model_config = ConfigDict(protected_namespaces=())

    provider: str
    bookmaker: str
    market_type: str = "1X2"
    captured_at: datetime
    staleness_seconds: Optional[int] = None
    is_complete: bool
    is_suspended: bool = False
    pre_kickoff: bool = True
    devig_method: str = "POWER_METHOD"
    model_version: str
    feature_schema_version: str
    certification_state: str
    uncertainty_available: bool = False


class MarketIntelligenceSummary(BaseModel):
    """Aggregated market intelligence report with fail-closed governance."""

    model_config = ConfigDict(protected_namespaces=())

    outcomes: Dict[str, OutcomeMarketIntel]
    market_overround: float
    margin_percentage: float
    best_edge_outcome: Optional[str] = None
    best_edge_value: Optional[float] = None
    stake_permitted: bool = False
    decision: MarketDecisionState = MarketDecisionState.RESEARCH_ONLY
    provenance: MarketProvenance
    data_gaps: list[str] = Field(default_factory=list)


def build_market_intelligence(
    odds: Mapping[str, float],
    model_probabilities: Optional[Mapping[str, float]] = None,
    provider: str = "the_odds_api",
    bookmaker: str = "consensus",
    captured_at: Optional[datetime] = None,
    staleness_seconds: Optional[int] = None,
    is_suspended: bool = False,
    pre_kickoff: bool = True,
    uncertainty_available: bool = False,
) -> MarketIntelligenceSummary:
    """Build unified market intelligence with full provenance and fail-closed staking gates.

    Reuses validated de-vigging arithmetic from ``connectors.odds_market`` and
    verdict gates from ``services.betting_intelligence``.

    Args:
        odds: Mapping of outcome names (e.g. 'home_win', 'draw', 'away_win') to decimal odds.
        model_probabilities: Optional model-estimated probabilities for each outcome.
        provider: Market data provider identifier.
        bookmaker: Bookmaker or consensus source name.
        captured_at: Timestamp when odds were observed (UTC).
        staleness_seconds: Age of the odds snapshot in seconds.
        is_suspended: Whether the market is currently suspended.
        pre_kickoff: True if the match has not kicked off yet.
        uncertainty_available: Whether model uncertainty intervals are available.

    Returns:
        MarketIntelligenceSummary with outcomes, overround, edge, and provenance.
    """
    captured_dt = captured_at or datetime.now(timezone.utc)
    clean_odds = normalize_decimal_odds(odds or {})
    complete = is_complete_market(clean_odds)

    data_gaps: list[str] = []
    if not clean_odds:
        data_gaps.append("market_odds_unavailable")
    elif not complete:
        data_gaps.append("incomplete_1x2_market")

    if model_probabilities is None:
        data_gaps.append("model_probabilities_unavailable")

    if is_suspended:
        data_gaps.append("market_suspended")

    if not pre_kickoff:
        data_gaps.append("in_play_or_post_match")

    # Bookmaker margin and overround calculation
    if clean_odds:
        margin = bookmaker_margin(clean_odds)
        overround = 1.0 + margin
        margin_pct = round(margin * 100.0, 4)
        overround_val = round(overround, 4)
    else:
        margin = 0.0
        overround_val = 0.0
        margin_pct = 0.0

    # De-vigging fair probability calculation
    devig_method = "NONE"
    fair_probs: dict[str, float] = {}
    if complete:
        fair_probs = power_method_probs(clean_odds)
        if not fair_probs:
            fair_probs = implied_probabilities(clean_odds, remove_vig=True)
            devig_method = "PROPORTIONAL"
        else:
            devig_method = "POWER_METHOD"
    elif clean_odds:
        fair_probs = implied_probabilities(clean_odds, remove_vig=True)
        devig_method = "PROPORTIONAL"

    raw_implied_map = {m: 1.0 / p for m, p in clean_odds.items()}

    # Resolve active generation certification and schema
    try:
        is_certified = active_generation_is_certified()
    except (ActiveGenerationError, Exception):
        is_certified = False

    try:
        model_ver = active_model_version()
    except (ActiveGenerationError, Exception):
        model_ver = "v5_unverified"

    try:
        schema_ver = active_feature_schema_version()
    except (ActiveGenerationError, Exception):
        schema_ver = "canonical_58"

    cert_state = "CERTIFIED" if is_certified else "UNVERIFIED"

    # Outcome evaluation
    outcomes: Dict[str, OutcomeMarketIntel] = {}
    best_edge_outcome: Optional[str] = None
    best_edge_val: Optional[float] = None
    best_ev: Optional[float] = None
    max_edge = -float("inf")

    # Evaluate across all 1X2 markets present in clean_odds
    for outcome in MARKETS_1X2:
        if outcome not in clean_odds:
            continue

        price = clean_odds[outcome]
        raw_p = raw_implied_map.get(outcome, 0.0)
        fair_p = fair_probs.get(outcome, raw_p)

        model_p: Optional[float] = None
        edge: Optional[float] = None
        ev: Optional[float] = None
        classification = EdgeClassification.INSUFFICIENT_DATA

        if model_probabilities is not None and outcome in model_probabilities:
            raw_model_val = model_probabilities[outcome]
            try:
                m_val = float(raw_model_val)
                if math.isfinite(m_val) and m_val >= 0.0:
                    model_p = m_val
            except (TypeError, ValueError):
                model_p = None

        if model_p is not None:
            edge = model_p - fair_p
            ev = _expected_value(model_p, price)

            if edge > 0.0001:
                classification = EdgeClassification.POSITIVE_EDGE
            elif edge < -0.0001:
                classification = EdgeClassification.NEGATIVE_EDGE
            else:
                classification = EdgeClassification.FAIR

            if edge > max_edge:
                max_edge = edge
                best_edge_outcome = outcome
                best_edge_val = round(edge, 4)
                best_ev = ev

        outcomes[outcome] = OutcomeMarketIntel(
            outcome=outcome,
            decimal_odds=round(price, 4),
            raw_implied_probability=round(raw_p, 4),
            fair_market_probability=round(fair_p, 4),
            model_probability=round(model_p, 4) if model_p is not None else None,
            probability_edge=round(edge, 4) if edge is not None else None,
            expected_value=round(ev, 4) if ev is not None else None,
            classification=classification,
        )

    # Fail-closed staking decision logic
    stake_permitted = False
    if not clean_odds or not complete:
        decision = MarketDecisionState.PARTIAL
    elif not is_certified:
        # Invariant: Uncertified model generation MUST NEVER permit staking
        stake_permitted = False
        decision = MarketDecisionState.RESEARCH_ONLY
    elif is_suspended:
        decision = MarketDecisionState.HOLD
    elif not pre_kickoff:
        decision = MarketDecisionState.HOLD
    elif best_edge_val is not None and best_edge_val >= MIN_ACTIONABLE_EDGE and best_ev is not None and best_ev > 0:
        stake_permitted = True
        decision = MarketDecisionState.ACTIONABLE
    elif best_edge_val is not None and best_edge_val > 0:
        decision = MarketDecisionState.HOLD
    else:
        decision = MarketDecisionState.NO_BET

    provenance = MarketProvenance(
        provider=provider,
        bookmaker=bookmaker,
        market_type="1X2",
        captured_at=captured_dt,
        staleness_seconds=staleness_seconds,
        is_complete=complete,
        is_suspended=is_suspended,
        pre_kickoff=pre_kickoff,
        devig_method=devig_method,
        model_version=model_ver,
        feature_schema_version=schema_ver,
        certification_state=cert_state,
        uncertainty_available=uncertainty_available,
    )

    return MarketIntelligenceSummary(
        outcomes=outcomes,
        market_overround=overround_val,
        margin_percentage=margin_pct,
        best_edge_outcome=best_edge_outcome,
        best_edge_value=best_edge_val,
        stake_permitted=stake_permitted,
        decision=decision,
        provenance=provenance,
        data_gaps=data_gaps,
    )


__all__ = [
    "EdgeClassification",
    "MarketDecisionState",
    "MarketIntelligenceSummary",
    "MarketProvenance",
    "OutcomeMarketIntel",
    "build_market_intelligence",
]
