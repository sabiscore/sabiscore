"""Schemas for the deterministic SabiScore core engine endpoint."""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


Verdict = Literal[
    "HIGH_CONVICTION",
    "ACTIONABLE",
    "SPECULATIVE",
    "HOLD",
    "PARTIAL",
    "NO_BET",
]


class CoreModelInput(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    home_probability: Optional[float] = None
    draw_probability: Optional[float] = None
    away_probability: Optional[float] = None
    model_version: Optional[str] = None
    calibration_method: Optional[str] = None
    calibration_validated: Optional[bool] = None
    generation_certified: Optional[bool] = None
    epistemic_uncertainty: Optional[float] = None
    aleatoric_uncertainty: Optional[float] = None
    confidence_tier: Optional[Literal["OK", "LOW_EVIDENCE"]] = None


class CoreMarketInput(BaseModel):
    bookmaker: Optional[str] = None
    market_type: Optional[str] = None
    home_odds: Optional[float] = None
    draw_odds: Optional[float] = None
    away_odds: Optional[float] = None
    opening_home_odds: Optional[float] = None
    opening_draw_odds: Optional[float] = None
    opening_away_odds: Optional[float] = None
    captured_at: Optional[datetime] = None


class CoreSignalsInput(BaseModel):
    xg_differential: Optional[float] = None
    xga_differential: Optional[float] = None
    opponent_adjusted_form: Optional[float] = None
    club_elo_difference: Optional[float] = None
    schedule_congestion: Optional[float] = None
    travel_load: Optional[float] = None
    confirmed_absences: Optional[List[str]] = None
    lineup_status: Optional[Literal["CONFIRMED", "PROVISIONAL", "UNKNOWN"]] = None
    sharp_market_signal: Optional[
        Literal["CONFIRMING", "NEUTRAL", "CONFLICTING", "UNKNOWN"]
    ] = None


class CoreFreshnessInput(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    model_features_seconds: Optional[int] = None
    market_seconds: Optional[int] = None
    injury_news_seconds: Optional[int] = None
    lineup_seconds: Optional[int] = None


class CoreSourceStatusInput(BaseModel):
    model: Optional[Literal["VERIFIED", "STALE", "CONFLICTING", "DATA_GAP"]] = None
    market: Optional[Literal["VERIFIED", "STALE", "CONFLICTING", "DATA_GAP"]] = None
    team_metrics: Optional[
        Literal["VERIFIED", "STALE", "CONFLICTING", "DATA_GAP"]
    ] = None
    availability: Optional[
        Literal["VERIFIED", "STALE", "CONFLICTING", "DATA_GAP"]
    ] = None


class CoreMatchInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    match_id: Optional[str] = None
    home_team: Optional[str] = None
    away_team: Optional[str] = None
    competition: Optional[str] = None
    kickoff_utc: Optional[datetime] = None
    model: Optional[CoreModelInput] = None
    market: Optional[CoreMarketInput] = None
    signals: Optional[CoreSignalsInput] = None
    freshness: Optional[CoreFreshnessInput] = None
    source_status: Optional[CoreSourceStatusInput] = None
    # Provider ceiling enforcement (directive §9, C-07/08/09/10).
    # None = caller omitted provenance → treated as 0 → PARTIAL.
    # [] = explicitly 0 verified providers → PARTIAL.
    verified_evidence_providers: Optional[List[str]] = None


class CoreEngineAnalyzeRequest(BaseModel):
    matches: List[CoreMatchInput] = Field(default_factory=list)


class CoreProbabilitiesOutput(BaseModel):
    home: Optional[float]
    draw: Optional[float]
    away: Optional[float]


class CoreDataFreshnessOutput(BaseModel):
    status: Literal["FRESH", "RECENT", "STALE", "DATA_GAP", "CONFLICTING"]
    market_captured_at: Optional[datetime]
    oldest_critical_input_seconds: Optional[int]
    lineup_status: Optional[Literal["CONFIRMED", "PROVISIONAL", "UNKNOWN"]]


class CoreCalculationAuditOutput(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    bookmaker: Optional[str]
    market_overround: Optional[float]
    calibration_method: Optional[str]
    model_version: Optional[str]
    kelly_fraction: float = 0.25   # quarter-Kelly
    kelly_cap: float = 0.05        # 5% hard cap


class CoreMatchOutput(BaseModel):
    match_identifier: Optional[str]
    match_id: Optional[str]
    competition: Optional[str]
    kickoff_utc: Optional[datetime]
    verdict: Verdict
    watchlist: bool = False
    probabilities: CoreProbabilitiesOutput
    best_market: Optional[Literal["HOME_ML", "DRAW_ML", "AWAY_ML"]]
    market_odds: Optional[float]
    raw_market_implied_probability: Optional[float]
    fair_market_probability: Optional[float]
    edge: Optional[float]
    edge_percentage_points: Optional[float]
    expected_value: Optional[float]
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    confidence_adjusted_value: float
    stake: Literal["1u", "2.5u", "pass"]
    stake_fraction: float
    minimum_acceptable_odds: Optional[float]
    drivers: List[str]
    risks: List[str]
    invalidation_conditions: List[str]
    data_freshness: CoreDataFreshnessOutput
    data_gaps: List[str]
    calculation_audit: CoreCalculationAuditOutput
    explanation: str


class CoreEngineResponse(BaseModel):
    engine_version: Literal["2.1.0-prod"] = "2.1.0-prod"
    generated_at: datetime
    top_opportunities: List[str]
    batch_watchlist: List[str] = Field(default_factory=list)
    matches: List[CoreMatchOutput]


__all__ = [
    "CoreEngineAnalyzeRequest",
    "CoreEngineResponse",
    "CoreMatchInput",
]
