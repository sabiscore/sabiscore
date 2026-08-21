"""Safety regression tests for the historical semantic/Elo repair planner."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, League, Match, Team
from src.services import historical_identity_repair_service
from src.services.historical_identity_repair_manifest_service import (
    ProposedTeamCreation,
)
from src.services.historical_identity_repair_service import (
    LeagueEloReplayPlan,
    ReplayMatchEvidence,
    _apply_identity_manifest,
    _apply_proposed_team_creations,
    _day_boundary,
    _rebuild_league_elo,
    _sequence_hash,
    acquire_semantic_elo_repair_locks,
    apply_semantic_identity_and_rebuild_elo,
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


def _creation() -> ProposedTeamCreation:
    return ProposedTeamCreation(
        team_id="fdco-team-epl-west_ham",
        team_name="West Ham",
        league_id="EPL",
        participant_references=1,
        source_fixture_ids=("fdco-match",),
        source_evidence_sha256s=("a" * 64,),
    )


async def _seed_repair_match(session: AsyncSession) -> None:
    session.add_all(
        [
            League(id="EPL", name="Premier League", country="England"),
            League(id="BUNDESLIGA", name="Bundesliga", country="Germany"),
            Team(id="hamburg", name="Hamburg", league_id="BUNDESLIGA"),
            Team(id="arsenal", name="Arsenal", league_id="EPL"),
        ]
    )
    session.add(
        Match(
            id="fdco-match",
            league_id="EPL",
            home_team_id="hamburg",
            away_team_id="arsenal",
            match_date=datetime(2025, 8, 10),
            season="2025/2026",
            status="finished",
            home_score=1,
            away_score=2,
        )
    )
    await session.commit()


async def test_apply_creates_target_before_updating_match(
    session: AsyncSession,
) -> None:
    await _seed_repair_match(session)
    entry = SimpleNamespace(
        repair_ready=True,
        match_id="fdco-match",
        target_home_team_id="fdco-team-epl-west_ham",
        target_away_team_id="arsenal",
        stored_home_team_id="hamburg",
        stored_away_team_id="arsenal",
        match_league="EPL",
    )
    manifest = SimpleNamespace(
        proposed_team_creations=(_creation(),),
        entries=(entry,),
    )

    created = await _apply_proposed_team_creations(session, manifest)
    repaired = await _apply_identity_manifest(session, manifest)

    assert created == ("fdco-team-epl-west_ham",)
    assert repaired == 1
    team = await session.get(Team, "fdco-team-epl-west_ham")
    match = await session.get(Match, "fdco-match")
    assert team is not None
    assert (team.name, team.league_id) == ("West Ham", "EPL")
    assert match is not None
    assert match.home_team_id == "fdco-team-epl-west_ham"


async def test_apply_rolls_back_team_creation_when_match_precondition_drifts(
    session: AsyncSession,
) -> None:
    await _seed_repair_match(session)
    entry = SimpleNamespace(
        repair_ready=True,
        match_id="fdco-match",
        target_home_team_id="fdco-team-epl-west_ham",
        target_away_team_id="arsenal",
        stored_home_team_id="stale-home-id",
        stored_away_team_id="arsenal",
        match_league="EPL",
    )
    manifest = SimpleNamespace(
        proposed_team_creations=(_creation(),),
        entries=(entry,),
    )

    with pytest.raises(RuntimeError, match="optimistic precondition failed"):
        await _apply_proposed_team_creations(session, manifest)
        await _apply_identity_manifest(session, manifest)
    await session.rollback()

    assert await session.get(Team, "fdco-team-epl-west_ham") is None
    match = await session.get(Match, "fdco-match")
    assert match is not None
    assert match.home_team_id == "hamburg"


async def test_apply_rejects_an_occupied_deterministic_team_id(
    session: AsyncSession,
) -> None:
    await _seed_repair_match(session)
    session.add(
        Team(
            id="fdco-team-epl-west_ham",
            name="Conflicting Identity",
            league_id="EPL",
        )
    )
    await session.commit()
    manifest = SimpleNamespace(
        proposed_team_creations=(_creation(),),
        entries=(),
    )

    with pytest.raises(RuntimeError, match="already exists"):
        await _apply_proposed_team_creations(session, manifest)


async def test_production_locks_cover_teams_matches_and_elo() -> None:
    session = MagicMock()
    session.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    session.execute = AsyncMock()

    await acquire_semantic_elo_repair_locks(session)

    assert session.execute.await_count == 2
    lock_sql = str(session.execute.await_args_list[1].args[0]).lower()
    assert "teams" in lock_sql
    assert "matches" in lock_sql
    assert "elo_rating_snapshots" in lock_sql


async def test_full_apply_creates_updates_and_reports_exact_counts(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_repair_match(session)
    entry = SimpleNamespace(
        repair_ready=True,
        blockers=(),
        match_id="fdco-match",
        target_home_team_id="fdco-team-epl-west_ham",
        target_away_team_id="arsenal",
        stored_home_team_id="hamburg",
        stored_away_team_id="arsenal",
        match_league="EPL",
    )
    manifest = SimpleNamespace(
        manifest_sha256="a" * 64,
        summary={"complete": True},
        proposed_team_creations=(_creation(),),
        entries=(entry,),
    )
    league_plan = SimpleNamespace(league="EPL")
    plan = SimpleNamespace(plan_sha256="b" * 64, leagues=(league_plan,))
    monkeypatch.setattr(
        historical_identity_repair_service,
        "acquire_semantic_elo_repair_locks",
        AsyncMock(),
    )
    monkeypatch.setattr(
        historical_identity_repair_service,
        "build_semantic_identity_repair_manifest",
        AsyncMock(return_value=manifest),
    )
    monkeypatch.setattr(
        historical_identity_repair_service,
        "build_semantic_elo_repair_plan",
        AsyncMock(return_value=plan),
    )
    monkeypatch.setattr(
        historical_identity_repair_service,
        "audit_historical_semantic_identity",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        historical_identity_repair_service,
        "_rebuild_league_elo",
        AsyncMock(return_value=(7, 14)),
    )

    result = await apply_semantic_identity_and_rebuild_elo(
        session,
        expected_manifest_sha256="a" * 64,
        expected_plan_sha256="b" * 64,
    )

    assert result.created_team_ids == ("fdco-team-epl-west_ham",)
    assert result.repaired_matches == 1
    assert result.rebuilt_matches == 7
    assert result.rebuilt_snapshots == 14
    assert result.leagues == ("EPL",)


async def test_full_apply_rejects_manifest_hash_drift_before_writes(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_repair_match(session)
    manifest = SimpleNamespace(
        manifest_sha256="f" * 64,
        summary={"complete": True},
        proposed_team_creations=(_creation(),),
        entries=(),
    )
    monkeypatch.setattr(
        historical_identity_repair_service,
        "acquire_semantic_elo_repair_locks",
        AsyncMock(),
    )
    monkeypatch.setattr(
        historical_identity_repair_service,
        "build_semantic_identity_repair_manifest",
        AsyncMock(return_value=manifest),
    )

    with pytest.raises(RuntimeError, match="manifest changed since review"):
        await apply_semantic_identity_and_rebuild_elo(
            session,
            expected_manifest_sha256="a" * 64,
            expected_plan_sha256="b" * 64,
        )

    assert await session.get(Team, "fdco-team-epl-west_ham") is None


async def test_rebuild_replays_and_validates_two_snapshots_per_match(
    session: AsyncSession,
) -> None:
    session.add(League(id="EPL", name="Premier League", country="England"))
    session.add_all(
        [
            Team(id="west-ham", name="West Ham", league_id="EPL"),
            Team(id="arsenal", name="Arsenal", league_id="EPL"),
        ]
    )
    match = Match(
        id="fdco-replay-match",
        league_id="EPL",
        home_team_id="west-ham",
        away_team_id="arsenal",
        match_date=datetime(2025, 8, 10, 15, 0),
        season="2025/2026",
        status="finished",
        home_score=1,
        away_score=2,
    )
    session.add(match)
    await session.commit()
    evidence = ReplayMatchEvidence(
        match_id=match.id,
        league="EPL",
        match_date=match.match_date.isoformat(),
        home_team_id=match.home_team_id,
        away_team_id=match.away_team_id,
        home_score=1,
        away_score=2,
    )
    plan = LeagueEloReplayPlan(
        league="EPL",
        boundary_utc="2025-08-10T00:00:00",
        finished_matches=1,
        existing_snapshots_to_replace=0,
        expected_rebuilt_snapshots=2,
        match_sequence_sha256=_sequence_hash((evidence,)),
        matches=(evidence,),
    )

    rebuilt, snapshots = await _rebuild_league_elo(session, plan)

    assert rebuilt == 1
    assert snapshots == 2


def test_day_boundary_rewinds_to_start_of_earliest_affected_day() -> None:
    value = datetime(2019, 8, 10, 15, 37, 42, 1234)
    assert _day_boundary(value) == datetime(2019, 8, 10, 0, 0)


def test_replay_match_sequence_hash_is_order_sensitive_and_deterministic() -> None:
    first = ReplayMatchEvidence(
        match_id="m-1",
        league="EPL",
        match_date="2019-08-10T15:00:00",
        home_team_id="west-ham",
        away_team_id="city",
        home_score=0,
        away_score=5,
    )
    second = ReplayMatchEvidence(
        match_id="m-2",
        league="EPL",
        match_date="2019-08-11T15:00:00",
        home_team_id="united",
        away_team_id="chelsea",
        home_score=4,
        away_score=0,
    )
    assert _sequence_hash((first, second)) == _sequence_hash((first, second))
    assert _sequence_hash((first, second)) != _sequence_hash((second, first))


def test_sequence_hash_changes_when_corrected_identity_changes() -> None:
    good = ReplayMatchEvidence(
        match_id="m-1",
        league="EPL",
        match_date="2019-08-10T15:00:00",
        home_team_id="west-ham",
        away_team_id="city",
        home_score=0,
        away_score=5,
    )
    contaminated = ReplayMatchEvidence(
        match_id="m-1",
        league="EPL",
        match_date="2019-08-10T15:00:00",
        home_team_id="hamburg",
        away_team_id="city",
        home_score=0,
        away_score=5,
    )
    assert _sequence_hash((good,)) != _sequence_hash((contaminated,))


def test_apply_cli_requires_literal_confirmation() -> None:
    from scripts.repair_semantic_identity_and_rebuild_elo import _CONFIRMATION

    assert _CONFIRMATION == "APPLY_SEMANTIC_IDENTITY_AND_REBUILD_ELO"


@pytest.mark.parametrize(
    "value",
    ["", "abc", "g" * 64, "0" * 63, "0" * 65],
)
def test_apply_cli_rejects_invalid_hashes(value: str) -> None:
    from scripts.repair_semantic_identity_and_rebuild_elo import _validate_sha256

    with pytest.raises(ValueError):
        _validate_sha256(value, field="--manifest-sha256")


def test_apply_cli_accepts_sha256_case_insensitively() -> None:
    from scripts.repair_semantic_identity_and_rebuild_elo import _validate_sha256

    assert _validate_sha256("A" * 64, field="--plan-sha256") == "a" * 64
