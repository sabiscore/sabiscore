"""
Prediction Schemas - Production-ready Pydantic models
Naira-based currency, comprehensive value bet information
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Tuple
from pydantic import BaseModel, Field, field_validator, ConfigDict
from enum import Enum

from .value_bet import ValueBetResponse


class PredictionOutcome(str, Enum):
    """Match outcome types"""

    HOME_WIN = "home_win"
    DRAW = "draw"
    AWAY_WIN = "away_win"


class LeagueCode(str, Enum):
    """Supported leagues"""

    EPL = "epl"
    BUNDESLIGA = "bundesliga"
    LA_LIGA = "la_liga"
    SERIE_A = "serie_a"
    LIGUE_1 = "ligue_1"
    EREDIVISIE = "eredivisie"
    UCL = "ucl"


class MatchPredictionRequest(BaseModel):
    """Request model for match prediction"""

    match_id: Optional[str] = None
    home_team: str = Field(..., min_length=2, max_length=100)
    away_team: str = Field(..., min_length=2, max_length=100)
    league: LeagueCode = Field(..., description="League identifier")
    kickoff_time: Optional[datetime] = None
    odds: Dict[str, float] = Field(
        default_factory=dict, description="Market odds (home_win, draw, away_win)"
    )
    bankroll: Optional[float] = Field(
        default=10_000,
        description="Bankroll in Naira (₦) for Kelly calculation",
        ge=1000,
        le=100_000_000,
    )

    @field_validator("odds", mode="after")
    def validate_odds(cls, v: Dict[str, float]) -> Dict[str, float]:
        """Ensure odds are valid decimal odds"""
        for market, odd in v.items():
            if odd < 1.01 or odd > 1000:
                raise ValueError(f"Invalid odd for {market}: {odd}")
        return v


class CredibleInterval(BaseModel):
    """Credible interval bounds for uncertainty display."""

    lower: float = Field(..., ge=0, le=1)
    upper: float = Field(..., ge=0, le=1)


class UncertaintyBreakdown(BaseModel):
    """Uncertainty decomposition payload."""

    epistemic_unc: float = Field(..., ge=0)
    aleatoric_unc: float = Field(..., ge=0)
    concentration: float = Field(..., ge=0)
    credible_interval: CredibleInterval
    confidence_tier: str = Field(
        default="OK", description='"LOW_EVIDENCE" | "OK" — C12'
    )


class RLRecommendation(BaseModel):
    """Optional reinforcement-learning betting recommendation."""

    stake_fraction: float = Field(..., ge=0, le=1)
    abstain: bool = False
    reward_components: Dict[str, float] = Field(default_factory=dict)
    reason: Optional[str] = None


class PredictionResponse(BaseModel):
    """Comprehensive match prediction response"""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "match_id": "epl_2025_234",
                "home_team": "Arsenal",
                "away_team": "Liverpool",
                "league": "epl",
                "predictions": {
                    "home_win": 0.421,
                    "draw": 0.286,
                    "away_win": 0.293,
                },
                "confidence": 0.421,
                "brier_score": 0.178,
                "metadata": {"model_version": "3.0", "processing_time_ms": 142},
                "created_at": "2025-11-11T14:32:00Z",
            }
        }
    )

    match_id: str
    home_team: str
    away_team: str
    league: LeagueCode
    predictions: Dict[str, float] = Field(
        ..., description="Probabilities for home_win, draw, away_win"
    )
    confidence: float = Field(..., ge=0, le=1, description="Highest probability")
    brier_score: float = Field(..., ge=0, le=2, description="Expected Brier score")
    value_bets: List[ValueBetResponse] = Field(
        default_factory=list, description="Identified value betting opportunities"
    )
    confidence_intervals: Dict[str, Tuple[float, float]] = Field(
        default_factory=dict, description="95% confidence intervals for each outcome"
    )
    explanations: Dict[str, Any] = Field(
        default_factory=dict, description="SHAP feature importance and explanations"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Model metadata and performance metrics"
    )
    uncertainty: Optional[UncertaintyBreakdown] = Field(
        default=None,
        description="Epistemic and aleatoric uncertainty decomposition",
    )
    rl_recommendation: Optional[RLRecommendation] = Field(
        default=None,
        description="Optional RL-based staking recommendation",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("predictions", mode="after")
    def validate_probabilities_sum(cls, v: Dict[str, float]) -> Dict[str, float]:
        """Ensure probabilities sum to 1.0 (within tolerance)"""
        total = sum(v.values())
        if not 0.98 <= total <= 1.02:
            raise ValueError(f"Probabilities must sum to ~1.0, got {total}")
        return v


class PredictionCreate(BaseModel):
    """Schema for storing predictions in database"""

    model_config = ConfigDict(protected_namespaces=())

    match_id: str
    home_win_prob: float = Field(..., ge=0, le=1)
    draw_prob: float = Field(..., ge=0, le=1)
    away_win_prob: float = Field(..., ge=0, le=1)
    confidence: float = Field(..., ge=0, le=1)
    brier_score: Optional[float] = None
    model_version: str = "3.0"
    is_calibrated: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CalibrationMetrics(BaseModel):
    """Live calibration status and metrics"""

    platt_a: float = Field(..., description="Platt scaling parameter A")
    platt_b: float = Field(..., description="Platt scaling parameter B")
    last_calibration: Optional[datetime] = None
    samples_used: int = Field(..., ge=0, description="Samples in calibration window")
    calibration_window_hours: int = 24
    mean_squared_error: Optional[float] = None
    log_loss: Optional[float] = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "platt_a": 1.042,
                "platt_b": -0.018,
                "last_calibration": "2025-11-11T14:30:00Z",
                "samples_used": 127,
                "mean_squared_error": 0.0184,
            }
        }
    )


class EdgeDetectionRequest(BaseModel):
    """Request for edge detection on specific markets"""

    match_id: str
    fair_probabilities: Dict[str, float]
    market_odds: Dict[str, float]
    bankroll_ngn: float = Field(default=10_000, ge=1000)
    min_edge_threshold: float = Field(default=0.042, ge=0, le=1)
    kelly_fraction: float = Field(default=0.25, ge=0.01, le=1.0)


class EdgeDetectionResponse(BaseModel):
    """Response with detected edges and stake recommendations"""

    match_id: str
    edges_found: int
    value_bets: List[ValueBetResponse]
    total_potential_edge_ngn: float
    recommended_total_stake_ngn: float
    expected_roi_percent: float
    risk_assessment: str = Field(..., description="LOW, MEDIUM, HIGH based on variance")

    @field_validator("risk_assessment", mode="after")
    def validate_risk(cls, v: str) -> str:
        if v not in ["LOW", "MEDIUM", "HIGH"]:
            raise ValueError("Risk must be LOW, MEDIUM, or HIGH")
        return v


class LivePredictionUpdate(BaseModel):
    """WebSocket update for live predictions"""

    match_id: str
    event_type: str = Field(..., description="goal, card, substitution, etc.")
    updated_probabilities: Dict[str, float]
    minute: int = Field(..., ge=0, le=120)
    confidence: float
    new_value_bets: List[ValueBetResponse] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PredictionHistoryResponse(BaseModel):
    """Historical prediction performance"""

    total_predictions: int
    accuracy: float = Field(..., ge=0, le=1)
    high_confidence_accuracy: float = Field(..., ge=0, le=1)
    avg_brier_score: float
    avg_clv_ngn: float
    roi_percent: float
    value_bets_count: int
    profitable_bets: int
    league_breakdown: Dict[str, Dict[str, float]]
    date_range: Dict[str, datetime]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "total_predictions": 500,
                "accuracy": 0.45,
                "high_confidence_accuracy": 0.50,
                "avg_brier_score": 0.230,
                "avg_clv_ngn": 5,
                "roi_percent": 2.1,
                "value_bets_count": 80,
                "profitable_bets": 44,
                "league_breakdown": {
                    "epl": {"accuracy": 0.447, "roi": 2.4},
                    "bundesliga": {"accuracy": 0.419, "roi": 1.8},
                },
                "date_range": {
                    "start": "2025-08-01T00:00:00Z",
                    "end": "2026-07-05T00:00:00Z",
                },
            }
        }
    )


class ModelPerformanceMetrics(BaseModel):
    """Real-time model performance metrics"""

    predictions_today: int
    avg_processing_time_ms: float = Field(
        ...,
        description=(
            "Average model inference time (predict_proba over 68-vector). "
            "Budget: ≤150ms p95 for inference only — not the full request cycle (~1–2.5s)."
        ),
    )
    cache_hit_rate: float = Field(..., ge=0, le=1)
    calibration_status: CalibrationMetrics
    value_bets_identified: int
    avg_edge_ngn: float
    uptime_percent: float = Field(..., ge=0, le=100)
    errors_last_hour: int

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "predictions_today": 347,
                "avg_processing_time_ms": 142,
                "cache_hit_rate": 0.87,
                "value_bets_identified": 73,
                "avg_edge_ngn": 172,
                "uptime_percent": 99.94,
                "errors_last_hour": 0,
            }
        }
    )
