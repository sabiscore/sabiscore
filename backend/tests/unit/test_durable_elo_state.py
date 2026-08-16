"""Durable Elo state contracts for production feature serving."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, League, Match, Team
from src.db.models import EloRatingSnapshot
from src.services.elo_state_service import (
    apply_finished_match_to_elo,
    get_elo_context,
    sync_elo_from_finished_matches,
)


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _seed_identity(session: AsyncSession) -> None:
    session.add(League(id="EPL", name="Premier League", country="England", active=True))
    session.add_all(
        [
            Team(id="arsenal", name="Arsenal", league_id="EPL", active=True),
            Team(id="chelsea", name="Chelsea", league_id="EPL", active=True),
        ]
    )
    await session.flush()


async def test_unknown_durable_elo_is_explicitly_unresolved(session_factory) -> None:
    async with session_factory() as session:
        await _seed_identity(session)
        context = await get_elo_context(
            session,
            home_team_id="arsenal",
            away_team_id="chelsea",
            league="EPL",
            season="2026/2027",
            match_date=datetime(2026, 8, 16, 15, 0),
        )

    assert context.home_elo == 1500.0
    assert context.away_elo == 1500.0
    assert context.resolved is False


async def test_finished_match_creates_two_real_identity_snapshots_and_is_idempotent(
    session_factory,
) -> None:
    async with session_factory() as session:
        await _seed_identity(session)
        match = Match(
            id="m1",
            league_id="EPL",
            home_team_id="arsenal",
            away_team_id="chelsea",
            match_date=datetime(2026, 8, 1, 15, 0),
            season="2026/2027",
            status="finished",
            home_score=2,
            away_score=1,
        )
        session.add(match)
        await session.flush()

        assert await apply_finished_match_to_elo(session, match) is True
        assert await apply_finished_match_to_elo(session, match) is False
        await session.commit()

        rows = (
            await session.execute(
                select(EloRatingSnapshot).where(EloRatingSnapshot.match_id == "m1")
            )
        ).scalars().all()

    assert {row.team_id for row in rows} == {"arsenal", "chelsea"}
    assert len(rows) == 2
    assert all(row.pre_match_elo == pytest.approx(1500.0) for row in rows)
    assert rows[0].post_match_elo != rows[0].pre_match_elo


async def test_malformed_match_date_fails_at_legacy_orm_boundary(session_factory) -> None:
    async with session_factory() as session:
        match = Match(
            id="bad-date",
            league_id="EPL",
            home_team_id="arsenal",
            away_team_id="chelsea",
            match_date=datetime(2026, 8, 1, 15, 0),
            season="2026/2027",
            status="finished",
            home_score=2,
            away_score=1,
        )
        # The legacy declarative model is not Mapped[]-typed. Simulate malformed
        # runtime data without flushing it through SQLite so the service boundary,
        # rather than the dialect adapter, owns the failure semantics.
        match.match_date = "2026-08-01T15:00:00"  # type: ignore[assignment]

        with pytest.raises(TypeError, match="non-datetime match_date"):
            await apply_finished_match_to_elo(session, match)


async def test_incremental_sync_is_chronological_and_resolves_next_fixture(session_factory) -> None:
    async with session_factory() as session:
        await _seed_identity(session)
        base = datetime(2026, 8, 1, 15, 0)
        session.add_all(
            [
                Match(
                    id="m2",
                    league_id="EPL",
                    home_team_id="chelsea",
                    away_team_id="arsenal",
                    match_date=base + timedelta(days=7),
                    season="2026/2027",
                    status="finished",
                    home_score=0,
                    away_score=1,
                ),
                Match(
                    id="m1",
                    league_id="EPL",
                    home_team_id="arsenal",
                    away_team_id="chelsea",
                    match_date=base,
                    season="2026/2027",
                    status="finished",
                    home_score=2,
                    away_score=0,
                ),
            ]
        )
        await session.commit()

        first = await sync_elo_from_finished_matches(session)
        second = await sync_elo_from_finished_matches(session)
        row_count = int(
            (await session.execute(select(func.count(EloRatingSnapshot.id)))).scalar_one()
        )
        context = await get_elo_context(
            session,
            home_team_id="arsenal",
            away_team_id="chelsea",
            league="EPL",
            season="2026/2027",
            match_date=base + timedelta(days=14),
        )

    assert first["processed"] == 2
    assert second["processed"] == 0
    assert row_count == 4
    assert context.resolved is True
    assert context.home_elo != 1500.0
