"""Certified prediction routes backed by the strict analytics engine."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.session import get_async_session
from ...schemas.betting_intelligence import MatchAnalysisResult
from ...services.analytics import CertifiedAnalyticsService


router = APIRouter(prefix="/predictions", tags=["certified-predictions"])


class CertifiedModelInput(BaseModel):
    home_probability: float = Field(..., ge=0.0, le=1.0)
    draw_probability: float = Field(..., ge=0.0, le=1.0)
    away_probability: float = Field(..., ge=0.0, le=1.0)
    model_version: str | None = None
    calibration_method: str | None = None
    calibration_validated: bool | None = None
    epistemic_uncertainty: float | None = Field(default=None, ge=0.0)
    aleatoric_uncertainty: float | None = Field(default=None, ge=0.0)
    confidence_tier: Literal["OK", "LOW_EVIDENCE"] | None = None


class CertifiedMarketInput(BaseModel):
    bookmaker: str = Field(..., min_length=2)
    market_type: Literal["1X2"] = "1X2"
    home_odds: float = Field(..., gt=1.0)
    draw_odds: float = Field(..., gt=1.0)
    away_odds: float = Field(..., gt=1.0)
    opening_home_odds: float | None = Field(default=None, gt=1.0)
    opening_draw_odds: float | None = Field(default=None, gt=1.0)
    opening_away_odds: float | None = Field(default=None, gt=1.0)
    captured_at: datetime


class CertifiedSignalsInput(BaseModel):
    xg_differential: float | None = None
    xga_differential: float | None = None
    opponent_adjusted_form: float | None = None
    club_elo_difference: float | None = None
    schedule_congestion: float | None = None
    travel_load: float | None = None
    confirmed_absences: list[str] = Field(default_factory=list)
    lineup_status: Literal["CONFIRMED", "PROVISIONAL", "UNKNOWN"] = "UNKNOWN"
    sharp_market_signal: Literal["CONFIRMING", "NEUTRAL", "CONFLICTING", "UNKNOWN"] = "UNKNOWN"


class CertifiedFreshnessInput(BaseModel):
    model_features_seconds: int | None = None
    market_seconds: int | None = None
    injury_news_seconds: int | None = None
    lineup_seconds: int | None = None


class CertifiedSourceStatusInput(BaseModel):
    model: Literal["VERIFIED", "STALE", "CONFLICTING", "DATA_GAP"] = "DATA_GAP"
    market: Literal["VERIFIED", "STALE", "CONFLICTING", "DATA_GAP"] = "DATA_GAP"
    team_metrics: Literal["VERIFIED", "STALE", "CONFLICTING", "DATA_GAP"] = "DATA_GAP"
    availability: Literal["VERIFIED", "STALE", "CONFLICTING", "DATA_GAP"] = "DATA_GAP"


class CertifiedPredictionRequest(BaseModel):
    match_id: str = Field(..., min_length=1)
    home_team: str = Field(..., min_length=1)
    away_team: str = Field(..., min_length=1)
    competition: str = "EPL"
    kickoff_utc: datetime
    model: CertifiedModelInput
    market: CertifiedMarketInput | None = None
    signals: CertifiedSignalsInput = Field(default_factory=CertifiedSignalsInput)
    freshness: CertifiedFreshnessInput = Field(default_factory=CertifiedFreshnessInput)
    source_status: CertifiedSourceStatusInput = Field(default_factory=CertifiedSourceStatusInput)
    data_gaps: list[str] = Field(default_factory=list)
    known_risks: list[str] = Field(default_factory=list)


class CertifiedPredictionHealth(BaseModel):
    status: Literal["ready"]
    engine: Literal["betting_intelligence"]


@router.post("/analyze", response_model=MatchAnalysisResult)
async def analyze_prediction(
    request: CertifiedPredictionRequest,
    db: AsyncSession = Depends(get_async_session),
) -> MatchAnalysisResult:
    """Evaluate untrusted caller input without certifying it for execution."""
    try:
        service = CertifiedAnalyticsService(db)
        return await service.analyze_payload(request.model_dump(), trusted_backend=False)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/certified-health", response_model=CertifiedPredictionHealth)
async def certified_prediction_health() -> CertifiedPredictionHealth:
    return CertifiedPredictionHealth(status="ready", engine="betting_intelligence")
