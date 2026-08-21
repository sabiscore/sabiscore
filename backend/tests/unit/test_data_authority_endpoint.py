"""Release data-authority endpoints must stay read-only and non-secret."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.api.endpoints import data_authority


async def test_postgres_data_authority_exposes_exact_database_and_integrity_state() -> None:
    db = MagicMock()
    db.get_bind.return_value = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
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


async def test_semantic_repair_manifest_exposes_hash_and_gate_without_entries() -> None:
    db = MagicMock()
    manifest = SimpleNamespace(
        schema_version=2,
        manifest_sha256="a" * 64,
        summary={
            "affected_matches": 518,
            "repair_ready_matches": 518,
            "repair_blocked_matches": 0,
            "source_records_found": 518,
            "source_records_missing": 0,
            "source_evidence_hashed": 518,
            "replay_required_matches": 518,
            "blocker_counts": {},
            "first_affected_match": "2019-08-10T00:00:00",
            "last_affected_match": "2026-05-24T00:00:00",
            "complete": True,
        },
        entries=(object(),),
    )

    with patch.object(
        data_authority,
        "build_semantic_identity_repair_manifest",
        new=AsyncMock(return_value=manifest),
    ) as builder:
        payload = await data_authority.semantic_repair_manifest(db)

    builder.assert_awaited_once_with(db)
    assert payload["read_only"] is True
    assert payload["manifest_schema_version"] == 2
    assert payload["repair_manifest_sha256"] == "a" * 64
    assert payload["summary"]["affected_matches"] == 518
    assert payload["authorization_ready"] is True
    assert payload["production_mutation_authorized"] is False
    assert "entries" not in payload


async def test_semantic_repair_manifest_fails_authorization_gate_when_blocked() -> None:
    db = MagicMock()
    manifest = SimpleNamespace(
        schema_version=2,
        manifest_sha256="b" * 64,
        summary={
            "affected_matches": 518,
            "repair_ready_matches": 517,
            "repair_blocked_matches": 1,
            "source_records_missing": 0,
            "complete": False,
        },
    )

    with patch.object(
        data_authority,
        "build_semantic_identity_repair_manifest",
        new=AsyncMock(return_value=manifest),
    ):
        payload = await data_authority.semantic_repair_manifest(db)

    assert payload["authorization_ready"] is False
    assert payload["production_mutation_authorized"] is False
