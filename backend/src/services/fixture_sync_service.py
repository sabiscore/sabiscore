"""Seed the matches table with upcoming fixtures from football-data.org.

Called once at startup as a non-blocking background task. Only runs when
FOOTBALL_DATA_API_KEY is configured. Failures are logged and silently
swallowed so they never prevent the API from serving requests.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from ..utils.season import canonical_season
from ..monitoring.metrics import metrics_collector
from .team_identity import resolve_team_id

logger = logging.getLogger(__name__)

# Human-readable league name (as returned by FootballDataAPIClient.TOP_COMPETITIONS)
# mapped to (canonical_league_id, country). Closed set — only supported competitions.
# IMPORTANT: the second tuple element is the canonical SabiScore league_id (as used
# by league_policy, model_fetcher, full_analysis, etc.) — NOT the fd.org competition
# code. Migration 0006_canonical_league_ids renamed any existing fd.org code rows.
_LEAGUE_META: dict[str, tuple[str, str]] = {
    "EPL":        ("EPL",        "England"),
    "La Liga":    ("LA_LIGA",    "Spain"),
    "Bundesliga": ("BUNDESLIGA", "Germany"),
    "Serie A":    ("SERIE_A",    "Italy"),
    "Ligue 1":    ("LIGUE_1",    "France"),
    "Eredivisie": ("EREDIVISIE", "Netherlands"),
    "UCL":        ("UCL",        "Europe"),
}


# How far ahead fixtures are seeded. The readiness capability probe imports this
# so the two horizons can never drift apart: a probe window narrower than the sync
# window leaves the probe with nothing to test even when fixtures exist (observed
# 2026-08-08 — 28 required-league fixtures seeded, probe still reporting
# "unverified_no_fixtures" against its own hardcoded 7 days).
SYNC_HORIZON_DAYS = 14


def _team_id(team_name: str, league_id: str) -> str:
    """Deterministic stable team ID so re-syncs are idempotent."""
    slug = f"{league_id}:{team_name}".lower().replace(" ", "_")
    return f"fd-team-{slug}"


async def sync_upcoming_fixtures(session: AsyncSession) -> int:
    """Fetch upcoming fixtures and upsert League/Team/Match rows.

    Returns the number of new Match rows inserted.
    """
    from ..data.loaders.football_data_api import FootballDataAPIClient, FootballDataAPIError
    from ..core.database import League, Team, Match

    started_at = time.perf_counter()
    client = FootballDataAPIClient()
    try:
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
            continue  # unsupported competition — fail closed

        league_id, country = meta

        # League upsert
        if not await session.get(League, league_id):
            session.add(League(id=league_id, name=league_name, country=country))
            await session.flush()

        # Team upserts — resolve against existing rows first (exact / affix-stripped /
        # fuzzy match) so a re-sync doesn't mint a second ID for a team already known
        # under a slightly different name; only mint fd-team-* on a genuine miss.
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

        # Match upsert
        match_id: str = raw.get("id", "")
        if not match_id or await session.get(Match, match_id):
            continue

        raw_date = raw.get("match_date", "")
        try:
            match_date = datetime.fromisoformat(raw_date.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            logger.debug("fixture_sync: unparseable date %r — skipping %s", raw_date, match_id)
            continue

        session.add(Match(
            id=match_id,
            league_id=league_id,
            home_team_id=home_id,
            away_team_id=away_id,
            match_date=match_date,
            season=canonical_season(match_date),
            status="scheduled",
        ))
        inserted += 1

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

    Looks up each result by the same deterministic fd-{id} scheme
    sync_upcoming_fixtures already wrote — no team/fixture identity
    re-resolution needed, only a keyed lookup. Never creates a Match row (a
    fixture never synced as upcoming is a fixture-sync coverage gap, not this
    function's job) and never re-writes a row already settled (idempotent).
    """
    from ..data.loaders.football_data_api import FootballDataAPIClient, FootballDataAPIError
    from ..core.database import Match
    from ..repositories.fixtures import SETTLED_MATCH_STATUSES

    client = FootballDataAPIClient()
    try:
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
            continue  # belt-and-suspenders — _normalize_result already filters these

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
    """Entry point for the background sync loop — swallows all errors.

    Called immediately at boot and then every _FIXTURE_SYNC_INTERVAL_SECONDS
    (api/main.py), so a failed tick self-corrects on the next one rather than
    leaving the platform with zero fixtures until the next deploy. Failures are
    recorded via the same metrics_collector GET /metrics already surfaces
    (docs/DEBT.md item 3), rather than a bespoke tracking dict.
    """
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
