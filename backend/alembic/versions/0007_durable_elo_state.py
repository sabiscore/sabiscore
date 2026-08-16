"""Add durable real-identity Elo rating snapshots.

Revision ID: 0007_durable_elo_state
Revises: 0006_canonical_league_ids
"""

from alembic import op
import sqlalchemy as sa

revision = "0007_durable_elo_state"
down_revision = "0006_canonical_league_ids"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "elo_rating_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("match_id", sa.String(), sa.ForeignKey("matches.id"), nullable=False),
        sa.Column("team_id", sa.String(), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("pre_match_elo", sa.Float(), nullable=False),
        sa.Column("post_match_elo", sa.Float(), nullable=False),
        sa.Column("league", sa.String(), nullable=False),
        sa.Column("season", sa.String(), nullable=False),
        sa.Column("match_date", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("match_id", "team_id", name="uq_elo_rating_match_team"),
    )
    op.create_index(
        "ix_elo_rating_team_league_date",
        "elo_rating_snapshots",
        ["team_id", "league", "match_date"],
    )
    op.create_index("ix_elo_rating_match", "elo_rating_snapshots", ["match_id"])


def downgrade() -> None:
    op.drop_index("ix_elo_rating_match", table_name="elo_rating_snapshots")
    op.drop_index("ix_elo_rating_team_league_date", table_name="elo_rating_snapshots")
    op.drop_table("elo_rating_snapshots")
