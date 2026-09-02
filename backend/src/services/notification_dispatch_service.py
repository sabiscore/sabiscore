"""Scheduled notification dispatch: kickoff reminders and probability-swing alerts.

Advisory only. Reads existing subscriptions (``UserNotificationSubscription``)
and predictions (``MatchPredictionLog``) and writes in-app notification rows
(``UserNotificationLog``). Never touches prediction, verdict, evidence, or
stake state, and never raises into the caller's background loop — the same
swallow-and-log convention ``run_fixture_sync``/``run_settlement_pass`` use.

All three channels are dispatched: ``IN_APP``, ``EMAIL`` and ``WEB_PUSH``.
Every one of them writes an in-app log row first, so the notification inbox
stays complete regardless of channel; the out-of-app transports are then
attempted as best-effort side effects that are counted but never allowed to
block or undo the log write. ``EMAIL`` goes through ``email_delivery``
(stdlib SMTP), ``WEB_PUSH`` through ``web_push_delivery`` (VAPID + RFC 8291
aes128gcm). Both are config-gated and inert until an operator supplies
credentials.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import Match
from ..db.models import (
    MatchPredictionLog,
    PushDevice,
    UserNotificationLog,
    UserNotificationSubscription,
)
from ..monitoring.metrics import metrics_collector
from .email_delivery import send_notification_email
from .web_push_delivery import is_web_push_configured, send_web_push

logger = logging.getLogger(__name__)

_DISPATCHED_CHANNELS = {"IN_APP", "EMAIL", "WEB_PUSH"}
_DEFAULT_SWING_THRESHOLD_PCT = 0.05


def _dispatch_email_if_applicable(
    sub: UserNotificationSubscription, *, title: str, message: str, counters: Dict[str, int]
) -> None:
    """Best-effort EMAIL side-effect alongside the in-app log row. Never raises
    and never blocks the log write — a transport failure only affects the
    counters, matching the swallow-and-log convention this module already
    uses at the pass level."""
    if sub.channel != "EMAIL":
        return
    if not sub.destination:
        counters["email_skipped_no_destination"] = counters.get("email_skipped_no_destination", 0) + 1
        return
    result = send_notification_email(to_address=sub.destination, subject=title, body=message)
    key = "email_sent" if result.sent else f"email_{result.reason}"
    counters[key] = counters.get(key, 0) + 1


async def _active_devices_for(
    session: AsyncSession, sub: UserNotificationSubscription
) -> list[PushDevice]:
    """Scope strictly to the subscription's owner. Without an owner there is no
    safe query — an unscoped select would push one person's alert to every
    registered browser."""
    if sub.user_id:
        stmt = select(PushDevice).where(
            PushDevice.user_id == sub.user_id, PushDevice.is_active.is_(True)
        )
    elif sub.anonymous_session_id:
        stmt = select(PushDevice).where(
            PushDevice.anonymous_session_id == sub.anonymous_session_id,
            PushDevice.is_active.is_(True),
        )
    else:
        return []
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _dispatch_web_push_if_applicable(
    session: AsyncSession,
    sub: UserNotificationSubscription,
    *,
    title: str,
    message: str,
    counters: Dict[str, int],
) -> None:
    """Best-effort WEB_PUSH fan-out to every active device this owner registered.

    Same contract as the EMAIL helper: never raises, never blocks the in-app log
    row. A device the push service reports as permanently gone (404/410) is
    deactivated here rather than retried forever — that is the only way a stale
    endpoint ever leaves the send set.
    """
    if sub.channel != "WEB_PUSH":
        return
    if not is_web_push_configured():
        counters["web_push_not_configured"] = counters.get("web_push_not_configured", 0) + 1
        return

    devices = await _active_devices_for(session, sub)
    if not devices:
        counters["web_push_skipped_no_device"] = counters.get("web_push_skipped_no_device", 0) + 1
        return

    for device in devices:
        result = await send_web_push(
            endpoint=device.endpoint,
            p256dh=device.p256dh,
            auth=device.auth,
            title=title,
            body=message,
            url=f"/match/{sub.match_id}" if sub.match_id else None,
        )
        if result.expired:
            device.is_active = False
            device.updated_at = datetime.now(timezone.utc)
        elif result.sent:
            device.last_delivery_at = datetime.now(timezone.utc)
        key = "web_push_sent" if result.sent else f"web_push_{result.reason}"
        counters[key] = counters.get(key, 0) + 1


async def _dispatch_channel_side_effects(
    session: AsyncSession,
    sub: UserNotificationSubscription,
    *,
    title: str,
    message: str,
    counters: Dict[str, int],
) -> None:
    """One place every out-of-app channel is fanned out from, so adding the next
    one does not mean finding every notification-creation site again."""
    _dispatch_email_if_applicable(sub, title=title, message=message, counters=counters)
    await _dispatch_web_push_if_applicable(
        session, sub, title=title, message=message, counters=counters
    )


_last_result: Dict[str, Any] = {
    "outcome": "never_run",
    "consecutive_failures": 0,
    "total_failures": 0,
    "last_success_at": None,
}


def last_notification_dispatch_result() -> Dict[str, Any]:
    """Sync accessor for /health — a copy, never the live dict."""
    result = dict(_last_result)
    last_success_at = result.get("last_success_at")
    if isinstance(last_success_at, str):
        try:
            observed = datetime.fromisoformat(last_success_at.replace("Z", "+00:00"))
            result["last_success_age_seconds"] = max(
                0, int((datetime.now(timezone.utc) - observed).total_seconds())
            )
        except ValueError:
            result["last_success_age_seconds"] = None
    else:
        result["last_success_age_seconds"] = None
    return result


def _now_naive_utc() -> datetime:
    # Match.match_date is a naive TIMESTAMP WITHOUT TIME ZONE column (established
    # convention across fixture_sync_service/upcoming_match_service).
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _already_logged(
    session: AsyncSession, *, subscription_id: str, match_id: str, category: str
) -> bool:
    existing = await session.execute(
        select(UserNotificationLog.id).where(
            UserNotificationLog.subscription_id == subscription_id,
            UserNotificationLog.match_id == match_id,
            UserNotificationLog.category == category,
        )
    )
    return existing.scalar_one_or_none() is not None


async def _add_notification_log(session: AsyncSession, log: UserNotificationLog) -> bool:
    """Insert one notification, returning false if another worker already did."""
    try:
        async with session.begin_nested():
            session.add(log)
            await session.flush()
    except IntegrityError as exc:
        constraint_name = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        sqlite_duplicate = (
            "UNIQUE constraint failed: user_notification_logs.subscription_id,"
            " user_notification_logs.match_id, user_notification_logs.category"
        )
        if constraint_name != "uq_notification_log_subscription_match_category" and (
            sqlite_duplicate not in str(exc.orig)
        ):
            raise
        return False
    return True


async def _dispatch_kickoff_reminders(session: AsyncSession) -> Dict[str, int]:
    counters = {
        "examined": 0,
        "created": 0,
        "skipped_existing": 0,
        "skipped_channel": 0,
        "skipped_missing_data": 0,
    }
    now = _now_naive_utc()

    subs = (
        await session.execute(
            select(UserNotificationSubscription).where(
                UserNotificationSubscription.subscription_type == "KICKOFF_REMINDER",
                UserNotificationSubscription.is_active.is_(True),
                UserNotificationSubscription.match_id.is_not(None),
            )
        )
    ).scalars().all()

    for sub in subs:
        counters["examined"] += 1
        if sub.channel not in _DISPATCHED_CHANNELS:
            counters["skipped_channel"] += 1
            continue

        match = (
            await session.execute(select(Match).where(Match.id == sub.match_id))
        ).scalar_one_or_none()
        if match is None or match.match_date is None or (match.status or "scheduled") != "scheduled":
            counters["skipped_missing_data"] += 1
            continue

        minutes_before = sub.reminder_minutes_before or 60
        due_at = match.match_date - timedelta(minutes=minutes_before)
        if not (due_at <= now < match.match_date):
            continue

        if await _already_logged(
            session, subscription_id=sub.id, match_id=sub.match_id, category="KICKOFF_REMINDER"
        ):
            counters["skipped_existing"] += 1
            continue

        remaining_minutes = max(0, int((match.match_date - now).total_seconds() / 60))
        created = await _add_notification_log(
            session,
            UserNotificationLog(
                id=str(uuid.uuid4()),
                user_id=sub.user_id,
                anonymous_session_id=sub.anonymous_session_id if not sub.user_id else None,
                subscription_id=sub.id,
                match_id=sub.match_id,
                title="Kickoff reminder",
                message=f"Match starts in about {remaining_minutes} minutes.",
                category="KICKOFF_REMINDER",
                read=False,
                read_at=None,
                payload={"match_id": sub.match_id, "reminder_minutes_before": minutes_before},
                created_at=datetime.now(timezone.utc),
            ),
        )
        if created:
            counters["created"] += 1
            await _dispatch_channel_side_effects(
                session,
                sub,
                title="Kickoff reminder",
                message=f"Match starts in about {remaining_minutes} minutes.",
                counters=counters,
            )
        else:
            counters["skipped_existing"] += 1

    return counters


async def _dispatch_probability_swing_alerts(session: AsyncSession) -> Dict[str, int]:
    counters = {
        "examined": 0,
        "created": 0,
        "skipped_existing": 0,
        "skipped_channel": 0,
        "skipped_missing_data": 0,
    }

    subs = (
        await session.execute(
            select(UserNotificationSubscription).where(
                UserNotificationSubscription.subscription_type == "PROBABILITY_SWING",
                UserNotificationSubscription.is_active.is_(True),
                UserNotificationSubscription.match_id.is_not(None),
            )
        )
    ).scalars().all()

    for sub in subs:
        counters["examined"] += 1
        if sub.channel not in _DISPATCHED_CHANNELS:
            counters["skipped_channel"] += 1
            continue

        recent = (
            await session.execute(
                select(MatchPredictionLog)
                .where(MatchPredictionLog.match_id == sub.match_id)
                .order_by(MatchPredictionLog.created_at.desc())
                .limit(2)
            )
        ).scalars().all()
        if len(recent) < 2 or recent[0].model_version != recent[1].model_version:
            counters["skipped_missing_data"] += 1
            continue

        latest, previous = recent[0], recent[1]
        delta = max(
            abs(latest.home_probability - previous.home_probability),
            abs(latest.draw_probability - previous.draw_probability),
            abs(latest.away_probability - previous.away_probability),
        )
        threshold = (
            sub.threshold_pct if sub.threshold_pct is not None else _DEFAULT_SWING_THRESHOLD_PCT
        )
        if delta < threshold:
            continue

        if await _already_logged(
            session, subscription_id=sub.id, match_id=sub.match_id, category="PROBABILITY_SWING"
        ):
            counters["skipped_existing"] += 1
            continue

        created = await _add_notification_log(
            session,
            UserNotificationLog(
                id=str(uuid.uuid4()),
                user_id=sub.user_id,
                anonymous_session_id=sub.anonymous_session_id if not sub.user_id else None,
                subscription_id=sub.id,
                match_id=sub.match_id,
                title="Model probability shift",
                message=f"Model probabilities moved by {delta:.0%} since the last snapshot.",
                category="PROBABILITY_SWING",
                read=False,
                read_at=None,
                payload={"match_id": sub.match_id, "delta": round(delta, 4)},
                created_at=datetime.now(timezone.utc),
            ),
        )
        if created:
            counters["created"] += 1
            await _dispatch_channel_side_effects(
                session,
                sub,
                title="Model probability shift",
                message=f"Model probabilities moved by {delta:.0%} since the last snapshot.",
                counters=counters,
            )
        else:
            counters["skipped_existing"] += 1

    return counters


async def run_notification_dispatch_pass() -> Dict[str, Any]:
    """One pass: generate due kickoff reminders and probability-swing alerts.

    Never raises — every failure lands in the returned/stored dict, matching
    the swallow-and-log convention ``run_settlement_pass``/``run_fixture_sync``
    use, so a background-loop failure never affects readiness or startup.
    """
    global _last_result

    from ..db.session import AsyncSessionLocal

    checked_at = datetime.now(timezone.utc).isoformat()

    if AsyncSessionLocal is None:
        _last_result = {**_last_result, "outcome": "db_not_ready", "checked_at": checked_at}
        return _last_result

    try:
        async with AsyncSessionLocal() as session:
            kickoff_counts = await _dispatch_kickoff_reminders(session)
            swing_counts = await _dispatch_probability_swing_alerts(session)
            await session.commit()

        metrics_collector.increment("notifications.dispatch.kickoff_created", kickoff_counts["created"])
        metrics_collector.increment("notifications.dispatch.swing_created", swing_counts["created"])
        emails_sent = kickoff_counts.get("email_sent", 0) + swing_counts.get("email_sent", 0)
        metrics_collector.increment("notifications.dispatch.email_sent", emails_sent)

        _last_result = {
            "outcome": "ok",
            "checked_at": checked_at,
            "last_success_at": checked_at,
            "kickoff_reminders": kickoff_counts,
            "probability_swing_alerts": swing_counts,
            "consecutive_failures": 0,
            "total_failures": int(_last_result.get("total_failures", 0)),
        }
    except Exception as exc:
        logger.exception("notification_dispatch_pass: unhandled error")
        metrics_collector.increment("notifications.dispatch.failures")
        consecutive_failures = int(_last_result.get("consecutive_failures", 0)) + 1
        from ..core.redaction import redact_text

        _last_result = {
            **_last_result,
            "outcome": "error",
            "checked_at": checked_at,
            "message": redact_text(exc),
            "consecutive_failures": consecutive_failures,
            "total_failures": int(_last_result.get("total_failures", 0)) + 1,
        }

    return _last_result


__all__ = [
    "run_notification_dispatch_pass",
    "last_notification_dispatch_result",
]
