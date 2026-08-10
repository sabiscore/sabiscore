"""
GET /teams/{slug}/intelligence

Rolling form analysis, H2H summary, upcoming fixtures with edge_quality_score,
and form-state verdict for a team.

Verdict taxonomy (non-overlapping with match TYPE-F verdicts):
  IMPROVING  — last-5 PPG meaningfully exceeds last-10 PPG
  DECLINING  — last-5 PPG meaningfully below last-10 PPG
  VOLATILE   — high variance across last-10 results
  STABLE     — consistent form; no clear trajectory
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_, select
from ...data.team_database import TEAM_ELO_RATINGS
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...db.models import Match, Team
from ...db.session import get_async_session
from ...services.upcoming_match_service import UpcomingMatchService
from ...services.odds_service import OddsService, get_odds_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/teams", tags=["team-intelligence"])

_VERDICT_EDGE = 0.30          # PPG delta required to call IMPROVING / DECLINING
_VOLATILE_STD = 1.20          # stddev above which form is VOLATILE
_FORM_WINDOW_SHORT = 5
_FORM_WINDOW_LONG = 10
_H2H_LIMIT = 5                # top opponents by encounter count


# ── Response schemas ─────────────────────────────────────────────────────────

class FormResultSchema(BaseModel):
    match_date: str
    opponent: str
    home_or_away: str          # "home" | "away"
    goals_for: Optional[int]
    goals_against: Optional[int]
    result: str                # "W" | "D" | "L"
    points: int


class H2HEntrySchema(BaseModel):
    opponent: str
    played: int
    wins: int
    draws: int
    losses: int
    goals_for: int
    goals_against: int


class UpcomingFixtureSchema(BaseModel):
    match_id: str
    home_team: str
    away_team: str
    match_date: str
    league: str
    edge_quality_score: Optional[float] = None
    has_prediction: bool = False


class TeamIntelligenceResponse(BaseModel):
    team_slug: str
    team_name: str
    league: Optional[str] = None
    form_verdict: str          # IMPROVING | STABLE | DECLINING | VOLATILE
    ppg_last5: Optional[float] = None
    ppg_last10: Optional[float] = None
    recent_form: List[FormResultSchema]
    h2h_summary: List[H2HEntrySchema]
    upcoming_fixtures: List[UpcomingFixtureSchema]
    queried_at: str


# ── Helpers ──────────────────────────────────────────────────────────────────

def _slug_to_search(slug: str) -> str:
    """Convert URL slug to a fuzzy display-name fragment for DB ILIKE search."""
    return slug.strip().lower().replace("-", " ").replace("_", " ")


def _match_result(team_id: str, match: Match) -> tuple[str, int, int, int]:
    """Return (result, goals_for, goals_against, points) from the team's perspective."""
    is_home = match.home_team_id == team_id
    gf = match.home_score if is_home else match.away_score
    ga = match.away_score if is_home else match.home_score
    if gf is None or ga is None:
        return "?", 0, 0, 0
    if gf > ga:
        return "W", gf, ga, 3
    if gf == ga:
        return "D", gf, ga, 1
    return "L", gf, ga, 0


def _compute_std(points: List[int]) -> float:
    if len(points) < 2:
        return 0.0
    n = len(points)
    mean = sum(points) / n
    variance = sum((p - mean) ** 2 for p in points) / n
    return variance ** 0.5


def _form_verdict(ppg5: Optional[float], ppg10: Optional[float], pts_list: List[int]) -> str:
    std = _compute_std(pts_list[-_FORM_WINDOW_LONG:]) if pts_list else 0.0
    if std > _VOLATILE_STD:
        return "VOLATILE"
    if ppg5 is not None and ppg10 is not None:
        delta = ppg5 - ppg10
        if delta >= _VERDICT_EDGE:
            return "IMPROVING"
        if delta <= -_VERDICT_EDGE:
            return "DECLINING"
    return "STABLE"


# ── Endpoint ─────────────────────────────────────────────────────────────────

@router.get("/{slug}/intelligence", response_model=TeamIntelligenceResponse)
async def get_team_intelligence(
    slug: str,
    db: AsyncSession = Depends(get_async_session),
    history_matches: int = Query(
        20, ge=5, le=50, description="Finished matches to include in form analysis"
    ),
    upcoming_days: int = Query(
        14, ge=1, le=30, description="Days ahead for upcoming fixture window"
    ),
    odds_service: OddsService = Depends(get_odds_service),
) -> TeamIntelligenceResponse:
    """Return rolling form, H2H summary, upcoming fixtures, and form-state verdict for a team."""

    search_term = _slug_to_search(slug)

    # ── Resolve team ─────────────────────────────────────────────────────────
    # selectinload avoids the async lazy-load prohibition on team.league
    team_result = await db.execute(
        select(Team)
        .options(selectinload(Team.league))
        .where(
            or_(
                Team.id == slug,
                Team.name.ilike(f"%{search_term}%"),
            )
        )
        .limit(1)
    )
    team = team_result.scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=404, detail=f"Team '{slug}' not found")

    league_name: Optional[str] = None
    try:
        if team.league is not None:
            league_name = getattr(team.league, "name", None)
    except Exception:
        pass  # league relationship unavailable — proceed without league filter

    # ── Fetch recent finished matches ─────────────────────────────────────────
    matches_result = await db.execute(
        select(Match)
        .where(
            or_(
                Match.home_team_id == team.id,
                Match.away_team_id == team.id,
            ),
            Match.status == "finished",
            Match.home_score.isnot(None),
            Match.away_score.isnot(None),
        )
        .order_by(Match.match_date.desc())
        .limit(history_matches)
    )
    recent_matches: List[Match] = list(matches_result.scalars().all())
    recent_matches.sort(key=lambda m: m.match_date)  # oldest first for form list

    # ── Build form list ───────────────────────────────────────────────────────
    form_rows: List[FormResultSchema] = []
    pts_list: List[int] = []
    h2h_map: Dict[str, Dict[str, Any]] = {}

    for m in recent_matches:
        result, gf, ga, pts = _match_result(team.id, m)
        is_home = m.home_team_id == team.id
        opponent_rel = m.home_team if not is_home else m.away_team
        opponent_name = getattr(opponent_rel, "name", "Unknown") if opponent_rel else "Unknown"

        form_rows.append(
            FormResultSchema(
                match_date=m.match_date.isoformat() if isinstance(m.match_date, datetime) else str(m.match_date),
                opponent=opponent_name,
                home_or_away="home" if is_home else "away",
                goals_for=gf,
                goals_against=ga,
                result=result,
                points=pts,
            )
        )
        pts_list.append(pts)

        # H2H accumulation
        opp_key = opponent_name.lower()
        if opp_key not in h2h_map:
            h2h_map[opp_key] = {"name": opponent_name, "played": 0, "W": 0, "D": 0, "L": 0, "gf": 0, "ga": 0}
        h2h_map[opp_key]["played"] += 1
        h2h_map[opp_key][result] = h2h_map[opp_key].get(result, 0) + 1
        h2h_map[opp_key]["gf"] += gf or 0
        h2h_map[opp_key]["ga"] += ga or 0

    # ── PPG windows ───────────────────────────────────────────────────────────
    ppg5: Optional[float] = None
    ppg10: Optional[float] = None
    if len(pts_list) >= _FORM_WINDOW_SHORT:
        ppg5 = round(sum(pts_list[-_FORM_WINDOW_SHORT:]) / _FORM_WINDOW_SHORT, 3)
    if len(pts_list) >= _FORM_WINDOW_LONG:
        ppg10 = round(sum(pts_list[-_FORM_WINDOW_LONG:]) / _FORM_WINDOW_LONG, 3)

    verdict = _form_verdict(ppg5, ppg10, pts_list)

    # ── H2H summary (top opponents by encounter count) ────────────────────────
    h2h_summary = sorted(h2h_map.values(), key=lambda x: x["played"], reverse=True)[:_H2H_LIMIT]
    h2h_out = [
        H2HEntrySchema(
            opponent=h["name"],
            played=h["played"],
            wins=h.get("W", 0),
            draws=h.get("D", 0),
            losses=h.get("L", 0),
            goals_for=h["gf"],
            goals_against=h["ga"],
        )
        for h in h2h_summary
    ]

    # ── Upcoming fixtures ─────────────────────────────────────────────────────
    upcoming_fixtures: List[UpcomingFixtureSchema] = []
    try:
        svc = UpcomingMatchService(
            odds_service=odds_service if isinstance(odds_service, OddsService) else None
        )
        payload = await svc.get_upcoming_matches_with_predictions(
            db, league=league_name, days_ahead=upcoming_days, limit=50, include_value_bets=False
        )
        team_name_lower = team.name.lower()
        for match in payload.get("upcoming_matches", []):
            home = str(match.get("home_team", "")).lower()
            away = str(match.get("away_team", "")).lower()
            if team_name_lower not in home and team_name_lower not in away:
                continue

            value_bets = match.get("value_bets") or []
            best_edge = None
            if value_bets:
                try:
                    best_edge = float(max(v.get("edge_pct", 0.0) for v in value_bets))
                except Exception:
                    pass

            # Simplified edge_quality_score for upcoming fixture context
            preds = match.get("predictions")
            conf = float(preds.get("confidence", 0.0)) if preds else 0.0
            market_edge = min(1.0, (best_edge or 0.0) / 10.0)
            edge_qs = round(0.40 * conf + 0.60 * market_edge, 3) if (preds or best_edge) else None

            upcoming_fixtures.append(
                UpcomingFixtureSchema(
                    match_id=str(match.get("match_id") or ""),
                    home_team=str(match.get("home_team", "")),
                    away_team=str(match.get("away_team", "")),
                    match_date=str(match.get("match_date", "")),
                    league=str(match.get("league", "")),
                    edge_quality_score=edge_qs,
                    has_prediction=preds is not None,
                )
            )
    except Exception as exc:
        logger.warning(f"[team_intelligence] upcoming fixture fetch failed for {slug}: {exc}")

    return TeamIntelligenceResponse(
        team_slug=slug,
        team_name=team.name,
        league=league_name,
        form_verdict=verdict,
        ppg_last5=ppg5,
        ppg_last10=ppg10,
        recent_form=form_rows[-_FORM_WINDOW_LONG:],  # return last 10 for display
        h2h_summary=h2h_out,
        upcoming_fixtures=upcoming_fixtures,
        queried_at=datetime.now(timezone.utc).isoformat(),
    )


# ── Static league→team index (derived from team_database.TEAM_ELO_RATINGS) ──

_LEAGUE_TEAM_INDEX: Dict[str, str] = {
    "Manchester City": "EPL", "Arsenal": "EPL", "Liverpool": "EPL",
    "Chelsea": "EPL", "Manchester United": "EPL", "Newcastle United": "EPL",
    "Tottenham": "EPL", "Tottenham Hotspur": "EPL", "Brighton": "EPL",
    "Brighton & Hove Albion": "EPL", "Aston Villa": "EPL", "West Ham": "EPL",
    "West Ham United": "EPL", "Brentford": "EPL", "Crystal Palace": "EPL",
    "Fulham": "EPL", "Wolverhampton": "EPL", "Wolves": "EPL",
    "Bournemouth": "EPL", "Nottingham Forest": "EPL", "Everton": "EPL",
    "Real Madrid": "La Liga", "Barcelona": "La Liga", "Atletico Madrid": "La Liga",
    "Athletic Bilbao": "La Liga", "Real Sociedad": "La Liga", "Villarreal": "La Liga",
    "Real Betis": "La Liga", "Sevilla": "La Liga", "Girona": "La Liga",
    "Valencia": "La Liga", "Osasuna": "La Liga", "Celta Vigo": "La Liga",
    "Bayern Munich": "Bundesliga", "Bayer Leverkusen": "Bundesliga",
    "Borussia Dortmund": "Bundesliga", "RB Leipzig": "Bundesliga",
    "Union Berlin": "Bundesliga", "SC Freiburg": "Bundesliga",
    "Freiburg": "Bundesliga", "Eintracht Frankfurt": "Bundesliga",
    "VfB Stuttgart": "Bundesliga", "Stuttgart": "Bundesliga",
    "Werder Bremen": "Bundesliga", "Hoffenheim": "Bundesliga",
    "Inter Milan": "Serie A", "Napoli": "Serie A", "AC Milan": "Serie A",
    "Juventus": "Serie A", "Atalanta": "Serie A", "Roma": "Serie A",
    "AS Roma": "Serie A", "Lazio": "Serie A", "Fiorentina": "Serie A",
    "Paris Saint-Germain": "Ligue 1", "PSG": "Ligue 1", "Monaco": "Ligue 1",
    "AS Monaco": "Ligue 1", "Marseille": "Ligue 1", "Olympique Marseille": "Ligue 1",
    "Lyon": "Ligue 1", "Olympique Lyon": "Ligue 1", "Lille": "Ligue 1",
    "LOSC Lille": "Ligue 1", "Nice": "Ligue 1", "Rennes": "Ligue 1",
    "Ajax": "Eredivisie", "PSV Eindhoven": "Eredivisie", "PSV": "Eredivisie",
    "Feyenoord": "Eredivisie", "AZ Alkmaar": "Eredivisie", "AZ": "Eredivisie",
    "Twente": "Eredivisie", "FC Twente": "Eredivisie",
    "Utrecht": "Eredivisie", "Vitesse": "Eredivisie",
}


class TeamSearchResult(BaseModel):
    id: str
    name: str
    league: str


@router.get("/search", response_model=List[TeamSearchResult])
async def search_teams(
    q: str = Query(..., min_length=2, description="Team name fragment to search"),
    league: Optional[str] = Query(None, description="Filter by league identifier (e.g. EPL)"),
) -> List[TeamSearchResult]:
    """
    In-memory team name search. Queries the known team roster from team_database.

    Returns up to 20 matches ordered by relevance (exact prefix first, then contains).
    """
    q_lower = q.strip().lower()
    league_filter = league.strip().upper() if league else None

    results: List[TeamSearchResult] = []
    for name in TEAM_ELO_RATINGS:
        assigned_league = _LEAGUE_TEAM_INDEX.get(name, "unknown")
        if league_filter and assigned_league.upper() != league_filter:
            continue
        if q_lower in name.lower():
            results.append(
                TeamSearchResult(
                    id=name.lower().replace(" ", "_"),
                    name=name,
                    league=assigned_league,
                )
            )

    results.sort(key=lambda r: (not r.name.lower().startswith(q_lower), r.name))
    return results[:20]
