"""provider team identity reconciliation table

Revision ID: 0003_team_reconciliation
Revises: 0002_canonical_identity
Create Date: 2026-06-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_team_reconciliation"
down_revision = "0002_canonical_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_team_mappings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("provider_team_id", sa.String(), nullable=False),
        sa.Column("provider_team_name", sa.String(), nullable=False),
        sa.Column(
            "canonical_team_id",
            sa.String(),
            sa.ForeignKey("canonical_teams.id"),
            nullable=True,
        ),
        sa.Column("competition", sa.String(), nullable=False),
        sa.Column("reconciliation_status", sa.String(), nullable=False),
        sa.Column("reconciliation_confidence", sa.Float(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("checked_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_provider_team_provider_id",
        "provider_team_mappings",
        ["provider", "provider_team_id"],
    )
    op.create_index(
        "ix_provider_team_canonical", "provider_team_mappings", ["canonical_team_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_provider_team_canonical", table_name="provider_team_mappings")
    op.drop_index("ix_provider_team_provider_id", table_name="provider_team_mappings")
    op.drop_table("provider_team_mappings")
