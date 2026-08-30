"""Pydantic v2 schemas for the Advanced Insights endpoint (R4 of v5 directive)."""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

from ..services.advanced_metrics import MetricStatus
from ..services.market_intel import MarketIntelligenceSummary


class AdvancedMetricsPayload(BaseModel):
    """Calculated tactical and advanced metrics."""
    ppda_home: Optional[float] = Field(None, description="Home team PPDA (opponent passes / defensive actions)")
    ppda_away: Optional[float] = Field(None, description="Away team PPDA")
    ppda_status: str = Field(MetricStatus.UNAVAILABLE.value, description="Status of PPDA metric")

    psxg_home_delta: Optional[float] = Field(None, description="Home keeper PSxG - goals conceded (positive = saved > expected)")
    psxg_away_delta: Optional[float] = Field(None, description="Away keeper PSxG - goals conceded")
    psxg_status: str = Field(MetricStatus.UNAVAILABLE.value, description="Status of PSxG metric")

    xt_status: str = Field(MetricStatus.ADVISORY_REQUIRES_CORPUS.value, description="Expected Threat status")
    xt_home: Optional[float] = Field(None, description="Home xT generation")
    xt_away: Optional[float] = Field(None, description="Away xT generation")
    xt_reason: Optional[str] = Field("Requires certified event-corpus pipeline", description="xT diagnostic note")


class RefereeInsightPayload(BaseModel):
    """Referee profile context."""
    name: str
    avg_yellow_cards: Optional[float] = None
    avg_red_cards: Optional[float] = None
    penalties_awarded: Optional[int] = None
    strictness_index: Optional[float] = None
    sample_size: Optional[int] = None
    source: Optional[str] = None


class MatchContextPayload(BaseModel):
    """Match environmental, tactical, and fatigue context."""
    weather_condition: Optional[str] = None
    weather_source: Optional[str] = None
    weather_observed_at: Optional[str] = None
    fatigue_index_home: Optional[float] = None
    fatigue_index_away: Optional[float] = None
    referee: Optional[RefereeInsightPayload] = None


class ModelIdentityPayload(BaseModel):
    """Model versioning and certification provenance."""
    version: str = Field("v5_phase7", description="Active model generation")
    feature_schema_version: str = Field("phase7_68", description="Feature schema version")
    certification_state: str = Field("UNVERIFIED", description="Certification verdict")


class DecisionStatePayload(BaseModel):
    """Risk and staking gate decision."""
    research_only: bool = Field(True, description="Whether staking is prohibited due to uncertified state")
    stake_permitted: bool = Field(False, description="Public staking permission flag")
    verdict: str = Field("RESEARCH_ONLY", description="High-level analytical decision")


class AdvancedInsightsResponse(BaseModel):
    """Unified Advanced Insights response payload."""
    model_config = ConfigDict(protected_namespaces=())

    match_id: str
    home_team: str
    away_team: str
    league: str
    kickoff_utc: Optional[str] = None
    advanced_metrics: AdvancedMetricsPayload
    match_context: MatchContextPayload
    market_intelligence: Optional[MarketIntelligenceSummary] = None
    decision_state: DecisionStatePayload
    model_identity: ModelIdentityPayload
    generated_at: str
    staleness_seconds: Optional[float] = None
