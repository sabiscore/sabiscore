"""canonical identity and provider observation tables

Revision ID: 0002_canonical_identity
Revises: 0001_baseline_schema
Create Date: 2026-06-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_canonical_identity"
down_revision = "0001_baseline_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_request_summaries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("trust_tier", sa.String(), nullable=False),
        sa.Column("acquired_at", sa.DateTime(), nullable=False),
        sa.Column("provider_timestamp", sa.DateTime(), nullable=True),
        sa.Column("quota_limit", sa.Integer(), nullable=True),
        sa.Column("quota_remaining", sa.Integer(), nullable=True),
        sa.Column("quota_reset_at", sa.DateTime(), nullable=True),
        sa.Column("quota_cost", sa.Integer(), nullable=True),
        sa.Column("warnings", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("raw_snapshot_id", sa.String(), nullable=True),
        sa.Column("response_hash", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_provider_request_provider_time",
        "provider_request_summaries",
        ["provider", "acquired_at"],
    )
    op.create_index(
        "ix_provider_request_status", "provider_request_summaries", ["status"]
    )

    op.create_table(
        "provider_capabilities",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("competition", sa.String(), nullable=False),
        sa.Column("season", sa.String(), nullable=True),
        sa.Column("fixtures", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("standings", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("lineups", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("injuries", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column(
            "team_statistics", sa.Boolean(), nullable=True, server_default=sa.false()
        ),
        sa.Column(
            "player_statistics", sa.Boolean(), nullable=True, server_default=sa.false()
        ),
        sa.Column("odds", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("xg", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column(
            "provider_predictions",
            sa.Boolean(),
            nullable=True,
            server_default=sa.false(),
        ),
        sa.Column("checked_at", sa.DateTime(), nullable=False),
        sa.Column("notes", sa.JSON(), nullable=True),
    )
    op.create_index(
        "ix_provider_capability_provider_comp",
        "provider_capabilities",
        ["provider", "competition"],
    )

    op.create_table(
        "provider_quota_observations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("quota_limit", sa.Integer(), nullable=True),
        sa.Column("quota_remaining", sa.Integer(), nullable=True),
        sa.Column("quota_reset_at", sa.DateTime(), nullable=True),
        sa.Column("quota_cost", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_provider_quota_provider_time",
        "provider_quota_observations",
        ["provider", "observed_at"],
    )

    op.create_table(
        "canonical_competitions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "coverage_tier", sa.String(), nullable=False, server_default="STANDARD"
        ),
        sa.Column("active", sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "canonical_teams",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "competition_id",
            sa.String(),
            sa.ForeignKey("canonical_competitions.id"),
            nullable=True,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("normalized_name", sa.String(), nullable=False),
        sa.Column("country", sa.String(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_canonical_teams_competition_name",
        "canonical_teams",
        ["competition_id", "name"],
    )

    op.create_table(
        "canonical_fixtures",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "competition_id",
            sa.String(),
            sa.ForeignKey("canonical_competitions.id"),
            nullable=True,
        ),
        sa.Column("season", sa.String(), nullable=True),
        sa.Column(
            "home_team_id",
            sa.String(),
            sa.ForeignKey("canonical_teams.id"),
            nullable=True,
        ),
        sa.Column(
            "away_team_id",
            sa.String(),
            sa.ForeignKey("canonical_teams.id"),
            nullable=True,
        ),
        sa.Column("kickoff_utc", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="scheduled"),
        sa.Column("venue_id", sa.String(), nullable=True),
        sa.Column(
            "reconciliation_status",
            sa.String(),
            nullable=False,
            server_default="UNKNOWN",
        ),
        sa.Column("reconciliation_confidence", sa.Float(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_canonical_fixtures_comp_kickoff",
        "canonical_fixtures",
        ["competition_id", "kickoff_utc"],
    )

    op.create_table(
        "provider_event_mappings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("provider_event_id", sa.String(), nullable=False),
        sa.Column(
            "canonical_fixture_id",
            sa.String(),
            sa.ForeignKey("canonical_fixtures.id"),
            nullable=True,
        ),
        sa.Column("competition", sa.String(), nullable=False),
        sa.Column("reconciliation_status", sa.String(), nullable=False),
        sa.Column("reconciliation_confidence", sa.Float(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("checked_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_provider_event_provider_id",
        "provider_event_mappings",
        ["provider", "provider_event_id"],
    )
    op.create_index(
        "ix_provider_event_fixture", "provider_event_mappings", ["canonical_fixture_id"]
    )

    op.create_table(
        "market_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "canonical_fixture_id",
            sa.String(),
            sa.ForeignKey("canonical_fixtures.id"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("bookmaker", sa.String(), nullable=False),
        sa.Column("market_type", sa.String(), nullable=False, server_default="1X2"),
        sa.Column("home_odds", sa.Float(), nullable=False),
        sa.Column("draw_odds", sa.Float(), nullable=False),
        sa.Column("away_odds", sa.Float(), nullable=False),
        sa.Column("provider_timestamp", sa.DateTime(), nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("coherent", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "executable", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("provenance", sa.JSON(), nullable=True),
    )
    op.create_index(
        "ix_market_snapshots_fixture_time",
        "market_snapshots",
        ["canonical_fixture_id", "captured_at"],
    )
    op.create_index("ix_market_snapshots_bookmaker", "market_snapshots", ["bookmaker"])

    op.create_table(
        "match_prediction_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("match_id", sa.String(), nullable=False),
        sa.Column(
            "canonical_fixture_id",
            sa.String(),
            sa.ForeignKey("canonical_fixtures.id"),
            nullable=True,
        ),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("calibration_method", sa.String(), nullable=True),
        sa.Column("home_probability", sa.Float(), nullable=False),
        sa.Column("draw_probability", sa.Float(), nullable=False),
        sa.Column("away_probability", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("input_hash", sa.String(), nullable=True),
        sa.Column("decision_id", sa.String(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_match_prediction_logs_match_time",
        "match_prediction_logs",
        ["match_id", "created_at"],
    )
    op.create_index(
        "ix_match_prediction_logs_fixture",
        "match_prediction_logs",
        ["canonical_fixture_id"],
    )

    op.create_table(
        "provider_health_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("checked_at", sa.DateTime(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("warnings", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
    )
    op.create_index(
        "ix_provider_health_provider_time",
        "provider_health_log",
        ["provider", "checked_at"],
    )
    op.create_index("ix_provider_health_status", "provider_health_log", ["status"])

    op.create_table(
        "provider_capability_observations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("competition", sa.String(), nullable=False),
        sa.Column("season", sa.String(), nullable=True),
        sa.Column("checked_at", sa.DateTime(), nullable=False),
        sa.Column("capabilities_json", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_provider_capability_obs_provider_comp",
        "provider_capability_observations",
        ["provider", "competition", "checked_at"],
    )

    op.create_table(
        "circuit_state",
        sa.Column("provider", sa.String(), primary_key=True),
        sa.Column("open", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_failure_at", sa.DateTime(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("retry_after", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("circuit_state")

    op.drop_index(
        "ix_provider_capability_obs_provider_comp",
        table_name="provider_capability_observations",
    )
    op.drop_table("provider_capability_observations")

    op.drop_index("ix_provider_health_status", table_name="provider_health_log")
    op.drop_index("ix_provider_health_provider_time", table_name="provider_health_log")
    op.drop_table("provider_health_log")

    op.drop_index(
        "ix_match_prediction_logs_fixture", table_name="match_prediction_logs"
    )
    op.drop_index(
        "ix_match_prediction_logs_match_time", table_name="match_prediction_logs"
    )
    op.drop_table("match_prediction_logs")

    op.drop_index("ix_market_snapshots_bookmaker", table_name="market_snapshots")
    op.drop_index("ix_market_snapshots_fixture_time", table_name="market_snapshots")
    op.drop_table("market_snapshots")

    op.drop_index("ix_provider_event_fixture", table_name="provider_event_mappings")
    op.drop_index("ix_provider_event_provider_id", table_name="provider_event_mappings")
    op.drop_table("provider_event_mappings")

    op.drop_index("ix_canonical_fixtures_comp_kickoff", table_name="canonical_fixtures")
    op.drop_table("canonical_fixtures")

    op.drop_index("ix_canonical_teams_competition_name", table_name="canonical_teams")
    op.drop_table("canonical_teams")
    op.drop_table("canonical_competitions")

    op.drop_index(
        "ix_provider_quota_provider_time", table_name="provider_quota_observations"
    )
    op.drop_table("provider_quota_observations")

    op.drop_index(
        "ix_provider_capability_provider_comp", table_name="provider_capabilities"
    )
    op.drop_table("provider_capabilities")

    op.drop_index("ix_provider_request_status", table_name="provider_request_summaries")
    op.drop_index(
        "ix_provider_request_provider_time", table_name="provider_request_summaries"
    )
    op.drop_table("provider_request_summaries")
