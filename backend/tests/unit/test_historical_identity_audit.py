"""Regression coverage for the read-only historical semantic identity audit."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, League, Match, Team
from src.services.historical_backfill_service import historical_match_id
from src.services.historical_identity_audit_service import (
    audit_historical_semantic_identity,
    build_historical_source_index,
    summarize_semantic_identity_findings,
)


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as value:
        yield value
    await engine.dispose()


def _write_epl_source(cache_dir: Path) -> None:
    (cache_dir / "fd_E0_2526.csv").write_text(
        "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG\n"
        "E0,10/08/2025,West Ham,Arsenal,1,2\n"
        "E0,17/08/2025,Chelsea,Aston Villa,0,1\n",
        encoding="utf-8",
    )


async def _seed_leagues(session: AsyncSession) -> None:
    session.add_all(
        [
            League(id="EPL", name="Premier League", country="England"),
            League(id="BUNDESLIGA", name="Bundesliga", country="Germany"),
            League(id="LA_LIGA", name="La Liga", country="Spain"),
        ]
    )
    await session.flush()


def test_source_index_uses_production_deterministic_ids(tmp_path: Path) -> None:
    _write_epl_source(tmp_path)
    index = build_historical_source_index(tmp_path)

    west_ham_id = historical_match_id(
        "EPL", datetime(2025, 8, 10), "West Ham", "Arsenal"
    )
    villa_id = historical_match_id(
        "EPL", datetime(2025, 8, 17), "Chelsea", "Aston Villa"
    )
    assert index[west_ham_id].home_team == "West Ham"
    assert index[west_ham_id].source_file == "fd_E0_2526.csv"
    assert index[villa_id].away_team == "Aston Villa"


async def test_audit_attaches_source_to_hamburg_and_villarreal_residuals(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    _write_epl_source(tmp_path)
    await _seed_leagues(session)
    session.add_all(
        [
            Team(id="hamburg", name="Hamburg", league_id="BUNDESLIGA"),
            Team(id="villarreal", name="Villarreal CF", league_id="LA_LIGA"),
            Team(id="arsenal", name="Arsenal", league_id="EPL"),
            Team(id="chelsea", name="Chelsea", league_id="EPL"),
        ]
    )
    await session.flush()

    west_ham_match_id = historical_match_id(
        "EPL", datetime(2025, 8, 10), "West Ham", "Arsenal"
    )
    villa_match_id = historical_match_id(
        "EPL", datetime(2025, 8, 17), "Chelsea", "Aston Villa"
    )
    session.add_all(
        [
            Match(
                id=west_ham_match_id,
                league_id="EPL",
                home_team_id="hamburg",
                away_team_id="arsenal",
                match_date=datetime(2025, 8, 10),
                season="2025/2026",
                status="finished",
                home_score=1,
                away_score=2,
            ),
            Match(
                id=villa_match_id,
                league_id="EPL",
                home_team_id="chelsea",
                away_team_id="villarreal",
                match_date=datetime(2025, 8, 17),
                season="2025/2026",
                status="finished",
                home_score=0,
                away_score=1,
            ),
        ]
    )
    await session.commit()

    findings = await audit_historical_semantic_identity(session, cache_dir=tmp_path)
    assert len(findings) == 2
    by_id = {finding.match_id: finding for finding in findings}

    west_ham = by_id[west_ham_match_id]
    assert west_ham.home_league_mismatch is True
    assert west_ham.away_league_mismatch is False
    assert west_ham.source_record_found is True
    assert west_ham.source_home_team == "West Ham"
    assert west_ham.stored_home_team_name == "Hamburg"

    villa = by_id[villa_match_id]
    assert villa.home_league_mismatch is False
    assert villa.away_league_mismatch is True
    assert villa.source_record_found is True
    assert villa.source_away_team == "Aston Villa"
    assert villa.stored_away_team_name == "Villarreal CF"

    assert summarize_semantic_identity_findings(findings) == {
        "affected_matches": 2,
        "home_league_mismatches": 1,
        "away_league_mismatches": 1,
        "source_records_found": 2,
        "source_records_missing": 0,
        "first_affected_match": "2025-08-10T00:00:00",
        "last_affected_match": "2025-08-17T00:00:00",
    }


async def test_same_league_historical_identity_is_not_a_finding(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    _write_epl_source(tmp_path)
    await _seed_leagues(session)
    session.add_all(
        [
            Team(id="west-ham", name="West Ham", league_id="EPL"),
            Team(id="arsenal", name="Arsenal", league_id="EPL"),
        ]
    )
    session.add(
        Match(
            id=historical_match_id(
                "EPL", datetime(2025, 8, 10), "West Ham", "Arsenal"
            ),
            league_id="EPL",
            home_team_id="west-ham",
            away_team_id="arsenal",
            match_date=datetime(2025, 8, 10),
            season="2025/2026",
            status="finished",
            home_score=1,
            away_score=2,
        )
    )
    await session.commit()

    assert await audit_historical_semantic_identity(session, cache_dir=tmp_path) == []


async def test_missing_source_record_remains_explicit_in_manifest(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    _write_epl_source(tmp_path)
    await _seed_leagues(session)
    session.add_all(
        [
            Team(id="foreign", name="Foreign Club", league_id="LA_LIGA"),
            Team(id="arsenal", name="Arsenal", league_id="EPL"),
        ]
    )
    session.add(
        Match(
            id="fdco-source-missing",
            league_id="EPL",
            home_team_id="foreign",
            away_team_id="arsenal",
            match_date=datetime(2025, 9, 1),
            season="2025/2026",
            status="finished",
            home_score=0,
            away_score=0,
        )
    )
    await session.commit()

    findings = await audit_historical_semantic_identity(session, cache_dir=tmp_path)
    assert len(findings) == 1
    assert findings[0].source_record_found is False
    assert findings[0].source_home_team is None
    assert summarize_semantic_identity_findings(findings)["source_records_missing"] == 1
