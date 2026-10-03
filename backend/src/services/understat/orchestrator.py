"""Understat Ingestion Orchestrator & Cache Invalidation.

Orchestrates the scraping, entity resolution, PostgreSQL idempotent upsert,
and Redis cache invalidation for Understat match telemetry.
Designed to be executed directly or scheduled as a FastAPI BackgroundTask.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Sequence

import asyncpg  # type: ignore[import-untyped]
import redis.asyncio as aioredis

from ...core.config import settings
from ...core.redis import get_redis_client
from .entity_map import UnmappedEntityError, resolve_slug
from .scraper import UnderstatMatchPayload, UnderstatScraper

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQL Queries
# ---------------------------------------------------------------------------

UPSERT_MATCH_TELEMETRY_SQL = """
INSERT INTO match_telemetry (
    match_id,
    provider_id,
    home_team_slug,
    away_team_slug,
    home_xg,
    away_xg,
    home_xa,
    away_xa,
    shot_telemetry,
    created_at,
    updated_at
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11
)
ON CONFLICT (match_id) DO UPDATE SET
    provider_id = EXCLUDED.provider_id,
    home_team_slug = EXCLUDED.home_team_slug,
    away_team_slug = EXCLUDED.away_team_slug,
    home_xg = EXCLUDED.home_xg,
    away_xg = EXCLUDED.away_xg,
    home_xa = EXCLUDED.home_xa,
    away_xa = EXCLUDED.away_xa,
    shot_telemetry = EXCLUDED.shot_telemetry,
    updated_at = EXCLUDED.updated_at;
"""

# Global asyncpg pool singleton
_asyncpg_pool: asyncpg.Pool | None = None


def _clean_postgres_dsn(raw_url: str) -> str:
    """Normalize SQLAlchemy or psycopg DSN into a clean standard postgres DSN for asyncpg."""
    url = raw_url
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg://", "postgres://"):
        if url.startswith(prefix):
            url = url.replace(prefix, "postgresql://", 1)
            break
    return url


async def get_asyncpg_pool(dsn: str | None = None) -> asyncpg.Pool:
    """Get or create the global asyncpg connection pool."""
    global _asyncpg_pool
    if _asyncpg_pool is None or _asyncpg_pool._closed:
        target_dsn = _clean_postgres_dsn(dsn or settings.database_url)
        min_size = min(2, settings.database_pool_size)
        max_size = max(min_size, settings.database_pool_size)
        _asyncpg_pool = await asyncpg.create_pool(
            dsn=target_dsn,
            min_size=min_size,
            max_size=max_size,
            command_timeout=settings.database_pool_timeout,
        )
        logger.info("Created asyncpg connection pool (max_size=%d)", max_size)
    return _asyncpg_pool


async def close_asyncpg_pool() -> None:
    """Close the global asyncpg connection pool if open."""
    global _asyncpg_pool
    if _asyncpg_pool is not None and not _asyncpg_pool._closed:
        await _asyncpg_pool.close()
        _asyncpg_pool = None
        logger.info("Closed asyncpg connection pool")


async def invalidate_telemetry_cache(
    match_id: int,
    home_team_slug: str,
    away_team_slug: str,
    redis_client: aioredis.Redis | None = None,
) -> None:
    """Execute atomic Redis pipeline DELETE commands for match and rolling xG keys.

    Target keys:
    - sabiscore:telemetry:{match_id}
    - sabiscore:rolling_xg:{home_team_slug}
    - sabiscore:rolling_xg:{away_team_slug}
    """
    client = redis_client
    if client is None:
        client = await get_redis_client().get_client()

    keys = [
        f"sabiscore:telemetry:{match_id}",
        f"sabiscore:rolling_xg:{home_team_slug}",
        f"sabiscore:rolling_xg:{away_team_slug}",
    ]

    pipe = client.pipeline()
    for key in keys:
        pipe.delete(key)
    await pipe.execute()
    logger.debug(
        "Invalidated Redis telemetry caches for match_id=%d, home=%s, away=%s",
        match_id,
        home_team_slug,
        away_team_slug,
    )


async def ingest_single_match(
    match_id: int,
    scraper: UnderstatScraper,
    conn: asyncpg.Connection,
    redis_client: aioredis.Redis | None = None,
) -> dict[str, Any]:
    """Ingest a single Understat match: scrape, resolve, upsert, and invalidate cache.

    Returns:
        Dict describing the status and extracted metadata.
    """
    payload: UnderstatMatchPayload = await scraper.fetch_match(match_id)

    # Extract team titles
    home_title = payload.match_info.h.title
    away_title = payload.match_info.a.title

    # Resolve slugs - let UnmappedEntityError bubble to be handled per-row
    home_slug = resolve_slug(home_title)
    away_slug = resolve_slug(away_title)

    shot_telemetry_json = json.dumps(payload.shots_data.model_dump())
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    # Idempotent upsert inside a database transaction
    async with conn.transaction():
        await conn.execute(
            UPSERT_MATCH_TELEMETRY_SQL,
            match_id,
            str(payload.match_id),
            home_slug,
            away_slug,
            payload.home_xg,
            payload.away_xg,
            payload.home_xa,
            payload.away_xa,
            shot_telemetry_json,
            now_utc,
            now_utc,
        )

    # Immediately upon successful commit, invalidate Redis cache via pipeline
    await invalidate_telemetry_cache(
        match_id=match_id,
        home_team_slug=home_slug,
        away_team_slug=away_slug,
        redis_client=redis_client,
    )

    return {
        "match_id": match_id,
        "home_slug": home_slug,
        "away_slug": away_slug,
        "home_xg": payload.home_xg,
        "away_xg": payload.away_xg,
        "home_xa": payload.home_xa,
        "away_xa": payload.away_xa,
    }


async def ingest_understat_telemetry(
    match_ids: Sequence[int],
    pool: asyncpg.Pool | None = None,
    redis_client: aioredis.Redis | None = None,
) -> dict[str, Any]:
    """FastAPI BackgroundTask orchestrator to ingest Understat match telemetry.

    Processes a batch of match IDs, mapping entities, performing idempotent
    PostgreSQL upserts, and executing atomic Redis cache invalidations.

    Args:
        match_ids: Sequence of integer Understat match IDs to ingest.
        pool: Optional existing asyncpg.Pool (created from settings if omitted).
        redis_client: Optional existing Redis client.

    Returns:
        Summary dict containing counts of processed, succeeded, failed, and unmapped matches.
    """
    if not match_ids:
        return {"processed": 0, "succeeded": 0, "failed": 0, "unmapped": 0}

    logger.info("Starting Understat telemetry ingestion for %d matches", len(match_ids))
    db_pool = pool or await get_asyncpg_pool()

    succeeded: list[int] = []
    unmapped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    async with UnderstatScraper() as scraper:
        for match_id in match_ids:
            try:
                async with db_pool.acquire() as conn:
                    result = await ingest_single_match(
                        match_id=match_id,
                        scraper=scraper,
                        conn=conn,
                        redis_client=redis_client,
                    )
                    succeeded.append(match_id)
                    logger.info("Successfully ingested match_id=%d: %s", match_id, result)

            except UnmappedEntityError as uerr:
                logger.critical(
                    "Skipping match_id=%d due to unmapped entity: %s",
                    match_id,
                    uerr,
                )
                unmapped.append({"match_id": match_id, "error": str(uerr), "team": uerr.raw_name})

            except Exception as exc:
                logger.error(
                    "Failed to ingest Understat match_id=%d: %s",
                    match_id,
                    exc,
                    exc_info=True,
                )
                failed.append({"match_id": match_id, "error": str(exc)})

    summary = {
        "processed": len(match_ids),
        "succeeded": len(succeeded),
        "failed": len(failed),
        "unmapped": len(unmapped),
        "succeeded_ids": succeeded,
        "unmapped_details": unmapped,
        "failed_details": failed,
    }
    logger.info("Completed Understat telemetry ingestion: %s", summary)
    return summary


__all__ = [
    "ingest_understat_telemetry",
    "ingest_single_match",
    "invalidate_telemetry_cache",
    "get_asyncpg_pool",
    "close_asyncpg_pool",
    "UPSERT_MATCH_TELEMETRY_SQL",
]
