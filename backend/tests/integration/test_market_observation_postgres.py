"""PostgreSQL-backed market lifecycle regressions.

This test intentionally uses the canonical CI Postgres service because asyncpg's
TIMESTAMP WITHOUT TIME ZONE handling previously exposed a production-only
naive/aware datetime failure that SQLite accepted. The test is hard-gated to
``APP_ENV=test`` and rolls its transaction back, so it cannot mutate a production
or developer database accidentally.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from src.core.database import League, Match, OddsHistory, Team
from src.db.models import MarketSnapshot
from src.services.market_observation_service import PRE_MATCH_CLOSING, persist_market_board


def _ci_postgres_url() -> str:
    if os.getenv("APP_ENV", "").casefold() != "test":
        pytest.skip("PostgreSQL lifecycle regression runs only with APP_ENV=test")
    url = os.getenv("DATABASE_URL", "")
    if not url.startswith("postgresql://"):
        pytest.skip("canonical CI PostgreSQL DATABASE_URL is required")
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)


async def test_offset_aware_closing_persists_through_asyncpg_without_poisoning_session() -> None:
    engine = create_async_engine(_ci_postgres_url(), echo=False)
    conn = await engine.connect()
    tx = await conn.begin()
    session = AsyncSession(bind=conn, expire_on_commit=False)

    league_id = "TEST_MARKET"
    home_id = "test-market-home"
    away_id = "test-market-away"
    match_id = "test-market-match"
    kickoff = datetime(2026, 8, 20, 18, 0)
    plus_one = timezone(timedelta(hours=1))
    observed_aware = datetime(2026, 8, 20, 18, 56, tzinfo=plus_one)

    try:
        session.add_all(
            [
                League(id=league_id, name="Test Market League", country="test"),
                Team(id=home_id, name="Alpha FC", league_id=league_id),
                Team(id=away_id, name="Beta FC", league_id=league_id),
                Match(
                    id=match_id,
                    league_id=league_id,
                    home_team_id=home_id,
                    away_team_id=away_id,
                    match_date=kickoff,
                    season="2026",
                    status="scheduled",
                ),
            ]
        )
        await session.flush()

        result = await persist_market_board(
            session,
            league=league_id,
            observed_at=observed_aware,
            records=[
                {
                    "provider": "the_odds_api",
                    "provider_event_id": "test-provider-event",
                    "provider_event_timestamp": kickoff.replace(tzinfo=timezone.utc).isoformat(),
                    "home_team": "Alpha",
                    "away_team": "Beta",
                    "bookmaker": "test-book",
                    "bookmaker_last_update": observed_aware.isoformat(),
                    "home_odds": 2.0,
                    "draw_odds": 3.5,
                    "away_odds": 4.0,
                    "captured_at": observed_aware.isoformat(),
                    "coherent": True,
                    "executable": True,
                }
            ],
        )
        await session.flush()

        history = (
            (
                await session.execute(
                    select(OddsHistory).where(OddsHistory.match_id == match_id)
                )
            )
            .scalars()
            .one()
        )
        snapshot = (
            (
                await session.execute(
                    select(MarketSnapshot).where(MarketSnapshot.match_id == match_id)
                )
            )
            .scalars()
            .one()
        )

        assert result.closing == 1
        assert history.timestamp == datetime(2026, 8, 20, 17, 56)
        assert snapshot.captured_at == datetime(2026, 8, 20, 17, 56)
        assert snapshot.provider_timestamp == datetime(2026, 8, 20, 17, 56)
        assert snapshot.provenance["evidence_class"] == PRE_MATCH_CLOSING

        # A normal query after the writes proves the AsyncSession/connection was
        # not left in failed-transaction state.
        assert (
            await session.scalar(
                select(Match.id).where(Match.id == match_id)
            )
        ) == match_id
    finally:
        await session.close()
        await tx.rollback()
        await conn.close()
        await engine.dispose()
