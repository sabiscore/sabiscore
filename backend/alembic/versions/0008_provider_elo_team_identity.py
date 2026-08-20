"""Add provider identity bridge to Elo-bearing application teams.

Revision ID: 0008_provider_elo_team_identity
Revises: 0007_durable_elo_state
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_provider_elo_team_identity"
down_revision = "0007_durable_elo_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_elo_team_mappings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("provider_team_id", sa.String(), nullable=False),
        sa.Column("provider_team_name", sa.String(), nullable=False),
        sa.Column("competition", sa.String(), nullable=False),
        sa.Column("team_id", sa.String(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("reconciliation_status", sa.String(), nullable=False),
        sa.Column("reconciliation_confidence", sa.Float(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("checked_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "provider",
            "provider_team_id",
            "competition",
            name="uq_provider_elo_team_identity",
        ),
    )
    op.create_index(
        "ix_provider_elo_team_provider_id",
        "provider_elo_team_mappings",
        ["provider", "provider_team_id"],
    )
    op.create_index(
        "ix_provider_elo_team_team_id",
        "provider_elo_team_mappings",
        ["team_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_provider_elo_team_team_id", table_name="provider_elo_team_mappings")
    op.drop_index("ix_provider_elo_team_provider_id", table_name="provider_elo_team_mappings")
    op.drop_table("provider_elo_team_mappings")
