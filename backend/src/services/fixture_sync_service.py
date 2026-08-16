"""Seed the matches table with upcoming fixtures from football-data.org.

Called once at startup as a non-blocking background task. Only runs when
FOOTBALL_DATA_API_KEY is configured. Failures are logged and silently
swallowed so they never prevent the API from serving requests.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ..utils.season import canonical_season
from ..monitoring.metrics import metrics_collector
from .team_identity import resolve_team_id

logger = logging.getLogger(__name__)

_LEAGUE_META: dict[str, tuple[str, str]] = {
    "EPL":        ("EPL",        "England"),
    "La Liga":    ("LA_LIGA",    "Spain"),
    "Bundesliga": ("BUNDESLIGA", "Germany"),
    "Serie A":    ("SERIE_A",    "Italy"),
    "Ligue 1":    ("LIGUE_1",    "France"),
    "Eredivisie": ("EREDIVISIE", "Netherlands"),
    "UCL":        ("UCL",        "Europe"),
}

SYNC_HORIZON_DAYS = 14
_FOOTBALL_DATA_SYNC_LIMITER = asyncio.Lock()


def _team_id(team_name: str, league_id: str) -> str:
    """Deterministic stable team ID so re-syncs are idempotent."""
    slug = f"{league_id}:{team_name}".lower().replace(" ", "_")
    return f"fd-team-{slug}"


async def sync_upcoming_fixtures(session: AsyncSession) -> int:
    """Fetch upcoming fixtures and upsert League/Team/Match/canonical rows.

    Existing *unsettled* provider fixtures are refreshed in place so verified
    kickoff reschedules propagate to both the legacy Match row and its stable
    canonical fixture. Settled rows are never rewritten by an upcoming feed.

    Returns the number of new Match rows inserted.
    """
    from ..data.loaders.football_data_api import FootballDataAPIClient, FootballDataAPIError
    from ..core.database import League, Team, Match
    from ..repositories.fixtures import SETTLED_MATCH_STATUSES

    started_at = time.perf_counter()
    client = FootballDataAPIClient()
    try:
        async with _FOOTBALL_DATA_SYNC_LIMITER:
            matches_raw = await client.get_upcoming_matches(days_ahead=SYNC_HORIZON_DAYS, limit=50)
    except FootballDataAPIError as exc:
        logger.warning("fixture_sync: football-data.org unavailable: %s", exc)
        metrics_collector.record_provider_outcome(
            provider="football_data_org",
            outcome="fixture_sync_failed",
            duration_ms=(time.perf_counter() - started_at) * 1000,
        )
        return 0

    inserted = 0
    for raw in matches_raw:
        league_name: str = raw.get("league", "")
        meta = _LEAGUE_META.get(league_name)
        if not meta:
            continue

        league_id, country = meta

        if not await session.get(League, league_id):
            session.add(League(id=league_id, name=league_name, country=country))
            await session.flush()

        home_name: str = raw.get("home_team", "")
        away_name: str = raw.get("away_team", "")
        home_id = (await resolve_team_id(home_name, session) if home_name else None) or _team_id(
            home_name, league_id
        )
        away_id = (await resolve_team_id(away_name, session) if away_name else None) or _team_id(
            away_name, league_id
        )
        for tid, tname in [(home_id, home_name), (away_id, away_name)]:
            if tname and not await session.get(Team, tid):
                session.add(Team(id=tid, name=tname, league_id=league_id))
        await session.flush()

        match_id: str = raw.get("id", "")
        if not match_id:
            continue

        raw_date = raw.get("match_date", "")
        try:
            match_date = datetime.fromisoformat(raw_date.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            logger.debug("fixture_sync: unparseable date %r — skipping %s", raw_date, match_id)
            continue

        season = canonical_season(match_date)
        match = await session.get(Match, match_id)
        if match is None:
            session.add(
                Match(
                    id=match_id,
                    league_id=league_id,
                    home_team_id=home_id,
                    away_team_id=away_id,
                    match_date=match_date,
                    season=season,
                    status="scheduled",
                )
            )
            inserted += 1
        elif (match.status or "").lower() not in SETTLED_MATCH_STATUSES:
            previous_kickoff = match.match_date
            match.league_id = league_id
            match.home_team_id = home_id
            match.away_team_id = away_id
            match.match_date = match_date
            match.season = season
            match.status = "scheduled"
            if previous_kickoff != match_date:
                metrics_collector.increment("fixture_sync.reschedules")
                logger.info(
                    "fixture_sync: provider reschedule applied for match_id=%s (%s -> %s)",
                    match_id,
                    previous_kickoff,
                    match_date,
                )

        from .canonical_identity_service import ensure_canonical_fixture

        try:
            await ensure_canonical_fixture(
                session,
                provider="football-data.org",
                provider_event_id=match_id,
                competition_id=league_id,
                competition_name=league_name,
                home_provider_id=home_id,
                home_name=home_name,
                away_provider_id=away_id,
                away_name=away_name,
                kickoff_utc=match_date,
                season=season,
                status="scheduled",
                evidence={
                    "source": raw.get("source") or "football-data.org",
                    "provider_event_id": match_id,
                    "provider_timestamp": raw_date,
                    "reconciled_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        except ValueError as exc:
            # A same-event kickoff reschedule is reconciled in place by
            # ensure_canonical_fixture. Reaching this branch now means the
            # provider event conflicts on stable identity attributes (team,
            # competition, or a missing mapped fixture), so keep it isolated
            # from the rest of the batch and fail closed for canonical mapping.
            logger.warning(
                "fixture_sync: canonical identity conflict for match_id=%s (%s vs %s): %s",
                match_id,
                home_name,
                away_name,
                exc,
            )
            metrics_collector.increment("fixture_sync.identity_conflicts")

    await session.commit()
    duration_ms = (time.perf_counter() - started_at) * 1000
    metrics_collector.increment("fixture_sync.successes")
    metrics_collector.increment("fixture_sync.inserted", inserted)
    metrics_collector.record_timer("fixture_sync.latency", duration_ms)
    metrics_collector.record_provider_outcome(
        provider="football_data_org",
        outcome="fixture_sync_success",
        duration_ms=duration_ms,
    )
    return inserted


async def sync_settled_results(session: AsyncSession, *, days_back: int = 3) -> dict[str, int]:
    """Fetch recently finished fixtures and settle matching Match rows.

    Never creates a Match row and never rewrites a row already settled.
    """
    from ..data.loaders.football_data_api import FootballDataAPIClient, FootballDataAPIError
    from ..core.database import Match
    from ..repositories.fixtures import SETTLED_MATCH_STATUSES

    client = FootballDataAPIClient()
    try:
        async with _FOOTBALL_DATA_SYNC_LIMITER:
            results_raw = await client.get_recent_results(days_back=days_back, limit=100)
    except FootballDataAPIError as exc:
        logger.warning("settlement_sync: football-data.org unavailable: %s", exc)
        return {"updated": 0, "unmatched": 0, "already_settled": 0}

    updated = unmatched = already_settled = 0
    for raw in results_raw:
        match_id = raw.get("id")
        home_score = raw.get("home_score")
        away_score = raw.get("away_score")
        if not match_id or home_score is None or away_score is None:
            continue

        match = await session.get(Match, match_id)
        if match is None:
            unmatched += 1
            continue
        if (match.status or "").lower() in SETTLED_MATCH_STATUSES:
            already_settled += 1
            continue

        match.status = "finished"
        match.home_score = home_score
        match.away_score = away_score
        updated += 1

    await session.commit()
    return {"updated": updated, "unmatched": unmatched, "already_settled": already_settled}


async def run_fixture_sync() -> None:
    """Entry point for the background sync loop — swallows all errors."""
    from ..db.session import AsyncSessionLocal
    from ..monitoring.metrics import metrics_collector

    if AsyncSessionLocal is None:
        logger.warning("fixture_sync: DB not ready, skipping")
        return

    try:
        async with AsyncSessionLocal() as session:
            count = await sync_upcoming_fixtures(session)
            logger.info("fixture_sync: %d new upcoming fixtures seeded", count)
    except Exception as exc:
        logger.exception("fixture_sync: unhandled error — continuing without fixture data")
        metrics_collector.increment("fixture_sync.failures")
        metrics_collector.record_error(
            error_type=type(exc).__name__,
            message=str(exc),
            context={"task": "fixture_sync"},
        )
