"""Regression coverage for the source-backed semantic identity repair manifest."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, League, Match, Team
from src.services.historical_backfill_service import historical_match_id
from src.services.historical_identity_repair_manifest_service import (
    build_semantic_identity_repair_manifest,
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


async def _seed_common(session: AsyncSession) -> tuple[str, str]:
    session.add_all(
        [
            League(id="EPL", name="Premier League", country="England"),
            League(id="BUNDESLIGA", name="Bundesliga", country="Germany"),
            League(id="LA_LIGA", name="La Liga", country="Spain"),
            Team(id="hamburg", name="Hamburg", league_id="BUNDESLIGA"),
            Team(id="villarreal", name="Villarreal CF", league_id="LA_LIGA"),
            Team(id="west-ham", name="West Ham", league_id="EPL"),
            Team(id="arsenal", name="Arsenal", league_id="EPL"),
            Team(id="chelsea", name="Chelsea", league_id="EPL"),
            Team(id="aston-villa", name="Aston Villa", league_id="EPL"),
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
    return west_ham_match_id, villa_match_id


async def test_manifest_resolves_known_residuals_and_is_hash_stable(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    _write_epl_source(tmp_path)
    west_ham_match_id, villa_match_id = await _seed_common(session)

    first = await build_semantic_identity_repair_manifest(session, cache_dir=tmp_path)
    second = await build_semantic_identity_repair_manifest(session, cache_dir=tmp_path)

    assert first.schema_version == 3
    assert first.manifest_sha256 == second.manifest_sha256
    assert len(first.manifest_sha256) == 64
    assert first.summary["affected_matches"] == 2
    assert first.summary["repair_ready_matches"] == 2
    assert first.summary["repair_blocked_matches"] == 0
    assert first.summary["source_records_missing"] == 0
    assert first.summary["source_evidence_hashed"] == 2
    assert first.summary["replay_required_matches"] == 2
    assert first.summary["proposed_team_creations"] == 0
    assert first.summary["proposed_team_creation_references"] == 0
    assert first.summary["complete"] is True
    assert first.proposed_team_creations == ()

    by_id = {entry.match_id: entry for entry in first.entries}
    west_ham = by_id[west_ham_match_id]
    assert west_ham.repair_ready is True
    assert west_ham.repair_status == "READY"
    assert west_ham.blocking_reason is None
    assert west_ham.target_home_team_id == "west-ham"
    assert west_ham.target_away_team_id == "arsenal"
    assert west_ham.source_fixture_id == west_ham_match_id
    assert west_ham.source_evidence_sha256 is not None
    assert len(west_ham.source_evidence_sha256) == 64
    assert (
        west_ham.source_evidence_sha256
        == by_id[west_ham_match_id].source_evidence_sha256
    )
    assert west_ham.repair_reason == "home_cross_league_identity"
    assert west_ham.replay_required is True
    assert west_ham.blockers == ()

    villa = by_id[villa_match_id]
    assert villa.repair_ready is True
    assert villa.repair_status == "READY"
    assert villa.target_home_team_id == "chelsea"
    assert villa.target_away_team_id == "aston-villa"
    assert villa.source_fixture_id == villa_match_id
    assert villa.source_evidence_sha256 is not None
    assert villa.repair_reason == "away_cross_league_identity"
    assert villa.replay_required is True


async def test_manifest_blocks_when_persisted_score_disagrees_with_source(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    _write_epl_source(tmp_path)
    west_ham_match_id, _ = await _seed_common(session)

    match = await session.get(Match, west_ham_match_id)
    assert match is not None
    match.home_score = 9
    await session.commit()

    manifest = await build_semantic_identity_repair_manifest(
        session, cache_dir=tmp_path
    )
    entry = {row.match_id: row for row in manifest.entries}[west_ham_match_id]

    assert entry.repair_ready is False
    assert entry.repair_status == "BLOCKED"
    assert entry.blocking_reason is not None
    assert "source_score_mismatch" in entry.blockers
    assert "source_score_mismatch" in entry.blocking_reason
    assert entry.source_evidence_sha256 is not None
    assert entry.replay_required is True
    assert manifest.summary["complete"] is False


async def test_manifest_proposes_missing_cross_league_target_deterministically(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    _write_epl_source(tmp_path)
    west_ham_match_id, _ = await _seed_common(session)

    west_ham = await session.get(Team, "west-ham")
    assert west_ham is not None
    await session.delete(west_ham)
    await session.commit()

    manifest = await build_semantic_identity_repair_manifest(
        session, cache_dir=tmp_path
    )
    entry = {row.match_id: row for row in manifest.entries}[west_ham_match_id]

    assert entry.repair_ready is True
    assert entry.repair_status == "READY"
    assert entry.target_home_team_id == "fdco-team-epl-west_ham"
    assert entry.blockers == ()
    assert entry.source_evidence_sha256 is not None
    assert manifest.summary["proposed_team_creations"] == 1
    assert manifest.summary["proposed_team_creation_references"] == 1
    proposal = manifest.proposed_team_creations[0]
    assert proposal.team_id == "fdco-team-epl-west_ham"
    assert proposal.team_name == "West Ham"
    assert proposal.league_id == "EPL"
    assert proposal.participant_references == 1
    assert proposal.source_fixture_ids == (west_ham_match_id,)
    assert proposal.source_evidence_sha256s == (entry.source_evidence_sha256,)


async def test_manifest_does_not_create_an_unaffected_unresolved_opponent(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    _write_epl_source(tmp_path)
    west_ham_match_id, _ = await _seed_common(session)

    arsenal = await session.get(Team, "arsenal")
    assert arsenal is not None
    await session.delete(arsenal)
    await session.commit()

    manifest = await build_semantic_identity_repair_manifest(
        session, cache_dir=tmp_path
    )
    entry = {row.match_id: row for row in manifest.entries}[west_ham_match_id]

    assert entry.repair_ready is False
    assert entry.target_away_team_id is None
    assert "target_away_unresolved" in entry.blockers
    assert manifest.proposed_team_creations == ()


async def test_manifest_blocks_a_conflicting_deterministic_team_id(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    _write_epl_source(tmp_path)
    west_ham_match_id, _ = await _seed_common(session)

    west_ham = await session.get(Team, "west-ham")
    assert west_ham is not None
    await session.delete(west_ham)
    session.add(
        Team(
            id="fdco-team-epl-west_ham",
            name="Conflicting Identity",
            league_id="EPL",
        )
    )
    await session.commit()

    manifest = await build_semantic_identity_repair_manifest(
        session, cache_dir=tmp_path
    )
    entry = {row.match_id: row for row in manifest.entries}[west_ham_match_id]

    assert entry.repair_ready is False
    assert "target_home_unresolved" in entry.blockers
    assert "proposed_team_id_conflict" in entry.blockers
    assert manifest.proposed_team_creations == ()


async def test_manifest_hash_changes_when_team_creation_enters_authorization(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    _write_epl_source(tmp_path)
    await _seed_common(session)
    without_creation = await build_semantic_identity_repair_manifest(
        session, cache_dir=tmp_path
    )

    west_ham = await session.get(Team, "west-ham")
    assert west_ham is not None
    await session.delete(west_ham)
    await session.commit()
    with_creation = await build_semantic_identity_repair_manifest(
        session, cache_dir=tmp_path
    )

    assert without_creation.manifest_sha256 != with_creation.manifest_sha256
    assert with_creation.summary["complete"] is True


async def test_manifest_is_read_only(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    _write_epl_source(tmp_path)
    west_ham_match_id, _ = await _seed_common(session)

    before = await session.get(Match, west_ham_match_id)
    assert before is not None
    stored_home = before.home_team_id

    manifest = await build_semantic_identity_repair_manifest(
        session, cache_dir=tmp_path
    )
    assert manifest.summary["repair_ready_matches"] == 2

    session.expire_all()
    after = await session.get(Match, west_ham_match_id)
    assert after is not None
    assert after.home_team_id == stored_home == "hamburg"
