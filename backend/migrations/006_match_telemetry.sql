-- ==============================================================================
-- Migration 006: Understat Match Telemetry
-- ==============================================================================
-- Creates the match_telemetry table for storing Understat expected goals (xG),
-- expected assists (xA), and granular JSONB shot telemetry.
-- Includes foreign keys mapping home and away team slugs to the core teams table.

CREATE TABLE IF NOT EXISTS match_telemetry (
    match_id INTEGER PRIMARY KEY,
    provider_id VARCHAR(64) NOT NULL,
    home_team_slug VARCHAR(128) NOT NULL,
    away_team_slug VARCHAR(128) NOT NULL,
    home_xg DOUBLE PRECISION NULL,
    away_xg DOUBLE PRECISION NULL,
    home_xa DOUBLE PRECISION NULL,
    away_xa DOUBLE PRECISION NULL,
    shot_telemetry JSONB NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NULL,
    CONSTRAINT fk_match_telemetry_home_team FOREIGN KEY (home_team_slug) REFERENCES teams(id) ON DELETE CASCADE,
    CONSTRAINT fk_match_telemetry_away_team FOREIGN KEY (away_team_slug) REFERENCES teams(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_match_telemetry_home_slug ON match_telemetry(home_team_slug);
CREATE INDEX IF NOT EXISTS ix_match_telemetry_away_slug ON match_telemetry(away_team_slug);
CREATE INDEX IF NOT EXISTS ix_match_telemetry_provider_id ON match_telemetry(provider_id);
