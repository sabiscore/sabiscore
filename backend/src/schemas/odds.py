"""Odds schemas for market data exposure."""

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class OddsBase(BaseModel):
	"""Common attributes tracked for bookmaker odds."""

	match_id: str = Field(..., description="Associated match identifier")
	bookmaker: str = Field(..., description="Bookmaker name")
	home_win: Optional[float] = Field(default=None, ge=1.01)
	draw: Optional[float] = Field(default=None, ge=1.01)
	away_win: Optional[float] = Field(default=None, ge=1.01)
	over_under: Optional[float] = Field(default=None, ge=1.01)


class OddsCreate(OddsBase):
	"""Payload used when ingesting odds snapshots."""

	timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class OddsResponse(OddsBase):
	"""Legacy odds reference that cannot establish executable evidence."""

	model_config = ConfigDict(from_attributes=True)

	id: Optional[int] = None
	created_at: Optional[datetime] = None
	updated_at: Optional[datetime] = None
	evidence_state: Literal["RESEARCH_ONLY"] = "RESEARCH_ONLY"
	executable: Literal[False] = False


__all__ = ["Odds", "OddsCreate", "OddsResponse"]


# Backwards compatibility alias
class Odds(OddsResponse):
	"""Alias maintained for legacy imports expecting `Odds`."""

	pass
