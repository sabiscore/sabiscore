"""Regression coverage for fail-closed historical team identity resolution.

These cases mirror real production self-play rows discovered by read-only audit.
A missing provider team must reduce historical coverage; it must never cause a
shared city/name token to bind both sides of a fixture to one Team id.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, League, Match, Team
from src.services.historical_backfill_service import (
    TeamIndex,
    backfill_historical_matches,
    historical_match_id,
)


@pytest.mark.parametrize(
    "rows,probe",
    [
        ([("inter", "FC Internazionale Milano")], "Milan"),
        ([("espanyol", "RCD Espanyol de Barcelona")], "Barcelona"),
        ([("paris-fc", "Paris FC")], "Paris SG"),
    ],
)
def test_shared_place_tokens_do_not_resolve_to_a_different_club(rows, probe):
    index = TeamIndex(rows)
    assert index.resolve(probe) is None


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


async def test_backfill_never_inserts_distinct_clubs_as_self_play(
    session: AsyncSession, tmp_path: Path
):
    session.add(
        Team(
            id="fd-team-serie_a:fc_internazionale_milano",
            name="FC Internazionale Milano",
            league_id="SERIE_A",
        )
    )
    await session.commit()

    (tmp_path / "fd_I1_1920.csv").write_text(
        "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG\n"
        "I1,21/09/2019,Milan,Inter,0,2\n",
        encoding="utf-8",
    )

    report = await backfill_historical_matches(session, cache_dir=tmp_path)
    matches = (await session.execute(select(Match))).scalars().all()

    assert report.matches_inserted == 1
    assert len(matches) == 1
    assert matches[0].home_team_id != matches[0].away_team_id


async def test_backfill_guard_skips_collision_even_if_resolver_regresses(
    session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    shared_id = "fd-team-serie_a:fc_internazionale_milano"
    session.add(Team(id=shared_id, name="FC Internazionale Milano", league_id="SERIE_A"))
    await session.commit()

    (tmp_path / "fd_I1_1920.csv").write_text(
        "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG\n"
        "I1,21/09/2019,Milan,Inter,0,2\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(TeamIndex, "resolve", lambda self, name: shared_id)
    report = await backfill_historical_matches(session, cache_dir=tmp_path)

    assert report.matches_inserted == 0
    assert report.identity_conflicts_skipped == 1
    assert (await session.execute(select(Match))).scalars().all() == []


async def test_existing_match_is_filtered_before_team_creation(
    session: AsyncSession, tmp_path: Path
):
    """An idempotent boot must not mint fallback teams for already-ingested history."""
    match_date = datetime(2024, 8, 16)
    match_id = historical_match_id("EPL", match_date, "Ghost Home", "Ghost Away")

    session.add(League(id="EPL", name="Premier League", country="England"))
    session.add_all(
        [
            Team(id="canonical-home", name="Canonical Home", league_id="EPL"),
            Team(id="canonical-away", name="Canonical Away", league_id="EPL"),
        ]
    )
    session.add(
        Match(
            id=match_id,
            league_id="EPL",
            home_team_id="canonical-home",
            away_team_id="canonical-away",
            match_date=match_date,
            season="2024-25",
            status="finished",
            home_score=1,
            away_score=0,
        )
    )
    await session.commit()

    before_team_ids = set((await session.execute(select(Team.id))).scalars().all())
    (tmp_path / "fd_E0_2425.csv").write_text(
        "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG\n"
        "E0,16/08/2024,Ghost Home,Ghost Away,1,0\n",
        encoding="utf-8",
    )

    report = await backfill_historical_matches(session, cache_dir=tmp_path)
    after_team_ids = set((await session.execute(select(Team.id))).scalars().all())

    assert report.matches_inserted == 0
    assert report.matches_existing == 1
    assert report.teams_created == 0
    assert report.teams_resolved == 0
    assert after_team_ids == before_team_ids
