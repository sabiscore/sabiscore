"""Release data-authority endpoint must stay read-only and non-secret."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.api.endpoints import data_authority


async def test_postgres_data_authority_exposes_exact_database_and_recovery_state() -> None:
    db = MagicMock()
    db.get_bind.return_value = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    result = MagicMock()
    result.scalar_one_or_none.return_value = "sabiscore_db_v3"
    db.execute = AsyncMock(return_value=result)
    recovery = {
        "authority": "postgres",
        "rows": 3000,
        "eligible_finished_matches": 12765,
        "processed_finished_matches": 1500,
        "pending_finished_matches": 11265,
        "recovery_complete": False,
        "coverage_ratio": 1500 / 12765,
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
    assert payload["certification"]["semantic_identity"] == "NOT_EVALUATED"
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
    db.execute.assert_not_awaited()
