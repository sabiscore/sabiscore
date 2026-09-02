"""Add browser push device registry for the WEB_PUSH notification channel.

Revision ID: 0013_push_devices
Revises: 0012_notif_log_idempotency

Stores the RFC 8030 push endpoint and its RFC 8291 key material for a browser
that has granted notification permission. Deliberately a separate table from
`user_notification_subscriptions`: that row records *what* someone wants to be
told about, this one records *where* a WEB_PUSH message can be delivered. A
device outlives any single match subscription.

`endpoint` carries the unique constraint because it is the device identity as
far as the push service is concerned — a re-subscribe from the same browser
must update the stored keys in place, not accumulate rows.
"""

import sqlalchemy as sa
from alembic import op


revision = "0013_push_devices"
down_revision = "0012_notif_log_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "push_devices",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("anonymous_session_id", sa.String(), nullable=True),
        sa.Column("endpoint", sa.String(), nullable=False),
        sa.Column("p256dh", sa.String(), nullable=False),
        sa.Column("auth", sa.String(), nullable=False),
        sa.Column("user_agent", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_delivery_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("endpoint", name="uq_push_devices_endpoint"),
    )
    op.create_index("ix_push_devices_user_id", "push_devices", ["user_id"])
    op.create_index("ix_push_devices_anon_id", "push_devices", ["anonymous_session_id"])


def downgrade() -> None:
    op.drop_index("ix_push_devices_anon_id", table_name="push_devices")
    op.drop_index("ix_push_devices_user_id", table_name="push_devices")
    op.drop_table("push_devices")
