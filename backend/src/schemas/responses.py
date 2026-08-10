from pydantic import BaseModel, Field, ConfigDict
from typing import List, Dict, Any, Optional, Tuple
from enum import Enum
from datetime import datetime, timezone


class CacheMetricsResponse(BaseModel):
    hits: int = Field(..., ge=0)
    misses: int = Field(..., ge=0)
    errors: int = Field(..., ge=0)
    circuit_open: bool = Field(...)
    memory_entries: int = Field(..., ge=0)


class HealthResponse(BaseModel):
    # include json encoder and allow use of properties starting with 'model_'
    model_config = ConfigDict(protected_namespaces=())

    status: str = Field(..., json_schema_extra={"example": "healthy"})
    database: bool = Field(..., json_schema_extra={"example": True})
    models: bool = Field(..., json_schema_extra={"example": True})
    model_loading: Optional[bool] = Field(False, json_schema_extra={"example": False})
    model_error: Optional[str] = Field(None, json_schema_extra={"example": "No model available"})
    cache: bool = Field(..., json_schema_extra={"example": True})
    cache_metrics: Optional[CacheMetricsResponse] = None
    latency_ms: float = Field(..., ge=0, json_schema_extra={"example": 12.5})
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class MatchSearchResponse(BaseModel):
    id: str = Field(..., json_schema_extra={"example": "1"})
    home_team: str = Field(..., json_schema_extra={"example": "Manchester City"})
    away_team: str = Field(..., json_schema_extra={"example": "Liverpool"})
    league: str = Field(..., json_schema_extra={"example": "EPL"})
    match_date: str = Field(..., json_schema_extra={"example": "2024-10-26T15:00:00Z"})
    venue: str = Field(..., json_schema_extra={"example": "Etihad Stadium"})

class PredictionData(BaseModel):
    home_win_prob: float = Field(..., ge=0, le=1, json_schema_extra={"example": 0.65})
    draw_prob: float = Field(..., ge=0, le=1, json_schema_extra={"example": 0.20})
    away_win_prob: float = Field(..., ge=0, le=1, json_schema_extra={"example": 0.15})
    prediction: str = Field(..., json_schema_extra={"example": "home_win"})
    confidence: float = Field(..., ge=0, le=1, json_schema_extra={"example": 0.78})
    # True when the model was unavailable and these are baseline rates, not an inference.
    is_baseline: bool = Field(default=False, json_schema_extra={"example": False})

class XGData(BaseModel):
    home_xg: float = Field(..., ge=0, json_schema_extra={"example": 2.1})
    away_xg: float = Field(..., ge=0, json_schema_extra={"example": 1.3})
    total_xg: float = Field(..., ge=0, json_schema_extra={"example": 3.4})
    xg_difference: float = Field(..., json_schema_extra={"example": 0.8})

class ValueBetQuality(BaseModel):
    quality_score: float = Field(..., ge=0, le=100, json_schema_extra={"example": 75.5})
    tier: str = Field(..., json_schema_extra={"example": "Good"})
    recommendation: str = Field(..., json_schema_extra={"example": "Consider betting"})
    ev_contribution: float = Field(..., json_schema_extra={"example": 15.2})
    confidence_contribution: float = Field(..., json_schema_extra={"example": 39.0})
    liquidity_contribution: float = Field(..., json_schema_extra={"example": 18.75})

class ValueBet(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    bet_type: str = Field(..., json_schema_extra={"example": "home_win"})
    market_odds: float = Field(..., gt=0, json_schema_extra={"example": 2.10})
    model_prob: float = Field(..., ge=0, le=1, json_schema_extra={"example": 0.65})
    market_prob: float = Field(..., ge=0, le=1, json_schema_extra={"example": 0.476})
    expected_value: float = Field(..., json_schema_extra={"example": 0.152})
    value_pct: float = Field(..., json_schema_extra={"example": 36.6})
    # Bankroll fraction (Quarter-Kelly), never a currency amount. Bounded by the
    # global 5% ceiling so an uncapped sizing bug cannot reach a client.
    kelly_stake: float = Field(..., ge=0, le=0.05, json_schema_extra={"example": 0.05})
    confidence_interval: List[float] = Field(..., json_schema_extra={"example": [0.58, 0.72]})
    edge: float = Field(..., json_schema_extra={"example": 0.174})
    recommendation: str = Field(..., json_schema_extra={"example": "Strong bet"})
    quality: ValueBetQuality

class MonteCarloData(BaseModel):
    simulations: int = Field(..., json_schema_extra={"example": 10000})
    distribution: Dict[str, float] = Field(..., json_schema_extra={"example": {"home_win": 0.65, "draw": 0.20, "away_win": 0.15}})
    confidence_intervals: Dict[str, List[float]] = Field(..., json_schema_extra={"example": {"home_win": [0.63, 0.67]}})

class Scenario(BaseModel):
    name: str = Field(..., json_schema_extra={"example": "Most Likely"})
    probability: float = Field(..., ge=0, le=1, json_schema_extra={"example": 0.65})
    home_score: int = Field(..., ge=0, json_schema_extra={"example": 2})
    away_score: int = Field(..., ge=0, json_schema_extra={"example": 1})
    result: str = Field(..., json_schema_extra={"example": "home_win"})

class RiskAssessment(BaseModel):
    risk_level: str = Field(..., json_schema_extra={"example": "low"})
    confidence_score: float = Field(..., ge=0, le=1, json_schema_extra={"example": 0.78})
    value_available: bool = Field(..., json_schema_extra={"example": True})
    best_bet: Optional[ValueBet] = None
    distribution: Dict[str, float] = Field(default_factory=dict)
    recommendation: str = Field(..., json_schema_extra={"example": "Proceed"})

class Metadata(BaseModel):
    matchup: str = Field(..., json_schema_extra={"example": "Manchester City vs Liverpool"})
    league: str = Field(..., json_schema_extra={"example": "EPL"})
    home_team: str = Field(..., json_schema_extra={"example": "Manchester City"})
    away_team: str = Field(..., json_schema_extra={"example": "Liverpool"})


class TransformationStep(BaseModel):
    step: str = Field(..., json_schema_extra={"example": "feature_engineering"})
    function: str = Field(..., json_schema_extra={"example": "FeatureTransformer.engineer_features"})
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DataProvenance(BaseModel):
    """Traceability metadata for insights responses."""

    source: Dict[str, Any] = Field(
        default_factory=dict,
        description="Details about the primary origin (e.g., ml_model, cache, database)",
        json_schema_extra={
            "example": {
                "type": "ml_model",
                "origin": "ensemble_v7",
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "version": "7.0.0",
            }
        },
    )
    computed_from: List[str] = Field(
        default_factory=list,
        description="Identifiers of upstream records used to compute this response",
        json_schema_extra={"example": ["match:ARS-BOU", "team_stats:arsenal", "team_stats:bournemouth"]},
    )
    transformations: List[TransformationStep] = Field(
        default_factory=list,
        description="Ordered pipeline steps applied to produce the response",
    )
    real_time_adjusted: bool = Field(
        default=False,
        description="Indicates whether live market odds or last-mile adjustments were applied",
    )
    drift_detected: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Drift detection status and metrics",
        json_schema_extra={
            "example": {
                "flag": False,
                "baseline_value": 0.71,
                "current_value": 0.73,
                "threshold_exceeded": False,
            }
        },
    )
    validation_status: str = Field(
        default="pending",
        description="Validation state of the response (pending | passed | failed)",
        json_schema_extra={"example": "pending"},
    )


class InsightsUncertainty(BaseModel):
    epistemic_unc: float = Field(..., ge=0)
    aleatoric_unc: float = Field(..., ge=0)
    concentration: float = Field(..., ge=0)
    credible_interval: Dict[str, float] = Field(default_factory=dict)
    confidence_tier: str = Field(default="OK", description='"LOW_EVIDENCE" | "OK" — C12')


class CausalSummary(BaseModel):
    top_drivers: List[str] = Field(default_factory=list)
    collider_warnings: List[str] = Field(default_factory=list)
    source: Optional[str] = None
    status: str = Field(default="unavailable")


class CausalClassification(str, Enum):
    CAUSAL_DRIVER = "CAUSAL_DRIVER"
    CONFOUNDED = "CONFOUNDED"
    INDEPENDENT = "INDEPENDENT"
    COLLIDER_WARNING = "COLLIDER_WARNING"


class CausalFeatureResponse(BaseModel):
    name: str
    ate_win: float
    ate_draw: float
    ate_ci: Tuple[float, float]
    p_value: float = Field(..., ge=0, le=1)
    classification: CausalClassification


class CausalFeaturesResponse(BaseModel):
    features: List[CausalFeatureResponse] = Field(default_factory=list)
    source: str
    count: int = Field(..., ge=0)


class RLRecommendation(BaseModel):
    stake_fraction: float = Field(..., ge=0, le=1)
    abstain: bool = Field(default=False)
    reward_components: Dict[str, float] = Field(default_factory=dict)
    reason: Optional[str] = None


class InsightsResponse(BaseModel):
    model_config = ConfigDict()

    matchup: str = Field(..., json_schema_extra={"example": "Manchester City vs Liverpool"})
    league: str = Field(..., json_schema_extra={"example": "EPL"})
    metadata: Metadata
    predictions: PredictionData
    xg_analysis: XGData
    value_analysis: Dict[str, Any] = Field(..., description="Enhanced value betting analysis")
    monte_carlo: MonteCarloData
    scenarios: List[Scenario] = Field(default_factory=list)
    explanation: Dict[str, Any] = Field(default_factory=dict)
    risk_assessment: RiskAssessment
    narrative: str = Field(..., description="Human-readable analysis summary")
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    confidence_level: float = Field(..., ge=0, le=1, json_schema_extra={"example": 0.78})
    uncertainty: Optional[InsightsUncertainty] = Field(default=None)
    causal_summary: Optional[CausalSummary] = Field(default=None)
    rl_recommendation: Optional[RLRecommendation] = Field(default=None)
    provenance: Optional[DataProvenance] = Field(
        default=None,
        description="Traceability metadata describing source, transformations, and validation state",
    )

class ErrorResponse(BaseModel):
    model_config = ConfigDict()

    detail: str = Field(..., json_schema_extra={"example": "An error occurred"})
    error_code: Optional[str] = Field(None, json_schema_extra={"example": "VALIDATION_ERROR"})
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
