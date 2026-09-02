"""Notification service: match reminders, probability swing alerts, timezones, and in-app logs."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import (
    PushDevice,
    UserNotificationLog,
    UserNotificationSubscription,
    UserPreference,
)


class NotificationService:
    """Manages match subscriptions, push settings, and in-app notification centers."""

    @staticmethod
    async def get_or_create_preferences(
        db: AsyncSession,
        *,
        user_id: Optional[str] = None,
        anonymous_session_id: Optional[str] = None,
    ) -> UserPreference:
        if user_id:
            stmt = select(UserPreference).where(UserPreference.user_id == user_id)
        else:
            stmt = select(UserPreference).where(
                UserPreference.anonymous_session_id == anonymous_session_id
            )
        result = await db.execute(stmt)
        pref = result.scalar_one_or_none()
        if not pref:
            now = datetime.now(timezone.utc)
            pref = UserPreference(
                id=str(uuid.uuid4()),
                user_id=user_id,
                anonymous_session_id=anonymous_session_id if not user_id else None,
                odds_format="DECIMAL",
                timezone="Africa/Lagos",
                default_league="EPL",
                created_at=now,
                updated_at=now,
            )
            db.add(pref)
            await db.commit()
            await db.refresh(pref)
        return pref

    @staticmethod
    async def update_timezone(
        db: AsyncSession,
        *,
        user_id: Optional[str] = None,
        anonymous_session_id: Optional[str] = None,
        timezone_iana: str,
    ) -> UserPreference:
        pref = await NotificationService.get_or_create_preferences(
            db, user_id=user_id, anonymous_session_id=anonymous_session_id
        )
        pref.timezone = timezone_iana.strip()
        pref.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(pref)
        return pref

    @staticmethod
    async def subscribe_match(
        db: AsyncSession,
        *,
        user_id: Optional[str] = None,
        anonymous_session_id: Optional[str] = None,
        match_id: str,
        subscription_type: str = "KICKOFF_REMINDER",
        channel: str = "IN_APP",
        destination: Optional[str] = None,
        threshold_pct: Optional[float] = None,
        reminder_minutes_before: int = 60,
    ) -> UserNotificationSubscription:
        clean_match_id = match_id.strip()
        clean_sub_type = subscription_type.strip().upper()

        if user_id:
            stmt = select(UserNotificationSubscription).where(
                UserNotificationSubscription.user_id == user_id,
                UserNotificationSubscription.match_id == clean_match_id,
                UserNotificationSubscription.subscription_type == clean_sub_type,
            )
        else:
            stmt = select(UserNotificationSubscription).where(
                UserNotificationSubscription.anonymous_session_id == anonymous_session_id,
                UserNotificationSubscription.match_id == clean_match_id,
                UserNotificationSubscription.subscription_type == clean_sub_type,
            )
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            existing.is_active = True
            existing.channel = channel
            existing.destination = destination
            existing.threshold_pct = threshold_pct
            existing.reminder_minutes_before = reminder_minutes_before
            existing.updated_at = datetime.now(timezone.utc)
            await db.commit()
            await db.refresh(existing)
            return existing

        now = datetime.now(timezone.utc)
        sub = UserNotificationSubscription(
            id=str(uuid.uuid4()),
            user_id=user_id,
            anonymous_session_id=anonymous_session_id if not user_id else None,
            match_id=clean_match_id,
            subscription_type=clean_sub_type,
            channel=channel,
            destination=destination,
            threshold_pct=threshold_pct,
            reminder_minutes_before=reminder_minutes_before,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        db.add(sub)
        await db.commit()
        await db.refresh(sub)
        return sub

    @staticmethod
    async def unsubscribe_match(
        db: AsyncSession,
        *,
        user_id: Optional[str] = None,
        anonymous_session_id: Optional[str] = None,
        match_id: str,
        subscription_type: Optional[str] = None,
    ) -> bool:
        clean_match_id = match_id.strip()
        if user_id:
            stmt = delete(UserNotificationSubscription).where(
                UserNotificationSubscription.user_id == user_id,
                UserNotificationSubscription.match_id == clean_match_id,
            )
        else:
            stmt = delete(UserNotificationSubscription).where(
                UserNotificationSubscription.anonymous_session_id == anonymous_session_id,
                UserNotificationSubscription.match_id == clean_match_id,
            )

        if subscription_type:
            stmt = stmt.where(
                UserNotificationSubscription.subscription_type == subscription_type.strip().upper()
            )

        res = await db.execute(stmt)
        await db.commit()
        return (res.rowcount or 0) > 0

    @staticmethod
    async def get_subscriptions(
        db: AsyncSession,
        *,
        user_id: Optional[str] = None,
        anonymous_session_id: Optional[str] = None,
    ) -> List[UserNotificationSubscription]:
        if user_id:
            stmt = select(UserNotificationSubscription).where(
                UserNotificationSubscription.user_id == user_id,
                UserNotificationSubscription.is_active.is_(True),
            )
        else:
            stmt = select(UserNotificationSubscription).where(
                UserNotificationSubscription.anonymous_session_id == anonymous_session_id,
                UserNotificationSubscription.is_active.is_(True),
            )
        result = await db.execute(stmt.order_by(UserNotificationSubscription.created_at.desc()))
        return list(result.scalars().all())

    @staticmethod
    async def create_in_app_notification(
        db: AsyncSession,
        *,
        user_id: Optional[str] = None,
        anonymous_session_id: Optional[str] = None,
        title: str,
        message: str,
        category: str = "INFO",
        match_id: Optional[str] = None,
        subscription_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> UserNotificationLog:
        log = UserNotificationLog(
            id=str(uuid.uuid4()),
            user_id=user_id,
            anonymous_session_id=anonymous_session_id if not user_id else None,
            match_id=match_id,
            subscription_id=subscription_id,
            title=title,
            message=message,
            category=category,
            read=False,
            read_at=None,
            payload=payload,
            created_at=datetime.now(timezone.utc),
        )
        db.add(log)
        await db.commit()
        await db.refresh(log)
        return log

    @staticmethod
    async def get_in_app_notifications(
        db: AsyncSession,
        *,
        user_id: Optional[str] = None,
        anonymous_session_id: Optional[str] = None,
        unread_only: bool = False,
        limit: int = 50,
    ) -> List[UserNotificationLog]:
        if user_id:
            stmt = select(UserNotificationLog).where(UserNotificationLog.user_id == user_id)
        else:
            stmt = select(UserNotificationLog).where(
                UserNotificationLog.anonymous_session_id == anonymous_session_id
            )
        if unread_only:
            stmt = stmt.where(UserNotificationLog.read.is_(False))

        stmt = stmt.order_by(UserNotificationLog.created_at.desc()).limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def mark_as_read(
        db: AsyncSession,
        *,
        notification_id: str,
        user_id: Optional[str] = None,
        anonymous_session_id: Optional[str] = None,
    ) -> bool:
        stmt = select(UserNotificationLog).where(UserNotificationLog.id == notification_id)
        if user_id:
            stmt = stmt.where(UserNotificationLog.user_id == user_id)
        elif anonymous_session_id:
            stmt = stmt.where(
                UserNotificationLog.anonymous_session_id == anonymous_session_id
            )

        result = await db.execute(stmt)
        log = result.scalar_one_or_none()
        if not log:
            return False

        log.read = True
        log.read_at = datetime.now(timezone.utc)
        await db.commit()
        return True

    @staticmethod
    async def mark_all_as_read(
        db: AsyncSession,
        *,
        user_id: Optional[str] = None,
        anonymous_session_id: Optional[str] = None,
    ) -> int:
        now = datetime.now(timezone.utc)
        if user_id:
            stmt = (
                update(UserNotificationLog)
                .where(UserNotificationLog.user_id == user_id, UserNotificationLog.read.is_(False))
                .values(read=True, read_at=now)
            )
        elif anonymous_session_id:
            stmt = (
                update(UserNotificationLog)
                .where(
                    UserNotificationLog.anonymous_session_id == anonymous_session_id,
                    UserNotificationLog.read.is_(False),
                )
                .values(read=True, read_at=now)
            )
        else:
            return 0

        res = await db.execute(stmt)
        await db.commit()
        return int(res.rowcount or 0)

    # ── WEB_PUSH device registry ──────────────────────────────────────────────
    #
    # A push device is transport, not intent: it records *where* a WEB_PUSH
    # message can be delivered, while UserNotificationSubscription above records
    # *what* the person asked to hear about. Keeping them apart is what lets one
    # browser registration serve every match a person subscribes to.

    @staticmethod
    async def register_push_device(
        db: AsyncSession,
        *,
        user_id: Optional[str] = None,
        anonymous_session_id: Optional[str] = None,
        endpoint: str,
        p256dh: str,
        auth: str,
        user_agent: Optional[str] = None,
    ) -> PushDevice:
        """Upsert on ``endpoint``.

        The push service treats the endpoint as the device identity, so a
        re-subscribe from the same browser (new keys after a permission reset,
        say) must overwrite in place. Inserting instead would leave a row whose
        keys no longer decrypt, and every send to it would fail forever.
        """
        clean_endpoint = endpoint.strip()
        result = await db.execute(
            select(PushDevice).where(PushDevice.endpoint == clean_endpoint)
        )
        existing = result.scalar_one_or_none()
        now = datetime.now(timezone.utc)

        if existing:
            existing.p256dh = p256dh
            existing.auth = auth
            existing.user_agent = user_agent
            existing.user_id = user_id
            existing.anonymous_session_id = anonymous_session_id if not user_id else None
            existing.is_active = True
            existing.updated_at = now
            await db.commit()
            await db.refresh(existing)
            return existing

        device = PushDevice(
            id=str(uuid.uuid4()),
            user_id=user_id,
            anonymous_session_id=anonymous_session_id if not user_id else None,
            endpoint=clean_endpoint,
            p256dh=p256dh,
            auth=auth,
            user_agent=user_agent,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        db.add(device)
        await db.commit()
        await db.refresh(device)
        return device

    @staticmethod
    async def unregister_push_device(db: AsyncSession, *, endpoint: str) -> bool:
        """Deactivate rather than delete, so a browser that re-subscribes to the
        same endpoint reuses one row instead of churning the unique index."""
        result = await db.execute(
            select(PushDevice).where(PushDevice.endpoint == endpoint.strip())
        )
        device = result.scalar_one_or_none()
        if device is None:
            return False
        device.is_active = False
        device.updated_at = datetime.now(timezone.utc)
        await db.commit()
        return True

    @staticmethod
    async def get_active_push_devices(
        db: AsyncSession,
        *,
        user_id: Optional[str] = None,
        anonymous_session_id: Optional[str] = None,
    ) -> List[PushDevice]:
        """Devices a WEB_PUSH notification for this owner should reach.

        Returns [] when neither identifier is supplied — an unscoped query here
        would fan a private notification out to every device in the table.
        """
        if user_id:
            stmt = select(PushDevice).where(
                PushDevice.user_id == user_id, PushDevice.is_active.is_(True)
            )
        elif anonymous_session_id:
            stmt = select(PushDevice).where(
                PushDevice.anonymous_session_id == anonymous_session_id,
                PushDevice.is_active.is_(True),
            )
        else:
            return []
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def mark_push_device_expired(db: AsyncSession, *, device_id: str) -> None:
        """The push service reported 404/410 — the subscription is gone for good.
        Flushes without committing; the caller owns the transaction boundary."""
        await db.execute(
            update(PushDevice)
            .where(PushDevice.id == device_id)
            .values(is_active=False, updated_at=datetime.now(timezone.utc))
        )
