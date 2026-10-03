"""Add match_telemetry table for Understat xG/xA shot telemetry.

Revision ID: 0015_match_telemetry
Revises: 0014_social_auth_identities
Create Date: 2026-10-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0015_match_telemetry"
down_revision = "0014_social_auth_identities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "match_telemetry",
        sa.Column("match_id", sa.Integer(), nullable=False),
        # provider_id stores the raw Understat numeric match identifier as a string
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column(
            "home_team_slug",
            sa.String(length=128),
            sa.ForeignKey("teams.id", name="fk_match_telemetry_home_team"),
            nullable=False,
        ),
        sa.Column(
            "away_team_slug",
            sa.String(length=128),
            sa.ForeignKey("teams.id", name="fk_match_telemetry_away_team"),
            nullable=False,
        ),
        # xG / xA per side
        sa.Column("home_xg", sa.Float(), nullable=True),
        sa.Column("away_xg", sa.Float(), nullable=True),
        sa.Column("home_xa", sa.Float(), nullable=True),
        sa.Column("away_xa", sa.Float(), nullable=True),
        # Full shot-level telemetry from Understat's shotsData payload
        sa.Column(
            "shot_telemetry",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("match_id", name="pk_match_telemetry"),
    )
    op.create_index(
        "ix_match_telemetry_home_slug",
        "match_telemetry",
        ["home_team_slug"],
    )
    op.create_index(
        "ix_match_telemetry_away_slug",
        "match_telemetry",
        ["away_team_slug"],
    )


def downgrade() -> None:
    op.drop_index("ix_match_telemetry_away_slug", table_name="match_telemetry")
    op.drop_index("ix_match_telemetry_home_slug", table_name="match_telemetry")
    op.drop_table("match_telemetry")
