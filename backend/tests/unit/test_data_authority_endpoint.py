"""Release data-authority endpoints must stay read-only and non-secret."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.api.endpoints import data_authority


async def test_postgres_data_authority_exposes_exact_database_and_integrity_state() -> (
    None
):
    db = MagicMock()
    db.get_bind.return_value = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql")
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = "sabiscore_db_v3"
    db.execute = AsyncMock(return_value=result)
    recovery = {
        "authority": "postgres",
        "rows": 25580,
        "eligible_finished_matches": 12790,
        "processed_finished_matches": 12790,
        "pending_finished_matches": 0,
        "recovery_complete": True,
        "coverage_ratio": 1.0,
        "structural_integrity": {"status": "PASS", "counters": {}},
        "semantic_integrity": {"status": "PASS", "counters": {}},
    }

    with patch.object(
        data_authority,
        "elo_recovery_health",
        new=AsyncMock(return_value=recovery),
    ):
        payload = await data_authority.data_authority(db)

    assert payload["read_only"] is True
    assert payload["database"] == {"dialect": "postgresql", "name": "sabiscore_db_v3"}
    assert payload["elo"] == recovery
    assert payload["certification"]["structural_elo"] == "PASS"
    assert payload["certification"]["semantic_identity"] == "PASS"
    assert payload["certification"]["model"] == "NOT_EVALUATED"
    assert payload["certification"]["clv"] == "NOT_EVALUATED"
    assert payload["certification"]["staking"] == "NOT_AUTHORIZED"
    db.execute.assert_awaited_once()
    assert "current_database" in str(db.execute.await_args.args[0]).lower()


async def test_non_postgres_data_authority_never_invents_database_name() -> None:
    db = MagicMock()
    db.get_bind.return_value = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
    db.execute = AsyncMock()

    with patch.object(
        data_authority,
        "elo_recovery_health",
        new=AsyncMock(return_value={"authority": "postgres", "rows": 0}),
    ):
        payload = await data_authority.data_authority(db)

    assert payload["database"] == {"dialect": "sqlite", "name": None}
    assert payload["certification"]["structural_elo"] == "NOT_EVALUATED"
    assert payload["certification"]["semantic_identity"] == "NOT_EVALUATED"
    db.execute.assert_not_awaited()


async def test_semantic_repair_review_exposes_hashes_without_authorizing_mutation() -> (
    None
):
    db = MagicMock()
    db.get_bind.return_value = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql")
    )
    db.execute = AsyncMock()
    db.rollback = AsyncMock()

    entries = (
        SimpleNamespace(
            stored_home_team_id="fdco-team-bundesliga-hamburg",
            stored_home_team_name="Hamburg",
            target_home_team_id="fdco-team-epl-west_ham",
            source_home_team="West Ham",
            stored_away_team_id="epl-opponent-1",
            stored_away_team_name="Opponent One",
            target_away_team_id="epl-opponent-1",
            source_away_team="Opponent One",
        ),
        SimpleNamespace(
            stored_home_team_id="epl-opponent-2",
            stored_home_team_name="Opponent Two",
            target_home_team_id="epl-opponent-2",
            source_home_team="Opponent Two",
            stored_away_team_id="fd-team-la_liga:villarreal_cf",
            stored_away_team_name="Villarreal CF",
            target_away_team_id="fd-team-epl:aston_villa_fc",
            source_away_team="Aston Villa",
        ),
    )
    manifest = SimpleNamespace(
        schema_version=3,
        manifest_sha256="a" * 64,
        summary={
            "affected_matches": 518,
            "source_records_missing": 0,
            "repair_blocked_matches": 0,
            "complete": True,
        },
        proposed_team_creations=(
            SimpleNamespace(
                as_dict=lambda: {
                    "team_id": "fdco-team-epl-west_ham",
                    "team_name": "West Ham",
                    "league_id": "EPL",
                    "participant_references": 1,
                    "source_fixture_ids": ["fdco-match"],
                    "source_evidence_sha256s": ["c" * 64],
                }
            ),
        ),
        entries=entries,
    )
    plan = SimpleNamespace(
        as_dict=lambda *, include_matches: {
            "schema_version": 1,
            "semantic_manifest_sha256": "a" * 64,
            "plan_sha256": "b" * 64,
            "leagues": [
                {
                    "league": "epl",
                    "boundary_utc": "2019-08-10T00:00:00",
                    "finished_matches": 2660,
                    "existing_snapshots_to_replace": 5320,
                    "expected_rebuilt_snapshots": 5320,
                    "match_sequence_sha256": "c" * 64,
                }
            ],
        }
    )

    with (
        patch.object(
            data_authority,
            "build_semantic_identity_repair_manifest",
            new=AsyncMock(return_value=manifest),
        ),
        patch.object(
            data_authority,
            "build_semantic_elo_repair_plan",
            new=AsyncMock(return_value=plan),
        ),
    ):
        payload = await data_authority.semantic_repair_review(db)

    assert payload["read_only"] is True
    assert payload["blocked"] is False
    assert payload["manifest"]["repair_manifest_sha256"] == "a" * 64
    assert payload["replay_plan"]["plan_sha256"] == "b" * 64
    assert payload["authorization"]["review_ready"] is True
    assert payload["authorization"]["production_mutation_authorized"] is False
    assert payload["proposed_team_creations"] == [
        {
            "team_id": "fdco-team-epl-west_ham",
            "team_name": "West Ham",
            "league_id": "EPL",
            "participant_references": 1,
            "source_fixture_ids": ["fdco-match"],
            "source_evidence_sha256s": ["c" * 64],
        }
    ]
    assert payload["proposed_replacements"] == [
        {
            "stored_team_id": "fd-team-la_liga:villarreal_cf",
            "stored_team_name": "Villarreal CF",
            "target_team_id": "fd-team-epl:aston_villa_fc",
            "source_team_name": "Aston Villa",
            "participant_references": 1,
        },
        {
            "stored_team_id": "fdco-team-bundesliga-hamburg",
            "stored_team_name": "Hamburg",
            "target_team_id": "fdco-team-epl-west_ham",
            "source_team_name": "West Ham",
            "participant_references": 1,
        },
    ]
    assert "read only" in str(db.execute.await_args.args[0]).lower()
    db.rollback.assert_awaited_once()


async def test_semantic_repair_review_stays_blocked_when_manifest_is_incomplete() -> (
    None
):
    db = MagicMock()
    db.get_bind.return_value = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql")
    )
    db.execute = AsyncMock()
    db.rollback = AsyncMock()
    manifest = SimpleNamespace(
        schema_version=3,
        manifest_sha256="d" * 64,
        summary={
            "affected_matches": 518,
            "source_records_missing": 1,
            "repair_blocked_matches": 1,
            "complete": False,
        },
        proposed_team_creations=(),
        entries=(),
    )
    plan_builder = AsyncMock()

    with (
        patch.object(
            data_authority,
            "build_semantic_identity_repair_manifest",
            new=AsyncMock(return_value=manifest),
        ),
        patch.object(
            data_authority, "build_semantic_elo_repair_plan", new=plan_builder
        ),
    ):
        payload = await data_authority.semantic_repair_review(db)

    assert payload["blocked"] is True
    assert payload["reason"] == "SEMANTIC_REPAIR_MANIFEST_INCOMPLETE"
    assert payload["replay_plan"] is None
    assert payload["authorization"]["review_ready"] is False
    assert payload["authorization"]["production_mutation_authorized"] is False
    plan_builder.assert_not_awaited()
    db.rollback.assert_awaited_once()


async def test_semantic_repair_review_requires_postgres() -> None:
    db = MagicMock()
    db.get_bind.return_value = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
    db.execute = AsyncMock()
    db.rollback = AsyncMock()

    payload = await data_authority.semantic_repair_review(db)

    assert payload["blocked"] is True
    assert payload["reason"] == "POSTGRES_REQUIRED"
    assert payload["manifest"] is None
    assert payload["proposed_team_creations"] == []
    assert payload["authorization"]["production_mutation_authorized"] is False
    db.execute.assert_not_awaited()
    db.rollback.assert_not_awaited()
