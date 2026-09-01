"""Unit tests for models and Alembic migration 0011."""

from __future__ import annotations

from datetime import datetime, timezone

from src.db.models import (
    AnalyticsEvent,
    ApiKey,
    UserFavorite,
    UserNotificationLog,
    UserNotificationSubscription,
    UserPreference,
    UserSavedMatch,
)


def test_models_instantiation() -> None:
    now = datetime.now(timezone.utc)
    fav = UserFavorite(
        id="fav-1",
        user_id="user-123",
        anonymous_session_id=None,
        entity_type="team",
        entity_id="arsenal",
        created_at=now,
    )
    assert fav.id == "fav-1"
    assert fav.entity_type == "team"
    assert fav.entity_id == "arsenal"

    saved = UserSavedMatch(
        id="save-1",
        user_id=None,
        anonymous_session_id="anon-456",
        match_id="fd-1001",
        target_outcome="HOME_WIN",
        notes="High edge potential",
        created_at=now,
    )
    assert saved.match_id == "fd-1001"
    assert saved.anonymous_session_id == "anon-456"

    pref = UserPreference(
        id="pref-1",
        user_id="user-123",
        anonymous_session_id=None,
        odds_format="DECIMAL",
        timezone="Africa/Lagos",
        default_league="EPL",
        created_at=now,
        updated_at=now,
    )
    assert pref.timezone == "Africa/Lagos"

    key = ApiKey(
        id="key-1",
        user_id="user-123",
        name="Production Bot",
        key_prefix="sbk_live_abcd",
        key_hash="hash-123",
        tier="PRO",
        rate_limit_per_minute=60,
        daily_quota=5000,
        is_active=True,
        created_at=now,
    )
    assert key.tier == "PRO"
    assert key.rate_limit_per_minute == 60

    event = AnalyticsEvent(
        id=1,
        event_id="evt-1",
        anonymous_session_id="anon-456",
        user_id=None,
        event_name="verdict_inspected",
        properties={"match_id": "fd-1001", "verdict": "ACTIONABLE"},
        session_id="sess-1",
        client_platform="web",
        timestamp=now,
        created_at=now,
    )
    assert event.event_name == "verdict_inspected"
    assert event.properties["verdict"] == "ACTIONABLE"

    sub = UserNotificationSubscription(
        id="sub-1",
        user_id="user-123",
        match_id="fd-1001",
        subscription_type="KICKOFF_REMINDER",
        channel="IN_APP",
        reminder_minutes_before=60,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    assert sub.subscription_type == "KICKOFF_REMINDER"

    log = UserNotificationLog(
        id="log-1",
        user_id="user-123",
        title="Match Kickoff Reminder",
        message="Arsenal vs Chelsea kicks off in 1 hour.",
        category="KICKOFF_REMINDER",
        read=False,
        created_at=now,
    )
    assert log.read is False


def test_alembic_migration_0011_script_loads() -> None:
    import importlib.util
    from pathlib import Path

    migration_path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0011_user_identity_dev_platform.py"
    assert migration_path.exists()
    spec = importlib.util.spec_from_file_location("migration_0011", str(migration_path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0011_user_identity_dev_platform"
    # Alembic's alembic_version.version_num defaults to VARCHAR(32); every
    # revision id in this repo must fit, or the final upgrade-head version
    # stamp raises StringDataRightTruncation on real PostgreSQL.
    assert len(module.revision) <= 32
    assert module.down_revision == "0010_match_context_referee"
    assert callable(module.upgrade)
    assert callable(module.downgrade)
