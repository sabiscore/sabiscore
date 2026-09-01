"""User identity, developer platform, analytics, and notification schemas.

Revision ID: 0011_user_identity_dev_platform
Revises: 0010_match_context_referee

Note: the revision id is intentionally shorter than the migration's own
description. Alembic's bookkeeping table (``alembic_version.version_num``)
defaults to VARCHAR(32); every prior revision in this repo stays under that
ceiling ("0009_quarantine_market_closings" is exactly 32) and this one must
too, or `alembic upgrade head`'s final version-stamp UPDATE raises
StringDataRightTruncation on real PostgreSQL (SQLite doesn't enforce VARCHAR
length, so this only surfaces once a Postgres-backed gate runs the chain).
"""

from alembic import op
import sqlalchemy as sa


revision = "0011_user_identity_dev_platform"
down_revision = "0010_match_context_referee"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. user_favorites ─────────────────────────────────────────────────────
    op.create_table(
        "user_favorites",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("anonymous_session_id", sa.String(), nullable=True),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "entity_type", "entity_id", name="uq_user_favorites_user_entity"),
    )
    op.create_index("ix_user_favorites_user_id", "user_favorites", ["user_id"])
    op.create_index("ix_user_favorites_anon_id", "user_favorites", ["anonymous_session_id"])

    # ── 2. user_saved_matches ─────────────────────────────────────────────────
    op.create_table(
        "user_saved_matches",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("anonymous_session_id", sa.String(), nullable=True),
        sa.Column("match_id", sa.String(), nullable=False),
        sa.Column("target_outcome", sa.String(), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "match_id", name="uq_user_saved_matches_user_match"),
    )
    op.create_index("ix_user_saved_matches_user_id", "user_saved_matches", ["user_id"])
    op.create_index("ix_user_saved_matches_anon_id", "user_saved_matches", ["anonymous_session_id"])
    op.create_index("ix_user_saved_matches_match_id", "user_saved_matches", ["match_id"])

    # ── 3. user_preferences ───────────────────────────────────────────────────
    op.create_table(
        "user_preferences",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True, unique=True),
        sa.Column("anonymous_session_id", sa.String(), nullable=True, unique=True),
        sa.Column("odds_format", sa.String(), nullable=False, server_default="DECIMAL"),
        sa.Column("timezone", sa.String(), nullable=False, server_default="Africa/Lagos"),
        sa.Column("default_league", sa.String(), nullable=True, server_default="EPL"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_user_preferences_user_id", "user_preferences", ["user_id"])
    op.create_index("ix_user_preferences_anon_id", "user_preferences", ["anonymous_session_id"])

    # ── 4. api_keys ───────────────────────────────────────────────────────────
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("key_prefix", sa.String(), nullable=False),
        sa.Column("key_hash", sa.String(), nullable=False, unique=True),
        sa.Column("tier", sa.String(), nullable=False, server_default="FREE"),
        sa.Column("rate_limit_per_minute", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("daily_quota", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"])
    op.create_index("ix_api_keys_key_prefix", "api_keys", ["key_prefix"])
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"])

    # ── 5. analytics_events ───────────────────────────────────────────────────
    op.create_table(
        "analytics_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(), nullable=False, unique=True),
        sa.Column("anonymous_session_id", sa.String(), nullable=True),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("event_name", sa.String(), nullable=False),
        sa.Column("properties", sa.JSON(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=True),
        sa.Column("client_platform", sa.String(), nullable=True, server_default="web"),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_analytics_events_event_name", "analytics_events", ["event_name"])
    op.create_index("ix_analytics_events_user_id", "analytics_events", ["user_id"])
    op.create_index("ix_analytics_events_anon_id", "analytics_events", ["anonymous_session_id"])
    op.create_index("ix_analytics_events_timestamp", "analytics_events", ["timestamp"])

    # ── 6. user_notification_subscriptions ────────────────────────────────────
    op.create_table(
        "user_notification_subscriptions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("anonymous_session_id", sa.String(), nullable=True),
        sa.Column("match_id", sa.String(), nullable=True),
        sa.Column("subscription_type", sa.String(), nullable=False, server_default="KICKOFF_REMINDER"),
        sa.Column("channel", sa.String(), nullable=False, server_default="IN_APP"),
        sa.Column("destination", sa.String(), nullable=True),
        sa.Column("threshold_pct", sa.Float(), nullable=True),
        sa.Column("reminder_minutes_before", sa.Integer(), nullable=True, server_default="60"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_notif_subs_user_id", "user_notification_subscriptions", ["user_id"])
    op.create_index("ix_notif_subs_anon_id", "user_notification_subscriptions", ["anonymous_session_id"])
    op.create_index("ix_notif_subs_match_id", "user_notification_subscriptions", ["match_id"])

    # ── 7. user_notification_logs ─────────────────────────────────────────────
    op.create_table(
        "user_notification_logs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("anonymous_session_id", sa.String(), nullable=True),
        sa.Column("subscription_id", sa.String(), nullable=True),
        sa.Column("match_id", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False, server_default="INFO"),
        sa.Column("read", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_notif_logs_user_unread", "user_notification_logs", ["user_id", "read", "created_at"])
    op.create_index("ix_notif_logs_anon_unread", "user_notification_logs", ["anonymous_session_id", "read", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_notif_logs_anon_unread", table_name="user_notification_logs")
    op.drop_index("ix_notif_logs_user_unread", table_name="user_notification_logs")
    op.drop_table("user_notification_logs")

    op.drop_index("ix_notif_subs_match_id", table_name="user_notification_subscriptions")
    op.drop_index("ix_notif_subs_anon_id", table_name="user_notification_subscriptions")
    op.drop_index("ix_notif_subs_user_id", table_name="user_notification_subscriptions")
    op.drop_table("user_notification_subscriptions")

    op.drop_index("ix_analytics_events_timestamp", table_name="analytics_events")
    op.drop_index("ix_analytics_events_anon_id", table_name="analytics_events")
    op.drop_index("ix_analytics_events_user_id", table_name="analytics_events")
    op.drop_index("ix_analytics_events_event_name", table_name="analytics_events")
    op.drop_table("analytics_events")

    op.drop_index("ix_api_keys_key_hash", table_name="api_keys")
    op.drop_index("ix_api_keys_key_prefix", table_name="api_keys")
    op.drop_index("ix_api_keys_user_id", table_name="api_keys")
    op.drop_table("api_keys")

    op.drop_index("ix_user_preferences_anon_id", table_name="user_preferences")
    op.drop_index("ix_user_preferences_user_id", table_name="user_preferences")
    op.drop_table("user_preferences")

    op.drop_index("ix_user_saved_matches_match_id", table_name="user_saved_matches")
    op.drop_index("ix_user_saved_matches_anon_id", table_name="user_saved_matches")
    op.drop_index("ix_user_saved_matches_user_id", table_name="user_saved_matches")
    op.drop_table("user_saved_matches")

    op.drop_index("ix_user_favorites_anon_id", table_name="user_favorites")
    op.drop_index("ix_user_favorites_user_id", table_name="user_favorites")
    op.drop_table("user_favorites")
