"""Add PIT provenance and governance columns to match_telemetry.

Revision ID: 0016_match_telemetry_pit_provenance
Revises: 0015_match_telemetry
Create Date: 2026-10-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016_match_telemetry_pit_provenance"
down_revision = "0015_match_telemetry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "match_telemetry",
        sa.Column("kickoff_utc", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "match_telemetry",
        sa.Column(
            "retrieved_at",
            sa.DateTime(),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.add_column(
        "match_telemetry",
        sa.Column(
            "observation_timestamp",
            sa.DateTime(),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.add_column(
        "match_telemetry",
        sa.Column("payload_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "match_telemetry",
        sa.Column(
            "source_policy",
            sa.String(length=64),
            server_default="AUTHORIZED_PRODUCTION_SOURCE",
            nullable=False,
        ),
    )
    op.create_index(
        "ix_match_telemetry_kickoff",
        "match_telemetry",
        ["kickoff_utc"],
    )


def downgrade() -> None:
    op.drop_index("ix_match_telemetry_kickoff", table_name="match_telemetry")
    op.drop_column("match_telemetry", "source_policy")
    op.drop_column("match_telemetry", "payload_sha256")
    op.drop_column("match_telemetry", "observation_timestamp")
    op.drop_column("match_telemetry", "retrieved_at")
    op.drop_column("match_telemetry", "kickoff_utc")
