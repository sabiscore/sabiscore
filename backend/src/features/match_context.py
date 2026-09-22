"""Match importance / pressure index.

1 feature: match_importance_score (float, 0.0–1.0)

Captures whether the match is high-stakes: relegation battle, title race,
top-4 run-in, or UCL knockout. High-stakes matches tend to be tighter and
lower-scoring — this feature provides the model a signal that pure form/rating
features cannot capture.

UCL knockout rounds always return 1.0 (maximum stakes).

Phase 8 Sprint 4: extended with async compute_match_context() that reads real
LeagueStanding data from the DB and applies UCL competition_stage multipliers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# UCL competition stage → base importance score.
# Qualifying rounds are meaningful but below group-stage intensity.
# knockout stages scale to 1.0 at the final.
UCL_STAGE_IMPORTANCE: Dict[str, float] = {
    "qualifying": 0.70,
    "group": 0.50,
    "r16": 0.80,
    "qf": 0.90,
    "sf": 0.95,
    "final": 1.00,
}

# League-size lookup — used to compute relegation zone and matches-remaining context.
LEAGUE_SIZE: Dict[str, int] = {
    "epl": 20,
    "premier_league": 20,
    "la_liga": 20,
    "serie_a": 20,
    "ligue_1": 18,
    "bundesliga": 18,
    "eredivisie": 18,
    "ucl": 32,  # group-stage clubs; not used for positional stakes
}

# Total league rounds — used to derive matches_remaining when the DB only stores
# matches_played. Source: standard domestic seasons.
LEAGUE_TOTAL_ROUNDS: Dict[str, int] = {
    "epl": 38,
    "premier_league": 38,
    "la_liga": 38,
    "serie_a": 38,
    "ligue_1": 34,
    "bundesliga": 34,
    "eredivisie": 34,
}

CONTEXT_FEATURE_NAMES: List[str] = ["match_importance_score"]
_DEFAULT_IMPORTANCE = 0.2


@dataclass(frozen=True)
class MatchContextResult:
    """Result from compute_match_context.

    Attributes:
        features: Dict containing "match_importance_score" (0.0–1.0).
        data_gaps: Feature names that could not be computed from live standings.
        per_feature_freshness_seconds: Seconds since league standings were last updated.
            0 when standings are unavailable (DATA_GAP).
    """

    features: Dict[str, float]
    data_gaps: List[str]
    per_feature_freshness_seconds: Dict[str, Optional[int]]


def match_importance_score(
    pos_home: int,
    pos_away: int,
    matches_remaining: int,
    league: str = "epl",
    match_round: str = "group",
    league_size: int = 20,
) -> float:
    """Compute a 0.0–1.0 pressure index for this fixture.

    Args:
        pos_home:          Current league position of the home team (1=top).
        pos_away:          Current league position of the away team.
        matches_remaining: Matches left in the season (including this one).
        league:            League code — "ucl" triggers knockout shortcut.
        match_round:       UCL round string; "group" = no knockout boost.
        league_size:       Number of teams in the league (default 20 for big-5).

    Returns:
        Importance score in [0.0, 1.0].
    """
    if league.lower() == "ucl" and match_round.lower() != "group":
        return UCL_STAGE_IMPORTANCE.get(match_round.lower(), 0.8)

    relegation_zone_top = league_size - 2

    def _stakes(pos: int, mr: int) -> float:
        if pos > relegation_zone_top and mr <= 10:
            return min(1.0, (10 - mr + 1) / 10.0)
        if pos <= 2 and mr <= 8:
            return min(1.0, (8 - mr + 1) / 8.0)
        if pos <= 6 and mr <= 6:
            return min(0.7, (6 - mr + 1) / 8.0)
        return 0.0

    score = max(
        _stakes(pos_home, matches_remaining), _stakes(pos_away, matches_remaining)
    )
    return round(min(1.0, score), 3)


async def compute_match_context(
    home_team_id: str,
    away_team_id: str,
    league: str,
    db: "AsyncSession",
    competition_stage: str = "group",
) -> MatchContextResult:
    """Compute match_importance_score from real competition context.

    For UCL, the competition_stage string directly determines the importance tier
    without a DB standings query. For domestic leagues, queries LeagueStanding to
    derive league position and compute matches_remaining from played + league total.

    B13: falls back to DATA_GAP default when standings are absent — never injects
    a fabricated high-importance score.

    Args:
        home_team_id:      Home team DB ID (string).
        away_team_id:      Away team DB ID (string).
        league:            League slug (e.g., "epl", "ucl", "bundesliga").
        db:                Async SQLAlchemy session.
        competition_stage: UCL stage string from {"qualifying","group","r16","qf","sf","final"}.
                           Ignored for domestic leagues.

    Returns:
        MatchContextResult — data_gaps is empty when live standings are used.
    """
    _gap = MatchContextResult(
        features={"match_importance_score": _DEFAULT_IMPORTANCE},
        data_gaps=list(CONTEXT_FEATURE_NAMES),
        per_feature_freshness_seconds={"match_importance_score": None},
    )

    league_key = league.lower().replace(" ", "_")

    # UCL: stage-based importance without standings query
    if league_key == "ucl":
        stage = competition_stage.lower()
        importance = UCL_STAGE_IMPORTANCE.get(stage, _DEFAULT_IMPORTANCE)
        return MatchContextResult(
            features={"match_importance_score": importance},
            data_gaps=[],
            per_feature_freshness_seconds={"match_importance_score": 0},
        )

    try:
        from sqlalchemy import select

        from ..db.models import LeagueStanding

        query = (
            select(LeagueStanding)
            .where(LeagueStanding.league == league)
            .where(LeagueStanding.team_id.in_([home_team_id, away_team_id]))
        )
        result = await db.execute(query)
        rows = result.scalars().all()
    except Exception as exc:
        logger.debug(
            "compute_match_context: standings query failed for %s: %s", league, exc
        )
        return _gap

    if not rows:
        return _gap

    home_row = next((r for r in rows if str(r.team_id) == str(home_team_id)), None)
    away_row = next((r for r in rows if str(r.team_id) == str(away_team_id)), None)

    if home_row is None or away_row is None:
        return _gap

    pos_home = int(home_row.position or 10)
    pos_away = int(away_row.position or 10)
    played = int(home_row.played or 0)
    total_rounds = LEAGUE_TOTAL_ROUNDS.get(league_key, 38)
    matches_remaining = max(1, total_rounds - played)
    size = LEAGUE_SIZE.get(league_key, 20)

    importance = match_importance_score(
        pos_home=pos_home,
        pos_away=pos_away,
        matches_remaining=matches_remaining,
        league=league_key,
        match_round=competition_stage,
        league_size=size,
    )

    # Freshness: seconds since standings were last written
    freshness_secs = 0
    updated = getattr(home_row, "updated_at", None)
    if updated is not None:
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        freshness_secs = max(
            0, int((datetime.now(timezone.utc) - updated).total_seconds())
        )

    return MatchContextResult(
        features={"match_importance_score": importance},
        data_gaps=[],
        per_feature_freshness_seconds={"match_importance_score": freshness_secs},
    )
