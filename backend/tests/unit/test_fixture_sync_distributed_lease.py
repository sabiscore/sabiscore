"""Cross-instance fixture-sync lease regressions.

Render can overlap old/live and candidate instances during deploys. These tests
pin the invariant that only one production process may spend the shared
football-data.org quota in a recent execution window.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from redis.exceptions import RedisError

from src.core.cache import cache
from src.services import fixture_sync_service as service


async def test_production_without_external_redis_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(service.settings, "app_env", "production")
    monkeypatch.setattr(cache, "redis_client", None)

    acquired, token = await service._claim_fixture_sync_lease()

    assert acquired is False
    assert token is None


async def test_nonproduction_without_external_redis_preserves_local_flow(monkeypatch) -> None:
    monkeypatch.setattr(service.settings, "app_env", "test")
    monkeypatch.setattr(cache, "redis_client", None)

    acquired, token = await service._claim_fixture_sync_lease()

    assert acquired is True
    assert token is None


async def test_recent_completion_marker_suppresses_duplicate_candidate(monkeypatch) -> None:
    monkeypatch.setattr(service.settings, "app_env", "production")
    client = MagicMock()
    client.get.return_value = b"completed-by-sibling"
    monkeypatch.setattr(cache, "redis_client", client)

    acquired, token = await service._claim_fixture_sync_lease()

    assert acquired is False
    assert token is None
    client.set.assert_not_called()


async def test_first_candidate_claims_token_owned_lease(monkeypatch) -> None:
    monkeypatch.setattr(service.settings, "app_env", "production")
    client = MagicMock()
    client.get.return_value = None
    client.set.return_value = True
    monkeypatch.setattr(cache, "redis_client", client)

    acquired, token = await service._claim_fixture_sync_lease()

    assert acquired is True
    assert token
    client.set.assert_called_once_with(
        service._FIXTURE_SYNC_LEASE_KEY,
        token,
        nx=True,
        ex=service._FIXTURE_SYNC_LEASE_TTL_SECONDS,
    )


async def test_held_lease_times_out_without_duplicate_provider_pass(monkeypatch) -> None:
    monkeypatch.setattr(service.settings, "app_env", "production")
    monkeypatch.setattr(service, "_FIXTURE_SYNC_LEASE_WAIT_SECONDS", 0)
    client = MagicMock()
    client.get.return_value = None
    client.set.return_value = False
    monkeypatch.setattr(cache, "redis_client", client)

    acquired, token = await service._claim_fixture_sync_lease()

    assert acquired is False
    assert token is None


async def test_redis_error_fails_closed_in_production(monkeypatch) -> None:
    monkeypatch.setattr(service.settings, "app_env", "production")
    client = MagicMock()
    client.get.side_effect = RedisError("redis unavailable")
    monkeypatch.setattr(cache, "redis_client", client)

    acquired, token = await service._claim_fixture_sync_lease()

    assert acquired is False
    assert token is None


async def test_success_marks_completion_before_token_safe_release(monkeypatch) -> None:
    client = MagicMock()
    monkeypatch.setattr(cache, "redis_client", client)

    await service._finish_fixture_sync_lease("owner-token", completed=True)

    client.setex.assert_called_once_with(
        service._FIXTURE_SYNC_COMPLETED_KEY,
        service._FIXTURE_SYNC_COMPLETED_TTL_SECONDS,
        "owner-token",
    )
    client.eval.assert_called_once_with(
        service._RELEASE_LEASE_SCRIPT,
        1,
        service._FIXTURE_SYNC_LEASE_KEY,
        "owner-token",
    )


async def test_completion_marker_failure_retains_lease_until_ttl(monkeypatch) -> None:
    client = MagicMock()
    client.setex.side_effect = RedisError("marker write failed")
    monkeypatch.setattr(cache, "redis_client", client)

    await service._finish_fixture_sync_lease("owner-token", completed=True)

    client.eval.assert_not_called()


async def test_failed_pass_releases_lease_for_retry(monkeypatch) -> None:
    client = MagicMock()
    monkeypatch.setattr(cache, "redis_client", client)

    await service._finish_fixture_sync_lease("owner-token", completed=False)

    client.setex.assert_not_called()
    client.eval.assert_called_once()


async def test_run_fixture_sync_never_opens_db_when_sibling_owns_window() -> None:
    factory = MagicMock()
    with (
        patch("src.db.session.AsyncSessionLocal", factory),
        patch.object(
            service,
            "_claim_fixture_sync_lease",
            new=AsyncMock(return_value=(False, None)),
        ),
    ):
        await service.run_fixture_sync()

    factory.assert_not_called()
