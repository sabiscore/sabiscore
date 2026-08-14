"""Deterministic SabiScore Core Engine v2.1 evaluator."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Iterable, Literal, Optional, cast

from ..core.league_policy import LeaguePolicy, get_league_policy
from ..schemas.core_engine import (
    CoreCalculationAuditOutput,
    CoreDataFreshnessOutput,
    CoreEngineResponse,
    CoreMatchInput,
    CoreMatchOutput,
    CoreProbabilitiesOutput,
)


ENGINE_VERSION = "2.1.0-prod"
SUPPORTED_COMPETITIONS = {
    "EPL",
    "LA_LIGA",
    "SERIE_A",
    "BUNDESLIGA",
    "LIGUE_1",
    "EREDIVISIE",
    "UCL",
}
OUTCOMES = (
    ("HOME_ML", "home", "home_probability", "home_odds"),
    ("DRAW_ML", "draw", "draw_probability", "draw_odds"),
    ("AWAY_ML", "away", "away_probability", "away_odds"),
)

CORE_MIN_ACTIONABLE_EDGE = 0.042
CORE_KELLY_FRACTION = 0.25   # quarter-Kelly (directive §12)
CORE_MAX_KELLY_CAP = 0.05    # 5% of bankroll hard cap (directive §12)
CORE_MIN_MARKET_OVERROUND = 1.0
CORE_MAX_MARKET_OVERROUND = 1.25
PROBABILITY_TOLERANCE = 0.005
FRESH_SECONDS = 900
RECENT_SECONDS = 3600
HIGH_CONVICTION_EPISTEMIC_MAX = 0.05


@dataclass(frozen=True)
class Candidate:
    market: Literal["HOME_ML", "DRAW_ML", "AWAY_ML"]
    probability_key: str
    model_probability: float
    odds: float
    raw_implied_probability: float
    fair_market_probability: float
    edge: float
    expected_value: float
    kelly_fraction: float
    confidence_adjusted_value: float
    minimum_acceptable_odds: Optional[float]


def _league_policy_for(competition: Optional[str]) -> Optional[LeaguePolicy]:
    if not competition:
        return None
    return get_league_policy(competition)


def _league_kelly_cap(competition: Optional[str]) -> float:
    try:
        policy = _league_policy_for(competition)
        return policy.kelly_cap if policy is not None else CORE_MAX_KELLY_CAP
    except Exception:
        return CORE_MAX_KELLY_CAP


def analyze_core_matches(matches: Iterable[CoreMatchInput]) -> CoreEngineResponse:
    """Evaluate a batch of matches independently and rank clear opportunities."""

    generated_at = datetime.now(timezone.utc)
    evaluated_pairs = [(match, _evaluate_match(match)) for match in matches]
    evaluated = [output for _, output in evaluated_pairs]

    def _rank_key(pair):
        source, output = pair
        return (
            -output.confidence_adjusted_value,
            -(output.expected_value or 0.0),
            _epistemic_for_match(source),
            _market_age_for_match(source),
            output.match_id or "",
        )

    top_verdicts = {"HIGH_CONVICTION", "ACTIONABLE"}
    top_pairs = [
        (source, output)
        for source, output in evaluated_pairs
        if output.verdict in top_verdicts and output.best_market is not None
    ]
    watchlist_pairs = [
        (source, output)
        for source, output in evaluated_pairs
        if output.verdict == "SPECULATIVE" and output.best_market is not None
    ]
    top_pairs.sort(key=_rank_key)
    watchlist_pairs.sort(key=_rank_key)

    return CoreEngineResponse(
        generated_at=generated_at,
        top_opportunities=[output.match_id for _, output in top_pairs[:3] if output.match_id],
        batch_watchlist=[output.match_id for _, output in watchlist_pairs if output.match_id],
        matches=evaluated,
    )


def _evaluate_match(match: CoreMatchInput) -> CoreMatchOutput:
    data_gaps: list[str] = []
    risks: list[str] = []
    drivers: list[str] = []
    invalidation_conditions: list[str] = []

    # Per-league Kelly cap — looked up once here so every _build_output call uses it.
    _eval_kelly_cap = CORE_MAX_KELLY_CAP
    try:
        policy = _league_policy_for(match.competition)
        if policy is not None:
            _eval_kelly_cap = policy.kelly_cap
    except Exception:
        data_gaps.append("DATA_GAP: LEAGUE_POLICY_UNAVAILABLE")

    model = match.model
    market = match.market
    signals = match.signals
    freshness = match.freshness
    source_status = match.source_status

    _collect_required_field_gaps(match, data_gaps)
    if model is not None and model.generation_certified is not True:
        data_gaps.append("DATA_GAP: MODEL_GENERATION_UNCERTIFIED")
    _collect_source_status_gaps(source_status, data_gaps)

    probabilities = _probabilities_output(match)
    probability_values = _probability_tuple(match)
    probability_sum_valid = False
    if probability_values is not None:
        prob_sum = sum(probability_values)
        probability_sum_valid = abs(prob_sum - 1.0) <= PROBABILITY_TOLERANCE
        if not probability_sum_valid:
            data_gaps.append("DATA_GAP: INVALID_MODEL_PROBABILITY_SUM")
        for name, value in zip(("home", "draw", "away"), probability_values):
            if not _valid_probability(value):
                data_gaps.append(f"DATA_GAP: INVALID_MODEL_PROBABILITY:{name}")

    market_overround: Optional[float] = None
    fair_probabilities: Optional[dict[str, float]] = None
    raw_implied: Optional[dict[str, float]] = None
    if market is not None and _has_complete_market(market):
        odds_values = (market.home_odds, market.draw_odds, market.away_odds)
        if all(_valid_odds(odds) for odds in odds_values):
            raw_implied = {
                "home": 1.0 / cast(float, market.home_odds),
                "draw": 1.0 / cast(float, market.draw_odds),
                "away": 1.0 / cast(float, market.away_odds),
            }
            market_overround = sum(raw_implied.values())
            if (
                market_overround <= CORE_MIN_MARKET_OVERROUND
                or market_overround > CORE_MAX_MARKET_OVERROUND
            ):
                data_gaps.append("DATA_GAP: INVALID_MARKET_OVERROUND")
            else:
                fair_probabilities = {
                    key: value / market_overround for key, value in raw_implied.items()
                }
        else:
            data_gaps.append("DATA_GAP: INVALID_MARKET_ODDS")

    freshness_status = _freshness_status(freshness, source_status)
    if freshness_status in {"STALE", "DATA_GAP", "CONFLICTING"}:
        if freshness_status == "STALE":
            data_gaps.append("DATA_GAP: STALE_MARKET")
        elif freshness_status == "DATA_GAP":
            data_gaps.append("DATA_GAP: FRESHNESS_METADATA")

    audit = CoreCalculationAuditOutput(
        bookmaker=market.bookmaker if market else None,
        market_overround=_round_or_none(market_overround),
        calibration_method=model.calibration_method if model else None,
        model_version=model.model_version if model else None,
        kelly_fraction=CORE_KELLY_FRACTION,
        kelly_cap=_eval_kelly_cap,
    )
    data_freshness = CoreDataFreshnessOutput(
        status=freshness_status,
        market_captured_at=market.captured_at if market else None,
        oldest_critical_input_seconds=_oldest_critical_input_seconds(freshness),
        lineup_status=signals.lineup_status if signals else None,
    )

    critical_gaps = _critical_data_gaps(data_gaps)

    # Provider ceiling gate (directive §9, C-07/08).
    # None = caller omitted provenance → treat as 0 (missing provenance = no verified evidence).
    provider_count: int = (
        len(set(match.verified_evidence_providers))
        if match.verified_evidence_providers is not None
        else 0
    )
    if provider_count == 0 and not critical_gaps:
        data_gaps.append("DATA_GAP: NO_VERIFIED_EVIDENCE_PROVIDERS")
        critical_gaps = ["DATA_GAP: NO_VERIFIED_EVIDENCE_PROVIDERS"]

    if critical_gaps or freshness_status == "CONFLICTING":
        return _build_output(
            match=match,
            verdict="PARTIAL",
            probabilities=probabilities,
            data_freshness=data_freshness,
            data_gaps=_dedupe(data_gaps),
            audit=audit,
            confidence="LOW",
            risks=["Critical input validation failed."],
            explanation="Analysis degraded because required verified inputs were missing, stale, conflicting, or mathematically invalid.",
        )

    candidates = _build_candidates(match, raw_implied or {}, fair_probabilities or {})
    best = _best_candidate(candidates)
    if best is None:
        return _build_output(
            match=match,
            verdict="PARTIAL",
            probabilities=probabilities,
            data_freshness=data_freshness,
            data_gaps=["DATA_GAP: VALUE_CANDIDATE_UNAVAILABLE"],
            audit=audit,
            confidence="LOW",
            risks=["No complete market candidate could be calculated."],
            explanation="Analysis degraded because no complete 1X2 candidate was available.",
        )

    drivers.extend(_drivers(match, best))
    risks.extend(_risks(match))
    invalidation_conditions.extend(_invalidation_conditions(match, best))

    restricted = (
        model is None
        or model.calibration_validated is not True
        or model.confidence_tier != "OK"
    )
    if restricted:
        risks.append("Model calibration or confidence tier restricts promotion.")

    if best.expected_value <= 0 or best.edge <= 0:
        return _build_output(
            match=match,
            verdict="NO_BET",
            probabilities=probabilities,
            data_freshness=data_freshness,
            data_gaps=[],
            audit=audit,
            candidate=best,
            confidence="LOW",
            drivers=drivers,
            risks=risks or ["Market price does not clear positive EV requirements."],
            invalidation_conditions=invalidation_conditions,
            explanation="Valid data received, but the best market does not produce positive expected value and positive edge.",
        )

    below_actionable = best.edge < CORE_MIN_ACTIONABLE_EDGE
    speculative_signal = (
        signals is not None
        and signals.sharp_market_signal == "CONFIRMING"
        and not restricted
        and best.expected_value > 0
    )

    # Provider ceiling: 1 verified owner → max HOLD (directive §9, C-09).
    if provider_count == 1:
        return _build_output(
            match=match,
            verdict="HOLD",
            probabilities=probabilities,
            data_freshness=data_freshness,
            data_gaps=[],
            audit=audit,
            candidate=best,
            confidence="LOW",
            drivers=drivers,
            risks=["Single-provider evidence: a second independent source is required before execution."],
            invalidation_conditions=invalidation_conditions,
            explanation="Only one independent evidence provider contributed to this analysis. Minimum two providers required for SPECULATIVE or above.",
        )

    if below_actionable and not speculative_signal:
        return _build_output(
            match=match,
            verdict="HOLD",
            probabilities=probabilities,
            data_freshness=data_freshness,
            data_gaps=[],
            audit=audit,
            candidate=best,
            confidence=_confidence(match, best),
            drivers=drivers,
            risks=risks or ["Positive edge remains below the actionable threshold."],
            invalidation_conditions=invalidation_conditions,
            explanation="Positive mathematical edge exists, but it is below the configured 4.2 percentage point action threshold.",
        )

    if below_actionable and speculative_signal:
        return _build_output(
            match=match,
            verdict="SPECULATIVE",
            probabilities=probabilities,
            data_freshness=data_freshness,
            data_gaps=[],
            audit=audit,
            candidate=best,
            confidence="LOW",
            stake_fraction=0.0,
            drivers=drivers,
            risks=risks or ["Speculative position remains below the actionable edge threshold."],
            invalidation_conditions=invalidation_conditions,
            explanation="Positive EV exists below the actionable threshold with confirming market signal; this remains watchlist-only with no public stake.",
        )

    if restricted:
        return _build_output(
            match=match,
            verdict="HOLD",
            probabilities=probabilities,
            data_freshness=data_freshness,
            data_gaps=[],
            audit=audit,
            candidate=best,
            confidence="LOW",
            drivers=drivers,
            risks=risks,
            invalidation_conditions=invalidation_conditions,
            explanation="Positive value clears the edge threshold, but model validation or confidence restrictions force a pass.",
        )

    verdict = "ACTIONABLE"
    if (
        match.competition != "UCL"
        and model is not None
        and model.epistemic_uncertainty is not None
        and model.epistemic_uncertainty <= HIGH_CONVICTION_EPISTEMIC_MAX
        and signals is not None
        and signals.lineup_status == "CONFIRMED"
        and provider_count >= 4  # C-10: 4 independent verified sources required
    ):
        verdict = "HIGH_CONVICTION"
    elif match.competition == "UCL":
        risks.append("UCL soft coverage caps the verdict at ACTIONABLE.")
    elif provider_count is not None and provider_count < 4 and provider_count >= 2:
        risks.append(f"Provider ceiling: {provider_count}/4 independent sources. Four required for HIGH_CONVICTION.")

    return _build_output(
        match=match,
        verdict=verdict,
        probabilities=probabilities,
        data_freshness=data_freshness,
        data_gaps=[],
        audit=audit,
        candidate=best,
        confidence=_confidence(match, best),
        stake_fraction=best.kelly_fraction,
        drivers=drivers,
        risks=risks,
        invalidation_conditions=invalidation_conditions,
        explanation="Valid data received and the selected market clears positive EV plus the configured minimum edge threshold.",
        effective_kelly_cap=_eval_kelly_cap,
    )


def _collect_required_field_gaps(match: CoreMatchInput, gaps: list[str]) -> None:
    if not match.match_id:
        gaps.append("DATA_GAP: match_id")
    if not match.home_team:
        gaps.append("DATA_GAP: home_team")
    if not match.away_team:
        gaps.append("DATA_GAP: away_team")
    if match.competition not in SUPPORTED_COMPETITIONS:
        gaps.append("DATA_GAP: competition")
    if match.kickoff_utc is None:
        gaps.append("DATA_GAP: kickoff_utc")

    model = match.model
    if model is None:
        gaps.append("DATA_GAP: model")
    else:
        for field in (
            "home_probability",
            "draw_probability",
            "away_probability",
            "model_version",
            "calibration_method",
            "calibration_validated",
            "epistemic_uncertainty",
            "aleatoric_uncertainty",
            "confidence_tier",
        ):
            if getattr(model, field) is None:
                gaps.append(f"DATA_GAP: model.{field}")

    market = match.market
    if market is None:
        gaps.append("DATA_GAP: market")
    else:
        for field in (
            "bookmaker",
            "market_type",
            "home_odds",
            "draw_odds",
            "away_odds",
            "captured_at",
        ):
            if getattr(market, field) is None:
                gaps.append(f"DATA_GAP: market.{field}")
        if market.market_type is not None and market.market_type != "1X2":
            gaps.append("DATA_GAP: market.market_type")

    freshness = match.freshness
    if freshness is None:
        gaps.append("DATA_GAP: freshness")
    else:
        for field in (
            "model_features_seconds",
            "market_seconds",
            "injury_news_seconds",
            "lineup_seconds",
        ):
            if getattr(freshness, field) is None:
                gaps.append(f"DATA_GAP: freshness.{field}")

    if match.source_status is None:
        gaps.append("DATA_GAP: source_status")

    signals = match.signals
    if signals is None:
        gaps.append("DATA_GAP: signals")
    elif signals.lineup_status is None:
        gaps.append("DATA_GAP: signals.lineup_status")


def _collect_source_status_gaps(source_status, gaps: list[str]) -> None:
    if source_status is None:
        return
    for field in ("model", "market", "team_metrics", "availability"):
        status_value = getattr(source_status, field)
        if status_value is None:
            gaps.append(f"DATA_GAP: source_status.{field}")
        elif status_value == "DATA_GAP":
            gaps.append(f"DATA_GAP: {field}")
        elif status_value == "CONFLICTING":
            gaps.append(f"CONFLICTING:{field}")
        elif status_value == "STALE":
            gaps.append(f"DATA_GAP: STALE:{field}")


def _critical_data_gaps(gaps: list[str]) -> list[str]:
    return [gap for gap in gaps if not _is_non_critical_gap(gap)]


def _is_non_critical_gap(gap: str) -> bool:
    return gap.startswith("CONFLICTING")


def _probabilities_output(match: CoreMatchInput) -> CoreProbabilitiesOutput:
    model = match.model
    return CoreProbabilitiesOutput(
        home=model.home_probability if model else None,
        draw=model.draw_probability if model else None,
        away=model.away_probability if model else None,
    )


def _probability_tuple(match: CoreMatchInput) -> Optional[tuple[float, float, float]]:
    model = match.model
    if model is None:
        return None
    values = (model.home_probability, model.draw_probability, model.away_probability)
    if any(value is None for value in values):
        return None
    return values  # type: ignore[return-value]


def _valid_probability(value: object) -> bool:
    return isinstance(value, (int, float)) and isfinite(value) and 0.0 <= value <= 1.0


def _valid_odds(value: object) -> bool:
    return isinstance(value, (int, float)) and isfinite(value) and value > 1.0


def _has_complete_market(market) -> bool:
    return all(
        getattr(market, field) is not None
        for field in ("home_odds", "draw_odds", "away_odds")
    )


def _freshness_status(
    freshness, source_status
) -> Literal["FRESH", "RECENT", "STALE", "DATA_GAP", "CONFLICTING"]:
    if source_status is not None:
        statuses = [
            getattr(source_status, field)
            for field in ("model", "market", "team_metrics", "availability")
        ]
        if any(status is None for status in statuses):
            return "DATA_GAP"
        if any(status == "CONFLICTING" for status in statuses):
            return "CONFLICTING"
        if any(status == "DATA_GAP" for status in statuses):
            return "DATA_GAP"
        if any(status == "STALE" for status in statuses):
            return "STALE"

    if freshness is None or freshness.market_seconds is None:
        return "DATA_GAP"
    if freshness.market_seconds > RECENT_SECONDS:
        return "STALE"
    if freshness.market_seconds > FRESH_SECONDS:
        return "RECENT"

    values = [
        freshness.model_features_seconds,
        freshness.market_seconds,
        freshness.injury_news_seconds,
        freshness.lineup_seconds,
    ]
    if any(value is None for value in values):
        return "DATA_GAP"
    if any(value > RECENT_SECONDS for value in values):
        return "STALE"
    if any(value > FRESH_SECONDS for value in values):
        return "RECENT"
    return "FRESH"


def _oldest_critical_input_seconds(freshness) -> Optional[int]:
    if freshness is None:
        return None
    values = [
        freshness.model_features_seconds,
        freshness.market_seconds,
        freshness.injury_news_seconds,
        freshness.lineup_seconds,
    ]
    if any(value is None for value in values):
        return None
    return max(values)


def _build_candidates(
    match: CoreMatchInput,
    raw_implied: dict[str, float],
    fair_probabilities: dict[str, float],
) -> list[Candidate]:
    model = match.model
    market = match.market
    if model is None or market is None:
        return []

    # Per-league Kelly cap (directive §11, C-13): look up policy, fall back to module default.
    effective_kelly_cap = CORE_MAX_KELLY_CAP
    try:
        from ..core.league_policy import get_league_policy
        if match.competition:
            _lp = get_league_policy(match.competition)
            effective_kelly_cap = _lp.kelly_cap
    except Exception:
        pass  # unknown league or import error → module default

    uncertainty_factor = _uncertainty_factor(model)
    freshness_factor = _freshness_factor(match.freshness)
    completeness_factor = 1.0
    stability_factor = _market_stability_factor(match.signals)

    candidates: list[Candidate] = []
    for market_name, key, probability_field, odds_field in OUTCOMES:
        model_probability = getattr(model, probability_field)
        odds = getattr(market, odds_field)
        if (
            model_probability is None
            or odds is None
            or key not in raw_implied
            or key not in fair_probabilities
        ):
            continue

        edge = model_probability - fair_probabilities[key]
        expected_value = (model_probability * odds) - 1.0
        kelly_full = expected_value / (odds - 1.0) if odds > 1.0 else 0.0
        kelly_fraction = min(max(kelly_full, 0.0) * CORE_KELLY_FRACTION, effective_kelly_cap)
        score = (
            max(expected_value, 0.0)
            * uncertainty_factor
            * freshness_factor
            * completeness_factor
            * stability_factor
        )
        denominator = model_probability - CORE_MIN_ACTIONABLE_EDGE
        minimum_acceptable_odds = 1.0 / denominator if denominator > 0 else None
        candidates.append(
            Candidate(
                market=cast(Literal["HOME_ML", "DRAW_ML", "AWAY_ML"], market_name),
                probability_key=key,
                model_probability=model_probability,
                odds=odds,
                raw_implied_probability=raw_implied[key],
                fair_market_probability=fair_probabilities[key],
                edge=edge,
                expected_value=expected_value,
                kelly_fraction=kelly_fraction,
                confidence_adjusted_value=score,
                minimum_acceptable_odds=minimum_acceptable_odds,
            )
        )
    return candidates


def _best_candidate(candidates: list[Candidate]) -> Optional[Candidate]:
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda candidate: (
            -candidate.confidence_adjusted_value,
            -candidate.expected_value,
            -candidate.edge,
            candidate.market,
        ),
    )[0]


def _uncertainty_factor(model) -> float:
    epistemic = _clamp(1.0 - (model.epistemic_uncertainty or 0.0), 0.0, 1.0)
    aleatoric = _clamp(1.0 - 0.5 * (model.aleatoric_uncertainty or 0.0), 0.0, 1.0)
    return epistemic * aleatoric


def _freshness_factor(freshness) -> float:
    if freshness is None or freshness.market_seconds is None:
        return 0.0
    if freshness.market_seconds > RECENT_SECONDS:
        return 0.0
    if freshness.market_seconds > FRESH_SECONDS:
        return 0.75
    return 1.0


def _market_stability_factor(signals) -> float:
    if signals is None:
        return 0.8
    return {
        "CONFIRMING": 1.0,
        "NEUTRAL": 0.9,
        "UNKNOWN": 0.8,
        "CONFLICTING": 0.5,
    }.get(signals.sharp_market_signal, 0.8)


def _drivers(match: CoreMatchInput, candidate: Candidate) -> list[str]:
    signals = match.signals
    drivers = [
        f"{candidate.market} model probability exceeds de-vigged market probability by {candidate.edge * 100:.2f}pp.",
        f"Unit expected value is {candidate.expected_value:.4f}.",
    ]
    if signals and signals.sharp_market_signal == "CONFIRMING":
        drivers.append("Sharp market signal is confirming.")
    if signals and signals.club_elo_difference is not None:
        drivers.append(f"Club Elo differential supplied: {signals.club_elo_difference:.2f}.")
    return drivers


def _risks(match: CoreMatchInput) -> list[str]:
    risks: list[str] = []
    model = match.model
    signals = match.signals
    if match.competition == "UCL":
        risks.append("UCL soft coverage has elevated cross-league epistemic variance.")
    if model and model.confidence_tier == "LOW_EVIDENCE":
        risks.append("Model confidence tier is LOW_EVIDENCE.")
    if signals and signals.lineup_status != "CONFIRMED":
        risks.append("Lineup status is not confirmed.")
    if signals and signals.sharp_market_signal == "CONFLICTING":
        risks.append("Sharp market signal is conflicting.")
    return risks


def _invalidation_conditions(match: CoreMatchInput, candidate: Candidate) -> list[str]:
    conditions = []
    if candidate.minimum_acceptable_odds is not None:
        conditions.append(
            f"Invalidate if {candidate.market} odds fall below {candidate.minimum_acceptable_odds:.4f}."
        )
    if match.signals and match.signals.lineup_status != "CONFIRMED":
        conditions.append("Invalidate or re-run if starting lineup status changes materially.")
    conditions.append("Invalidate if any critical source status becomes STALE, CONFLICTING, or DATA_GAP.")
    return conditions


def _confidence(match: CoreMatchInput, candidate: Candidate) -> str:
    model = match.model
    signals = match.signals
    if (
        model
        and model.confidence_tier == "OK"
        and model.calibration_validated is True
        and model.epistemic_uncertainty is not None
        and model.epistemic_uncertainty <= HIGH_CONVICTION_EPISTEMIC_MAX
        and signals
        and signals.lineup_status == "CONFIRMED"
        and candidate.edge >= CORE_MIN_ACTIONABLE_EDGE
    ):
        return "HIGH"
    if model and model.confidence_tier == "OK" and candidate.expected_value > 0:
        return "MEDIUM"
    return "LOW"


def _build_output(
    *,
    match: CoreMatchInput,
    verdict: str,
    probabilities: CoreProbabilitiesOutput,
    data_freshness: CoreDataFreshnessOutput,
    data_gaps: list[str],
    audit: CoreCalculationAuditOutput,
    candidate: Optional[Candidate] = None,
    confidence: str = "LOW",
    stake_fraction: Optional[float] = None,
    drivers: Optional[list[str]] = None,
    risks: Optional[list[str]] = None,
    invalidation_conditions: Optional[list[str]] = None,
    explanation: str,
    effective_kelly_cap: float = CORE_MAX_KELLY_CAP,
) -> CoreMatchOutput:
    pass_verdicts = {"PARTIAL", "HOLD", "NO_BET", "SPECULATIVE"}
    final_stake_fraction = 0.0 if verdict in pass_verdicts else (stake_fraction or 0.0)
    stake = _stake_label(final_stake_fraction, verdict, effective_kelly_cap)

    if verdict == "PARTIAL":
        candidate = None

    return CoreMatchOutput(
        match_identifier=_match_identifier(match),
        match_id=match.match_id,
        competition=match.competition,
        kickoff_utc=match.kickoff_utc,
        verdict=verdict,  # type: ignore[arg-type]
        watchlist=verdict == "SPECULATIVE",
        probabilities=probabilities,
        best_market=candidate.market if candidate else None,
        market_odds=_round_or_none(candidate.odds if candidate else None),
        raw_market_implied_probability=_round_or_none(
            candidate.raw_implied_probability if candidate else None
        ),
        fair_market_probability=_round_or_none(
            candidate.fair_market_probability if candidate else None
        ),
        edge=None if verdict == "PARTIAL" else _round_or_none(candidate.edge if candidate else None),
        edge_percentage_points=None
        if verdict == "PARTIAL"
        else _round_or_none((candidate.edge * 100.0) if candidate else None),
        expected_value=None
        if verdict == "PARTIAL"
        else _round_or_none(candidate.expected_value if candidate else None),
        confidence=confidence,  # type: ignore[arg-type]
        confidence_adjusted_value=_round_or_none(
            candidate.confidence_adjusted_value if candidate else 0.0
        )
        or 0.0,
        stake=stake,
        stake_fraction=_round_or_none(final_stake_fraction) or 0.0,
        minimum_acceptable_odds=None
        if verdict == "PARTIAL"
        else _round_or_none(candidate.minimum_acceptable_odds if candidate else None),
        drivers=drivers or [],
        risks=risks or [],
        invalidation_conditions=invalidation_conditions or [],
        data_freshness=data_freshness,
        data_gaps=data_gaps,
        calculation_audit=audit,
        explanation=explanation,
    )


def _stake_label(
    stake_fraction: float,
    verdict: str,
    kelly_cap: float = CORE_MAX_KELLY_CAP,
) -> Literal["1u", "2.5u", "pass"]:
    if verdict in {"PARTIAL", "HOLD", "NO_BET", "SPECULATIVE"} or stake_fraction <= 0:
        return "pass"
    # "2.5u" when at ≥90% of the effective cap (covers rounding); "1u" for smaller stakes.
    if stake_fraction >= kelly_cap * 0.90:
        return "2.5u"
    return "1u"


def _match_identifier(match: CoreMatchInput) -> Optional[str]:
    if match.home_team and match.away_team:
        return f"{match.home_team} vs {match.away_team}"
    return None


def _epistemic_for_match(match: CoreMatchInput) -> float:
    if match.model is None or match.model.epistemic_uncertainty is None:
        return 1.0
    return match.model.epistemic_uncertainty


def _market_age_for_match(match: CoreMatchInput) -> int:
    if match.freshness is None or match.freshness.market_seconds is None:
        return RECENT_SECONDS + 1
    return match.freshness.market_seconds


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _round_or_none(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), 6)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


__all__ = ["analyze_core_matches"]
