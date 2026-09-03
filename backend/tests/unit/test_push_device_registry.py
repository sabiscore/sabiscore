"""Unit tests for the WEB_PUSH device registry — service layer and endpoints.

Contracts verified:
  1. `register_push_device` upserts on `endpoint`. A browser that re-subscribes
     after a permission reset must overwrite its stored keys in place; inserting
     would leave a row whose keys no longer decrypt and every send to it would
     fail forever.
  2. `get_active_push_devices` refuses to answer without an owner. An unscoped
     query there would hand one person's alert to every registered browser.
  3. `unregister_push_device` deactivates rather than deletes, so a re-subscribe
     to the same endpoint reuses one row instead of churning the unique index.
  4. The endpoints fail closed while the channel is unconfigured, and report the
     VAPID key as absent rather than fabricating one.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.api.main import app
from src.core.config import settings
from src.core.database import Base
from src.db import models as _db_models  # noqa: F401  (registers the mappers)
from src.db.models import PushDevice
from src.db.session import get_async_session
from src.services.notification_service import NotificationService


# ponytail: SQLite silently discards tzinfo on a plain (non-timezone-aware)
# DateTime column round-trip — verified empirically (a tz-aware insert reads
# back with tzinfo=None). This suite therefore CANNOT catch a naive/aware
# datetime bug on PushDevice/UserNotificationLog writes: asyncpg raises at
# bind time in production, SQLite here just silently normalizes it away.
# Do not read a green run here as proof those writes are tz-safe.
# See docs/DEBT.md item 55, residual 1.
@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def configured_vapid(monkeypatch):
    monkeypatch.setattr(settings, "enable_web_push_notifications", True)
    monkeypatch.setattr(settings, "vapid_public_key", "BPublicKeyForTests")
    monkeypatch.setattr(settings, "vapid_private_key", "cHJpdmF0ZQ")
    monkeypatch.setattr(settings, "vapid_claims_sub", "mailto:ops@sabiscore.com")


# ── Service layer ─────────────────────────────────────────────────────────────


async def test_register_creates_a_device(session: AsyncSession) -> None:
    device = await NotificationService.register_push_device(
        session,
        user_id="user-1",
        endpoint="https://push.example/a",
        p256dh="key-a",
        auth="auth-a",
        user_agent="pytest",
    )

    assert device.user_id == "user-1"
    assert device.is_active is True
    assert device.anonymous_session_id is None
    rows = (await session.execute(select(PushDevice))).scalars().all()
    assert len(rows) == 1


async def test_register_upserts_on_endpoint_rather_than_duplicating(
    session: AsyncSession,
) -> None:
    """The push service treats the endpoint as the device identity. A second row
    for the same endpoint would carry keys that no longer decrypt."""
    first = await NotificationService.register_push_device(
        session,
        user_id="user-1",
        endpoint="https://push.example/a",
        p256dh="old-key",
        auth="old-auth",
    )
    second = await NotificationService.register_push_device(
        session,
        user_id="user-1",
        endpoint="https://push.example/a",
        p256dh="rotated-key",
        auth="rotated-auth",
    )

    assert second.id == first.id
    assert second.p256dh == "rotated-key"
    assert second.auth == "rotated-auth"
    rows = (await session.execute(select(PushDevice))).scalars().all()
    assert len(rows) == 1


async def test_re_registering_reactivates_a_deactivated_device(
    session: AsyncSession,
) -> None:
    await NotificationService.register_push_device(
        session, user_id="user-1", endpoint="https://push.example/a", p256dh="k", auth="a"
    )
    await NotificationService.unregister_push_device(session, endpoint="https://push.example/a")

    revived = await NotificationService.register_push_device(
        session, user_id="user-1", endpoint="https://push.example/a", p256dh="k2", auth="a2"
    )
    assert revived.is_active is True


async def test_anonymous_registration_never_carries_both_identities(
    session: AsyncSession,
) -> None:
    device = await NotificationService.register_push_device(
        session,
        anonymous_session_id="anon-9",
        endpoint="https://push.example/anon",
        p256dh="k",
        auth="a",
    )
    assert device.anonymous_session_id == "anon-9"
    assert device.user_id is None


async def test_unregister_deactivates_without_deleting(session: AsyncSession) -> None:
    await NotificationService.register_push_device(
        session, user_id="user-1", endpoint="https://push.example/a", p256dh="k", auth="a"
    )

    assert await NotificationService.unregister_push_device(
        session, endpoint="https://push.example/a"
    )
    rows = (await session.execute(select(PushDevice))).scalars().all()
    assert len(rows) == 1
    assert rows[0].is_active is False


async def test_unregister_unknown_endpoint_reports_not_found(session: AsyncSession) -> None:
    assert (
        await NotificationService.unregister_push_device(session, endpoint="https://nope")
        is False
    )


async def test_active_devices_are_scoped_to_their_owner(session: AsyncSession) -> None:
    await NotificationService.register_push_device(
        session, user_id="user-1", endpoint="https://push.example/mine", p256dh="k", auth="a"
    )
    await NotificationService.register_push_device(
        session, user_id="user-2", endpoint="https://push.example/theirs", p256dh="k", auth="a"
    )
    await NotificationService.register_push_device(
        session, anonymous_session_id="anon-9", endpoint="https://push.example/anon", p256dh="k", auth="a"
    )
    await NotificationService.unregister_push_device(session, endpoint="https://push.example/mine")
    await NotificationService.register_push_device(
        session, user_id="user-1", endpoint="https://push.example/live", p256dh="k", auth="a"
    )

    mine = await NotificationService.get_active_push_devices(session, user_id="user-1")
    assert [d.endpoint for d in mine] == ["https://push.example/live"]

    anon = await NotificationService.get_active_push_devices(
        session, anonymous_session_id="anon-9"
    )
    assert [d.endpoint for d in anon] == ["https://push.example/anon"]


async def test_active_devices_without_an_owner_returns_nothing(session: AsyncSession) -> None:
    """The safety property: no identifier means no query, not every row."""
    await NotificationService.register_push_device(
        session, user_id="user-1", endpoint="https://push.example/a", p256dh="k", auth="a"
    )
    assert await NotificationService.get_active_push_devices(session) == []


async def test_mark_expired_deactivates_a_single_device(session: AsyncSession) -> None:
    device = await NotificationService.register_push_device(
        session, user_id="user-1", endpoint="https://push.example/gone", p256dh="k", auth="a"
    )
    keep = await NotificationService.register_push_device(
        session, user_id="user-1", endpoint="https://push.example/keep", p256dh="k", auth="a"
    )

    await NotificationService.mark_push_device_expired(session, device_id=device.id)
    await session.commit()

    await session.refresh(device)
    await session.refresh(keep)
    assert device.is_active is False
    assert keep.is_active is True


# ── Endpoints ─────────────────────────────────────────────────────────────────


async def _client(session: AsyncSession):
    app.dependency_overrides[get_async_session] = lambda: session
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_public_key_endpoint_reports_unconfigured(session: AsyncSession, monkeypatch) -> None:
    monkeypatch.setattr(settings, "enable_web_push_notifications", False)
    try:
        async with await _client(session) as client:
            response = await client.get("/api/v1/notifications/push/public-key")
        assert response.status_code == 200
        # Never a fabricated key — the browser must not attempt a subscription
        # that could not be delivered to.
        assert response.json() == {"configured": False, "public_key": None}
    finally:
        app.dependency_overrides.pop(get_async_session, None)


async def test_public_key_endpoint_serves_the_key_when_configured(
    session: AsyncSession, configured_vapid
) -> None:
    try:
        async with await _client(session) as client:
            response = await client.get("/api/v1/notifications/push/public-key")
        assert response.json() == {"configured": True, "public_key": "BPublicKeyForTests"}
    finally:
        app.dependency_overrides.pop(get_async_session, None)


async def test_register_endpoint_persists_the_browser_subscription_shape(
    session: AsyncSession, configured_vapid
) -> None:
    try:
        async with await _client(session) as client:
            response = await client.post(
                "/api/v1/notifications/push/devices",
                json={
                    "endpoint": "https://push.example/browser",
                    "keys": {"p256dh": "p-key", "auth": "a-key"},
                },
                headers={"X-Anonymous-Session": "anon-42"},
            )
        assert response.status_code == 201
        body = response.json()
        assert body["endpoint"] == "https://push.example/browser"
        assert body["is_active"] is True

        rows = (await session.execute(select(PushDevice))).scalars().all()
        assert len(rows) == 1
        assert rows[0].p256dh == "p-key"
        assert rows[0].auth == "a-key"
    finally:
        app.dependency_overrides.pop(get_async_session, None)


async def test_register_endpoint_is_unavailable_while_unconfigured(
    session: AsyncSession, monkeypatch
) -> None:
    """Fails closed: storing a device for a deployment that cannot send would
    leave a subscription that never delivers and never explains why."""
    monkeypatch.setattr(settings, "enable_web_push_notifications", False)
    try:
        async with await _client(session) as client:
            response = await client.post(
                "/api/v1/notifications/push/devices",
                json={
                    "endpoint": "https://push.example/browser",
                    "keys": {"p256dh": "p", "auth": "a"},
                },
            )
        assert response.status_code == 503
        assert (await session.execute(select(PushDevice))).scalars().all() == []
    finally:
        app.dependency_overrides.pop(get_async_session, None)


async def test_register_endpoint_rejects_a_payload_missing_key_material(
    session: AsyncSession, configured_vapid
) -> None:
    try:
        async with await _client(session) as client:
            response = await client.post(
                "/api/v1/notifications/push/devices",
                json={"endpoint": "https://push.example/browser"},
            )
        assert response.status_code == 422
    finally:
        app.dependency_overrides.pop(get_async_session, None)


async def test_unregister_endpoint_deactivates_then_reports_not_found(
    session: AsyncSession, configured_vapid
) -> None:
    await NotificationService.register_push_device(
        session, user_id="user-1", endpoint="https://push.example/x", p256dh="k", auth="a"
    )
    try:
        async with await _client(session) as client:
            first = await client.request(
                "DELETE",
                "/api/v1/notifications/push/devices",
                json={"endpoint": "https://push.example/x"},
            )
            second = await client.request(
                "DELETE",
                "/api/v1/notifications/push/devices",
                json={"endpoint": "https://push.example/never-seen"},
            )
        assert first.json() == {"status": "UNREGISTERED"}
        assert second.json() == {"status": "NOT_FOUND"}
    finally:
        app.dependency_overrides.pop(get_async_session, None)
