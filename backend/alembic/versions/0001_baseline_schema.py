"""baseline schema with explicit Alembic operations

Revision ID: 0001_baseline_schema
Revises:
Create Date: 2026-06-27
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_baseline_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False, unique=True),
        sa.Column("full_name", sa.String(), nullable=True),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("is_superuser", sa.Boolean(), nullable=True),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "leagues",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("country", sa.String(), nullable=True),
        sa.Column("tier", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_leagues_name", "leagues", ["name"])

    op.create_table(
        "teams",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("league_id", sa.String(), sa.ForeignKey("leagues.id"), nullable=True),
        sa.Column("country", sa.String(), nullable=True),
        sa.Column("founded_year", sa.Integer(), nullable=True),
        sa.Column("stadium", sa.String(), nullable=True),
        sa.Column("manager", sa.String(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_teams_league", "teams", ["league_id"])
    op.create_index("ix_teams_name", "teams", ["name"])

    op.create_table(
        "players",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("team_id", sa.String(), sa.ForeignKey("teams.id"), nullable=True),
        sa.Column("position", sa.String(), nullable=True),
        sa.Column("nationality", sa.String(), nullable=True),
        sa.Column("age", sa.Integer(), nullable=True),
        sa.Column("market_value", sa.Float(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "matches",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("league_id", sa.String(), sa.ForeignKey("leagues.id"), nullable=True),
        sa.Column(
            "home_team_id", sa.String(), sa.ForeignKey("teams.id"), nullable=True
        ),
        sa.Column(
            "away_team_id", sa.String(), sa.ForeignKey("teams.id"), nullable=True
        ),
        sa.Column("match_date", sa.DateTime(), nullable=False),
        sa.Column("season", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("home_score", sa.Integer(), nullable=True),
        sa.Column("away_score", sa.Integer(), nullable=True),
        sa.Column("venue", sa.String(), nullable=True),
        sa.Column("referee", sa.String(), nullable=True),
        sa.Column("competition_stage", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_matches_league_date", "matches", ["league_id", "match_date"])
    op.create_index("ix_matches_home", "matches", ["home_team_id"])
    op.create_index("ix_matches_away", "matches", ["away_team_id"])

    op.create_table(
        "match_stats",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("match_id", sa.String(), sa.ForeignKey("matches.id"), nullable=True),
        sa.Column("team_id", sa.String(), sa.ForeignKey("teams.id"), nullable=True),
        sa.Column("possession", sa.Float(), nullable=True),
        sa.Column("shots", sa.Integer(), nullable=True),
        sa.Column("shots_on_target", sa.Integer(), nullable=True),
        sa.Column("corners", sa.Integer(), nullable=True),
        sa.Column("fouls", sa.Integer(), nullable=True),
        sa.Column("yellow_cards", sa.Integer(), nullable=True),
        sa.Column("red_cards", sa.Integer(), nullable=True),
        sa.Column("offsides", sa.Integer(), nullable=True),
        sa.Column("expected_goals", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_match_stats_match_team", "match_stats", ["match_id", "team_id"])

    op.create_table(
        "predictions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("match_id", sa.String(), sa.ForeignKey("matches.id"), nullable=True),
        sa.Column("model_version", sa.String(), nullable=True),
        sa.Column("home_win_prob", sa.Float(), nullable=True),
        sa.Column("draw_prob", sa.Float(), nullable=True),
        sa.Column("away_win_prob", sa.Float(), nullable=True),
        sa.Column("expected_goals_home", sa.Float(), nullable=True),
        sa.Column("expected_goals_away", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("features", sa.JSON(), nullable=True),
        sa.Column("shap_values", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_predictions_match", "predictions", ["match_id"])
    op.create_index("ix_predictions_model", "predictions", ["model_version"])

    op.create_table(
        "odds",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("match_id", sa.String(), sa.ForeignKey("matches.id"), nullable=True),
        sa.Column("bookmaker", sa.String(), nullable=True),
        sa.Column("home_win", sa.Float(), nullable=True),
        sa.Column("draw", sa.Float(), nullable=True),
        sa.Column("away_win", sa.Float(), nullable=True),
        sa.Column("over_under", sa.Float(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_odds_match_timestamp", "odds", ["match_id", "timestamp"])

    op.create_table(
        "value_bets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("match_id", sa.String(), sa.ForeignKey("matches.id"), nullable=True),
        sa.Column(
            "prediction_id",
            sa.Integer(),
            sa.ForeignKey("predictions.id"),
            nullable=True,
        ),
        sa.Column("bet_type", sa.String(), nullable=True),
        sa.Column("bookmaker", sa.String(), nullable=True),
        sa.Column("market_odds", sa.Float(), nullable=True),
        sa.Column("expected_odds", sa.Float(), nullable=True),
        sa.Column("value_percentage", sa.Float(), nullable=True),
        sa.Column("kelly_stake", sa.Float(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_value_bets_match", "value_bets", ["match_id"])
    op.create_index("ix_value_bets_prediction", "value_bets", ["prediction_id"])

    op.create_table(
        "league_standings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("league", sa.String(), sa.ForeignKey("leagues.id"), nullable=True),
        sa.Column("team_id", sa.String(), sa.ForeignKey("teams.id"), nullable=True),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("points", sa.Integer(), nullable=True),
        sa.Column("played", sa.Integer(), nullable=True),
        sa.Column("won", sa.Integer(), nullable=True),
        sa.Column("drawn", sa.Integer(), nullable=True),
        sa.Column("lost", sa.Integer(), nullable=True),
        sa.Column("goals_for", sa.Integer(), nullable=True),
        sa.Column("goals_against", sa.Integer(), nullable=True),
        sa.Column("goal_difference", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_league_standings_league_team", "league_standings", ["league", "team_id"]
    )

    op.create_table(
        "match_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("match_id", sa.String(), sa.ForeignKey("matches.id"), nullable=True),
        sa.Column("event_time", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(), nullable=True),
        sa.Column("team_id", sa.String(), sa.ForeignKey("teams.id"), nullable=True),
        sa.Column("player_id", sa.String(), sa.ForeignKey("players.id"), nullable=True),
        sa.Column("xg_value", sa.Float(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("event_metadata", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_match_events_match_time", "match_events", ["match_id", "event_time"]
    )
    op.create_index("ix_match_events_type", "match_events", ["event_type"])

    op.create_table(
        "odds_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("match_id", sa.String(), sa.ForeignKey("matches.id"), nullable=True),
        sa.Column("bookmaker", sa.String(), nullable=True),
        sa.Column("market_type", sa.String(), nullable=True),
        sa.Column("home_win", sa.Float(), nullable=True),
        sa.Column("draw", sa.Float(), nullable=True),
        sa.Column("away_win", sa.Float(), nullable=True),
        sa.Column("over_15", sa.Float(), nullable=True),
        sa.Column("under_15", sa.Float(), nullable=True),
        sa.Column("over_25", sa.Float(), nullable=True),
        sa.Column("under_25", sa.Float(), nullable=True),
        sa.Column("over_35", sa.Float(), nullable=True),
        sa.Column("under_35", sa.Float(), nullable=True),
        sa.Column("btts_yes", sa.Float(), nullable=True),
        sa.Column("btts_no", sa.Float(), nullable=True),
        sa.Column("asian_handicap_line", sa.Float(), nullable=True),
        sa.Column("asian_handicap_home", sa.Float(), nullable=True),
        sa.Column("asian_handicap_away", sa.Float(), nullable=True),
        sa.Column("total_matched", sa.Float(), nullable=True),
        sa.Column("home_volume", sa.Float(), nullable=True),
        sa.Column("draw_volume", sa.Float(), nullable=True),
        sa.Column("away_volume", sa.Float(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_odds_history_match_timestamp", "odds_history", ["match_id", "timestamp"]
    )
    op.create_index("ix_odds_history_bookmaker", "odds_history", ["bookmaker"])

    op.create_table(
        "feature_vectors",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("match_id", sa.String(), sa.ForeignKey("matches.id"), nullable=True),
        sa.Column("home_form_5", sa.Float(), nullable=True),
        sa.Column("home_form_10", sa.Float(), nullable=True),
        sa.Column("away_form_5", sa.Float(), nullable=True),
        sa.Column("away_form_10", sa.Float(), nullable=True),
        sa.Column("home_xg_avg_5", sa.Float(), nullable=True),
        sa.Column("home_xg_conceded_avg_5", sa.Float(), nullable=True),
        sa.Column("away_xg_avg_5", sa.Float(), nullable=True),
        sa.Column("away_xg_conceded_avg_5", sa.Float(), nullable=True),
        sa.Column("home_fatigue_index", sa.Float(), nullable=True),
        sa.Column("away_fatigue_index", sa.Float(), nullable=True),
        sa.Column("home_days_rest", sa.Integer(), nullable=True),
        sa.Column("away_days_rest", sa.Integer(), nullable=True),
        sa.Column("home_crowd_boost", sa.Float(), nullable=True),
        sa.Column("home_advantage_coefficient", sa.Float(), nullable=True),
        sa.Column("home_momentum_lambda", sa.Float(), nullable=True),
        sa.Column("away_momentum_lambda", sa.Float(), nullable=True),
        sa.Column("market_panic_score", sa.Float(), nullable=True),
        sa.Column("odds_volatility_1h", sa.Float(), nullable=True),
        sa.Column("odds_volatility_24h", sa.Float(), nullable=True),
        sa.Column("h2h_home_wins", sa.Integer(), nullable=True),
        sa.Column("h2h_draws", sa.Integer(), nullable=True),
        sa.Column("h2h_away_wins", sa.Integer(), nullable=True),
        sa.Column("h2h_avg_goals", sa.Float(), nullable=True),
        sa.Column("referee_home_bias", sa.Float(), nullable=True),
        sa.Column("referee_cards_per_game", sa.Float(), nullable=True),
        sa.Column("home_squad_value", sa.Float(), nullable=True),
        sa.Column("away_squad_value", sa.Float(), nullable=True),
        sa.Column("home_missing_value", sa.Float(), nullable=True),
        sa.Column("away_missing_value", sa.Float(), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("precipitation", sa.Float(), nullable=True),
        sa.Column("wind_speed", sa.Float(), nullable=True),
        sa.Column("home_elo", sa.Float(), nullable=True),
        sa.Column("away_elo", sa.Float(), nullable=True),
        sa.Column("elo_difference", sa.Float(), nullable=True),
        sa.Column("feature_vector_full", sa.JSON(), nullable=True),
        sa.Column("features_version", sa.String(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_feature_vectors_match", "feature_vectors", ["match_id"])
    op.create_index("ix_feature_vectors_timestamp", "feature_vectors", ["timestamp"])

    op.create_table(
        "player_valuations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("player_id", sa.String(), sa.ForeignKey("players.id"), nullable=True),
        sa.Column("team_id", sa.String(), sa.ForeignKey("teams.id"), nullable=True),
        sa.Column("valuation_date", sa.DateTime(), nullable=True),
        sa.Column("market_value", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_player_valuations_player_date",
        "player_valuations",
        ["player_id", "valuation_date"],
    )

    op.create_table(
        "scraping_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("job_type", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("records_processed", sa.Integer(), nullable=True),
        sa.Column("records_failed", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("execution_time_seconds", sa.Float(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=True),
        sa.Column("job_metadata", sa.JSON(), nullable=True),
    )
    op.create_index(
        "ix_scraping_logs_source_status", "scraping_logs", ["source", "status"]
    )
    op.create_index("ix_scraping_logs_timestamp", "scraping_logs", ["timestamp"])


def downgrade() -> None:
    op.drop_index("ix_scraping_logs_timestamp", table_name="scraping_logs")
    op.drop_index("ix_scraping_logs_source_status", table_name="scraping_logs")
    op.drop_table("scraping_logs")

    op.drop_index("ix_player_valuations_player_date", table_name="player_valuations")
    op.drop_table("player_valuations")

    op.drop_index("ix_feature_vectors_timestamp", table_name="feature_vectors")
    op.drop_index("ix_feature_vectors_match", table_name="feature_vectors")
    op.drop_table("feature_vectors")

    op.drop_index("ix_odds_history_bookmaker", table_name="odds_history")
    op.drop_index("ix_odds_history_match_timestamp", table_name="odds_history")
    op.drop_table("odds_history")

    op.drop_index("ix_match_events_type", table_name="match_events")
    op.drop_index("ix_match_events_match_time", table_name="match_events")
    op.drop_table("match_events")

    op.drop_index("ix_league_standings_league_team", table_name="league_standings")
    op.drop_table("league_standings")

    op.drop_index("ix_value_bets_prediction", table_name="value_bets")
    op.drop_index("ix_value_bets_match", table_name="value_bets")
    op.drop_table("value_bets")

    op.drop_index("ix_odds_match_timestamp", table_name="odds")
    op.drop_table("odds")

    op.drop_index("ix_predictions_model", table_name="predictions")
    op.drop_index("ix_predictions_match", table_name="predictions")
    op.drop_table("predictions")

    op.drop_index("ix_match_stats_match_team", table_name="match_stats")
    op.drop_table("match_stats")

    op.drop_index("ix_matches_away", table_name="matches")
    op.drop_index("ix_matches_home", table_name="matches")
    op.drop_index("ix_matches_league_date", table_name="matches")
    op.drop_table("matches")

    op.drop_table("players")

    op.drop_index("ix_teams_name", table_name="teams")
    op.drop_index("ix_teams_league", table_name="teams")
    op.drop_table("teams")

    op.drop_index("ix_leagues_name", table_name="leagues")
    op.drop_table("leagues")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
