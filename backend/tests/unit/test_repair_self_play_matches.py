"""Unit tests for src/services/self_play_repair_service.py.

Covers docs/DEBT.md item 23: 26 legacy ``matches`` rows were mis-resolved by a
since-fixed version of the team-name matcher onto the same team id for both
sides. The resolver is correct today; this repair recovers each corrupted
row's original raw CSV names (via the deterministic, name-keyed
``historical_match_id``) and re-resolves them.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, Match, Team
from src.services.historical_backfill_service import historical_match_id
from src.services.self_play_repair_service import find_and_repair_self_play_matches


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def _write_serie_a_csv(directory: Path) -> None:
    (directory / "fd_I1_1920.csv").write_text(
        "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG\n"
        "I1,21/09/2019,Milan,Inter,0,2\n",
        encoding="utf-8",
    )


async def test_repairs_a_known_self_play_row(session: AsyncSession, tmp_path: Path):
    # Correct, distinct team rows already exist (as they do live) — Inter's own
    # row, mis-registered as both sides by the legacy bug.
    session.add(Team(id="fd-team-serie_a:ac_milan", name="AC Milan", league_id="SERIE_A"))
    session.add(Team(
        id="fd-team-serie_a:fc_internazionale_milano",
        name="FC Internazionale Milano",
        league_id="SERIE_A",
    ))
    corrupted_id = historical_match_id("SERIE_A", datetime(2019, 9, 21), "Milan", "Inter")
    session.add(Match(
        id=corrupted_id,
        league_id="SERIE_A",
        home_team_id="fd-team-serie_a:fc_internazionale_milano",
        away_team_id="fd-team-serie_a:fc_internazionale_milano",
        match_date=datetime(2019, 9, 21),
        status="finished",
        home_score=0,
        away_score=2,
    ))
    await session.commit()
    _write_serie_a_csv(tmp_path)

    report = await find_and_repair_self_play_matches(session, cache_dir=tmp_path, apply=True)

    assert report.corrupted_found == 1
    assert report.repaired == 1
    assert report.skipped == 0

    fixed = (await session.execute(select(Match).where(Match.id == corrupted_id))).scalar_one()
    assert fixed.home_team_id == "fd-team-serie_a:ac_milan"
    assert fixed.away_team_id == "fd-team-serie_a:fc_internazionale_milano"


async def test_dry_run_reports_without_mutating(session: AsyncSession, tmp_path: Path):
    session.add(Team(id="fd-team-serie_a:ac_milan", name="AC Milan", league_id="SERIE_A"))
    session.add(Team(
        id="fd-team-serie_a:fc_internazionale_milano",
        name="FC Internazionale Milano",
        league_id="SERIE_A",
    ))
    corrupted_id = historical_match_id("SERIE_A", datetime(2019, 9, 21), "Milan", "Inter")
    session.add(Match(
        id=corrupted_id,
        league_id="SERIE_A",
        home_team_id="fd-team-serie_a:fc_internazionale_milano",
        away_team_id="fd-team-serie_a:fc_internazionale_milano",
        match_date=datetime(2019, 9, 21),
        status="finished",
        home_score=0,
        away_score=2,
    ))
    await session.commit()
    _write_serie_a_csv(tmp_path)

    report = await find_and_repair_self_play_matches(session, cache_dir=tmp_path, apply=False)
    assert report.repaired == 1

    unchanged = (await session.execute(select(Match).where(Match.id == corrupted_id))).scalar_one()
    assert unchanged.home_team_id == unchanged.away_team_id == "fd-team-serie_a:fc_internazionale_milano"


async def test_skips_row_whose_original_csv_is_unavailable(session: AsyncSession, tmp_path: Path):
    """Never guess: a corrupted row with no matching CSV source is reported, not repaired."""
    session.add(Team(id="fd-team-serie_a:fc_internazionale_milano", name="FC Internazionale Milano",
                     league_id="SERIE_A"))
    corrupted_id = historical_match_id("SERIE_A", datetime(2019, 9, 21), "Milan", "Inter")
    session.add(Match(
        id=corrupted_id,
        league_id="SERIE_A",
        home_team_id="fd-team-serie_a:fc_internazionale_milano",
        away_team_id="fd-team-serie_a:fc_internazionale_milano",
        match_date=datetime(2019, 9, 21),
        status="finished",
        home_score=0,
        away_score=2,
    ))
    await session.commit()
    # No CSV written for this cache_dir — the original row cannot be recovered.

    report = await find_and_repair_self_play_matches(session, cache_dir=tmp_path, apply=True)

    assert report.corrupted_found == 1
    assert report.repaired == 0
    assert report.skipped == 1
    still = (await session.execute(select(Match).where(Match.id == corrupted_id))).scalar_one()
    assert still.home_team_id == still.away_team_id


async def test_skips_row_that_still_collides_after_reresolution(session: AsyncSession, tmp_path: Path):
    """Two teams that still normalise identically must not be force-repaired."""
    session.add(Team(id="a", name="Real Madrid CF", league_id="LA_LIGA"))
    session.add(Team(id="b", name="Real Madrid FC", league_id="LA_LIGA"))
    corrupted_id = historical_match_id("LA_LIGA", datetime(2020, 1, 1), "Real Madrid", "Real Madrid")
    session.add(Match(
        id=corrupted_id,
        league_id="LA_LIGA",
        home_team_id="a",
        away_team_id="a",
        match_date=datetime(2020, 1, 1),
        status="finished",
        home_score=1,
        away_score=1,
    ))
    await session.commit()
    (tmp_path / "fd_SP1_1920.csv").write_text(
        "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG\n"
        "SP1,01/01/2020,Real Madrid,Real Madrid,1,1\n",
        encoding="utf-8",
    )

    report = await find_and_repair_self_play_matches(session, cache_dir=tmp_path, apply=True)

    assert report.repaired == 0
    assert report.skipped == 1
