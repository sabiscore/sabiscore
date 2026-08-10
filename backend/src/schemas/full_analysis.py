"""Typed public contract for the unified match-intelligence response."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class PredictionStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    REDUCED_EVIDENCE_BASELINE = "REDUCED_EVIDENCE_BASELINE"
    UNAVAILABLE = "UNAVAILABLE"


class PredictionSource(str, Enum):
    CERTIFIED_MODEL = "CERTIFIED_MODEL"
    DIAGNOSTIC_BASELINE = "DIAGNOSTIC_BASELINE"
    NONE = "NONE"


class FullMatchEnsembleResponse(BaseModel):
    home_win_prob: float = Field(ge=0.0, le=1.0)
    draw_prob: float = Field(ge=0.0, le=1.0)
    away_win_prob: float = Field(ge=0.0, le=1.0)
    prediction: str
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Deprecated compatibility alias for top_outcome_probability.",
    )
    top_outcome_probability: float = Field(ge=0.0, le=1.0)
    probabilities_available: bool
    league: str
    model_version: str
    calibration_method: str
    calibration_applied: bool
    overlay_applied: bool

    @model_validator(mode="after")
    def validate_probability_contract(self) -> "FullMatchEnsembleResponse":
        total = self.home_win_prob + self.draw_prob + self.away_win_prob
        if self.probabilities_available and abs(total - 1.0) > 1e-4:
            raise ValueError("available probabilities must sum to 1")
        expected_top = max(self.home_win_prob, self.draw_prob, self.away_win_prob)
        if abs(self.top_outcome_probability - expected_top) > 1e-4:
            raise ValueError("top_outcome_probability must equal the largest class probability")
        if abs(self.confidence - self.top_outcome_probability) > 1e-4:
            raise ValueError("confidence compatibility alias must equal top_outcome_probability")
        return self


class FullMatchUncertaintyResponse(BaseModel):
    epistemic_unc: float
    aleatoric_unc: float
    concentration: float
    credible_interval: List[float] = Field(min_length=2, max_length=2)
    confidence_tier: str


class FullMatchRLRecommendationResponse(BaseModel):
    stake_fraction: float = Field(ge=0.0)
    abstain: bool
    reason: Optional[str]
    reward_components: Dict[str, float]


class FullMatchEloResponse(BaseModel):
    home_elo: float
    away_elo: float
    elo_difference: float
    home_elo_trend_5: float
    away_elo_trend_5: float
    elo_momentum_cross: float


class FullMatchOddsEdgeResponse(BaseModel):
    market: str
    market_odds: float
    model_prob: float
    edge: float
    kelly_stake: float = Field(ge=0.0)


class MatchActionabilityResponse(BaseModel):
    edge_quality_score: float = Field(ge=0.0, le=1.0)
    clv_pct: Optional[float]
    closing_line_convergence_delta: Optional[float]
    suggested_stake_pct: float = Field(ge=0.0)
    abstain: bool
    abstain_reason: Optional[str]
    top_evidence: List[str]
    caveats: List[str]


class EvidenceQualityResponse(BaseModel):
    critical_gaps: List[str]
    advisory_gaps: List[str]
    conflicts: List[str]
    all_gaps: List[str]
    critical_gap_count: int = Field(ge=0)
    advisory_gap_count: int = Field(ge=0)
    conflict_count: int = Field(ge=0)
    total_gap_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_normalized_evidence(self) -> "EvidenceQualityResponse":
        groups = (self.critical_gaps, self.advisory_gaps, self.conflicts)
        if any(len(values) != len(dict.fromkeys(values)) for values in groups):
            raise ValueError("evidence categories must be deduplicated")
        expected_all = list(dict.fromkeys([*self.critical_gaps, *self.advisory_gaps, *self.conflicts]))
        if self.all_gaps != expected_all:
            raise ValueError("all_gaps must be the normalized evidence union")
        expected_counts = (
            len(self.critical_gaps),
            len(self.advisory_gaps),
            len(self.conflicts),
            len(self.all_gaps),
        )
        actual_counts = (
            self.critical_gap_count,
            self.advisory_gap_count,
            self.conflict_count,
            self.total_gap_count,
        )
        if actual_counts != expected_counts:
            raise ValueError("evidence category counts must match normalized lists")
        return self


class FullMatchAnalysisResponseSchema(BaseModel):
    match_id: str
    verdict: Literal[
        "HIGH_CONVICTION",
        "ACTIONABLE",
        "SPECULATIVE",
        "HOLD",
        "NO_BET",
        "PARTIAL",
    ]
    prediction_status: PredictionStatus
    prediction_source: PredictionSource
    probabilities_available: bool
    is_reduced_evidence_baseline: bool
    top_outcome_probability: float = Field(ge=0.0, le=1.0)
    effective_kelly_cap: float = Field(ge=0.0, le=0.05)
    stake_permitted: bool
    evidence_quality: EvidenceQualityResponse
    ensemble: FullMatchEnsembleResponse
    uncertainty: Optional[FullMatchUncertaintyResponse]
    model_drivers: List[str]
    causal_drivers: List[str]
    rl_recommendation: FullMatchRLRecommendationResponse
    elo_context: Optional[FullMatchEloResponse]
    odds_edge: Optional[FullMatchOddsEdgeResponse]
    narrative: str = Field(max_length=280)
    partial_intelligence: bool
    data_gaps: List[str] = Field(
        description="Backward-compatible alias of evidence_quality.all_gaps."
    )
    staleness_seconds: int = Field(ge=0)
    staleness_available: bool
    freshness_tag: Literal["LIVE", "RECENT", "STALE", "UNKNOWN"]
    feature_freshness_seconds: Dict[str, Optional[int]]
    feature_source: Dict[str, str]
    actionability: Optional[MatchActionabilityResponse]
    match_importance_score: Optional[float]
    competition_stage: Optional[str]
    home_team: Optional[str] = None
    away_team: Optional[str] = None
    league: Optional[str] = None
    kickoff_utc: Optional[datetime] = None
    fixture_verified: Optional[bool] = None
    field_availability: Dict[str, bool] = Field(default_factory=dict)
    unavailable_reasons: Dict[str, str] = Field(default_factory=dict)
    generated_at: datetime
    phase9_candidate_features: Optional[Dict[str, Any]] = None
    phase9_shadow_only: Optional[bool] = None

    @model_validator(mode="after")
    def validate_availability_and_staking(self) -> "FullMatchAnalysisResponseSchema":
        if self.data_gaps != self.evidence_quality.all_gaps:
            raise ValueError("data_gaps must remain an alias of evidence_quality.all_gaps")
        if self.probabilities_available != self.ensemble.probabilities_available:
            raise ValueError("probability availability fields must agree")
        if self.probabilities_available != (self.prediction_status == PredictionStatus.AVAILABLE):
            raise ValueError("prediction_status and probabilities_available must agree")
        expected_source = {
            PredictionStatus.AVAILABLE: PredictionSource.CERTIFIED_MODEL,
            PredictionStatus.REDUCED_EVIDENCE_BASELINE: PredictionSource.DIAGNOSTIC_BASELINE,
            PredictionStatus.UNAVAILABLE: PredictionSource.NONE,
        }[self.prediction_status]
        if self.prediction_source != expected_source:
            raise ValueError("prediction_source must agree with prediction_status")
        if self.is_reduced_evidence_baseline != (
            self.prediction_status == PredictionStatus.REDUCED_EVIDENCE_BASELINE
        ):
            raise ValueError("reduced-evidence flag must agree with prediction_status")
        if abs(self.top_outcome_probability - self.ensemble.top_outcome_probability) > 0.0001:
            raise ValueError("top_outcome_probability fields must agree")
        expected_partial = bool(
            self.evidence_quality.critical_gaps or self.evidence_quality.conflicts
        )
        if self.partial_intelligence != expected_partial:
            raise ValueError("partial_intelligence must derive only from critical gaps or conflicts")
        if self.stake_permitted and (
            self.partial_intelligence
            or self.verdict not in {"ACTIONABLE", "HIGH_CONVICTION"}
            or self.rl_recommendation.abstain
            or self.rl_recommendation.stake_fraction <= 0
            or self.uncertainty is None
            or self.fixture_verified is not True
        ):
            raise ValueError("stake_permitted is inconsistent with the verdict gate")
        if not self.stake_permitted:
            if self.rl_recommendation.stake_fraction > 0:
                raise ValueError("non-permitted states must expose zero RL stake")
            if self.odds_edge is not None and self.odds_edge.kelly_stake > 0:
                raise ValueError("non-permitted states must expose zero Kelly stake")
            if (
                self.actionability is not None
                and self.actionability.suggested_stake_pct > 0
            ):
                raise ValueError("non-permitted states must expose zero suggested stake")
        return self


__all__ = [
    "EvidenceQualityResponse",
    "FullMatchAnalysisResponseSchema",
    "PredictionSource",
    "PredictionStatus",
]
