from contextlib import contextmanager
from datetime import datetime
from threading import Lock
from typing import Iterator, Optional

import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, relationship, sessionmaker, declarative_base
from sqlalchemy.pool import QueuePool

from .config import settings

import logging

logger = logging.getLogger(__name__)

Base = declarative_base()


def _get_sync_database_url(url: str) -> str:
    """Convert async or bare database URL to a psycopg3 sync URL for Alembic."""
    if "+aiosqlite" in url:
        return url.replace("+aiosqlite", "")
    if "+asyncpg" in url:
        return url.replace("+asyncpg", "+psycopg")
    # Render provides plain postgresql:// / postgres:// — route to psycopg3 (installed)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


# Get sync-compatible database URL
_sync_url = _get_sync_database_url(settings.database_url)

# Flag to track database availability. Both start "unknown" (False) rather
# than "assumed available" -- they only become accurate once get_engine()
# has actually run (see docs/adr/0007-lazy-database-engine-init.md).
_db_available = False
_using_fallback = False


def _sqlite_fallback_allowed() -> bool:
    """Return True only for explicit non-production insecure fallback opt-in."""
    return settings.app_env != "production" and bool(settings.allow_sqlite_fallback)


def _create_postgres_engine(url: str):
    """Create PostgreSQL engine with connection pooling."""
    return create_engine(
        url,
        poolclass=QueuePool,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout,
        pool_recycle=settings.database_pool_recycle,
        echo=settings.debug,
        pool_pre_ping=True,
    )


def _create_sqlite_engine(url: str):
    """Create SQLite engine for fallback."""
    return create_engine(
        url,
        echo=settings.debug,
        poolclass=None,  # Disable connection pooling for SQLite
        connect_args={"check_same_thread": False},  # Allow multi-threading
    )


def _test_connection(eng) -> bool:
    """Test if engine can connect to database."""
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.warning("Connection test failed: %s", e)
        return False


def _init_engine() -> Engine:
    """Create and connection-test the database engine.

    This is the exact logic that used to run at module import time (see
    docs/adr/0007-lazy-database-engine-init.md) -- unchanged in substance,
    only in when it runs. Fail-closed semantics are preserved: PostgreSQL
    unreachable with no explicit SQLite fallback still raises here, just
    like it always did. Importing this module for `Base`/model classes
    (Alembic, tests, IDE tooling) no longer triggers it.
    """
    global _db_available, _using_fallback

    if _sync_url.startswith("sqlite"):
        if not _sqlite_fallback_allowed():
            raise RuntimeError(
                "SQLite database URLs require SABISCORE_ALLOW_INSECURE_FALLBACK=true "
                "and APP_ENV must not be production"
            )
        # SQLite-specific configuration
        eng = _create_sqlite_engine(_sync_url)
        _db_available = _test_connection(eng)
        return eng

    # Try PostgreSQL first
    try:
        eng = _create_postgres_engine(_sync_url)
        # Connect inline rather than via _test_connection(): that helper returns a
        # bool and swallows the driver's exception into a logger.warning, so the
        # raise below used to surface a bare "PostgreSQL connection test failed"
        # with no cause attached. Callers that configure no logging (CLI scripts,
        # alembic) then saw an unactionable error for what is usually a precise,
        # self-explaining driver message ("password authentication failed for
        # user X", "no pg_hba.conf entry", "could not translate host name").
        with eng.connect() as _conn:
            _conn.execute(text("SELECT 1"))
        logger.info("PostgreSQL connection successful")
        _db_available = True
        return eng
    except Exception as exc:
        if not _sqlite_fallback_allowed():
            logger.error("PostgreSQL unavailable and SQLite fallback is not explicitly allowed")
            raise
        logger.warning("PostgreSQL unavailable (%s), using explicit SQLite fallback", exc)
        _using_fallback = True
        fallback_url = "sqlite:///./sabiscore_fallback.db"
        eng = _create_sqlite_engine(fallback_url)
        _db_available = _test_connection(eng)
        if _db_available:
            logger.info("SQLite fallback database initialized")
        else:
            logger.error("Both PostgreSQL and SQLite fallback failed!")
        return eng


_engine: Optional[Engine] = None
_engine_lock = Lock()


def get_engine() -> Engine:
    """Return the lazily-created, connection-tested engine (memoized).

    First call wins: it runs `_init_engine()` exactly once (double-checked
    locking guards concurrent first callers) and every later call returns
    the same engine. A failure is not cached/retried on a timer -- the next
    call simply raises again, the same fail-closed shape as before.
    """
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = _init_engine()
    return _engine


def verify_database_connection() -> Engine:
    """Force the lazy engine to initialise now, raising on failure.

    Call this once, early and unguarded, from a real startup entrypoint
    (FastAPI's `lifespan`) so an unreachable database with no explicit
    fallback still fails fast and loud at process startup -- unchanged from
    the old import-time behaviour -- instead of surfacing lazily on
    whichever request happens to touch the database first.
    """
    return get_engine()


_session_factory: Optional[sessionmaker] = None


def _get_session_factory() -> sessionmaker:
    global _session_factory
    if _session_factory is None:
        eng = get_engine()  # outside the lock: does its own locking, and may raise
        with _engine_lock:
            if _session_factory is None:
                _session_factory = sessionmaker(autocommit=False, autoflush=False, bind=eng)
    return _session_factory


class SessionLocal:
    """Lazy stand-in for a bound `sessionmaker`.

    Every existing caller uses this as `SessionLocal()` to get a `Session` --
    that call surface is preserved exactly. What changes is that binding an
    engine (and connection-testing it) is deferred to the first actual call
    instead of happening at import time.
    """

    def __new__(cls, **kwargs) -> Session:
        return _get_session_factory()(**kwargs)


def is_db_available() -> bool:
    """Check if database is available."""
    return _db_available


def is_using_fallback() -> bool:
    """Check if using SQLite fallback instead of primary database."""
    return _using_fallback


def get_db_status() -> dict:
    """Get database status information."""
    return {
        "available": _db_available,
        "using_fallback": _using_fallback,
        "url_type": "sqlite" if _sync_url.startswith("sqlite") or _using_fallback else "postgresql",
    }


# Database models
class UserAccount(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_email", "email", unique=True),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, nullable=False, unique=True)
    full_name = Column(String, nullable=True)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    last_login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class League(Base):
    __tablename__ = "leagues"
    __table_args__ = (
        Index("ix_leagues_name", "name"),
    )

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    country = Column(String)
    tier = Column(Integer)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (
        Index("ix_teams_league", "league_id"),
        Index("ix_teams_name", "name"),
    )

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    league_id = Column(String, ForeignKey("leagues.id"))
    country = Column(String)
    founded_year = Column(Integer)
    stadium = Column(String)
    manager = Column(String)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

    league = relationship("League")

class Player(Base):
    __tablename__ = "players"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    team_id = Column(String, ForeignKey("teams.id"))
    position = Column(String)
    nationality = Column(String)
    age = Column(Integer)
    market_value = Column(Float)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

    team = relationship("Team")

class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (
        Index("ix_matches_league_date", "league_id", "match_date"),
        Index("ix_matches_home", "home_team_id"),
        Index("ix_matches_away", "away_team_id"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    league_id = Column(String, ForeignKey("leagues.id"))
    home_team_id = Column(String, ForeignKey("teams.id"))
    away_team_id = Column(String, ForeignKey("teams.id"))
    match_date = Column(DateTime, nullable=False)
    season = Column(String)
    status = Column(String)  # scheduled, live, finished
    home_score = Column(Integer, nullable=True)
    away_score = Column(Integer, nullable=True)
    venue = Column(String)
    referee = Column(String)
    competition_stage = Column(String, nullable=True)  # UCL: qualifying, group, r16, qf, sf, final
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

    league = relationship("League")
    home_team = relationship("Team", foreign_keys=[home_team_id])
    away_team = relationship("Team", foreign_keys=[away_team_id])

class MatchStats(Base):
    __tablename__ = "match_stats"
    __table_args__ = (
        Index("ix_match_stats_match_team", "match_id", "team_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(String, ForeignKey("matches.id"))
    team_id = Column(String, ForeignKey("teams.id"))
    possession = Column(Float)
    shots = Column(Integer)
    shots_on_target = Column(Integer)
    corners = Column(Integer)
    fouls = Column(Integer)
    yellow_cards = Column(Integer)
    red_cards = Column(Integer)
    offsides = Column(Integer)
    expected_goals = Column(Float)
    created_at = Column(DateTime)

    match = relationship("Match")
    team = relationship("Team")

class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (
        Index("ix_predictions_match", "match_id"),
        Index("ix_predictions_model", "model_version"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(String, ForeignKey("matches.id"))
    model_version = Column(String)
    home_win_prob = Column(Float)
    draw_prob = Column(Float)
    away_win_prob = Column(Float)
    expected_goals_home = Column(Float)
    expected_goals_away = Column(Float)
    confidence = Column(Float)
    features = Column(JSON)
    shap_values = Column(JSON)
    created_at = Column(DateTime)

    match = relationship("Match")

class Odds(Base):
    __tablename__ = "odds"
    __table_args__ = (
        Index("ix_odds_match_timestamp", "match_id", "timestamp"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(String, ForeignKey("matches.id"))
    bookmaker = Column(String)
    home_win = Column(Float)
    draw = Column(Float)
    away_win = Column(Float)
    over_under = Column(Float)
    timestamp = Column(DateTime)

    match = relationship("Match")

class ValueBet(Base):
    __tablename__ = "value_bets"
    __table_args__ = (
        Index("ix_value_bets_match", "match_id"),
        Index("ix_value_bets_prediction", "prediction_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(String, ForeignKey("matches.id"))
    prediction_id = Column(Integer, ForeignKey("predictions.id"))
    bet_type = Column(String)  # home_win, draw, away_win, over_under
    bookmaker = Column(String)
    market_odds = Column(Float)
    expected_odds = Column(Float)
    value_percentage = Column(Float)
    kelly_stake = Column(Float)
    timestamp = Column(DateTime)

    match = relationship("Match")
    prediction = relationship("Prediction")


class LeagueStanding(Base):
    __tablename__ = "league_standings"
    __table_args__ = (
        Index("ix_league_standings_league_team", "league", "team_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    league = Column(String, ForeignKey("leagues.id"))
    team_id = Column(String, ForeignKey("teams.id"))
    position = Column(Integer)
    points = Column(Integer)
    played = Column(Integer)
    won = Column(Integer)
    drawn = Column(Integer)
    lost = Column(Integer)
    goals_for = Column(Integer)
    goals_against = Column(Integer)
    goal_difference = Column(Integer)
    updated_at = Column(DateTime)
    
    team = relationship("Team")


class MatchEvent(Base):
    """Real-time match events (goals, cards, substitutions, xG shots)"""
    __tablename__ = "match_events"
    __table_args__ = (
        Index("ix_match_events_match_time", "match_id", "event_time"),
        Index("ix_match_events_type", "event_type"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(String, ForeignKey("matches.id"))
    event_time = Column(Integer)  # Minute of the match
    event_type = Column(String)  # goal, yellow_card, red_card, substitution, shot, xg_shot
    team_id = Column(String, ForeignKey("teams.id"))
    player_id = Column(String, ForeignKey("players.id"), nullable=True)
    xg_value = Column(Float, nullable=True)  # For xG shots
    description = Column(Text, nullable=True)
    event_metadata = Column(JSON, nullable=True)  # Extra data (shot location, assist, etc.) - renamed from 'metadata' to avoid SQLAlchemy conflict
    source = Column(String)  # espn, opta, understat, fbref
    timestamp = Column(DateTime)

    match = relationship("Match")
    team = relationship("Team")
    player = relationship("Player")


class OddsHistory(Base):
    """Time-series odds tracking for market movement analysis"""
    __tablename__ = "odds_history"
    __table_args__ = (
        Index("ix_odds_history_match_timestamp", "match_id", "timestamp"),
        Index("ix_odds_history_bookmaker", "bookmaker"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(String, ForeignKey("matches.id"))
    bookmaker = Column(String)  # betfair, pinnacle, bet365, etc.
    market_type = Column(String)  # match_odds, over_under_25, btts, etc.
    
    # Match odds (1X2)
    home_win = Column(Float, nullable=True)
    draw = Column(Float, nullable=True)
    away_win = Column(Float, nullable=True)
    
    # Over/Under markets
    over_15 = Column(Float, nullable=True)
    under_15 = Column(Float, nullable=True)
    over_25 = Column(Float, nullable=True)
    under_25 = Column(Float, nullable=True)
    over_35 = Column(Float, nullable=True)
    under_35 = Column(Float, nullable=True)
    
    # Both Teams to Score
    btts_yes = Column(Float, nullable=True)
    btts_no = Column(Float, nullable=True)
    
    # Asian Handicap
    asian_handicap_line = Column(Float, nullable=True)
    asian_handicap_home = Column(Float, nullable=True)
    asian_handicap_away = Column(Float, nullable=True)
    
    # Betting volumes (Betfair specific)
    total_matched = Column(Float, nullable=True)
    home_volume = Column(Float, nullable=True)
    draw_volume = Column(Float, nullable=True)
    away_volume = Column(Float, nullable=True)
    
    timestamp = Column(DateTime)
    created_at = Column(DateTime)

    match = relationship("Match")


class FeatureVector(Base):
    """Enriched feature vectors for ML models (220 features)"""
    __tablename__ = "feature_vectors"
    __table_args__ = (
        Index("ix_feature_vectors_match", "match_id"),
        Index("ix_feature_vectors_timestamp", "timestamp"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(String, ForeignKey("matches.id"))
    
    # Team form features (last 5, 10 matches)
    home_form_5 = Column(Float)
    home_form_10 = Column(Float)
    away_form_5 = Column(Float)
    away_form_10 = Column(Float)
    
    # xG features
    home_xg_avg_5 = Column(Float)
    home_xg_conceded_avg_5 = Column(Float)
    away_xg_avg_5 = Column(Float)
    away_xg_conceded_avg_5 = Column(Float)
    
    # Fatigue index (days since last match, travel distance)
    home_fatigue_index = Column(Float)
    away_fatigue_index = Column(Float)
    home_days_rest = Column(Integer)
    away_days_rest = Column(Integer)
    
    # Home advantage boost
    home_crowd_boost = Column(Float)  # Based on attendance, stadium size
    home_advantage_coefficient = Column(Float)
    
    # Momentum (Poisson λ parameter)
    home_momentum_lambda = Column(Float)
    away_momentum_lambda = Column(Float)
    
    # Market panic indicator (odds volatility)
    market_panic_score = Column(Float)
    odds_volatility_1h = Column(Float)
    odds_volatility_24h = Column(Float)
    
    # Head-to-head history
    h2h_home_wins = Column(Integer)
    h2h_draws = Column(Integer)
    h2h_away_wins = Column(Integer)
    h2h_avg_goals = Column(Float)
    
    # Referee bias
    referee_home_bias = Column(Float)
    referee_cards_per_game = Column(Float)
    
    # Squad strength (from Transfermarkt)
    home_squad_value = Column(Float)
    away_squad_value = Column(Float)
    home_missing_value = Column(Float)  # Injured/suspended players
    away_missing_value = Column(Float)
    
    # Weather conditions
    temperature = Column(Float, nullable=True)
    precipitation = Column(Float, nullable=True)
    wind_speed = Column(Float, nullable=True)
    
    # Elo ratings
    home_elo = Column(Float)
    away_elo = Column(Float)
    elo_difference = Column(Float)
    
    # Full 220-feature vector (JSON for flexibility)
    feature_vector_full = Column(JSON)
    
    # Metadata
    features_version = Column(String)  # Track feature engineering version
    timestamp = Column(DateTime)
    created_at = Column(DateTime)

    match = relationship("Match")


class PlayerValuation(Base):
    """Player market valuations from Transfermarkt"""
    __tablename__ = "player_valuations"
    __table_args__ = (
        Index("ix_player_valuations_player_date", "player_id", "valuation_date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    player_id = Column(String, ForeignKey("players.id"))
    team_id = Column(String, ForeignKey("teams.id"))
    valuation_date = Column(DateTime)
    market_value = Column(Float)  # In millions (EUR)
    currency = Column(String, default="EUR")
    source = Column(String, default="transfermarkt")
    created_at = Column(DateTime)

    player = relationship("Player")
    team = relationship("Team")


class ScrapingLog(Base):
    """Track scraping jobs for monitoring and debugging"""
    __tablename__ = "scraping_logs"
    __table_args__ = (
        Index("ix_scraping_logs_source_status", "source", "status"),
        Index("ix_scraping_logs_timestamp", "timestamp"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String)  # understat, fbref, transfermarkt, espn, opta, betfair
    job_type = Column(String)  # historical_load, real_time_fetch, incremental_update
    status = Column(String)  # started, success, failed, partial
    records_processed = Column(Integer, default=0)
    records_failed = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    execution_time_seconds = Column(Float, nullable=True)
    timestamp = Column(DateTime)
    job_metadata = Column(JSON, nullable=True)  # Job-specific config/params - renamed from 'metadata' to avoid SQLAlchemy conflict


def get_db() -> Iterator[Session]:
    """Yield a database session for FastAPI dependency injection."""
    with session_scope() as session:
        yield session


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional scope around a series of operations."""
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception as exc:
        session.rollback()
        logger.exception("Session rollback because of exception: %s", exc)
        raise
    finally:
        session.close()


def check_database_health() -> bool:
    """Return True if the database responds to a simple SELECT statement."""
    try:
        with session_scope() as session:
            session.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError as exc:
        logger.error("Database health check failed: %s", exc)
        return False


def init_database_schema() -> None:
    """Reject direct schema creation from application runtime."""
    raise RuntimeError("Direct table creation is disabled; run Alembic migrations instead")
