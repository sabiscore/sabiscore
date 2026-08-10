"""Phase 7-D: 6-layer intelligence fusion (ensemble × BNN × causal × RL × Elo × StatsBomb).

Produces a FullMatchAnalysisResponse with a TYPE-F fusion verdict using the gate
table from the APEX-SabiScore spec v6.0:

  HIGH_CONVICTION — confidence_tier OK, max_prob>0.52, elo_difference is
                    CAUSAL_DRIVER, RL does not abstain.
  ACTIONABLE      — confidence_tier OK, RL does not abstain, ≥1 causal driver.
  SPECULATIVE     — confidence_tier OK, no causal drivers fire.
  HOLD            — confidence_tier LOW_EVIDENCE OR RL abstains.
  PARTIAL         — any critical evidence gap or conflict (overrides others).

Behavioral contracts honoured:
  B11 — narrative ≤280 characters.
  B13 — no synthetic signal injection; missing features surface as DATA_GAP.
  B14 — narrative is grounded in actual layer values, no hallucinated claims.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import List, Optional

from ..data.elo_engine import EloContext
from ..models.causal_selector import CausalFeatureResult
from ..services.rl_betting_agent import RLRecommendationPayload
from ..services.uncertainty_service import UncertaintyBreakdown


# ---------------------------------------------------------------------------
# Transfer types for layers that don't yet have standalone dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EnsemblePrediction:
    home_win_prob: float
    draw_prob: float
    away_win_prob: float
    prediction: str  # "home_win" | "draw" | "away_win"
    confidence: float
    league: str = ""
    model_version: str = ""
    calibration_method: str = "raw"   # "raw" | "isotonic" | "platt" | …
    calibration_applied: bool = False
    overlay_applied: bool = False


@dataclass(frozen=True)
class OddsEdge:
    market: str  # "home_win" | "draw" | "away_win"
    market_odds: float
    model_prob: float
    edge: float          # model_prob − 1/market_odds
    kelly_stake: float


@dataclass(frozen=True)
class MatchActionability:
    """Advisory evidence block for CLV-centered actionability (Sprint 4 Slice A).

    edge_quality_score: composite 0.0–1.0 combining model confidence (0.40),
        market edge alignment (0.30), Phase 8 drift alignment (0.20), and
        data completeness (0.10).
    clv_pct: closing-line value as percentage points. Always null pre-kick-off
        (closing odds unavailable). Set post-match in a future sprint.
    closing_line_convergence_delta: implied-probability drift in the predicted
        outcome's direction since opening odds snapshot. Null when market data
        is a DATA_GAP.
    suggested_stake_pct: fractional Kelly stake × 100. 0.0 when abstain=True
        or edge_quality_score < edge_quality_abstain_threshold.
    abstain: True when RL layer advises no bet OR edge quality below threshold.
    abstain_reason: human-readable explanation (mirrors rl_recommendation.reason).
    top_evidence: up to 3 key signals behind this edge assessment.
    caveats: data gaps or quality warnings that reduce confidence.
    """
    edge_quality_score: float
    clv_pct: Optional[float]
    closing_line_convergence_delta: Optional[float]
    suggested_stake_pct: float
    abstain: bool
    abstain_reason: Optional[str]
    top_evidence: List[str]
    caveats: List[str]


@dataclass(frozen=True)
class EvidenceQuality:
    """One normalized evidence collection for gates, counts, and presentation."""

    critical_gaps: List[str]
    advisory_gaps: List[str]
    conflicts: List[str]
    all_gaps: List[str]

    def to_dict(self) -> dict:
        return {
            "critical_gaps": self.critical_gaps,
            "advisory_gaps": self.advisory_gaps,
            "conflicts": self.conflicts,
            "all_gaps": self.all_gaps,
            "critical_gap_count": len(self.critical_gaps),
            "advisory_gap_count": len(self.advisory_gaps),
            "conflict_count": len(self.conflicts),
            "total_gap_count": len(self.all_gaps),
        }


_CRITICAL_GAP_MARKERS = (
    "ensemble_prediction",
    "model_prediction",
    "model_probabilit",
    "feature_vector",
    "fixture_identity",
    "verified_evidence",
    "coherent_1x2_market",
    "market_data",
    "market_odds",
    "league_policy",
    "stale_required",
)


def _dedupe_gaps(values: List[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for raw in values:
        value = " ".join(str(raw).strip().split())
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def normalize_evidence_quality(
    data_gaps: Optional[List[str]] = None,
    critical_gaps: Optional[List[str]] = None,
    advisory_gaps: Optional[List[str]] = None,
    conflicts: Optional[List[str]] = None,
) -> EvidenceQuality:
    """Normalize and classify evidence without treating advisory gaps as blockers."""

    explicit_critical = _dedupe_gaps(list(critical_gaps or []))
    explicit_advisory = _dedupe_gaps(list(advisory_gaps or []))
    explicit_conflicts = _dedupe_gaps(list(conflicts or []))
    classified_critical: List[str] = []
    classified_advisory: List[str] = []
    classified_conflicts: List[str] = []

    known = {
        value.casefold()
        for value in explicit_critical + explicit_advisory + explicit_conflicts
    }
    for gap in _dedupe_gaps(list(data_gaps or [])):
        if gap.casefold() in known:
            continue
        lowered = gap.casefold()
        if lowered.startswith("conflicting") or " conflict" in lowered:
            classified_conflicts.append(gap)
        elif any(marker in lowered for marker in _CRITICAL_GAP_MARKERS):
            classified_critical.append(gap)
        else:
            classified_advisory.append(gap)

    critical = _dedupe_gaps(explicit_critical + classified_critical)
    advisory = _dedupe_gaps(explicit_advisory + classified_advisory)
    conflict_values = _dedupe_gaps(explicit_conflicts + classified_conflicts)
    all_gaps = _dedupe_gaps(critical + advisory + conflict_values)
    return EvidenceQuality(critical, advisory, conflict_values, all_gaps)


# ---------------------------------------------------------------------------
# Output type
# ---------------------------------------------------------------------------


@dataclass
class FullMatchAnalysisResponse:
    match_id: str
    verdict: str                             # HIGH_CONVICTION|ACTIONABLE|SPECULATIVE|HOLD|NO_BET|PARTIAL
    ensemble: EnsemblePrediction
    uncertainty: Optional[UncertaintyBreakdown]
    model_drivers: List[str]
    causal_drivers: List[str]
    rl_recommendation: RLRecommendationPayload
    elo_context: Optional[EloContext]
    odds_edge: Optional[OddsEdge]
    narrative: str                           # B11: ≤280 chars
    partial_intelligence: bool              # True only for critical gaps/conflicts
    data_gaps: List[str]
    evidence_quality: EvidenceQuality
    prediction_status: str = "AVAILABLE"
    prediction_source: str = "CERTIFIED_MODEL"
    probabilities_available: bool = True
    is_reduced_evidence_baseline: bool = False
    effective_kelly_cap: float = 0.0
    stake_permitted: bool = False
    staleness_seconds: int = 0              # Age of oldest live feature source
    staleness_available: bool = True        # False means freshness is unknown, never LIVE
    feature_freshness_seconds: dict = field(default_factory=dict)  # Phase 8: feature_name → seconds (None = DATA_GAP)
    feature_source: dict = field(default_factory=dict)             # Phase 8: feature_name → source identifier
    actionability: Optional[MatchActionability] = field(default=None)  # Sprint 4 Slice A advisory
    # Phase F: UCL + high-stakes metadata (populated in full_analysis.py from features_dict)
    match_importance_score: Optional[float] = field(default=None)
    competition_stage: Optional[str] = field(default=None)
    home_team: Optional[str] = field(default=None)
    away_team: Optional[str] = field(default=None)
    league: Optional[str] = field(default=None)
    kickoff_utc: Optional[str] = field(default=None)
    fixture_verified: Optional[bool] = field(default=None)
    field_availability: dict = field(default_factory=dict)
    unavailable_reasons: dict = field(default_factory=dict)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def freshness_tag(self) -> str:
        """Human-readable freshness label: LIVE / RECENT / STALE / UNKNOWN."""
        if not self.staleness_available:
            return "UNKNOWN"
        if self.staleness_seconds == 0:
            return "LIVE"
        if self.staleness_seconds < 86_400:   # < 24 h
            return "RECENT"
        return "STALE"

    def to_dict(self) -> dict:
        return {
            "match_id": self.match_id,
            "verdict": self.verdict,
            "prediction_status": self.prediction_status,
            "prediction_source": self.prediction_source,
            "probabilities_available": self.probabilities_available,
            "is_reduced_evidence_baseline": self.is_reduced_evidence_baseline,
            "top_outcome_probability": self.ensemble.confidence,
            "effective_kelly_cap": self.effective_kelly_cap,
            "stake_permitted": self.stake_permitted,
            "evidence_quality": self.evidence_quality.to_dict(),
            "ensemble": {
                "home_win_prob": self.ensemble.home_win_prob,
                "draw_prob": self.ensemble.draw_prob,
                "away_win_prob": self.ensemble.away_win_prob,
                "prediction": self.ensemble.prediction,
                "confidence": self.ensemble.confidence,
                "top_outcome_probability": self.ensemble.confidence,
                "league": self.ensemble.league,
                "model_version": self.ensemble.model_version,
                "calibration_method": self.ensemble.calibration_method,
                "calibration_applied": self.ensemble.calibration_applied,
                "overlay_applied": self.ensemble.overlay_applied,
                "probabilities_available": self.probabilities_available,
            },
            "uncertainty": (
                {
                    "epistemic_unc": self.uncertainty.epistemic_unc,
                    "aleatoric_unc": self.uncertainty.aleatoric_unc,
                    "concentration": self.uncertainty.concentration,
                    "credible_interval": list(self.uncertainty.credible_interval),
                    "confidence_tier": self.uncertainty.confidence_tier,
                }
                if self.uncertainty is not None
                else None
            ),
            "model_drivers": self.model_drivers,
            "causal_drivers": self.causal_drivers,
            "rl_recommendation": {
                "stake_fraction": self.rl_recommendation.stake_fraction,
                "abstain": self.rl_recommendation.abstain,
                "reason": self.rl_recommendation.reason,
                "reward_components": self.rl_recommendation.reward_components,
            },
            "elo_context": (
                {
                    "home_elo": self.elo_context.home_elo,
                    "away_elo": self.elo_context.away_elo,
                    "elo_difference": self.elo_context.elo_difference,
                    "home_elo_trend_5": self.elo_context.home_elo_trend_5,
                    "away_elo_trend_5": self.elo_context.away_elo_trend_5,
                    "elo_momentum_cross": self.elo_context.elo_momentum_cross,
                }
                if self.elo_context is not None
                else None
            ),
            "odds_edge": (
                {
                    "market": self.odds_edge.market,
                    "market_odds": self.odds_edge.market_odds,
                    "model_prob": self.odds_edge.model_prob,
                    "edge": self.odds_edge.edge,
                    "kelly_stake": self.odds_edge.kelly_stake,
                }
                if self.odds_edge is not None
                else None
            ),
            "narrative": self.narrative,
            "partial_intelligence": self.partial_intelligence,
            "data_gaps": self.data_gaps,
            "staleness_seconds": self.staleness_seconds,
            "staleness_available": self.staleness_available,
            "feature_freshness_seconds": self.feature_freshness_seconds,
            "feature_source": self.feature_source,
            "freshness_tag": self.freshness_tag,
            "actionability": (
                {
                    "edge_quality_score": self.actionability.edge_quality_score,
                    "clv_pct": self.actionability.clv_pct,
                    "closing_line_convergence_delta": self.actionability.closing_line_convergence_delta,
                    "suggested_stake_pct": self.actionability.suggested_stake_pct,
                    "abstain": self.actionability.abstain,
                    "abstain_reason": self.actionability.abstain_reason,
                    "top_evidence": self.actionability.top_evidence,
                    "caveats": self.actionability.caveats,
                }
                if self.actionability is not None
                else None
            ),
            # Phase F: UCL + high-stakes metadata
            "match_importance_score": self.match_importance_score,
            "competition_stage": self.competition_stage,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "league": self.league,
            "kickoff_utc": self.kickoff_utc,
            "fixture_verified": self.fixture_verified,
            "field_availability": self.field_availability,
            "unavailable_reasons": self.unavailable_reasons,
            "generated_at": self.generated_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# Synthesizer
# ---------------------------------------------------------------------------


class IntelligenceSynthesizer:
    """Fuse 6 intelligence layers into a single match-level verdict.

    All inputs are treated as optional; absent or None layers contribute
    sensible defaults and their omission is recorded in data_gaps so callers
    can surface partial intelligence (B13).
    """

    _CAUSAL_DRIVER_CLASS = "CAUSAL_DRIVER"

    def synthesize(
        self,
        match_id: str,
        ensemble: EnsemblePrediction,
        uncertainty: Optional[UncertaintyBreakdown],
        causal_results: List[CausalFeatureResult],
        rl_rec: RLRecommendationPayload,
        elo_ctx: Optional[EloContext],
        odds_edge: Optional[OddsEdge] = None,
        data_gaps: Optional[List[str]] = None,
        actionability: Optional[MatchActionability] = None,
        critical_gaps: Optional[List[str]] = None,
        advisory_gaps: Optional[List[str]] = None,
        conflicts: Optional[List[str]] = None,
        prediction_status: str = "AVAILABLE",
        prediction_source: str = "CERTIFIED_MODEL",
        effective_kelly_cap: float = 0.0,
        **kwargs,
    ) -> FullMatchAnalysisResponse:
        evidence_quality = normalize_evidence_quality(
            data_gaps=data_gaps,
            critical_gaps=critical_gaps,
            advisory_gaps=advisory_gaps,
            conflicts=conflicts,
        )
        gaps = evidence_quality.all_gaps
        partial = bool(evidence_quality.critical_gaps or evidence_quality.conflicts)
        probabilities_available = prediction_status == "AVAILABLE"

        active_drivers = [
            r.name
            for r in causal_results
            if r.classification == self._CAUSAL_DRIVER_CLASS
        ]

        verdict = self._compute_verdict(
            ensemble=ensemble,
            uncertainty=uncertainty,
            active_drivers=active_drivers,
            rl_rec=rl_rec,
            partial=partial,
        )
        if ensemble.league.strip().upper() in {"UCL", "UEFA_CHAMPIONS_LEAGUE"}:
            if verdict == "HIGH_CONVICTION":
                verdict = "ACTIONABLE"

        effective_kelly_cap = round(max(0.0, min(0.05, effective_kelly_cap)), 6)
        stake_permitted = bool(
            probabilities_available
            and kwargs.get("fixture_verified") is True
            and not partial
            and verdict in {"ACTIONABLE", "HIGH_CONVICTION"}
            and not rl_rec.abstain
            and rl_rec.stake_fraction > 0
            and effective_kelly_cap > 0
        )

        # Public stake values are fail-closed. Non-actionable and unavailable
        # states may retain diagnostic evidence, but never an executable stake.
        if not stake_permitted:
            rl_rec = replace(
                rl_rec,
                stake_fraction=0.0,
                abstain=True,
                reason=rl_rec.reason or "Public stake gate is closed.",
            )
            if odds_edge is not None:
                odds_edge = replace(odds_edge, kelly_stake=0.0)
            if actionability is not None:
                actionability = replace(
                    actionability,
                    suggested_stake_pct=0.0,
                    abstain=True,
                    abstain_reason=(
                        actionability.abstain_reason
                        or "Public stake gate is closed for this verdict."
                    ),
                )

        # Extract Phase 8 signals from features_dict when provided (not data gaps)
        features_dict: dict = kwargs.get("features_dict") or {}
        phase8_ctx = self._phase8_context(features_dict, gaps)

        if not probabilities_available or partial:
            narrative = textwrap.shorten(
                f"No bet — insufficient verified evidence. "
                f"{len(evidence_quality.critical_gaps)} critical gap(s), "
                f"{len(evidence_quality.conflicts)} conflict(s).",
                width=280,
                placeholder="…",
            )
        elif verdict == "SPECULATIVE":
            narrative = "Watchlist only — no stake is permitted."
        elif verdict in {"HOLD", "NO_BET"}:
            narrative = "No bet — the public stake gate is closed."
        elif uncertainty is not None and elo_ctx is not None:
            narrative = self._compose_narrative(
                ensemble=ensemble,
                uncertainty=uncertainty,
                verdict=verdict,
                active_drivers=active_drivers,
                elo_ctx=elo_ctx,
                rl_rec=rl_rec,
                phase8_ctx=phase8_ctx,
            )
        else:
            narrative = "No bet â€” measured model evidence is unavailable."

        staleness = int(kwargs.get("staleness_seconds", 0))
        staleness_available = bool(kwargs.get("staleness_available", True))
        freshness = dict(kwargs.get("feature_freshness_seconds") or {})
        feat_source = dict(kwargs.get("feature_source") or {})

        # Phase F: UCL + high-stakes metadata — pulled from features_dict when
        # present, overridable via explicit kwarg for callers with schedule data.
        raw_importance = features_dict.get("match_importance_score")
        match_importance_score: Optional[float] = (
            float(raw_importance)
            if raw_importance is not None
            else kwargs.get("match_importance_score")
        )
        competition_stage: Optional[str] = kwargs.get("competition_stage")

        return FullMatchAnalysisResponse(
            match_id=match_id,
            verdict=verdict,
            ensemble=ensemble,
            uncertainty=uncertainty,
            model_drivers=active_drivers,
            causal_drivers=active_drivers,
            rl_recommendation=rl_rec,
            elo_context=elo_ctx,
            odds_edge=odds_edge,
            narrative=narrative,
            partial_intelligence=partial,
            data_gaps=gaps,
            evidence_quality=evidence_quality,
            prediction_status=prediction_status,
            prediction_source=prediction_source,
            probabilities_available=probabilities_available,
            is_reduced_evidence_baseline=prediction_status == "REDUCED_EVIDENCE_BASELINE",
            effective_kelly_cap=effective_kelly_cap,
            stake_permitted=stake_permitted,
            staleness_seconds=staleness,
            staleness_available=staleness_available,
            feature_freshness_seconds=freshness,
            feature_source=feat_source,
            actionability=actionability,
            match_importance_score=match_importance_score,
            competition_stage=competition_stage,
            home_team=kwargs.get("home_team"),
            away_team=kwargs.get("away_team"),
            league=kwargs.get("league") or ensemble.league,
            kickoff_utc=kwargs.get("kickoff_utc"),
            fixture_verified=kwargs.get("fixture_verified"),
            field_availability=dict(kwargs.get("field_availability") or {}),
            unavailable_reasons=dict(kwargs.get("unavailable_reasons") or {}),
        )

    # ------------------------------------------------------------------
    # Verdict computation (TYPE-F fusion gate table, spec §7-D)
    # ------------------------------------------------------------------

    def _compute_verdict(
        self,
        ensemble: EnsemblePrediction,
        uncertainty: Optional[UncertaintyBreakdown],
        active_drivers: List[str],
        rl_rec: RLRecommendationPayload,
        partial: bool,
    ) -> str:
        # PARTIAL takes priority — analysis is incomplete (B13).
        if partial:
            return "PARTIAL"

        if uncertainty is None:
            return "HOLD"

        tier_ok = uncertainty.confidence_tier == "OK"
        abstains = rl_rec.abstain

        # HOLD: either model is uncertain or RL recommends no action.
        if not tier_ok or abstains:
            return "HOLD"

        elo_is_driver = "elo_difference" in active_drivers
        max_prob = ensemble.confidence

        # HIGH_CONVICTION: model confident + Elo causal signal + RL bets.
        if max_prob > 0.52 and elo_is_driver:
            return "HIGH_CONVICTION"

        # ACTIONABLE: RL bets + at least one causal driver fires.
        if active_drivers:
            return "ACTIONABLE"

        # SPECULATIVE: confidence tier is OK but no causal signal.
        return "SPECULATIVE"

    # ------------------------------------------------------------------
    # Phase 8 context extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _phase8_context(features_dict: dict, data_gaps: List[str]) -> dict:
        """Extract Phase 8 signals that are live (not in data_gaps)."""
        ctx: dict = {}
        for key in ("max_abs_odds_drift", "sharp_money_direction",
                    "match_importance_score", "odds_drift_home",
                    "odds_drift_draw", "odds_drift_away"):
            if key not in data_gaps and key in features_dict:
                val = features_dict[key]
                if val is not None:
                    ctx[key] = float(val)
        return ctx

    # ------------------------------------------------------------------
    # Narrative generation (B11: ≤280 chars, B14: grounded in values)
    # ------------------------------------------------------------------

    def _compose_narrative(
        self,
        ensemble: EnsemblePrediction,
        uncertainty: UncertaintyBreakdown,
        verdict: str,
        active_drivers: List[str],
        elo_ctx: EloContext,
        rl_rec: RLRecommendationPayload,
        phase8_ctx: Optional[dict] = None,
    ) -> str:
        outcome_label = {
            "home_win": "home win",
            "draw": "draw",
            "away_win": "away win",
        }.get(ensemble.prediction, ensemble.prediction)

        pct = round(ensemble.confidence * 100, 1)
        tier = uncertainty.confidence_tier

        parts: list[str] = [
            f"Model: {outcome_label} ({pct}%, {tier}).",
        ]

        elo_diff = elo_ctx.elo_difference
        if abs(elo_diff) >= 10:
            direction = "home" if elo_diff > 0 else "away"
            parts.append(f"Elo: {direction} +{abs(round(elo_diff))}pts.")

        if active_drivers:
            driver_str = ", ".join(active_drivers[:3])
            if len(active_drivers) > 3:
                driver_str += f" +{len(active_drivers) - 3} more"
            parts.append(f"Causal: {driver_str}.")

        # Phase 8 signals — only appended when live data is available (not data_gaps)
        if phase8_ctx:
            drift = phase8_ctx.get("max_abs_odds_drift", 0.0)
            if drift >= 0.05:
                direction_idx = int(phase8_ctx.get("sharp_money_direction", 0))
                direction_label = ("home", "draw", "away")[direction_idx]
                parts.append(f"Market: sharp move → {direction_label} (drift {drift:.3f}).")

            importance = phase8_ctx.get("match_importance_score", 0.0)
            if importance >= 0.70:
                parts.append(f"Stakes: high-importance fixture ({importance:.2f}).")

        if not rl_rec.abstain and rl_rec.stake_fraction > 0:
            stake_pct = round(rl_rec.stake_fraction * 100, 1)
            parts.append(f"RL: stake {stake_pct}%.")
        elif rl_rec.abstain:
            parts.append("RL: abstain.")

        narrative = " ".join(parts)
        # B11: hard cap at 280 characters.
        return textwrap.shorten(narrative, width=280, placeholder="…")
