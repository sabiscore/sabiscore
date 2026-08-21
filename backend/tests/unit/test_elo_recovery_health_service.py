"""Read-only release evidence for deterministic Elo recovery and integrity."""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, League, Match, Team
from src.db.models import EloRatingSnapshot
from src.services.elo_recovery_health_service import elo_recovery_health


@pytest.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield session_factory
    await engine.dispose()


async def test_recovery_health_keeps_progress_separate_from_structural_certification(factory) -> None:
    kickoff = datetime(2026, 8, 1, 15, 0)
    async with factory() as session:
        session.add(League(id="EPL", name="Premier League", country="England"))
        for index in range(1, 5):
            session.add(Team(id=f"team-{index}", name=f"Team {index}", league_id="EPL"))
        session.add_all(
            [
                Match(
                    id="match-1",
                    league_id="EPL",
                    home_team_id="team-1",
                    away_team_id="team-2",
                    match_date=kickoff,
                    status="finished",
                    home_score=2,
                    away_score=1,
                ),
                Match(
                    id="match-2",
                    league_id="EPL",
                    home_team_id="team-3",
                    away_team_id="team-4",
                    match_date=kickoff,
                    status="FINISHED",
                    home_score=1,
                    away_score=1,
                ),
                Match(
                    id="match-3",
                    league_id="EPL",
                    home_team_id="team-1",
                    away_team_id="team-3",
                    match_date=kickoff,
                    status="finished",
                    home_score=0,
                    away_score=1,
                ),
                Match(
                    id="scheduled",
                    league_id="EPL",
                    home_team_id="team-1",
                    away_team_id="team-4",
                    match_date=kickoff,
                    status="scheduled",
                ),
                Match(
                    id="self-play",
                    league_id="EPL",
                    home_team_id="team-1",
                    away_team_id="team-1",
                    match_date=kickoff,
                    status="finished",
                    home_score=1,
                    away_score=0,
                ),
            ]
        )
        session.add_all(
            [
                EloRatingSnapshot(
                    match_id="match-1",
                    team_id="team-1",
                    pre_match_elo=1500.0,
                    post_match_elo=1510.0,
                    league="EPL",
                    season="2026/2027",
                    match_date=kickoff,
                    created_at=kickoff,
                ),
                EloRatingSnapshot(
                    match_id="match-2",
                    team_id="team-3",
                    pre_match_elo=1500.0,
                    post_match_elo=1500.0,
                    league="EPL",
                    season="2026/2027",
                    match_date=kickoff,
                    created_at=kickoff,
                ),
            ]
        )
        await session.commit()

    async with factory() as session:
        result = await elo_recovery_health(session)

    assert result["authority"] == "postgres"
    assert result["rows"] == 2
    assert result["eligible_finished_matches"] == 3
    assert result["processed_finished_matches"] == 2
    assert result["pending_finished_matches"] == 1
    assert result["recovery_complete"] is False
    assert result["coverage_ratio"] == pytest.approx(2 / 3)
    assert result["structural_integrity"]["status"] == "FAIL"
    assert result["structural_integrity"]["counters"]["partial_one_row_matches"] == 2
    assert result["structural_integrity"]["counters"]["self_play_matches"] == 1
    assert result["semantic_integrity"]["status"] == "PASS"
    assert result["semantics"] == "recovery_progress_plus_direct_persisted_integrity_gates"


async def test_recovery_health_detects_cross_league_historical_identity_contamination(factory) -> None:
    kickoff = datetime(2026, 8, 2, 15, 0)
    async with factory() as session:
        session.add_all(
            [
                League(id="EPL", name="Premier League", country="England"),
                League(id="CHAMP", name="Championship", country="England"),
                Team(id="epl-home", name="EPL Home", league_id="EPL"),
                Team(id="wrong-away", name="Wrong Away", league_id="CHAMP"),
            ]
        )
        session.add(
            Match(
                id="fdco-semantic-bad",
                league_id="EPL",
                home_team_id="epl-home",
                away_team_id="wrong-away",
                match_date=kickoff,
                status="finished",
                home_score=1,
                away_score=0,
            )
        )
        session.add_all(
            [
                EloRatingSnapshot(
                    match_id="fdco-semantic-bad",
                    team_id="epl-home",
                    pre_match_elo=1500.0,
                    post_match_elo=1510.0,
                    league="EPL",
                    season="2026/2027",
                    match_date=kickoff,
                    created_at=kickoff,
                ),
                EloRatingSnapshot(
                    match_id="fdco-semantic-bad",
                    team_id="wrong-away",
                    pre_match_elo=1500.0,
                    post_match_elo=1490.0,
                    league="EPL",
                    season="2026/2027",
                    match_date=kickoff,
                    created_at=kickoff,
                ),
            ]
        )
        await session.commit()

    async with factory() as session:
        result = await elo_recovery_health(session)

    assert result["recovery_complete"] is True
    assert result["structural_integrity"]["status"] == "PASS"
    assert result["semantic_integrity"]["status"] == "FAIL"
    counters = result["semantic_integrity"]["counters"]
    assert counters["historical_match_home_team_league_mismatch"] == 0
    assert counters["historical_match_away_team_league_mismatch"] == 1
    assert counters["historical_matches_with_semantic_identity_mismatch"] == 1
    assert counters["elo_snapshot_team_league_mismatch"] == 1
