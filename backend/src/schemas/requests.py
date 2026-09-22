from pydantic import BaseModel, Field, field_validator
from typing import Optional


class InsightsRequest(BaseModel):
    matchup: str = Field(
        ...,
        json_schema_extra={"example": "Manchester United vs Liverpool"},
        description="Match matchup in format 'Home Team vs Away Team'",
    )
    league: Optional[str] = Field(
        None,
        json_schema_extra={"example": "EPL"},
        description="League identifier (EPL, La Liga, etc.)",
    )

    @field_validator("matchup")
    @classmethod
    def validate_matchup_format(cls, value: str) -> str:
        if " vs " not in value:
            raise ValueError("Matchup must be in format 'Home Team vs Away Team'")
        return value


class MatchSearchRequest(BaseModel):
    query: str = Field(..., description="Search query for teams or matches")
    league: Optional[str] = Field(None, description="Filter by league")


class ModelStatusRequest(BaseModel):
    league: Optional[str] = Field(None, description="Specific league to check")
