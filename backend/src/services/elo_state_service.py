"""Durable Elo state backed by PostgreSQL/SQLAlchemy.

The historical :mod:`src.data.elo_engine` Parquet implementation remains useful
for offline research and compatibility. Production feature projection uses this
service so Render process replacement cannot erase rating state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Iterable, Union, cast

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.database import Match
from ..core.league_policy import canonical_league_id
from ..db.models import EloRatingSnapshot
from ..monitoring.metrics import metrics_collector

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..data.elo_engine import EloContext
from ..utils.season import canonical_season

logger = logging.getLogger(__name__)

_BASE_ELO = 1500.0


@dataclass(frozen=True)
class DurableEloContext:
    home_elo: float
    away_elo: float
    elo_difference: float
    home_elo_trend_5: float
    away_elo_trend_5: float
    elo_momentum_cross: float
    home_resolved: bool
    away_resolved: bool

    @property
    def resolved(self) -> bool:
        return self.home_resolved and self.away_resolved


# The offline Parquet research engine defines a field-identical context type.
# Consumers read only the shared float fields, so both flow through the same
# call sites; this alias states that instead of leaving one of them unannotated.
AnyEloContext = Union["EloContext", DurableEloContext]


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _league_key(league: str) -> str:
    return canonical_league_id(league)


def _league_importance(league: str) -> float:
    return {
        "EPL": 1.2,
        "LA_LIGA": 1.2,
        "SERIE_A": 1.2,
        "BUNDESLIGA": 1.0,
        "LIGUE_1": 1.0,
        "EREDIVISIE": 0.9,
        "UCL": 1.2,
    }.get(_league_key(league), 1.0)


async def _team_state(
    session: AsyncSession,
    *,
    team_id: str,
    league: str,
    season: str,
    match_date: datetime,
) -> tuple[float, float, bool]:
    league_id = _league_key(league)
    cutoff = _naive_utc(match_date)
    rows = (
        await session.execute(
            select(EloRatingSnapshot)
            .where(
                EloRatingSnapshot.team_id == str(team_id),
                EloRatingSnapshot.league == league_id,
                EloRatingSnapshot.match_date < cutoff,
            )
            .order_by(EloRatingSnapshot.match_date.desc(), EloRatingSnapshot.id.desc())
            .limit(5)
        )
    ).scalars().all()
    if not rows:
        return _BASE_ELO, 0.0, False

    latest = rows[0]
    last_post = float(latest.post_match_elo)
    trend = sum(float(row.post_match_elo - row.pre_match_elo) for row in rows) / len(rows)

    has_current_season = any(str(row.season) == str(season) for row in rows)
    if not has_current_season:
        league_mean = (
            await session.execute(
                select(func.avg(EloRatingSnapshot.post_match_elo)).where(
                    EloRatingSnapshot.league == league_id,
                    EloRatingSnapshot.season == str(season),
                    EloRatingSnapshot.match_date < cutoff,
                )
            )
        ).scalar_one_or_none()
        mean = float(league_mean) if league_mean is not None else _BASE_ELO
        last_post = mean + 0.5 * (last_post - mean)

    return last_post, trend, True


async def get_elo_context(
    session: AsyncSession,
    *,
    home_team_id: str,
    away_team_id: str,
    league: str,
    season: str,
    match_date: datetime,
) -> DurableEloContext:
    home_pre, home_trend, home_found = await _team_state(
        session,
        team_id=home_team_id,
        league=league,
        season=season,
        match_date=match_date,
    )
    away_pre, away_trend, away_found = await _team_state(
        session,
        team_id=away_team_id,
        league=league,
        season=season,
        match_date=match_date,
    )
    metrics_collector.increment("elo.lookup.total")
    if home_found and away_found:
        metrics_collector.increment("elo.lookup.resolved")
    else:
        metrics_collector.increment("elo.lookup.unresolved")
    return DurableEloContext(
        home_elo=home_pre,
        away_elo=away_pre,
        elo_difference=home_pre - away_pre,
        home_elo_trend_5=home_trend,
        away_elo_trend_5=away_trend,
        elo_momentum_cross=home_trend - away_trend,
        home_resolved=home_found,
        away_resolved=away_found,
    )


async def apply_finished_match_to_elo(session: AsyncSession, match: Match) -> bool:
    """Persist two pre/post snapshots for one finished match.

    Returns ``True`` when rows were created and ``False`` when the match was
    already represented. A partial one-team state is treated as corruption and
    fails closed rather than silently repairing from a potentially changed base.
    """

    existing = (
        await session.execute(
            select(EloRatingSnapshot).where(EloRatingSnapshot.match_id == str(match.id))
        )
    ).scalars().all()
    if len(existing) == 2:
        return False
    if existing:
        raise RuntimeError(f"Partial Elo state for match_id={match.id}")
    if match.home_score is None or match.away_score is None:
        return False
    if str(match.home_team_id) == str(match.away_team_id):
        # Corrupt fixture data (a team recorded as playing itself), not a real
        # result — inserting both sides would collide on the (match_id, team_id)
        # unique constraint and, left uncaught, aborts the whole batch's flush,
        # permanently wedging sync_elo_from_finished_matches on the first such
        # row it ever encounters (observed in production 2026-08-16: 0 rows
        # ever committed). Skip and keep going; the real-data fix is separate.
        logger.warning(
            "Elo skip: match_id=%s has identical home/away team_id=%s — "
            "corrupt fixture data (self-play), not a real result",
            match.id,
            match.home_team_id,
        )
        metrics_collector.increment("elo.update.skipped_self_play")
        return False

    league = _league_key(str(match.league_id or ""))
    raw_match_date = match.match_date
    if not isinstance(raw_match_date, datetime):
        raise TypeError(f"Match {match.id} has a non-datetime match_date")
    match_date = _naive_utc(cast(datetime, raw_match_date))
    season = canonical_season(match_date)
    context = await get_elo_context(
        session,
        home_team_id=str(match.home_team_id),
        away_team_id=str(match.away_team_id),
        league=league,
        season=season,
        match_date=match_date,
    )

    adjusted_home = context.home_elo + float(settings.elo_home_advantage)
    home_expected = 1.0 / (1.0 + 10 ** ((context.away_elo - adjusted_home) / 400.0))
    away_expected = 1.0 - home_expected
    if match.home_score > match.away_score:
        home_actual, away_actual = 1.0, 0.0
    elif match.home_score < match.away_score:
        home_actual, away_actual = 0.0, 1.0
    else:
        home_actual = away_actual = 0.5

    k_factor = float(settings.elo_k_base) * _league_importance(league)
    home_post = context.home_elo + k_factor * (home_actual - home_expected)
    away_post = context.away_elo + k_factor * (away_actual - away_expected)
    created_at = _naive_utc(datetime.now(timezone.utc))

    session.add_all(
        [
            EloRatingSnapshot(
                match_id=str(match.id),
                team_id=str(match.home_team_id),
                pre_match_elo=context.home_elo,
                post_match_elo=home_post,
                league=league,
                season=season,
                match_date=match_date,
                created_at=created_at,
            ),
            EloRatingSnapshot(
                match_id=str(match.id),
                team_id=str(match.away_team_id),
                pre_match_elo=context.away_elo,
                post_match_elo=away_post,
                league=league,
                season=season,
                match_date=match_date,
                created_at=created_at,
            ),
        ]
    )
    await session.flush()
    metrics_collector.increment("elo.update.matches")
    return True


async def sync_elo_from_finished_matches(
    session: AsyncSession,
    *,
    limit: int = 500,
) -> dict[str, int]:
    """Apply newly-finished real-identity matches in chronological order."""

    already_has_elo = exists(
        select(EloRatingSnapshot.id).where(EloRatingSnapshot.match_id == Match.id)
    )
    matches: Iterable[Match] = (
        await session.execute(
            select(Match)
            .where(
                func.lower(Match.status) == "finished",
                Match.home_score.is_not(None),
                Match.away_score.is_not(None),
                Match.league_id.is_not(None),
                ~already_has_elo,
            )
            .order_by(Match.match_date.asc(), Match.id.asc())
            .limit(limit)
        )
    ).scalars().all()

    processed = 0
    skipped = 0
    for match in matches:
        if await apply_finished_match_to_elo(session, match):
            processed += 1
        else:
            skipped += 1
    await session.commit()
    metrics_collector.increment("elo.sync.runs")
    metrics_collector.increment("elo.sync.processed", processed)
    if skipped:
        metrics_collector.increment("elo.sync.skipped", skipped)
    return {"processed": processed, "skipped": skipped, "limit": limit}


async def elo_state_health(session: AsyncSession) -> dict[str, object]:
    row_count = int(
        (await session.execute(select(func.count(EloRatingSnapshot.id)))).scalar_one()
    )
    team_count = int(
        (await session.execute(select(func.count(func.distinct(EloRatingSnapshot.team_id))))).scalar_one()
    )
    latest = (
        await session.execute(select(func.max(EloRatingSnapshot.match_date)))
    ).scalar_one_or_none()
    return {
        "authority": "postgres",
        "rows": row_count,
        "unique_teams": team_count,
        "last_match_date": latest.isoformat() if latest else None,
    }


__all__ = [
    "DurableEloContext",
    "apply_finished_match_to_elo",
    "elo_state_health",
    "get_elo_context",
    "sync_elo_from_finished_matches",
]
