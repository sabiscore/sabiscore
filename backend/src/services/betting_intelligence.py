"""
SabiScore Core Engine - Pure Deterministic Betting Intelligence Service
CONTRACT VERSION: 1.1.0

This module is the single authoritative source for betting decisions.
It is a pure function module: all inputs are explicit, all outputs are
deterministic and reproducible. No I/O, no side effects, no defaults
substituted for missing evidence.

Key invariants enforced here:
  1. Zero fabrication: missing input -> DATA_GAP, never a plausible default
  2. Fail-closed: every gate defaults to the most conservative verdict
  3. De-vigged edge: edge is against fair market probability, not raw implied
  4. All-outcome evaluation: all three 1X2 outcomes ranked, best selected
  5. Both edge AND EV must be positive for ACTIONABLE+
  6. UCL structurally capped below HIGH_CONVICTION
  7. Actionability abstain overrides verdict (capital preservation beats conviction)
  8. Deterministic tie-breakers for batch ranking
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..schemas.betting_intelligence import (
    AnalysisModeEnum,
    BatchAnalysisRequest,
    BatchAnalysisResponse,
    BestMarketEnum,
    CalculationAudit,
    CompetitionEnum,
    ConfidenceLabelEnum,
    DataFreshness,
    EvidenceTierEnum,
    FreshnessStatusEnum,
    LineupStatusEnum,
    MarketInput,
    MatchAnalysisRequest,
    MatchAnalysisResult,
    ModelInput,
    ProbabilitySet,
    SharpSignalEnum,
    SourceStatusEnum,
    VerdictEnum,
)

# ---------------------------------------------------------------------------
# Production constants (mirror backend/src/core/config.py)
# Override via environment/config injection in the endpoint layer.
# ---------------------------------------------------------------------------

MIN_ACTIONABLE_EDGE: float = 0.042        # 4.2 percentage points de-vigged
HIGH_CONVICTION_EDGE: float = 0.062       # max(MIN_ACTIONABLE_EDGE + 0.02, 0.06)
KELLY_FRACTION: float = 0.25             # quarter-Kelly (directive §12)
MAX_KELLY_CAP: float = 0.05              # 5% of bankroll hard cap (directive §12)
MARKET_FRESH_SECONDS: int = 900           # 15 min
MARKET_RECENT_SECONDS: int = 3600         # 60 min
MODEL_FEATURES_FRESH_SECONDS: int = 3600  # LIVE_THRESHOLD_SECONDS default
INJURY_FRESH_SECONDS: int = 21600         # 6 h
MAX_MARKET_OVERROUND: float = 1.20        # reject >120% book
MIN_MARKET_OVERROUND: float = 0.90        # reject <90% book (integrity)
SPECULATIVE_STAKE_CAP: float = 0.0025     # 0.25u cap for SPECULATIVE
DEFAULT_TARGET_EXPECTED_VALUE: float = 0.0
CONTRACT_VERSION: str = "1.2.0"
POLICY_VERSION: str = "1.0"


# ---------------------------------------------------------------------------
# De-vig and market mathematics
# ---------------------------------------------------------------------------


def _raw_implied(odds: float) -> float:
    """1 / decimal_odds - raw bookmaker-implied probability."""
    if odds <= 1.0:
        raise ValueError(f"Decimal odds must be > 1.0; got {odds}")
    return 1.0 / odds


def _compute_devig(
    home_odds: float,
    draw_odds: float,
    away_odds: float,
) -> Tuple[float, float, float, float]:
    """Return (overround, fair_home, fair_draw, fair_away).

    De-vigs a coherent 1X2 snapshot by dividing raw implied probabilities
    by the market overround (bookmaker margin). The resulting fair-market
    probabilities sum to 1.0.
    """
    q_h = _raw_implied(home_odds)
    q_d = _raw_implied(draw_odds)
    q_a = _raw_implied(away_odds)
    overround = q_h + q_d + q_a
    return overround, q_h / overround, q_d / overround, q_a / overround


def _expected_value(model_prob: float, decimal_odds: float) -> float:
    """EV per unit staked: model_prob Ã- odds - 1."""
    return model_prob * decimal_odds - 1.0


def _full_kelly(ev: float, decimal_odds: float) -> float:
    """Kelly criterion: max(0, EV / (odds - 1))."""
    denom = decimal_odds - 1.0
    if denom <= 0 or ev <= 0:
        return 0.0
    return max(0.0, ev / denom)


def _breakeven_odds(model_prob: float) -> Optional[float]:
    """Return the decimal price where EV is exactly zero."""
    if model_prob <= 0:
        return None
    return round(1.0 / model_prob, 3)


def _minimum_odds_for_target_ev(
    model_prob: float,
    target_expected_value: float = DEFAULT_TARGET_EXPECTED_VALUE,
) -> Optional[float]:
    """Return decimal odds needed to clear a target EV."""
    if model_prob <= 0:
        return None
    return round((1.0 + target_expected_value) / model_prob, 3)


def _edge_preserving_minimum_odds(
    *,
    outcome: str,
    model_prob: float,
    min_edge: float,
    home_odds: float,
    draw_odds: float,
    away_odds: float,
) -> Optional[float]:
    """Solve the de-vigged 1X2 edge threshold holding other prices fixed."""
    target_fair_probability = model_prob - min_edge
    if target_fair_probability <= 0 or target_fair_probability >= 1:
        return None

    if outcome == "home":
        other_sum = (1.0 / draw_odds) + (1.0 / away_odds)
    elif outcome == "draw":
        other_sum = (1.0 / home_odds) + (1.0 / away_odds)
    else:
        other_sum = (1.0 / home_odds) + (1.0 / draw_odds)

    if other_sum <= 0:
        return None
    selected_raw_implied = (target_fair_probability * other_sum) / (
        1.0 - target_fair_probability
    )
    if selected_raw_implied <= 0:
        return None
    price = 1.0 / selected_raw_implied
    if not math.isfinite(price) or price <= 1.0:
        return None
    return round(price, 3)


def _minimum_acceptable_odds(model_prob: float, min_edge: float) -> Optional[float]:
    """Backward-compatible alias for the target-EV price-window method."""
    if model_prob <= min_edge:
        return None
    return _minimum_odds_for_target_ev(model_prob, DEFAULT_TARGET_EXPECTED_VALUE)


def _stable_hash(payload: Any) -> str:
    serialized = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _policy_payload(settings_override: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    s = settings_override or {}
    return {
        "policy_version": s.get("POLICY_VERSION", POLICY_VERSION),
        "min_actionable_edge": s.get("MIN_ACTIONABLE_EDGE", MIN_ACTIONABLE_EDGE),
        "high_conviction_edge": s.get("HIGH_CONVICTION_EDGE", HIGH_CONVICTION_EDGE),
        "kelly_fraction": s.get("KELLY_FRACTION", KELLY_FRACTION),
        "max_kelly_cap": s.get("MAX_KELLY_CAP", MAX_KELLY_CAP),
        "market_fresh_seconds": s.get("MARKET_FRESH_SECONDS", MARKET_FRESH_SECONDS),
        "market_recent_seconds": s.get("MARKET_RECENT_SECONDS", MARKET_RECENT_SECONDS),
        "model_features_fresh_seconds": s.get(
            "MODEL_FEATURES_FRESH_SECONDS",
            MODEL_FEATURES_FRESH_SECONDS,
        ),
        "min_market_overround": s.get("MIN_MARKET_OVERROUND", MIN_MARKET_OVERROUND),
        "max_market_overround": s.get("MAX_MARKET_OVERROUND", MAX_MARKET_OVERROUND),
        "speculative_stake_cap": s.get("SPECULATIVE_STAKE_CAP", SPECULATIVE_STAKE_CAP),
        "target_expected_value": s.get("TARGET_EXPECTED_VALUE", DEFAULT_TARGET_EXPECTED_VALUE),
    }


def _confidence_label(
    competition: CompetitionEnum,
    tier: EvidenceTierEnum,
    calibration_validated: bool,
    market_status: FreshnessStatusEnum,
    edge: float,
    min_actionable_edge: float = MIN_ACTIONABLE_EDGE,
) -> ConfidenceLabelEnum:
    """Map evidence quality to HIGH / MEDIUM / LOW."""
    if (
        competition != CompetitionEnum.UCL
        and tier == EvidenceTierEnum.OK
        and calibration_validated
        and market_status == FreshnessStatusEnum.FRESH
        and edge >= min_actionable_edge
    ):
        return ConfidenceLabelEnum.HIGH
    if tier == EvidenceTierEnum.LOW_EVIDENCE or not calibration_validated:
        return ConfidenceLabelEnum.LOW
    if market_status == FreshnessStatusEnum.STALE:
        return ConfidenceLabelEnum.LOW
    return ConfidenceLabelEnum.MEDIUM


def _confidence_adjusted_value(
    ev: float,
    epistemic_unc: float,
    market_status: FreshnessStatusEnum,
    completeness: float,
    sharp_signal: SharpSignalEnum,
) -> float:
    """Composite ranking score for batch prioritization.

    Factors:
      uncertainty_factor    = 1 - min(epistemic_unc, 1.0)
      freshness_factor      = 1.0 (FRESH) | 0.7 (RECENT) | 0.3 (STALE)
      completeness_factor   = fraction of non-gap inputs
      market_stability      = 1.0 (CONFIRMING) | 0.8 (NEUTRAL) | 0.5 (CONFLICTING) | 0.6 (UNKNOWN)
    """
    if ev <= 0:
        return 0.0
    uncertainty_factor = 1.0 - min(max(epistemic_unc, 0.0), 1.0)
    freshness_factor = {
        FreshnessStatusEnum.FRESH: 1.0,
        FreshnessStatusEnum.RECENT: 0.7,
        FreshnessStatusEnum.STALE: 0.3,
        FreshnessStatusEnum.DATA_GAP: 0.0,
        FreshnessStatusEnum.CONFLICTING: 0.0,
    }.get(market_status, 0.5)
    stability_factor = {
        SharpSignalEnum.CONFIRMING: 1.0,
        SharpSignalEnum.NEUTRAL: 0.8,
        SharpSignalEnum.CONFLICTING: 0.5,
        SharpSignalEnum.UNKNOWN: 0.6,
    }.get(sharp_signal, 0.6)
    score = max(ev, 0.0) * uncertainty_factor * freshness_factor * completeness * stability_factor
    return round(score, 6)


# ---------------------------------------------------------------------------
# Market freshness evaluation
# ---------------------------------------------------------------------------


def _evaluate_market_freshness(
    market: Optional[MarketInput],
    freshness_seconds: Optional[int],
    source_status: SourceStatusEnum,
    *,
    fresh_seconds: int = MARKET_FRESH_SECONDS,
    recent_seconds: int = MARKET_RECENT_SECONDS,
) -> Tuple[FreshnessStatusEnum, List[str]]:
    """Return freshness status and any data gaps from the market snapshot."""
    gaps: List[str] = []

    if market is None or source_status == SourceStatusEnum.DATA_GAP:
        gaps.append("DATA_GAP: market_odds")
        return FreshnessStatusEnum.DATA_GAP, gaps

    if source_status == SourceStatusEnum.CONFLICTING:
        gaps.append("CONFLICTING: market_odds")
        return FreshnessStatusEnum.CONFLICTING, gaps

    if source_status == SourceStatusEnum.STALE:
        gaps.append("STALE: market_odds")
        return FreshnessStatusEnum.STALE, gaps

    if freshness_seconds is None:
        gaps.append("DATA_GAP: market_freshness_unknown")
        return FreshnessStatusEnum.UNKNOWN, gaps

    if freshness_seconds <= fresh_seconds:
        return FreshnessStatusEnum.FRESH, gaps
    if freshness_seconds <= recent_seconds:
        return FreshnessStatusEnum.RECENT, gaps
    gaps.append(f"STALE: market_odds ({freshness_seconds}s old)")
    return FreshnessStatusEnum.STALE, gaps


def _evaluate_model_freshness(
    model: Optional[ModelInput],
    freshness_seconds: Optional[int],
    source_status: SourceStatusEnum,
    *,
    fresh_seconds: int = MODEL_FEATURES_FRESH_SECONDS,
) -> List[str]:
    """Return data gaps for model source and feature freshness."""
    gaps: List[str] = []

    if model is None or source_status == SourceStatusEnum.DATA_GAP:
        gaps.append("DATA_GAP: model_probabilities")
        return gaps

    if source_status == SourceStatusEnum.CONFLICTING:
        gaps.append("CONFLICTING: model_source")
        return gaps

    if source_status == SourceStatusEnum.STALE:
        gaps.append("STALE: model_features")
        return gaps

    if freshness_seconds is None:
        gaps.append("DATA_GAP: model_features_freshness_unknown")
        return gaps

    if freshness_seconds > fresh_seconds:
        gaps.append(f"STALE: model_features ({freshness_seconds}s old)")

    return gaps


# ---------------------------------------------------------------------------
# Outcome evaluation
# ---------------------------------------------------------------------------


def _evaluate_all_outcomes(
    model: ModelInput,
    market: MarketInput,
    fair_home: float,
    fair_draw: float,
    fair_away: float,
    *,
    kelly_fraction: float = KELLY_FRACTION,
    max_kelly_cap: float = MAX_KELLY_CAP,
) -> List[Dict[str, Any]]:
    """Evaluate all three 1X2 outcomes and return ranked evaluations.

    Returns list of dicts sorted by confidence_adjusted_value descending.
    This ensures the highest-EV market is selected, not just the most
    probable model outcome.
    """
    outcomes = [
        ("home", BestMarketEnum.HOME_ML, model.home_probability, market.home_odds, fair_home),
        ("draw", BestMarketEnum.DRAW_ML, model.draw_probability, market.draw_odds, fair_draw),
        ("away", BestMarketEnum.AWAY_ML, model.away_probability, market.away_odds, fair_away),
    ]

    results = []
    for name, market_label, model_prob, odds, fair_prob in outcomes:
        raw_implied = _raw_implied(odds)
        edge = model_prob - fair_prob
        ev = _expected_value(model_prob, odds)
        fk = _full_kelly(ev, odds)
        stake_frac = min(fk * kelly_fraction, max_kelly_cap) if ev > 0 and edge > 0 else 0.0
        # Simple CAV for ranking within this call (full CAV computed at synthesis)
        cav = max(ev, 0.0) * (1.0 - model.epistemic_uncertainty) if ev > 0 and edge > 0 else 0.0
        results.append({
            "outcome": name,
            "market_label": market_label,
            "model_probability": round(model_prob, 6),
            "market_odds": odds,
            "raw_implied_probability": round(raw_implied, 6),
            "fair_market_probability": round(fair_prob, 6),
            "edge": round(edge, 6),
            "edge_pct": round(edge * 100, 4),
            "expected_value": round(ev, 6),
            "stake_fraction": round(stake_frac, 6),
            "confidence_adjusted_value": round(cav, 8),
        })

    # Sort by confidence-adjusted value descending (best market first)
    results.sort(key=lambda r: r["confidence_adjusted_value"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Verdict gate (strict precedence, fail-closed)
# ---------------------------------------------------------------------------


def _apply_verdict_gate(
    critical_gaps: List[str],
    competition: CompetitionEnum,
    model: Optional[ModelInput],
    market: Optional[MarketInput],
    market_freshness: FreshnessStatusEnum,
    best_ev: float,
    best_edge: float,
    best_stake_fraction: float,
    sharp_signal: SharpSignalEnum,
    lineup_status: LineupStatusEnum,
    kickoff_utc: Optional[datetime],
    causal_drivers: Optional[List[str]] = None,
    evaluation_at: Optional[datetime] = None,
    min_actionable_edge: float = MIN_ACTIONABLE_EDGE,
    high_conviction_edge: float = HIGH_CONVICTION_EDGE,
    verified_provider_count: Optional[int] = None,
) -> VerdictEnum:
    """Apply verdict gates in strict precedence order (Section 6 of contract).

    Gate 1: PARTIAL - any critical input missing, invalid, stale, or zero providers.
    Gate 2: NO_BET  - reliable data but no positive value.
    Gate 3: HOLD    - positive value exists but execution blocked; also single-provider ceiling.
    Gate 4: SPECULATIVE - sub-threshold positive edge.
    Gate 5: ACTIONABLE - all execution gates satisfied.
    Gate 6: HIGH_CONVICTION - strongest evidence, all gates + UCL exclusion + ≥4 providers.

    verified_provider_count=None means caller omitted provenance → treated as 0 → PARTIAL.
    verified_provider_count=int enforces ceiling when orchestrator supplies provenance.
    """
    # -- Gate 1: PARTIAL ------------------------------------------------------
    if critical_gaps:
        return VerdictEnum.PARTIAL

    if model is None or market is None:
        return VerdictEnum.PARTIAL

    # None means caller did not pass provenance — treat as 0 verified owners (C-07/C-08)
    if verified_provider_count is None:
        verified_provider_count = 0

    # Provider ceiling: 0 verified owners → no independent evidence (C-07/C-08)
    if verified_provider_count == 0:
        return VerdictEnum.PARTIAL

    if market_freshness in (
        FreshnessStatusEnum.DATA_GAP,
        FreshnessStatusEnum.CONFLICTING,
        FreshnessStatusEnum.UNKNOWN,
    ):
        return VerdictEnum.PARTIAL

    # -- Gate 2: NO_BET -------------------------------------------------------
    if best_ev <= 0 or best_edge <= 0 or best_stake_fraction <= 0:
        return VerdictEnum.NO_BET

    # -- Gate 3: HOLD ---------------------------------------------------------
    # Provider ceiling: 1 verified owner → max HOLD (C-09)
    if verified_provider_count == 1:
        return VerdictEnum.HOLD

    tier_low = model.confidence_tier == EvidenceTierEnum.LOW_EVIDENCE
    cal_unvalidated = not model.calibration_validated
    market_stale = market_freshness == FreshnessStatusEnum.STALE

    lineup_risk = False
    if kickoff_utc is not None:
        now = evaluation_at or datetime.now(timezone.utc)
        minutes_to_kickoff = (kickoff_utc - now).total_seconds() / 60.0
        if minutes_to_kickoff <= 90 and lineup_status != LineupStatusEnum.CONFIRMED:
            lineup_risk = True

    if tier_low or cal_unvalidated or market_stale or sharp_signal == SharpSignalEnum.CONFLICTING or lineup_risk:
        if best_edge < min_actionable_edge:
            return VerdictEnum.HOLD
        if tier_low or cal_unvalidated or market_stale or lineup_risk:
            return VerdictEnum.HOLD

    # -- Gate 4: SPECULATIVE ---------------------------------------------------
    if best_edge < min_actionable_edge:
        return VerdictEnum.SPECULATIVE

    # -- Gate 5: ACTIONABLE ---------------------------------------------------
    if market_freshness == FreshnessStatusEnum.RECENT:
        return VerdictEnum.ACTIONABLE

    # -- Gate 6: HIGH_CONVICTION -----------------------------------------------
    hc_edge_required = max(high_conviction_edge, min_actionable_edge + 0.02, 0.06)

    ucl_soft = competition == CompetitionEnum.UCL
    if ucl_soft:
        return VerdictEnum.ACTIONABLE  # UCL structurally capped

    # Provider ceiling: <4 verified owners → max ACTIONABLE (C-10)
    if verified_provider_count < 4:
        return VerdictEnum.ACTIONABLE

    has_causal_support = bool(causal_drivers)
    high_epistemic = model.epistemic_uncertainty > 0.05  # aligned with core_engine HIGH_CONVICTION_EPISTEMIC_MAX

    if (
        best_edge >= hc_edge_required
        and not high_epistemic
        and market_freshness == FreshnessStatusEnum.FRESH
        and has_causal_support
        and sharp_signal in (SharpSignalEnum.CONFIRMING, SharpSignalEnum.NEUTRAL, SharpSignalEnum.UNKNOWN)
    ):
        return VerdictEnum.HIGH_CONVICTION

    return VerdictEnum.ACTIONABLE


# ---------------------------------------------------------------------------
# Invalidation conditions
# ---------------------------------------------------------------------------


def _build_invalidation_conditions(
    model: ModelInput,
    best_market: BestMarketEnum,
    best_odds: float,
    best_edge: float,
    known_risks: List[str],
    min_actionable_edge: float = MIN_ACTIONABLE_EDGE,
) -> List[str]:
    """Build concrete invalidation conditions for the recommended position."""
    conditions = [
        "Price moves below minimum acceptable odds (see calculation_audit).",
        f"Edge falls below {min_actionable_edge * 100:.1f}pp after live odds refresh.",
        "Model probability changes materially after confirmed lineup ingestion.",
    ]
    if best_market == BestMarketEnum.HOME_ML:
        conditions.append("Key home starter ruled out or unexpected rotation disclosed.")
    elif best_market == BestMarketEnum.AWAY_ML:
        conditions.append("Key away starter ruled out or unexpected rotation disclosed.")
    conditions.append("Sharp movement reverses direction against the selected outcome.")
    conditions.append("Market snapshot becomes stale before execution (>15 min without refresh).")
    conditions.extend(known_risks)
    return conditions


# ---------------------------------------------------------------------------
# Data completeness
# ---------------------------------------------------------------------------


def _compute_completeness(request: MatchAnalysisRequest) -> float:
    """Fraction of non-null signal fields (0.0-1.0)."""
    fields = [
        request.signals.xg_differential,
        request.signals.xga_differential,
        request.signals.opponent_adjusted_form,
        request.signals.club_elo_difference,
        request.signals.schedule_congestion,
        request.signals.travel_load,
    ]
    non_null = sum(1 for f in fields if f is not None)
    return round(non_null / len(fields), 4) if fields else 0.0


# ---------------------------------------------------------------------------
# Core engine - single match
# ---------------------------------------------------------------------------


def analyze_match(
    request: MatchAnalysisRequest,
    causal_drivers: Optional[List[str]] = None,
    settings_override: Optional[Dict[str, Any]] = None,
    evaluation_at: Optional[datetime] = None,
) -> MatchAnalysisResult:
    """Analyze a single match and return a deterministic betting recommendation.

    Arguments:
        request: Complete match analysis request.
        causal_drivers: Optional list of active causal driver feature names
                        (from the causal analysis layer). Only used for the
                        HIGH_CONVICTION gate check.
        settings_override: Optional dict of {MIN_ACTIONABLE_EDGE, KELLY_FRACTION,
                           MAX_KELLY_CAP} to override module-level constants.
    """
    # Per-league policy lookup (directive §11, C-13).
    # Merges league-specific thresholds into the policy payload so each league
    # can have independent kelly_cap, edge threshold, and calibration metadata.
    # LeaguePolicyUnavailableError for unknown leagues maps to DATA_GAP + PARTIAL.
    league_policy_gap: str | None = None
    _league_override: Dict[str, Any] = dict(settings_override or {})
    try:
        from ..core.league_policy import get_league_policy
        _lp = get_league_policy(request.competition.value)
        # Only override from policy when no explicit caller override for these keys.
        if "MAX_KELLY_CAP" not in _league_override:
            _league_override["MAX_KELLY_CAP"] = _lp.kelly_cap
        if "HIGH_CONVICTION_EDGE" not in _league_override:
            _league_override["HIGH_CONVICTION_EDGE"] = _lp.high_conviction_edge_threshold
        if "MARKET_FRESH_SECONDS" not in _league_override:
            _league_override["MARKET_FRESH_SECONDS"] = float(_lp.market_freshness_ttl_seconds)
        if "MODEL_FEATURES_FRESH_SECONDS" not in _league_override:
            _league_override["MODEL_FEATURES_FRESH_SECONDS"] = float(
                _lp.model_feature_freshness_ttl_seconds
            )
        if "POLICY_VERSION" not in _league_override:
            _league_override["POLICY_VERSION"] = f"{_lp.league_id}@{_lp.version}"
    except Exception:
        # Unknown league or import error → use module defaults; DATA_GAP injected below.
        league_policy_gap = "DATA_GAP: LEAGUE_POLICY_UNAVAILABLE"
    policy = _policy_payload(_league_override or None)
    policy_version = str(policy["policy_version"])
    min_edge = float(policy["min_actionable_edge"])
    high_conviction_edge = float(policy["high_conviction_edge"])
    kelly_frac = float(policy["kelly_fraction"])
    kelly_cap = float(policy["max_kelly_cap"])
    target_expected_value = float(policy["target_expected_value"])
    evaluation_at = evaluation_at or datetime.now(timezone.utc)
    input_hash = _stable_hash(request.model_dump(mode="json"))
    policy_hash = _stable_hash(policy)
    decision_id = _stable_hash(
        {
            "input_hash": input_hash,
            "policy_hash": policy_hash,
            "evaluation_at": evaluation_at.isoformat(),
        }
    )[:24]

    gaps: List[str] = list(request.data_gaps)  # start with caller-declared gaps
    if league_policy_gap is not None:
        gaps.append(league_policy_gap)
    model = request.model
    if model is not None and model.generation_certified is not True:
        gaps.append("DATA_GAP: MODEL_GENERATION_UNCERTIFIED")
    market = request.market

    # -- Model validation -----------------------------------------------------
    model_gaps = _evaluate_model_freshness(
        model,
        request.freshness.model_features_seconds,
        request.source_status.model,
        fresh_seconds=int(policy["model_features_fresh_seconds"]),
    )
    gaps.extend(model_gaps)
    if model_gaps:
        model = None

    # -- Market validation ----------------------------------------------------
    market_freshness, market_gaps = _evaluate_market_freshness(
        market,
        request.freshness.market_seconds,
        request.source_status.market,
        fresh_seconds=int(policy["market_fresh_seconds"]),
        recent_seconds=int(policy["market_recent_seconds"]),
    )
    gaps.extend(market_gaps)

    # Validate overround integrity
    if market is not None and not market_gaps:
        try:
            overround, fair_h, fair_d, fair_a = _compute_devig(
                market.home_odds, market.draw_odds, market.away_odds
            )
            if overround > float(policy["max_market_overround"]) or overround < float(policy["min_market_overround"]):
                gaps.append(
                    f"DATA_GAP: market_overround_outside_integrity_limits ({overround:.4f})"
                )
                market = None
        except ValueError as exc:
            gaps.append(f"DATA_GAP: market_odds_invalid ({exc})")
            market = None

    # -- Evaluate all outcomes when we have both model and market -------------
    all_evals: Optional[List[Dict[str, Any]]] = None
    best_eval: Optional[Dict[str, Any]] = None
    overround: Optional[float] = None
    fair_h = fair_d = fair_a = None

    if model is not None and market is not None and not gaps:
        overround, fair_h, fair_d, fair_a = _compute_devig(
            market.home_odds, market.draw_odds, market.away_odds
        )
        all_evals = _evaluate_all_outcomes(
            model,
            market,
            fair_h,
            fair_d,
            fair_a,
            kelly_fraction=kelly_frac,
            max_kelly_cap=kelly_cap,
        )
        # best is first (sorted by confidence_adjusted_value)
        best_eval = all_evals[0] if all_evals else None

    # -- Apply verdict gate ----------------------------------------------------
    best_ev = best_eval["expected_value"] if best_eval else -1.0
    best_edge = best_eval["edge"] if best_eval else -1.0
    best_stake_fraction = best_eval["stake_fraction"] if best_eval else 0.0
    critical_gaps = _extract_critical_gaps(gaps)

    # None = caller omitted provenance; _apply_verdict_gate maps it to 0 → PARTIAL.
    verified_provider_count = (
        len(set(request.verified_evidence_providers))
        if request.verified_evidence_providers is not None
        else None
    )
    verdict = _apply_verdict_gate(
        critical_gaps=critical_gaps,
        competition=request.competition,
        model=model,
        market=market,
        market_freshness=market_freshness,
        best_ev=best_ev,
        best_edge=best_edge,
        best_stake_fraction=best_stake_fraction,
        sharp_signal=request.signals.sharp_market_signal,
        lineup_status=request.signals.lineup_status,
        kickoff_utc=request.kickoff_utc,
        causal_drivers=causal_drivers,
        evaluation_at=evaluation_at,
        min_actionable_edge=min_edge,
        high_conviction_edge=high_conviction_edge,
        verified_provider_count=verified_provider_count,
    )

    # -- Build result ----------------------------------------------------------
    probs = None
    best_market_field = None
    market_odds_field = None
    raw_implied_field = None
    fair_market_field = None
    edge_field = None
    edge_pct_field = None
    ev_field = None
    confidence_field = None
    cav_field = None
    stake_str = "pass"
    final_stake_fraction = 0.0
    min_acceptable_odds = None
    minimum_method = None
    drivers: List[str] = []
    invalidation: List[str] = []
    calc_audit: Optional[CalculationAudit] = None

    if model is not None:
        probs = ProbabilitySet(
            home=model.home_probability,
            draw=model.draw_probability,
            away=model.away_probability,
        )

    if verdict not in (VerdictEnum.PARTIAL, VerdictEnum.NO_BET, VerdictEnum.HOLD) and best_eval:
        best_market_field = best_eval["market_label"]
        market_odds_field = best_eval["market_odds"]
        raw_implied_field = best_eval["raw_implied_probability"]
        fair_market_field = best_eval["fair_market_probability"]
        edge_field = best_eval["edge"]
        edge_pct_field = best_eval["edge_pct"]
        ev_field = best_eval["expected_value"]

        # Clamp stake for SPECULATIVE
        raw_frac = best_eval["stake_fraction"]
        if verdict == VerdictEnum.SPECULATIVE:
            final_stake_fraction = min(raw_frac, float(policy["speculative_stake_cap"]))
        else:
            final_stake_fraction = raw_frac

        if final_stake_fraction > 0:
            stake_str = f"{round(final_stake_fraction * 100, 2)}u"

        # Compute full CAV with all factors
        completeness = _compute_completeness(request)
        cav_field = _confidence_adjusted_value(
            ev=ev_field,
            epistemic_unc=model.epistemic_uncertainty,
            market_status=market_freshness,
            completeness=completeness,
            sharp_signal=request.signals.sharp_market_signal,
        )

        confidence_field = _confidence_label(
            competition=request.competition,
            tier=model.confidence_tier,
            calibration_validated=model.calibration_validated,
            market_status=market_freshness,
            edge=edge_field,
            min_actionable_edge=min_edge,
        )

        breakeven = _breakeven_odds(best_eval["model_probability"])
        target_ev_odds = _minimum_odds_for_target_ev(
            best_eval["model_probability"],
            target_expected_value,
        )
        edge_preserving_odds = _edge_preserving_minimum_odds(
            outcome=best_eval["outcome"],
            model_prob=best_eval["model_probability"],
            min_edge=min_edge,
            home_odds=market.home_odds,
            draw_odds=market.draw_odds,
            away_odds=market.away_odds,
        )
        min_acceptable_odds = edge_preserving_odds or target_ev_odds or breakeven
        minimum_method = (
            "DE_VIGGED_1X2_EDGE_SOLVE_HOLDING_OTHER_PRICES"
            if edge_preserving_odds is not None
            else "TARGET_EXPECTED_VALUE_PRICE"
        )

        # Drivers
        if causal_drivers:
            drivers = causal_drivers[:3]
        drivers_extra = []
        if edge_field >= min_edge:
            drivers_extra.append(
                f"+{round(edge_pct_field, 1)}pp de-vigged edge on {best_eval['outcome'].upper()}_ML"
            )
        if request.signals.sharp_market_signal == SharpSignalEnum.CONFIRMING:
            drivers_extra.append("Sharp market signal confirms model direction")
        drivers.extend(drivers_extra[:3 - len(drivers)])

        invalidation = _build_invalidation_conditions(
            model=model,
            best_market=best_market_field,
            best_odds=market_odds_field,
            best_edge=edge_field,
            known_risks=request.known_risks,
            min_actionable_edge=min_edge,
        )

        # Audit trail
        calc_audit = CalculationAudit(
            bookmaker=market.bookmaker,
            market_overround=round(overround, 6) if overround else None,
            raw_implied_home=round(1.0 / market.home_odds, 6) if market else None,
            raw_implied_draw=round(1.0 / market.draw_odds, 6) if market else None,
            raw_implied_away=round(1.0 / market.away_odds, 6) if market else None,
            fair_market_home=round(fair_h, 6) if fair_h is not None else None,
            fair_market_draw=round(fair_d, 6) if fair_d is not None else None,
            fair_market_away=round(fair_a, 6) if fair_a is not None else None,
            calibration_method=model.calibration_method,
            model_version=model.model_version,
            kelly_fraction=kelly_frac,
            kelly_cap=kelly_cap,
            breakeven_odds=breakeven,
            minimum_odds_for_target_ev=target_ev_odds,
            edge_preserving_minimum_odds=edge_preserving_odds,
        )

    # Risks
    risks: List[str] = list(request.known_risks[:3])
    if not risks:
        if request.signals.confirmed_absences:
            risks.append(
                f"Confirmed absences: {', '.join(request.signals.confirmed_absences[:3])}"
            )
        if request.signals.lineup_status != LineupStatusEnum.CONFIRMED:
            risks.append(f"Lineup status: {request.signals.lineup_status.value}")
        if request.signals.sharp_market_signal == SharpSignalEnum.CONFLICTING:
            risks.append("Sharp market signal conflicts with model direction")

    conflicts = _extract_conflicts(gaps, risks)
    advisory_gaps = _extract_advisory_gaps(risks)

    # Freshness block
    freshness_block = DataFreshness(
        status=market_freshness,
        market_captured_at=market.captured_at if market else None,
        oldest_critical_input_seconds=request.freshness.market_seconds,
        lineup_status=request.signals.lineup_status,
    )

    # Explanation
    explanation = _build_explanation(
        verdict=verdict,
        competition=request.competition,
        best_eval=best_eval,
        gaps=gaps,
        market_freshness=market_freshness,
        model=model,
    )

    return MatchAnalysisResult(
        contract_version=CONTRACT_VERSION,
        policy_version=policy_version,
        decision_id=decision_id,
        evaluation_at=evaluation_at,
        analysis_mode=(
            AnalysisModeEnum.VALUE_ANALYSIS
            if market is not None and market_freshness not in (FreshnessStatusEnum.DATA_GAP, FreshnessStatusEnum.UNKNOWN)
            else AnalysisModeEnum.FORECAST_ONLY
        ),
        execution_eligible=verdict in (VerdictEnum.HIGH_CONVICTION, VerdictEnum.ACTIONABLE),
        watchlist=verdict == VerdictEnum.SPECULATIVE,
        source_summary={
            "model": request.source_status.model.value,
            "market": request.source_status.market.value,
            "team_metrics": request.source_status.team_metrics.value,
            "availability": request.source_status.availability.value,
        },
        input_hash=input_hash,
        policy_hash=policy_hash,
        minimum_acceptable_odds_method=minimum_method,
        target_expected_value=target_expected_value,
        match_identifier=f"{request.home_team} vs {request.away_team}",
        match_id=request.match_id,
        competition=request.competition.value,
        kickoff_utc=request.kickoff_utc,
        verdict=verdict,
        probabilities=probs,
        best_market=best_market_field,
        market_odds=market_odds_field,
        raw_market_implied_probability=raw_implied_field,
        fair_market_probability=fair_market_field,
        edge=round(edge_field, 6) if edge_field is not None else None,
        edge_percentage_points=round(edge_pct_field, 4) if edge_pct_field is not None else None,
        expected_value=round(ev_field, 6) if ev_field is not None else None,
        confidence=confidence_field,
        confidence_adjusted_value=cav_field,
        stake=stake_str,
        stake_fraction=round(final_stake_fraction, 6),
        minimum_acceptable_odds=min_acceptable_odds,
        drivers=drivers,
        risks=risks,
        invalidation_conditions=invalidation,
        critical_gaps=critical_gaps,
        advisory_gaps=advisory_gaps,
        conflicts=conflicts,
        all_market_evaluations=all_evals,
        data_freshness=freshness_block,
        data_gaps=gaps,
        calculation_audit=calc_audit,
        explanation=explanation,
    )


def _extract_critical_gaps(gaps: List[str]) -> List[str]:
    return [gap for gap in gaps if not gap.startswith("CONFLICTING")]


def _extract_advisory_gaps(risks: List[str]) -> List[str]:
    advisory_markers = ("lineup", "absence", "ucl", "confidence tier")
    return [
        risk
        for risk in risks
        if any(marker in risk.lower() for marker in advisory_markers)
        and "conflict" not in risk.lower()
    ]


def _extract_conflicts(gaps: List[str], risks: List[str]) -> List[str]:
    conflicts = [gap for gap in gaps if gap.startswith("CONFLICTING")]
    conflicts.extend(risk for risk in risks if "conflict" in risk.lower())
    return list(dict.fromkeys(conflicts))


def _build_explanation(
    verdict: VerdictEnum,
    competition: CompetitionEnum,
    best_eval: Optional[Dict[str, Any]],
    gaps: List[str],
    market_freshness: FreshnessStatusEnum,
    model: Optional[ModelInput],
) -> str:
    """Build a concise, evidence-grounded, non-promotional explanation."""
    if verdict == VerdictEnum.PARTIAL:
        gap_summary = "; ".join(gaps[:3])
        return f"Analysis incomplete. Critical inputs unavailable: {gap_summary}. Resolve data gaps before execution."

    if verdict == VerdictEnum.NO_BET:
        if best_eval:
            return (
                f"No positive value found across all three 1X2 markets. "
                f"Best EV: {best_eval['expected_value']:.4f} on "
                f"{best_eval['outcome'].upper()}_ML. Pass this match."
            )
        return "No calculable value. Reliable evidence exists but no market offers positive EV. Pass."

    if verdict == VerdictEnum.HOLD:
        reasons = []
        if model and model.confidence_tier == EvidenceTierEnum.LOW_EVIDENCE:
            reasons.append("low model evidence")
        if market_freshness == FreshnessStatusEnum.STALE:
            reasons.append("stale market data")
        if not model or not model.calibration_validated:
            reasons.append("unvalidated calibration")
        reason_str = "; ".join(reasons) or "degraded evidence quality"
        return f"Hold - positive edge may exist but execution blocked by {reason_str}. Monitor and refresh data."

    if best_eval is None:
        return "Insufficient data to generate explanation."

    outcome = best_eval["outcome"].upper()
    edge_pp = best_eval["edge_pct"]
    ev = best_eval["expected_value"]
    odds = best_eval["market_odds"]
    fair_p = best_eval["fair_market_probability"]

    if verdict == VerdictEnum.SPECULATIVE:
        return (
            f"Sub-threshold edge on {outcome}_ML: {edge_pp:.2f}pp above fair market "
            f"(fair_p={fair_p:.3f}, EV={ev:.4f} at {odds:.2f}). "
            f"Watchlist only; the micro-allocation cap applies if the price remains valid."
        )

    if verdict == VerdictEnum.ACTIONABLE:
        ucl_note = " (UCL soft-coverage cap applied)" if competition == CompetitionEnum.UCL else ""
        return (
            f"{outcome}_ML: {edge_pp:.2f}pp de-vigged edge, EV={ev:.4f} at odds {odds:.2f}. "
            f"Fair market probability {fair_p:.3f}. "
            f"Qualifies above minimum acceptable odds{ucl_note}."
        )

    if verdict == VerdictEnum.HIGH_CONVICTION:
        return (
            f"{outcome}_ML: {edge_pp:.2f}pp de-vigged edge, EV={ev:.4f} at odds {odds:.2f}. "
            f"Fair market probability {fair_p:.3f}. "
            f"All conviction gates satisfied. Qualifies at current price or better."
        )

    return f"Verdict: {verdict.value}."


# ---------------------------------------------------------------------------
# Batch ranking and response assembly
# ---------------------------------------------------------------------------


def _rank_top_opportunities(results: List[MatchAnalysisResult]) -> Tuple[List[str], List[str]]:
    """Select up to 3 top opportunities, plus a separate SPECULATIVE watchlist.

    top_opportunities: HIGH_CONVICTION, ACTIONABLE only — capped at 3.
    batch_watchlist: SPECULATIVE only — never mixed into top_opportunities, uncapped.
    PARTIAL, HOLD, NO_BET are excluded from both.

    Tie-breakers (deterministic), applied identically to both lists:
      1. Higher EV
      2. Lower epistemic uncertainty (not directly available here - use CAV as proxy)
      3. Higher CAV (confidence-adjusted value)
      4. Stable lexical match_id
    """

    def _sort_key(r: MatchAnalysisResult):
        return (
            -(r.confidence_adjusted_value or 0),
            -(r.expected_value or 0),
            r.data_freshness.oldest_critical_input_seconds
            if r.data_freshness and r.data_freshness.oldest_critical_input_seconds is not None
            else 10**12,
            r.match_id,
        )

    def _qualifies(r: MatchAnalysisResult) -> bool:
        return r.confidence_adjusted_value is not None and r.confidence_adjusted_value > 0

    top = [
        r for r in results
        if r.verdict in (VerdictEnum.HIGH_CONVICTION, VerdictEnum.ACTIONABLE) and _qualifies(r)
    ]
    watchlist = [r for r in results if r.verdict == VerdictEnum.SPECULATIVE and _qualifies(r)]

    top.sort(key=_sort_key)
    watchlist.sort(key=_sort_key)

    return [r.match_id for r in top[:3]], [r.match_id for r in watchlist]


def analyze_batch(
    request: BatchAnalysisRequest,
    causal_drivers_map: Optional[Dict[str, List[str]]] = None,
    settings_override: Optional[Dict[str, Any]] = None,
    evaluation_at: Optional[datetime] = None,
) -> BatchAnalysisResponse:
    """Analyze all matches in the batch and return ranked results.

    Arguments:
        request: Batch request containing up to 100 matches.
        causal_drivers_map: Optional dict mapping match_id -> causal driver list.
        settings_override: Optional parameter overrides (edge thresholds, Kelly).
    """
    results: List[MatchAnalysisResult] = []
    cdm = causal_drivers_map or {}
    evaluation_at = evaluation_at or datetime.now(timezone.utc)

    for match_req in request.matches:
        drivers = cdm.get(match_req.match_id)
        result = analyze_match(
            match_req,
            causal_drivers=drivers,
            settings_override=settings_override,
            evaluation_at=evaluation_at,
        )
        results.append(result)

    top_opps, batch_watchlist = _rank_top_opportunities(results)

    return BatchAnalysisResponse(
        contract_version=CONTRACT_VERSION,
        policy_version=str(_policy_payload(settings_override)["policy_version"]),
        engine_version=request.engine_version,
        generated_at=evaluation_at,
        top_opportunities=top_opps,
        batch_watchlist=batch_watchlist,
        matches=results,
    )
