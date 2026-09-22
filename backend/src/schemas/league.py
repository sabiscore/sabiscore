"""League response schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class LeagueResponse(BaseModel):
    """Lightweight league representation for embedding in match payloads."""

    id: str = Field(..., description="League identifier, e.g. EPL")
    name: str = Field(..., description="Friendly league name")
    country: Optional[str] = Field(
        default=None, description="Country where the league is played"
    )
    tier: Optional[int] = Field(
        default=None, ge=1, description="Tier level within the national league system"
    )
    active: bool = Field(default=True)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


__all__ = ["LeagueResponse"]
