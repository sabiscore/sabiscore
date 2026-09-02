"""Enforce notification dispatch idempotency.

<<<<<<<< HEAD:backend/alembic/versions/0012_notif_log_idempotency.py
Revision ID: 0012_notif_log_idempotency
========
Revision ID: 0012_notification_idempotency
>>>>>>>> 179ca18 (Fix notification dispatch review feedback):backend/alembic/versions/0012_notification_idempotency.py
Revises: 0011_user_identity_dev_platform

Note: filename/revision id shortened from the original
0012_notification_log_idempotency (33 chars) to fit PostgreSQL's
alembic_version.version_num column (VARCHAR(32)) — same class of bug fixed
once before for migration 0011 (commit a1141c1). Content unchanged;
`test_every_alembic_revision_id_fits_the_version_num_column` caught it before
this migration was ever deployed.
"""

from alembic import op


<<<<<<<< HEAD:backend/alembic/versions/0012_notif_log_idempotency.py
revision = "0012_notif_log_idempotency"
========
revision = "0012_notification_idempotency"
>>>>>>>> 179ca18 (Fix notification dispatch review feedback):backend/alembic/versions/0012_notification_idempotency.py
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
