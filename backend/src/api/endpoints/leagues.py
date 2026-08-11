"""GET /api/v1/leagues — return ACTIVE_LEAGUES inventory with coverage metadata."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from ...core.league_config import ACTIVE_LEAGUES, LeagueProfile
from ...core.season_calendar import next_season_start

router = APIRouter(prefix="/leagues", tags=["leagues"])

# UCL uses the generic production model, not a league-specific artifact.
_MODEL_ARTIFACT: dict[str, str] = {
    "EPL": "epl_ensemble.pkl",
    "La Liga": "la_liga_ensemble.pkl",
    "Bundesliga": "bundesliga_ensemble.pkl",
    "Serie A": "serie_a_ensemble.pkl",
    "Ligue 1": "ligue_1_ensemble.pkl",
    "Eredivisie": "eredivisie_ensemble.pkl",
    "UCL": "sabiscore_production_v2.joblib",
}


class LeagueListItem(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    id: str
    name: str
    coverage: str
    low_evidence_allowed: bool
    caveat_text: Optional[str]
    model_artifact: str
    next_season_start: Optional[str]
    generated_at: str


def _to_item(profile: LeagueProfile) -> LeagueListItem:
    return LeagueListItem(
        id=profile.id,
        name=profile.name,
        coverage=profile.coverage,
        low_evidence_allowed=profile.low_evidence_allowed,
        caveat_text=profile.caveat_text,
        model_artifact=_MODEL_ARTIFACT.get(profile.id, f"{profile.id.lower()}_ensemble.pkl"),
        next_season_start=next_season_start(profile.id, default=None),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/", response_model=List[LeagueListItem])
async def list_leagues() -> List[LeagueListItem]:
    """Return all active leagues with coverage tier, model artifact, and next-season start date."""
    return sorted(
        [_to_item(p) for p in ACTIVE_LEAGUES],
        key=lambda item: item.id,
    )


__all__ = ["router"]
