"""Unit tests for notification_dispatch_service (kickoff reminders + probability
swing alerts).

Contracts verified:
  1. Kickoff reminder fires only inside its due window (reminder_minutes_before
     before kickoff, up to kickoff itself).
  2. Probability-swing alert fires only when the delta between the two most
     recent MatchPredictionLog snapshots meets/exceeds threshold_pct.
  3. Idempotency — a repeated pass over the same state creates no duplicates.
  4. WEB_PUSH gets an in-app log row plus a best-effort push to every active
     device the subscription's owner registered; a device the push service
     reports as permanently gone is deactivated rather than retried forever,
     and devices belonging to anyone else are never reached.
  5. EMAIL gets an in-app log row plus a best-effort SMTP send attempt via
     email_delivery, never blocking the log write on a transport failure.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, Match
from src.db import models as _db_models  # noqa: F401
from src.db.models import (
    MatchPredictionLog,
    PushDevice,
    UserNotificationLog,
    UserNotificationSubscription,
)
from src.services.email_delivery import EmailSendResult
from src.services.web_push_delivery import WebPushSendResult
from src.services.notification_dispatch_service import (
    _add_notification_log,
    _dispatch_kickoff_reminders,
    _dispatch_probability_swing_alerts,
)


@pytest.fixture(autouse=True)
def _reset_notification_dispatch_module_state():
    from src.services import notification_dispatch_service

    notification_dispatch_service._last_result = {
        "outcome": "never_run",
        "consecutive_failures": 0,
        "total_failures": 0,
        "last_success_at": None,
    }
    yield


# ponytail: SQLite silently discards tzinfo on a plain (non-timezone-aware)
# DateTime column round-trip — verified empirically (a tz-aware insert reads
# back with tzinfo=None). This suite therefore CANNOT catch a naive/aware
# datetime bug on the writes it exercises: asyncpg raises at bind time in
# production, SQLite here just silently normalizes it away. Do not read a
# green run here as proof those writes are tz-safe. See docs/DEBT.md item 55,
# residual 1.
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
async def factory():
    """Session factory (not an opened session) for run_notification_dispatch_pass(),
    which opens its own session via ``AsyncSessionLocal()`` — same fixture shape as
    test_clv_capture_service.py's ``factory``."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield session_factory
    await engine.dispose()


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _make_match(session: AsyncSession, match_id: str, *, minutes_until_kickoff: float, status: str = "scheduled") -> Match:
    match = Match(
        id=match_id,
        league_id="EPL",
        home_team_id=None,
        away_team_id=None,
        match_date=_now_naive() + timedelta(minutes=minutes_until_kickoff),
        status=status,
        created_at=_now_naive(),
        updated_at=_now_naive(),
    )
    session.add(match)
    await session.flush()
    return match


async def _make_subscription(
    session: AsyncSession,
    *,
    match_id: str,
    subscription_type: str,
    channel: str = "IN_APP",
    destination: str | None = None,
    reminder_minutes_before: int = 60,
    threshold_pct: float | None = None,
) -> UserNotificationSubscription:
    now = datetime.now(timezone.utc)
    sub = UserNotificationSubscription(
        id=str(uuid.uuid4()),
        user_id="user-1",
        anonymous_session_id=None,
        match_id=match_id,
        subscription_type=subscription_type,
        channel=channel,
        destination=destination,
        threshold_pct=threshold_pct,
        reminder_minutes_before=reminder_minutes_before,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    session.add(sub)
    await session.flush()
    return sub


async def test_kickoff_reminder_fires_inside_due_window(session: AsyncSession) -> None:
    await _make_match(session, "m1", minutes_until_kickoff=30)
    await _make_subscription(
        session, match_id="m1", subscription_type="KICKOFF_REMINDER", reminder_minutes_before=60
    )

    counts = await _dispatch_kickoff_reminders(session)
    await session.commit()

    assert counts["created"] == 1
    logs = (await session.execute(select(UserNotificationLog))).scalars().all()
    assert len(logs) == 1
    assert logs[0].category == "KICKOFF_REMINDER"


async def test_kickoff_reminder_does_not_fire_before_due_window(session: AsyncSession) -> None:
    await _make_match(session, "m2", minutes_until_kickoff=120)
    await _make_subscription(
        session, match_id="m2", subscription_type="KICKOFF_REMINDER", reminder_minutes_before=60
    )

    counts = await _dispatch_kickoff_reminders(session)
    await session.commit()

    assert counts["created"] == 0


async def test_kickoff_reminder_idempotent_across_repeated_passes(session: AsyncSession) -> None:
    await _make_match(session, "m3", minutes_until_kickoff=10)
    await _make_subscription(
        session, match_id="m3", subscription_type="KICKOFF_REMINDER", reminder_minutes_before=60
    )

    first = await _dispatch_kickoff_reminders(session)
    await session.commit()
    second = await _dispatch_kickoff_reminders(session)
    await session.commit()

    assert first["created"] == 1
    assert second["created"] == 0
    assert second["skipped_existing"] == 1


async def test_notification_log_unique_constraint_handles_dispatch_race(session: AsyncSession) -> None:
    sub = await _make_subscription(
        session, match_id="m-race", subscription_type="KICKOFF_REMINDER"
    )
    now = datetime.now(timezone.utc)
    existing = UserNotificationLog(
        id=str(uuid.uuid4()),
        user_id=sub.user_id,
        anonymous_session_id=None,
        subscription_id=sub.id,
        match_id=sub.match_id,
        title="Kickoff reminder",
        message="Match starts in about 60 minutes.",
        category="KICKOFF_REMINDER",
        read=False,
        read_at=None,
        payload={},
        created_at=now,
    )
    duplicate = UserNotificationLog(
        id=str(uuid.uuid4()),
        user_id=sub.user_id,
        anonymous_session_id=None,
        subscription_id=sub.id,
        match_id=sub.match_id,
        title="Kickoff reminder",
        message="Match starts in about 60 minutes.",
        category="KICKOFF_REMINDER",
        read=False,
        read_at=None,
        payload={},
        created_at=now,
    )

    assert await _add_notification_log(session, existing)
    assert not await _add_notification_log(session, duplicate)


async def _make_push_device(
    session: AsyncSession,
    *,
    endpoint: str,
    user_id: str | None = "user-1",
    anonymous_session_id: str | None = None,
    is_active: bool = True,
) -> PushDevice:
    now = datetime.now(timezone.utc)
    device = PushDevice(
        id=str(uuid.uuid4()),
        user_id=user_id,
        anonymous_session_id=anonymous_session_id,
        endpoint=endpoint,
        p256dh="test-p256dh",
        auth="test-auth",
        user_agent="pytest",
        is_active=is_active,
        created_at=now,
        updated_at=now,
    )
    session.add(device)
    await session.flush()
    return device


async def test_web_push_channel_creates_log_and_pushes_to_registered_devices(
    session: AsyncSession,
) -> None:
    """Supersedes the old `skips_web_push_channel` contract.

    WEB_PUSH is a dispatched channel now: it writes the in-app log row like
    every other channel and additionally attempts a push per active device.
    """
    await _make_match(session, "m4", minutes_until_kickoff=10)
    await _make_subscription(
        session, match_id="m4", subscription_type="KICKOFF_REMINDER", channel="WEB_PUSH"
    )
    await _make_push_device(session, endpoint="https://push.example/a")
    await _make_push_device(session, endpoint="https://push.example/b")

    with patch(
        "src.services.notification_dispatch_service.is_web_push_configured", return_value=True
    ), patch(
        "src.services.notification_dispatch_service.send_web_push",
        new=AsyncMock(return_value=WebPushSendResult(sent=True, reason="ok")),
    ) as mocked_send:
        counts = await _dispatch_kickoff_reminders(session)
    await session.commit()

    assert counts["created"] == 1
    assert counts["web_push_sent"] == 2
    assert mocked_send.await_count == 2
    # The deep link must point at the fixture the alert is about.
    assert mocked_send.await_args.kwargs["url"] == "/match/m4"
    logs = (await session.execute(select(UserNotificationLog))).scalars().all()
    assert len(logs) == 1


async def test_web_push_without_a_registered_device_still_writes_the_log(
    session: AsyncSession,
) -> None:
    """A person can subscribe with WEB_PUSH before granting browser permission.
    Losing the in-app row too would make that a silent double failure."""
    await _make_match(session, "m4f", minutes_until_kickoff=10)
    await _make_subscription(
        session, match_id="m4f", subscription_type="KICKOFF_REMINDER", channel="WEB_PUSH"
    )

    with patch(
        "src.services.notification_dispatch_service.is_web_push_configured", return_value=True
    ):
        counts = await _dispatch_kickoff_reminders(session)
    await session.commit()

    assert counts["created"] == 1
    assert counts["web_push_skipped_no_device"] == 1
    logs = (await session.execute(select(UserNotificationLog))).scalars().all()
    assert len(logs) == 1


async def test_web_push_unconfigured_is_counted_not_silently_dropped(
    session: AsyncSession,
) -> None:
    await _make_match(session, "m4g", minutes_until_kickoff=10)
    await _make_subscription(
        session, match_id="m4g", subscription_type="KICKOFF_REMINDER", channel="WEB_PUSH"
    )
    await _make_push_device(session, endpoint="https://push.example/c")

    with patch(
        "src.services.notification_dispatch_service.is_web_push_configured", return_value=False
    ):
        counts = await _dispatch_kickoff_reminders(session)

    assert counts["created"] == 1
    assert counts["web_push_not_configured"] == 1


async def test_expired_subscription_deactivates_the_device(session: AsyncSession) -> None:
    """404/410 means the endpoint is gone for good. Leaving it active would make
    every future pass burn a request on a subscription that can never deliver."""
    await _make_match(session, "m4h", minutes_until_kickoff=10)
    await _make_subscription(
        session, match_id="m4h", subscription_type="KICKOFF_REMINDER", channel="WEB_PUSH"
    )
    device = await _make_push_device(session, endpoint="https://push.example/gone")

    with patch(
        "src.services.notification_dispatch_service.is_web_push_configured", return_value=True
    ), patch(
        "src.services.notification_dispatch_service.send_web_push",
        new=AsyncMock(
            return_value=WebPushSendResult(
                sent=False, reason="subscription_expired", expired=True
            )
        ),
    ):
        counts = await _dispatch_kickoff_reminders(session)
    await session.commit()

    assert counts["created"] == 1
    assert counts["web_push_subscription_expired"] == 1
    await session.refresh(device)
    assert device.is_active is False


async def test_web_push_reaches_an_anonymous_reader_s_own_device(session: AsyncSession) -> None:
    """Push does not require an account. The anonymous session id is the owner
    key, and it must scope the device lookup exactly as a user id does."""
    await _make_match(session, "m4j", minutes_until_kickoff=10)
    sub = await _make_subscription(
        session, match_id="m4j", subscription_type="KICKOFF_REMINDER", channel="WEB_PUSH"
    )
    sub.user_id = None
    sub.anonymous_session_id = "anon-9"
    await _make_push_device(
        session, endpoint="https://push.example/anon", user_id=None, anonymous_session_id="anon-9"
    )
    await _make_push_device(session, endpoint="https://push.example/someone-else")
    await session.flush()

    with patch(
        "src.services.notification_dispatch_service.is_web_push_configured", return_value=True
    ), patch(
        "src.services.notification_dispatch_service.send_web_push",
        new=AsyncMock(return_value=WebPushSendResult(sent=True, reason="ok")),
    ) as mocked_send:
        await _dispatch_kickoff_reminders(session)

    assert mocked_send.await_count == 1
    assert mocked_send.await_args.kwargs["endpoint"] == "https://push.example/anon"


async def test_web_push_with_no_owner_at_all_sends_nothing(session: AsyncSession) -> None:
    """A subscription with neither identifier has no safe device query — an
    unscoped select would reach every browser in the table."""
    await _make_match(session, "m4k", minutes_until_kickoff=10)
    sub = await _make_subscription(
        session, match_id="m4k", subscription_type="KICKOFF_REMINDER", channel="WEB_PUSH"
    )
    sub.user_id = None
    sub.anonymous_session_id = None
    await _make_push_device(session, endpoint="https://push.example/orphan")
    await session.flush()

    with patch(
        "src.services.notification_dispatch_service.is_web_push_configured", return_value=True
    ), patch(
        "src.services.notification_dispatch_service.send_web_push",
        new=AsyncMock(return_value=WebPushSendResult(sent=True, reason="ok")),
    ) as mocked_send:
        counts = await _dispatch_kickoff_reminders(session)

    assert mocked_send.await_count == 0
    assert counts["web_push_skipped_no_device"] == 1


async def test_web_push_never_reaches_another_owners_device(session: AsyncSession) -> None:
    """The subscription belongs to user-1; an unscoped device query would fan a
    private alert out to every browser in the table."""
    await _make_match(session, "m4i", minutes_until_kickoff=10)
    await _make_subscription(
        session, match_id="m4i", subscription_type="KICKOFF_REMINDER", channel="WEB_PUSH"
    )
    await _make_push_device(session, endpoint="https://push.example/mine")
    await _make_push_device(session, endpoint="https://push.example/theirs", user_id="user-2")
    await _make_push_device(
        session, endpoint="https://push.example/stale", is_active=False
    )

    with patch(
        "src.services.notification_dispatch_service.is_web_push_configured", return_value=True
    ), patch(
        "src.services.notification_dispatch_service.send_web_push",
        new=AsyncMock(return_value=WebPushSendResult(sent=True, reason="ok")),
    ) as mocked_send:
        await _dispatch_kickoff_reminders(session)

    assert mocked_send.await_count == 1
    assert mocked_send.await_args.kwargs["endpoint"] == "https://push.example/mine"


async def test_kickoff_reminder_email_channel_creates_log(session: AsyncSession) -> None:
    """EMAIL is now dispatched like IN_APP for the in-app log; the transport
    side-effect is covered separately below."""
    await _make_match(session, "m4b", minutes_until_kickoff=10)
    await _make_subscription(
        session,
        match_id="m4b",
        subscription_type="KICKOFF_REMINDER",
        channel="EMAIL",
        destination="fan@example.com",
    )

    with patch(
        "src.services.notification_dispatch_service.send_notification_email",
        return_value=EmailSendResult(sent=False, reason="not_configured"),
    ) as mocked_send:
        counts = await _dispatch_kickoff_reminders(session)
    await session.commit()

    assert counts["created"] == 1
    assert counts["email_not_configured"] == 1
    mocked_send.assert_called_once()
    logs = (await session.execute(select(UserNotificationLog))).scalars().all()
    assert len(logs) == 1


async def test_email_dispatch_sends_when_configured(session: AsyncSession) -> None:
    await _make_match(session, "m4c", minutes_until_kickoff=10)
    await _make_subscription(
        session,
        match_id="m4c",
        subscription_type="KICKOFF_REMINDER",
        channel="EMAIL",
        destination="fan@example.com",
    )

    with patch(
        "src.services.notification_dispatch_service.send_notification_email",
        return_value=EmailSendResult(sent=True, reason="ok"),
    ) as mocked_send:
        counts = await _dispatch_kickoff_reminders(session)

    assert counts["email_sent"] == 1
    _, kwargs = mocked_send.call_args
    assert kwargs["to_address"] == "fan@example.com"
    assert "Kickoff" in kwargs["subject"]


async def test_email_dispatch_no_destination_skips_send(session: AsyncSession) -> None:
    await _make_match(session, "m4d", minutes_until_kickoff=10)
    await _make_subscription(
        session, match_id="m4d", subscription_type="KICKOFF_REMINDER", channel="EMAIL"
    )

    counts = await _dispatch_kickoff_reminders(session)

    assert counts["created"] == 1
    assert counts["email_skipped_no_destination"] == 1


async def test_email_send_failure_does_not_block_log_write(session: AsyncSession) -> None:
    await _make_match(session, "m4e", minutes_until_kickoff=10)
    await _make_subscription(
        session,
        match_id="m4e",
        subscription_type="KICKOFF_REMINDER",
        channel="EMAIL",
        destination="fan@example.com",
    )

    with patch(
        "src.services.notification_dispatch_service.send_notification_email",
        return_value=EmailSendResult(sent=False, reason="send_failed"),
    ):
        counts = await _dispatch_kickoff_reminders(session)
    await session.commit()

    assert counts["created"] == 1
    assert counts["email_send_failed"] == 1
    logs = (await session.execute(select(UserNotificationLog))).scalars().all()
    assert len(logs) == 1


async def _add_prediction_log(
    session: AsyncSession,
    *,
    match_id: str,
    home: float,
    draw: float,
    away: float,
    created_at: datetime,
    model_version: str = "test-v1",
) -> None:
    session.add(
        MatchPredictionLog(
            match_id=match_id,
            model_version=model_version,
            home_probability=home,
            draw_probability=draw,
            away_probability=away,
            created_at=created_at,
        )
    )
    await session.flush()


async def test_probability_swing_fires_when_delta_meets_threshold(session: AsyncSession) -> None:
    await _add_prediction_log(
        session, match_id="m5", home=0.40, draw=0.30, away=0.30, created_at=datetime.now(timezone.utc) - timedelta(minutes=10)
    )
    await _add_prediction_log(
        session, match_id="m5", home=0.55, draw=0.25, away=0.20, created_at=datetime.now(timezone.utc)
    )
    await _make_subscription(
        session, match_id="m5", subscription_type="PROBABILITY_SWING", threshold_pct=0.05
    )

    counts = await _dispatch_probability_swing_alerts(session)
    await session.commit()

    assert counts["created"] == 1


async def test_probability_swing_does_not_fire_below_threshold(session: AsyncSession) -> None:
    await _add_prediction_log(
        session, match_id="m6", home=0.40, draw=0.30, away=0.30, created_at=datetime.now(timezone.utc) - timedelta(minutes=10)
    )
    await _add_prediction_log(
        session, match_id="m6", home=0.42, draw=0.29, away=0.29, created_at=datetime.now(timezone.utc)
    )
    await _make_subscription(
        session, match_id="m6", subscription_type="PROBABILITY_SWING", threshold_pct=0.05
    )

    counts = await _dispatch_probability_swing_alerts(session)

    assert counts["created"] == 0


async def test_probability_swing_requires_two_snapshots(session: AsyncSession) -> None:
    await _add_prediction_log(
        session, match_id="m7", home=0.40, draw=0.30, away=0.30, created_at=datetime.now(timezone.utc)
    )
    await _make_subscription(
        session, match_id="m7", subscription_type="PROBABILITY_SWING", threshold_pct=0.05
    )

    counts = await _dispatch_probability_swing_alerts(session)

    assert counts["created"] == 0
    assert counts["skipped_missing_data"] == 1


async def test_probability_swing_does_not_compare_model_versions(session: AsyncSession) -> None:
    await _add_prediction_log(
        session,
        match_id="m-version",
        home=0.40,
        draw=0.30,
        away=0.30,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        model_version="old-model",
    )
    await _add_prediction_log(
        session,
        match_id="m-version",
        home=0.60,
        draw=0.20,
        away=0.20,
        created_at=datetime.now(timezone.utc),
        model_version="new-model",
    )
    await _make_subscription(
        session,
        match_id="m-version",
        subscription_type="PROBABILITY_SWING",
        threshold_pct=0.05,
    )

    counts = await _dispatch_probability_swing_alerts(session)

    assert counts["created"] == 0
    assert counts["skipped_missing_data"] == 1


async def test_probability_swing_idempotent_across_repeated_passes(session: AsyncSession) -> None:
    await _add_prediction_log(
        session, match_id="m8", home=0.40, draw=0.30, away=0.30, created_at=datetime.now(timezone.utc) - timedelta(minutes=10)
    )
    await _add_prediction_log(
        session, match_id="m8", home=0.60, draw=0.20, away=0.20, created_at=datetime.now(timezone.utc)
    )
    await _make_subscription(
        session, match_id="m8", subscription_type="PROBABILITY_SWING", threshold_pct=0.05
    )

    first = await _dispatch_probability_swing_alerts(session)
    await session.commit()
    second = await _dispatch_probability_swing_alerts(session)
    await session.commit()

    assert first["created"] == 1
    assert second["created"] == 0
    assert second["skipped_existing"] == 1


# ── run_notification_dispatch_pass() (public entry point) ──────────────────


async def test_run_notification_dispatch_pass_db_not_ready() -> None:
    from src.services.notification_dispatch_service import run_notification_dispatch_pass

    with patch("src.db.session.AsyncSessionLocal", new=None):
        result = await run_notification_dispatch_pass()

    assert result["outcome"] == "db_not_ready"


async def test_run_notification_dispatch_pass_success_creates_kickoff_reminder(factory) -> None:
    from src.services.notification_dispatch_service import run_notification_dispatch_pass

    async with factory() as session:
        await _make_match(session, "m-pass-1", minutes_until_kickoff=30)
        await _make_subscription(
            session,
            match_id="m-pass-1",
            subscription_type="KICKOFF_REMINDER",
            reminder_minutes_before=60,
        )
        await session.commit()

    with patch("src.db.session.AsyncSessionLocal", new=factory):
        result = await run_notification_dispatch_pass()

    assert result["outcome"] == "ok"
    assert result["kickoff_reminders"]["created"] == 1
    assert result["probability_swing_alerts"]["created"] == 0
    assert result["consecutive_failures"] == 0

    async with factory() as session:
        logs = (await session.execute(select(UserNotificationLog))).scalars().all()
    assert len(logs) == 1
    assert logs[0].category == "KICKOFF_REMINDER"


async def test_run_notification_dispatch_pass_genuine_exception_yields_error(factory) -> None:
    from src.services import notification_dispatch_service

    with patch("src.db.session.AsyncSessionLocal", new=factory), patch.object(
        notification_dispatch_service,
        "_dispatch_kickoff_reminders",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        result = await notification_dispatch_service.run_notification_dispatch_pass()

    assert result["outcome"] == "error"
    assert result["consecutive_failures"] == 1


# ── last_notification_dispatch_result() (sync /health accessor) ────────────


def test_last_notification_dispatch_result_computes_age_from_iso_timestamp() -> None:
    from src.services import notification_dispatch_service

    past = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    notification_dispatch_service._last_result = {
        "outcome": "ok",
        "last_success_at": past,
        "consecutive_failures": 0,
        "total_failures": 0,
    }

    result = notification_dispatch_service.last_notification_dispatch_result()

    assert result["last_success_age_seconds"] is not None
    assert result["last_success_age_seconds"] >= 120


def test_last_notification_dispatch_result_handles_missing_last_success_at() -> None:
    from src.services import notification_dispatch_service

    notification_dispatch_service._last_result = {"outcome": "never_run"}

    result = notification_dispatch_service.last_notification_dispatch_result()

    assert result["last_success_age_seconds"] is None


# ── _background_notification_dispatch() loop wiring (main.py) ──────────────


async def test_background_notification_dispatch_calls_run_pass_then_stops(monkeypatch) -> None:
    """Same pattern as test_settlement_startup_coordination.py: force the loop
    to run exactly once via a controlled asyncio.sleep, then cancel."""
    import asyncio

    from src.api import main

    run_pass = AsyncMock(return_value={"outcome": "ok"})
    sleep_calls = 0

    async def controlled_sleep(_seconds: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 1:
            raise asyncio.CancelledError

    with patch(
        "src.services.notification_dispatch_service.run_notification_dispatch_pass", run_pass
    ), patch("src.api.main.asyncio.sleep", new=controlled_sleep):
        with pytest.raises(asyncio.CancelledError):
            await main._background_notification_dispatch()

    run_pass.assert_awaited_once()
