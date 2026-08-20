"""Seed the matches table with upcoming fixtures from football-data.org.

Production acquisition is injected from the application lifespan provider
registry. The compatibility loader owns normalization only; it never opens an
independent HTTP client.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, cast
from uuid import uuid4

from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..monitoring.metrics import metrics_collector
from ..utils.season import canonical_season
from .team_identity import (
    bind_provider_elo_team_id,
    resolve_provider_elo_team_id,
    resolve_team_id,
)

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
_FOOTBALL_DATA_PROVIDER = "football-data.org"

# Render may overlap multiple candidate instances during deploy/retry. The
# in-process lock above cannot arbitrate between those processes, so a single
# deploy can otherwise multiply the seven football-data.org requests and burn
# the shared quota before one candidate is promoted. Tier-1 Redis is already a
# production readiness requirement, making it the narrowest authoritative
# cross-instance coordination boundary available here.
_FIXTURE_SYNC_LEASE_KEY = "sabiscore:job:fixture_sync:lease"
_FIXTURE_SYNC_COMPLETED_KEY = "sabiscore:job:fixture_sync:recently_completed"
_FIXTURE_SYNC_LEASE_TTL_SECONDS = 600
_FIXTURE_SYNC_COMPLETED_TTL_SECONDS = 900
_FIXTURE_SYNC_LEASE_WAIT_SECONDS = 620
_FIXTURE_SYNC_LEASE_POLL_SECONDS = 2.0
_RELEASE_LEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


def _team_id(team_name: str, league_id: str) -> str:
    """Deterministic stable team ID so re-syncs are idempotent."""
    slug = f"{league_id}:{team_name}".lower().replace(" ", "_")
    return f"fd-team-{slug}"


async def _resolve_upcoming_team_id(
    session: AsyncSession,
    *,
    provider_team_id: str | int | None,
    team_name: str,
    league_id: str,
    provider_event_id: str,
) -> tuple[str, bool]:
    """Resolve a live provider team to an Elo-bearing application Team.

    Resolution is deliberately provider-ID first. On a first-seen provider ID,
    name reconciliation is restricted to same-league teams that already have
    real durable Elo snapshots; a verified result is then bound to the provider
    ID for future observations. History-free clubs fall back to a deterministic
    unresolved Team ID and are never promoted merely through a neutral/default
    Elo value.
    """
    normalized_provider_id = str(provider_team_id or "").strip()

    if normalized_provider_id:
        mapped = await resolve_provider_elo_team_id(
            provider=_FOOTBALL_DATA_PROVIDER,
            provider_team_id=normalized_provider_id,
            competition=league_id,
            db=session,
        )
        if mapped:
            return mapped, True

    historical = await resolve_team_id(
        team_name,
        session,
        league_id=league_id,
        require_elo_history=True,
    )
    if historical:
        if normalized_provider_id:
            await bind_provider_elo_team_id(
                provider=_FOOTBALL_DATA_PROVIDER,
                provider_team_id=normalized_provider_id,
                provider_team_name=team_name,
                competition=league_id,
                team_id=historical,
                db=session,
                evidence={
                    "source": _FOOTBALL_DATA_PROVIDER,
                    "provider_event_id": provider_event_id,
                    "provider_team_id": normalized_provider_id,
                    "provider_team_name": team_name,
                    "reconciled_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        return historical, True

    return _team_id(team_name, league_id), False


async def _claim_fixture_sync_lease() -> tuple[bool, str | None]:
    """Claim one deploy-overlap-safe fixture-sync execution slot.

    A recently-completed marker suppresses duplicate boot passes from sibling
    Render candidates. If another instance currently owns the lease, wait long
    enough for a crashed holder's TTL to expire; a successful holder publishes
    the completion marker before releasing, so waiters stop without repeating
    the provider requests.

    Production fails closed when external Redis is unavailable. Non-production
    keeps the historical single-process behavior so local/SQLite workflows do
    not suddenly require Redis.
    """
    from ..core.cache import cache

    client = cache.redis_client
    if client is None:
        if settings.app_env == "production":
            logger.warning(
                "fixture_sync: external Redis unavailable; skipping uncoordinated provider pass"
            )
            return False, None
        return True, None

    token = uuid4().hex
    deadline = time.monotonic() + _FIXTURE_SYNC_LEASE_WAIT_SECONDS

    while True:
        try:
            recently_completed = await asyncio.to_thread(
                client.get,
                _FIXTURE_SYNC_COMPLETED_KEY,
            )
            if recently_completed is not None:
                return False, None

            # ``cache.redis_client`` is constructed as the synchronous
            # ``redis.Redis`` client. redis-py's shared sync/async overloads can
            # otherwise confuse static inference when the bound method is
            # passed through ``asyncio.to_thread``.
            sync_set = cast(Callable[..., Any], client.set)
            acquired = await asyncio.to_thread(
                sync_set,
                _FIXTURE_SYNC_LEASE_KEY,
                token,
                nx=True,
                ex=_FIXTURE_SYNC_LEASE_TTL_SECONDS,
            )
            if acquired:
                return True, token
        except RedisError as exc:
            logger.warning("fixture_sync: Redis lease check failed: %s", exc)
            if settings.app_env == "production":
                return False, None
            return True, None

        if time.monotonic() >= deadline:
            logger.info("fixture_sync: lease wait expired; another instance remains authoritative")
            return False, None
        await asyncio.sleep(_FIXTURE_SYNC_LEASE_POLL_SECONDS)


async def _finish_fixture_sync_lease(token: str | None, *, completed: bool) -> None:
    """Publish de-dup evidence, then token-safely release the execution lease.

    If the completion marker cannot be written after a successful pass, leave
    the lease in place until its TTL expires rather than risk an immediate
    duplicate acquisition burst. Failed/unhandled passes release immediately so
    another candidate can retry.
    """
    if token is None:
        return

    from ..core.cache import cache

    client = cache.redis_client
    if client is None:
        return

    if completed:
        try:
            await asyncio.to_thread(
                client.setex,
                _FIXTURE_SYNC_COMPLETED_KEY,
                _FIXTURE_SYNC_COMPLETED_TTL_SECONDS,
                token,
            )
        except RedisError as exc:
            logger.warning(
                "fixture_sync: completion marker write failed; retaining lease until TTL: %s",
                exc,
            )
            return

    try:
        await asyncio.to_thread(
            client.eval,
            _RELEASE_LEASE_SCRIPT,
            1,
            _FIXTURE_SYNC_LEASE_KEY,
            token,
        )
    except RedisError as exc:
        logger.warning("fixture_sync: Redis lease release failed; TTL will recover: %s", exc)


async def sync_upcoming_fixtures(
    session: AsyncSession,
    *,
    provider: Any = None,
) -> int:
    """Fetch upcoming fixtures and upsert League/Team/Match/canonical rows.

    ``provider`` must be the lifespan-owned ``football_data_org`` provider in
    production. Keeping it injectable makes persistence tests deterministic;
    the normalization adapter fails closed if no real provider is supplied.

    Existing *unsettled* provider fixtures are refreshed in place so verified
    kickoff reschedules propagate to both the legacy Match row and its stable
    canonical fixture. Settled rows are never rewritten by an upcoming feed.

    New fixtures may immediately use a verified provider-ID -> durable-Elo Team
    identity. Existing scheduled fixtures are deliberately not re-keyed when a
    better identity is discovered: the bridge evidence is persisted, but a
    participant-ID mismatch is only logged/metriced for an explicit authorized
    reconciliation step. This prevents a normal sync from becoming a hidden
    production backfill.

    Team identity must remain distinct before either the legacy ``Match`` row or
    canonical identity rows are staged. A resolver collision therefore fails
    closed at the raw persistence boundary rather than relying on the later
    canonical savepoint to reject it after a self-play ``Match`` already exists.

    Canonical reconciliation runs inside a per-fixture savepoint. A true
    canonical identity conflict rolls back every canonical row staged by that
    attempt without discarding unrelated later batch items.

    Returns the number of new Match rows inserted.
    """
    from ..core.database import League, Match, Team
    from ..data.loaders.football_data_api import FootballDataAPIClient, FootballDataAPIError
    from ..repositories.fixtures import SETTLED_MATCH_STATUSES

    started_at = time.perf_counter()
    client = FootballDataAPIClient(provider=provider)
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
        home_name = str(raw.get("home_team") or "").strip()
        away_name = str(raw.get("away_team") or "").strip()
        match_id = str(raw.get("id") or "").strip()
        home_provider_id = raw.get("home_provider_team_id")
        away_provider_id = raw.get("away_provider_team_id")

        if not match_id or not home_name or not away_name:
            continue
        if home_provider_id is None or away_provider_id is None:
            logger.warning(
                "fixture_sync: missing upstream team identity; skipping match_id=%s league=%s",
                match_id,
                league_id,
            )
            metrics_collector.increment("fixture_sync.provider_team_id_missing")
            continue

        try:
            home_id, home_elo_resolved = await _resolve_upcoming_team_id(
                session,
                provider_team_id=home_provider_id,
                team_name=home_name,
                league_id=league_id,
                provider_event_id=match_id,
            )
            away_id, away_elo_resolved = await _resolve_upcoming_team_id(
                session,
                provider_team_id=away_provider_id,
                team_name=away_name,
                league_id=league_id,
                provider_event_id=match_id,
            )
        except ValueError as exc:
            logger.error(
                "fixture_sync: provider/Elo identity conflict match_id=%s league=%s: %s",
                match_id,
                league_id,
                exc,
            )
            metrics_collector.increment("fixture_sync.identity_conflicts")
            continue

        if home_id == away_id:
            logger.error(
                "fixture_sync: refusing self-play identity collision match_id=%s league=%s "
                "home=%r away=%r resolved_team_id=%s",
                match_id,
                league_id,
                home_name,
                away_name,
                home_id,
            )
            metrics_collector.increment("fixture_sync.identity_conflicts")
            metrics_collector.increment("fixture_sync.self_play_rejected")
            continue

        if not await session.get(League, league_id):
            session.add(League(id=league_id, name=league_name, country=country))
            await session.flush()

        for tid, tname in [(home_id, home_name), (away_id, away_name)]:
            if tname and not await session.get(Team, tid):
                session.add(Team(id=tid, name=tname, league_id=league_id))
        await session.flush()

        raw_date = str(raw.get("match_date") or "")
        try:
            match_date = datetime.fromisoformat(raw_date.replace("Z", "+00:00")).replace(tzinfo=None)
        except (TypeError, ValueError):
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
            runtime_match = cast(Any, match)
            runtime_match.league_id = league_id
            runtime_match.match_date = match_date
            runtime_match.season = season
            runtime_match.status = "scheduled"

            if match.home_team_id != home_id or match.away_team_id != away_id:
                logger.warning(
                    "fixture_sync: verified identity differs from persisted participants; "
                    "leaving match unchanged pending explicit reconciliation "
                    "match_id=%s stored=(%s,%s) verified=(%s,%s)",
                    match_id,
                    match.home_team_id,
                    match.away_team_id,
                    home_id,
                    away_id,
                )
                metrics_collector.increment("fixture_sync.identity_rebind_pending")
            if previous_kickoff != match_date:
                metrics_collector.increment("fixture_sync.reschedules")
                logger.info(
                    "fixture_sync: provider reschedule applied for match_id=%s (%s -> %s)",
                    match_id,
                    previous_kickoff,
                    match_date,
                )

        from .canonical_identity_service import ensure_canonical_fixture

        evidence = {
            "source": raw.get("source") or _FOOTBALL_DATA_PROVIDER,
            "provider_event_id": match_id,
            "provider_timestamp": raw_date,
            "home_provider_team_id": str(home_provider_id),
            "away_provider_team_id": str(away_provider_id),
            "home_elo_identity_resolved": home_elo_resolved,
            "away_elo_identity_resolved": away_elo_resolved,
            "reconciled_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            async with session.begin_nested():
                await ensure_canonical_fixture(
                    session,
                    provider=_FOOTBALL_DATA_PROVIDER,
                    provider_event_id=match_id,
                    competition_id=league_id,
                    competition_name=league_name,
                    home_provider_id=str(home_provider_id),
                    home_name=home_name,
                    away_provider_id=str(away_provider_id),
                    away_name=away_name,
                    kickoff_utc=match_date,
                    season=season,
                    status="scheduled",
                    evidence=evidence,
                )
        except ValueError as exc:
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


async def sync_settled_results(
    session: AsyncSession,
    *,
    days_back: int = 3,
    provider: Any = None,
) -> dict[str, int]:
    """Fetch recently finished fixtures and settle matching Match rows.

    Never creates a Match row and never rewrites a row already settled.
    """
    from ..core.database import Match
    from ..data.loaders.football_data_api import FootballDataAPIClient, FootballDataAPIError
    from ..repositories.fixtures import SETTLED_MATCH_STATUSES

    client = FootballDataAPIClient(provider=provider)
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

        runtime_match = cast(Any, match)
        runtime_match.status = "finished"
        runtime_match.home_score = home_score
        runtime_match.away_score = away_score
        updated += 1

    await session.commit()
    return {"updated": updated, "unmatched": unmatched, "already_settled": already_settled}


async def run_fixture_sync(provider: Any = None) -> None:
    """Entry point for the background sync loop — swallows all errors."""
    from ..db.session import AsyncSessionLocal
    from ..monitoring.metrics import metrics_collector

    if AsyncSessionLocal is None:
        logger.warning("fixture_sync: DB not ready, skipping")
        return

    lease_acquired, lease_token = await _claim_fixture_sync_lease()
    if not lease_acquired:
        logger.info("fixture_sync: skipped; another instance owns the recent execution window")
        metrics_collector.increment("fixture_sync.lease_skips")
        return

    completed = False
    try:
        async with AsyncSessionLocal() as session:
            count = await sync_upcoming_fixtures(session, provider=provider)
            logger.info("fixture_sync: %d new upcoming fixtures seeded", count)
            completed = True
    except Exception as exc:
        logger.exception("fixture_sync: unhandled error — continuing without fixture data")
        metrics_collector.increment("fixture_sync.failures")
        metrics_collector.record_error(
            error_type=type(exc).__name__,
            message=str(exc),
            context={"task": "fixture_sync"},
        )
    finally:
        await _finish_fixture_sync_lease(lease_token, completed=completed)
