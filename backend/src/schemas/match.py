# backend/src/schemas/match.py

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .league import LeagueResponse
from .team import TeamResponse


class MatchBase(BaseModel):
    """Shared match attributes."""

    home_team_id: str
    away_team_id: str
    league_id: str
    match_date: datetime
    status: str = Field(default="scheduled", description="scheduled, live, finished")
    venue: Optional[str] = None
    season: Optional[str] = None


class MatchCreate(MatchBase):
    """Schema used when persisting a new match record."""

    pass


class MatchUpdate(BaseModel):
    """Patch-style match update payload."""

    home_team_id: Optional[str] = None
    away_team_id: Optional[str] = None
    league_id: Optional[str] = None
    match_date: Optional[datetime] = None
    status: Optional[str] = None
    venue: Optional[str] = None
    season: Optional[str] = None
    home_goals: Optional[int] = None
    away_goals: Optional[int] = None


class MatchInDBBase(MatchBase):
    """Fields stored in the database for a match."""

    id: str
    created_at: datetime
    updated_at: datetime
    home_goals: Optional[int] = None
    away_goals: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class Match(MatchInDBBase):
    """ORM-backed match representation."""

    pass


class MatchSummary(BaseModel):
    """Lean response tailored for listings and search results."""

    id: str
    home_team: str
    away_team: str
    league: str
    match_date: datetime
    venue: Optional[str] = None
    status: str = Field(default="scheduled")
    has_odds: bool = Field(default=False)


class MatchResponse(MatchInDBBase):
    """Full match payload containing nested resources."""

    home_team: TeamResponse
    away_team: TeamResponse
    league: LeagueResponse
    odds: List[Dict[str, Any]] = Field(default_factory=list)
    predictions: List[Dict[str, Any]] = Field(default_factory=list)


class MatchDetail(MatchResponse):
    """Extended response with officiating and round metadata."""

    referee: Optional[str] = None
    round_number: Optional[int] = None


MatchInDB = MatchInDBBase

# Lightweight API response models used by list/detail endpoints


class MatchListResponse(BaseModel):
    """Container for a list of matches with simple summary items."""

    matches: List[MatchSummary]
    total: int
    league_filter: Optional[str] = None
    date_range_days: Optional[int] = None
    source: Optional[str] = None


class MatchDetailResponse(BaseModel):
    """Lightweight match detail payload used by public endpoints."""

    id: str
    home_team: str
    away_team: str
    league: str
    match_date: datetime
    venue: Optional[str] = None
    status: str = Field(default="scheduled")
    odds: Optional[Dict[str, Optional[float]]] = None
    referee: Optional[str] = None
    season: Optional[str] = None
    round_number: Optional[int] = None
