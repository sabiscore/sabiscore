"""Add MatchContext and RefereeProfile tables for analytical intelligence.

Revision ID: 0010_match_context_referee
Revises: 0009_quarantine_market_closings
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_match_context_referee"
down_revision = "0009_quarantine_market_closings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. referee_profiles ───────────────────────────────────────────────────
    op.create_table(
        "referee_profiles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("avg_yellow_cards", sa.Float(), nullable=True),
        sa.Column("avg_red_cards", sa.Float(), nullable=True),
        sa.Column("penalties_awarded", sa.Integer(), nullable=True),
        sa.Column("strictness_index", sa.Float(), nullable=True),
        sa.Column("sample_size", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("name", name="uq_referee_profiles_name"),
    )
    op.create_index("ix_referee_profiles_name", "referee_profiles", ["name"])

    # ── 2. match_contexts ─────────────────────────────────────────────────────
    op.create_table(
        "match_contexts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("match_id", sa.String(), sa.ForeignKey("matches.id"), nullable=False),
        sa.Column("weather_condition", sa.String(), nullable=True),
        sa.Column("weather_source", sa.String(), nullable=True),
        sa.Column("weather_observed_at", sa.DateTime(), nullable=True),
        sa.Column("fatigue_index_home", sa.Float(), nullable=True),
        sa.Column("fatigue_index_away", sa.Float(), nullable=True),
        sa.Column("ppda_home", sa.Float(), nullable=True),
        sa.Column("ppda_away", sa.Float(), nullable=True),
        sa.Column("psxg_home", sa.Float(), nullable=True),
        sa.Column("psxg_away", sa.Float(), nullable=True),
        sa.Column("source_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("match_id", name="uq_match_contexts_match_id"),
    )
    op.create_index("ix_match_contexts_match_id", "match_contexts", ["match_id"])


def downgrade() -> None:
    op.drop_index("ix_match_contexts_match_id", table_name="match_contexts")
    op.drop_table("match_contexts")
    op.drop_index("ix_referee_profiles_name", table_name="referee_profiles")
    op.drop_table("referee_profiles")
