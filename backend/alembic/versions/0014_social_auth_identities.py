"""Add social authentication identities and user profile fields.

Revision ID: 0014_social_auth_identities
Revises: 0013_push_devices
"""

from alembic import op
import sqlalchemy as sa

revision = "0014_social_auth_identities"
down_revision = "0013_push_devices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "hashed_password",
        existing_type=sa.String(),
        nullable=True,
    )
    op.add_column("users", sa.Column("username", sa.String(length=32), nullable=True))
    op.add_column(
        "users", sa.Column("avatar_url", sa.String(length=1000), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column(
            "email_verified", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.create_table(
        "user_identities",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_subject", sa.String(length=255), nullable=False),
        sa.Column("provider_email", sa.String(length=320), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "provider",
            "provider_subject",
            name="uq_user_identities_provider_subject",
        ),
    )
    op.create_index("ix_user_identities_user_id", "user_identities", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_identities_user_id", table_name="user_identities")
    op.drop_table("user_identities")

    op.drop_index("ix_users_username", table_name="users")
    op.drop_column("users", "email_verified")
    op.drop_column("users", "avatar_url")
    op.drop_column("users", "username")
    op.alter_column(
        "users",
        "hashed_password",
        existing_type=sa.String(),
        nullable=False,
    )
