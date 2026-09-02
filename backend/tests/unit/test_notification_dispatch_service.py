"""Unit tests for notification_dispatch_service (kickoff reminders + probability
swing alerts).

Contracts verified:
  1. Kickoff reminder fires only inside its due window (reminder_minutes_before
     before kickoff, up to kickoff itself).
  2. Probability-swing alert fires only when the delta between the two most
     recent MatchPredictionLog snapshots meets/exceeds threshold_pct.
  3. Idempotency — a repeated pass over the same state creates no duplicates.
  4. Non-IN_APP channels are skipped and counted, never silently dropped.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, Match
from src.db import models as _db_models  # noqa: F401
from src.db.models import MatchPredictionLog, UserNotificationLog, UserNotificationSubscription
from src.services.notification_dispatch_service import (
    _dispatch_kickoff_reminders,
    _dispatch_probability_swing_alerts,
)


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
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
        destination=None,
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


async def test_kickoff_reminder_skips_non_in_app_channel(session: AsyncSession) -> None:
    await _make_match(session, "m4", minutes_until_kickoff=10)
    await _make_subscription(
        session, match_id="m4", subscription_type="KICKOFF_REMINDER", channel="EMAIL"
    )

    counts = await _dispatch_kickoff_reminders(session)

    assert counts["created"] == 0
    assert counts["skipped_channel"] == 1


async def _add_prediction_log(
    session: AsyncSession,
    *,
    match_id: str,
    home: float,
    draw: float,
    away: float,
    created_at: datetime,
) -> None:
    session.add(
        MatchPredictionLog(
            match_id=match_id,
            model_version="test-v1",
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
