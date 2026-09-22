"""CLV capture schema — market_snapshots extension + match_prediction_logs FK

Revision ID: 0005_clv_capture_schema
Revises: 0004_normalize_match_season
Create Date: 2026-08-05

docs/adr/0004-clv-capture.md: additive, nullable-only. Two additions beyond
the ADR's original text (see the ADR's addendum, added alongside this
migration): market_snapshots.canonical_fixture_id is relaxed from NOT NULL to
nullable, and a new market_snapshots.match_id column is added. Neither was in
the ADR as filed — implementation-time investigation found that
fixture_sync_service (the only writer of upcoming fixtures today) populates
only the legacy matches/teams/leagues tables, never canonical_fixtures, so a
non-nullable canonical_fixture_id FK would leave the capture job unable to
write against any fixture actually in the database. match_id (no FK, mirrors
match_prediction_logs.match_id's existing convention) is the real join key
until identity resolution work populates canonical_fixtures.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_clv_capture_schema"
down_revision = "0004_normalize_match_season"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("market_snapshots") as batch_op:
        batch_op.alter_column(
            "canonical_fixture_id", existing_type=sa.String(), nullable=True
        )
        batch_op.add_column(sa.Column("match_id", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column("home_implied_prob_devigged", sa.Float(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("draw_implied_prob_devigged", sa.Float(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("away_implied_prob_devigged", sa.Float(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "is_closing_line",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
    op.create_index("ix_market_snapshots_match_id", "market_snapshots", ["match_id"])

    with op.batch_alter_table("match_prediction_logs") as batch_op:
        batch_op.add_column(
            sa.Column("closing_market_snapshot_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_match_prediction_logs_closing_market_snapshot",
            "market_snapshots",
            ["closing_market_snapshot_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("match_prediction_logs") as batch_op:
        batch_op.drop_constraint(
            "fk_match_prediction_logs_closing_market_snapshot", type_="foreignkey"
        )
        batch_op.drop_column("closing_market_snapshot_id")

    op.drop_index("ix_market_snapshots_match_id", table_name="market_snapshots")
    with op.batch_alter_table("market_snapshots") as batch_op:
        batch_op.drop_column("is_closing_line")
        batch_op.drop_column("away_implied_prob_devigged")
        batch_op.drop_column("draw_implied_prob_devigged")
        batch_op.drop_column("home_implied_prob_devigged")
        batch_op.drop_column("match_id")
        # ponytail: canonical_fixture_id stays nullable on downgrade — nothing
        # ever wrote a NULL-invalidating row while nullable was in effect,
        # since MarketSnapshot had zero write callers before this migration
        # shipped, so there is no data to conflict with re-tightening it. Not
        # re-tightened anyway: the "nothing populates canonical_fixtures"
        # reality that motivated relaxing it does not reverse with this migration.
