"""Team-related Pydantic schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class TeamBase(BaseModel):
    """Common fields shared between team representations."""

    id: str = Field(..., description="Team identifier")
    name: str = Field(..., max_length=200)
    league_id: Optional[str] = Field(
        default=None, description="Associated league identifier"
    )


class TeamResponse(TeamBase):
    """Public team representation returned by APIs."""

    country: Optional[str] = Field(default=None, description="Country of the team")
    founded_year: Optional[int] = Field(
        default=None, description="Year the club was founded", ge=1850
    )
    stadium: Optional[str] = Field(default=None, description="Home stadium")
    manager: Optional[str] = Field(default=None, description="Current manager")
    active: bool = Field(
        default=True, description="Whether the team is active in the league"
    )
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


__all__ = ["TeamResponse"]
