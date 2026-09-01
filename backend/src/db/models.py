"""Typed SQLAlchemy model surface for the canonical SabiScore backend.

Alembic owns schema creation. This module exposes the legacy application tables
plus SQLAlchemy 2.0 typed mappings for canonical identity, market, prediction,
and provider-state tables used by the production API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import (  # noqa: F401
    Base,
    FeatureVector,
    League,
    LeagueStanding,
    Match,
    MatchEvent,
    MatchStats,
    Odds,
    OddsHistory,
    Player,
    PlayerValuation,
    Prediction,
    Team,
    UserAccount,
    ValueBet,
)


class ProviderRequestSummary(Base):
    __tablename__ = "provider_request_summaries"
    __table_args__ = (
        Index("ix_provider_request_provider_time", "provider", "acquired_at"),
        Index("ix_provider_request_status", "status"),
        {"extend_existing": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    operation: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    trust_tier: Mapped[str] = mapped_column(String, nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    provider_timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    quota_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quota_remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quota_reset_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    quota_cost: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warnings: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_snapshot_id: Mapped[str | None] = mapped_column(String, nullable=True)
    response_hash: Mapped[str | None] = mapped_column(String, nullable=True)


class ProviderCapabilityRecord(Base):
    __tablename__ = "provider_capabilities"
    __table_args__ = (
        Index("ix_provider_capability_provider_comp", "provider", "competition"),
        {"extend_existing": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    competition: Mapped[str] = mapped_column(String, nullable=False)
    season: Mapped[str | None] = mapped_column(String, nullable=True)
    fixtures: Mapped[bool | None] = mapped_column(Boolean, default=False)
    standings: Mapped[bool | None] = mapped_column(Boolean, default=False)
    lineups: Mapped[bool | None] = mapped_column(Boolean, default=False)
    injuries: Mapped[bool | None] = mapped_column(Boolean, default=False)
    team_statistics: Mapped[bool | None] = mapped_column(Boolean, default=False)
    player_statistics: Mapped[bool | None] = mapped_column(Boolean, default=False)
    odds: Mapped[bool | None] = mapped_column(Boolean, default=False)
    xg: Mapped[bool | None] = mapped_column(Boolean, default=False)
    provider_predictions: Mapped[bool | None] = mapped_column(Boolean, default=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    notes: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class ProviderQuotaObservation(Base):
    __tablename__ = "provider_quota_observations"
    __table_args__ = (
        Index("ix_provider_quota_provider_time", "provider", "observed_at"),
        {"extend_existing": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    quota_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quota_remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quota_reset_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    quota_cost: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str | None] = mapped_column(String, nullable=True)


class CanonicalCompetition(Base):
    __tablename__ = "canonical_competitions"
    __table_args__ = {"extend_existing": True}

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    coverage_tier: Mapped[str] = mapped_column(String, nullable=False, default="STANDARD")
    active: Mapped[bool | None] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CanonicalTeam(Base):
    __tablename__ = "canonical_teams"
    __table_args__ = (
        Index("ix_canonical_teams_competition_name", "competition_id", "name"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    competition_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("canonical_competitions.id"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    normalized_name: Mapped[str] = mapped_column(String, nullable=False)
    country: Mapped[str | None] = mapped_column(String, nullable=True)
    active: Mapped[bool | None] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CanonicalFixture(Base):
    __tablename__ = "canonical_fixtures"
    __table_args__ = (
        Index("ix_canonical_fixtures_comp_kickoff", "competition_id", "kickoff_utc"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    competition_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("canonical_competitions.id"),
        nullable=True,
    )
    season: Mapped[str | None] = mapped_column(String, nullable=True)
    home_team_id: Mapped[str | None] = mapped_column(String, ForeignKey("canonical_teams.id"), nullable=True)
    away_team_id: Mapped[str | None] = mapped_column(String, ForeignKey("canonical_teams.id"), nullable=True)
    kickoff_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="scheduled")
    venue_id: Mapped[str | None] = mapped_column(String, nullable=True)
    reconciliation_status: Mapped[str] = mapped_column(String, nullable=False, default="UNKNOWN")
    reconciliation_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ProviderEventMapping(Base):
    __tablename__ = "provider_event_mappings"
    __table_args__ = (
        Index("ix_provider_event_provider_id", "provider", "provider_event_id"),
        Index("ix_provider_event_fixture", "canonical_fixture_id"),
        {"extend_existing": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String, nullable=False)
    canonical_fixture_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("canonical_fixtures.id"),
        nullable=True,
    )
    competition: Mapped[str] = mapped_column(String, nullable=False)
    reconciliation_status: Mapped[str] = mapped_column(String, nullable=False)
    reconciliation_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ProviderTeamMapping(Base):
    __tablename__ = "provider_team_mappings"
    __table_args__ = (
        Index("ix_provider_team_provider_id", "provider", "provider_team_id"),
        Index("ix_provider_team_canonical", "canonical_team_id"),
        {"extend_existing": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    provider_team_id: Mapped[str] = mapped_column(String, nullable=False)
    provider_team_name: Mapped[str] = mapped_column(String, nullable=False)
    canonical_team_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("canonical_teams.id"),
        nullable=True,
    )
    competition: Mapped[str] = mapped_column(String, nullable=False)
    reconciliation_status: Mapped[str] = mapped_column(String, nullable=False)
    reconciliation_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"
    __table_args__ = (
        Index("ix_market_snapshots_fixture_time", "canonical_fixture_id", "captured_at"),
        Index("ix_market_snapshots_bookmaker", "bookmaker"),
        Index("ix_market_snapshots_match_id", "match_id"),
        {"extend_existing": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # ADR-0004 addendum (0005 migration): relaxed from nullable=False. Nothing
    # populates canonical_fixtures for an ordinary upcoming fixture today —
    # fixture_sync_service writes only the legacy matches/teams/leagues tables
    # (see match_id below), so a non-nullable FK here would make the CLV
    # capture job unable to write against any fixture currently in the DB.
    canonical_fixture_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("canonical_fixtures.id"), nullable=True
    )
    # ADR-0004 addendum (0005 migration): the legacy matches.id (fd-{id}
    # scheme) — the identifier fixture_sync_service and settlement_service
    # actually key on. No FK, matching MatchPredictionLog.match_id's existing
    # convention (plain indexed string, not a foreign key).
    match_id: Mapped[str | None] = mapped_column(String, nullable=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    bookmaker: Mapped[str] = mapped_column(String, nullable=False)
    market_type: Mapped[str] = mapped_column(String, nullable=False, default="1X2")
    home_odds: Mapped[float] = mapped_column(Float, nullable=False)
    draw_odds: Mapped[float] = mapped_column(Float, nullable=False)
    away_odds: Mapped[float] = mapped_column(Float, nullable=False)
    # ADR-0004: (1/odds_i) / overround per outcome, computed once at write
    # time so CLV consumers never re-derive the de-vig arithmetic themselves.
    home_implied_prob_devigged: Mapped[float | None] = mapped_column(Float, nullable=True)
    draw_implied_prob_devigged: Mapped[float | None] = mapped_column(Float, nullable=True)
    away_implied_prob_devigged: Mapped[float | None] = mapped_column(Float, nullable=True)
    # ADR-0004: disambiguates a true kickoff-captured snapshot from any future
    # ad-hoc MARKET_REFRESH snapshot the evidence orchestrator might write here.
    is_closing_line: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provider_timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    coherent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    executable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provenance: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class MatchPredictionLog(Base):
    __tablename__ = "match_prediction_logs"
    __table_args__ = (
        Index("ix_match_prediction_logs_match_time", "match_id", "created_at"),
        Index("ix_match_prediction_logs_fixture", "canonical_fixture_id"),
        {"extend_existing": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(String, nullable=False)
    canonical_fixture_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("canonical_fixtures.id"),
        nullable=True,
    )
    model_version: Mapped[str] = mapped_column(String, nullable=False)
    calibration_method: Mapped[str | None] = mapped_column(String, nullable=True)
    home_probability: Mapped[float] = mapped_column(Float, nullable=False)
    draw_probability: Mapped[float] = mapped_column(Float, nullable=False)
    away_probability: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    input_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    decision_id: Mapped[str | None] = mapped_column(String, nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # ADR-0004 (0005 migration): FK to a MarketSnapshot(is_closing_line=True)
    # row for this fixture, populated by a future backfill once identity
    # resolution (canonical_fixture_id above) is populated on write — always
    # NULL today. See ADR-0004 addendum; do not assume this column is live.
    closing_market_snapshot_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("market_snapshots.id"), nullable=True
    )


class EloRatingSnapshot(Base):
    """Durable pre/post-match Elo state keyed to real Match/Team identities."""

    __tablename__ = "elo_rating_snapshots"
    __table_args__ = (
        UniqueConstraint("match_id", "team_id", name="uq_elo_rating_match_team"),
        Index("ix_elo_rating_team_league_date", "team_id", "league", "match_date"),
        Index("ix_elo_rating_match", "match_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(String, ForeignKey("matches.id"), nullable=False)
    team_id: Mapped[str] = mapped_column(String, ForeignKey("teams.id"), nullable=False)
    pre_match_elo: Mapped[float] = mapped_column(Float, nullable=False)
    post_match_elo: Mapped[float] = mapped_column(Float, nullable=False)
    league: Mapped[str] = mapped_column(String, nullable=False)
    season: Mapped[str] = mapped_column(String, nullable=False)
    match_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ProviderHealthLog(Base):
    __tablename__ = "provider_health_log"
    __table_args__ = (
        Index("ix_provider_health_provider_time", "provider", "checked_at"),
        Index("ix_provider_health_status", "status"),
        {"extend_existing": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    warnings: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class ProviderCapabilityObservation(Base):
    __tablename__ = "provider_capability_observations"
    __table_args__ = (
        Index(
            "ix_provider_capability_obs_provider_comp",
            "provider",
            "competition",
            "checked_at",
        ),
        {"extend_existing": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    competition: Mapped[str] = mapped_column(String, nullable=False)
    season: Mapped[str | None] = mapped_column(String, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    capabilities_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    source: Mapped[str | None] = mapped_column(String, nullable=True)


class CircuitState(Base):
    __tablename__ = "circuit_state"
    __table_args__ = {"extend_existing": True}

    provider: Mapped[str] = mapped_column(String, primary_key=True)
    open: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    retry_after: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    state_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON, nullable=True)


class RefereeProfile(Base):
    __tablename__ = "referee_profiles"
    __table_args__ = (
        Index("ix_referee_profiles_name", "name"),
        UniqueConstraint("name", name="uq_referee_profiles_name"),
        {"extend_existing": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    avg_yellow_cards: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_red_cards: Mapped[float | None] = mapped_column(Float, nullable=True)
    penalties_awarded: Mapped[int | None] = mapped_column(Integer, nullable=True)
    strictness_index: Mapped[float | None] = mapped_column(Float, nullable=True)
    sample_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class MatchContext(Base):
    __tablename__ = "match_contexts"
    __table_args__ = (
        Index("ix_match_contexts_match_id", "match_id"),
        UniqueConstraint("match_id", name="uq_match_contexts_match_id"),
        {"extend_existing": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(String, ForeignKey("matches.id"), nullable=False)
    weather_condition: Mapped[str | None] = mapped_column(String, nullable=True)
    weather_source: Mapped[str | None] = mapped_column(String, nullable=True)
    weather_observed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fatigue_index_home: Mapped[float | None] = mapped_column(Float, nullable=True)
    fatigue_index_away: Mapped[float | None] = mapped_column(Float, nullable=True)
    ppda_home: Mapped[float | None] = mapped_column(Float, nullable=True)
    ppda_away: Mapped[float | None] = mapped_column(Float, nullable=True)
    psxg_home: Mapped[float | None] = mapped_column(Float, nullable=True)
    psxg_away: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class UserFavorite(Base):
    __tablename__ = "user_favorites"
    __table_args__ = (
        Index("ix_user_favorites_user_id", "user_id"),
        Index("ix_user_favorites_anon_id", "anonymous_session_id"),
        UniqueConstraint("user_id", "entity_type", "entity_id", name="uq_user_favorites_user_entity"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    anonymous_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)  # 'team' | 'competition'
    entity_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class UserSavedMatch(Base):
    __tablename__ = "user_saved_matches"
    __table_args__ = (
        Index("ix_user_saved_matches_user_id", "user_id"),
        Index("ix_user_saved_matches_anon_id", "anonymous_session_id"),
        Index("ix_user_saved_matches_match_id", "match_id"),
        UniqueConstraint("user_id", "match_id", name="uq_user_saved_matches_user_match"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    anonymous_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    match_id: Mapped[str] = mapped_column(String, nullable=False)
    target_outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class UserPreference(Base):
    __tablename__ = "user_preferences"
    __table_args__ = (
        Index("ix_user_preferences_user_id", "user_id"),
        Index("ix_user_preferences_anon_id", "anonymous_session_id"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, unique=True
    )
    anonymous_session_id: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    odds_format: Mapped[str] = mapped_column(String, nullable=False, default="DECIMAL")
    timezone: Mapped[str] = mapped_column(String, nullable=False, default="Africa/Lagos")
    default_league: Mapped[str | None] = mapped_column(String, nullable=True, default="EPL")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ApiKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (
        Index("ix_api_keys_user_id", "user_id"),
        Index("ix_api_keys_key_prefix", "key_prefix"),
        Index("ix_api_keys_key_hash", "key_hash"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    key_prefix: Mapped[str] = mapped_column(String, nullable=False)
    key_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    tier: Mapped[str] = mapped_column(String, nullable=False, default="FREE")
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    daily_quota: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"
    __table_args__ = (
        Index("ix_analytics_events_event_name", "event_name"),
        Index("ix_analytics_events_user_id", "user_id"),
        Index("ix_analytics_events_anon_id", "anonymous_session_id"),
        Index("ix_analytics_events_timestamp", "timestamp"),
        {"extend_existing": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    anonymous_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    event_name: Mapped[str] = mapped_column(String, nullable=False)
    properties: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    client_platform: Mapped[str | None] = mapped_column(String, nullable=True, default="web")
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class UserNotificationSubscription(Base):
    __tablename__ = "user_notification_subscriptions"
    __table_args__ = (
        Index("ix_notif_subs_user_id", "user_id"),
        Index("ix_notif_subs_anon_id", "anonymous_session_id"),
        Index("ix_notif_subs_match_id", "match_id"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    anonymous_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    match_id: Mapped[str | None] = mapped_column(String, nullable=True)
    subscription_type: Mapped[str] = mapped_column(
        String, nullable=False, default="KICKOFF_REMINDER"
    )
    channel: Mapped[str] = mapped_column(String, nullable=False, default="IN_APP")
    destination: Mapped[str | None] = mapped_column(String, nullable=True)
    threshold_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    reminder_minutes_before: Mapped[int | None] = mapped_column(Integer, nullable=True, default=60)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class UserNotificationLog(Base):
    __tablename__ = "user_notification_logs"
    __table_args__ = (
        Index("ix_notif_logs_user_unread", "user_id", "read", "created_at"),
        Index("ix_notif_logs_anon_unread", "anonymous_session_id", "read", "created_at"),
        {"extend_existing": True},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    anonymous_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    subscription_id: Mapped[str | None] = mapped_column(String, nullable=True)
    match_id: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False, default="INFO")
    read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


__all__ = [
    "Base",
    "FeatureVector",
    "League",
    "LeagueStanding",
    "Match",
    "MatchEvent",
    "MatchStats",
    "Odds",
    "OddsHistory",
    "Player",
    "PlayerValuation",
    "Prediction",
    "Team",
    "UserAccount",
    "ValueBet",
    "ProviderRequestSummary",
    "ProviderCapabilityRecord",
    "ProviderQuotaObservation",
    "CanonicalCompetition",
    "CanonicalFixture",
    "CanonicalTeam",
    "ProviderEventMapping",
    "MarketSnapshot",
    "MatchPredictionLog",
    "EloRatingSnapshot",
    "ProviderHealthLog",
    "ProviderCapabilityObservation",
    "CircuitState",
    "RefereeProfile",
    "MatchContext",
    "UserFavorite",
    "UserSavedMatch",
    "UserPreference",
    "ApiKey",
    "AnalyticsEvent",
    "UserNotificationSubscription",
    "UserNotificationLog",
]

