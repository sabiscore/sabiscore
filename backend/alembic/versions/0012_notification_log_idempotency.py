"""Enforce notification dispatch idempotency.

Revision ID: 0012_notification_log_idempotency
Revises: 0011_user_identity_dev_platform
"""

from alembic import op


revision = "0012_notification_log_idempotency"
down_revision = "0011_user_identity_dev_platform"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_notification_log_subscription_match_category",
        "user_notification_logs",
        ["subscription_id", "match_id", "category"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_notification_log_subscription_match_category",
        "user_notification_logs",
        type_="unique",
    )
