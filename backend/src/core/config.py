from pathlib import Path
from typing import List, Optional
import json

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_SECRET = "change-me-in-production"


class Settings(BaseSettings):
    """Centralised application settings with environment-aware validation."""

    model_config = SettingsConfigDict(
        # Search both the project root and backend/ so the CLI works from either cwd.
        env_file=(str(_PROJECT_ROOT / ".env"), ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: str = Field(
        default="postgresql://sabi@localhost:5432/sabiscore",
        alias="DATABASE_URL",
        description="SQLAlchemy-compatible database URL.",
    )
    allow_sqlite_fallback: bool = Field(
        default=False,
        validation_alias=AliasChoices("SABISCORE_ALLOW_INSECURE_FALLBACK", "ALLOW_SQLITE_FALLBACK"),
        description="Development/test-only opt-in for SQLite fallback when PostgreSQL is unavailable.",
    )
    database_pool_size: int = Field(default=20, ge=1, le=100)
    database_max_overflow: int = Field(default=30, ge=0, le=100)
    database_pool_timeout: int = Field(default=30, ge=1)
    database_pool_recycle: int = Field(default=3600, ge=60)

    # Redis Cache — Tier 1: Redis Labs Cloud (primary KV store)
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        alias="REDIS_URL",
        description="Redis connection URL.",
    )
    redis_cache_ttl: int = Field(default=3600, ge=60)
    redis_max_connections: int = Field(default=50, ge=1, le=200)
    redis_enabled: bool = Field(default=True, alias="REDIS_ENABLED")

    # Redis Cache — Tier 2: Upstash (serverless secondary, Redis-protocol endpoint)
    # Set UPSTASH_REDIS_URL to a rediss:// URL from your Upstash console to activate.
    upstash_redis_url: Optional[str] = Field(
        default=None,
        alias="UPSTASH_REDIS_URL",
        description="Upstash Redis-protocol URL (rediss://default:token@hostname:port). "
                    "When set, used as the middle tier between Redis Labs and in-memory.",
    )
    upstash_enabled: bool = Field(
        default=False,
        alias="UPSTASH_ENABLED",
        description="Enable Upstash as the 3-tier middle cache. "
                    "Activated automatically when UPSTASH_REDIS_URL is provided.",
    )
    upstash_max_connections: int = Field(default=20, ge=1, le=100)

    # Per-key TTL overrides for the two hottest cache namespaces
    prediction_cache_ttl: int = Field(
        default=30,
        ge=5,
        alias="PREDICTION_CACHE_TTL",
        description="TTL (seconds) for prediction:{league}:{match_id} keys.",
    )
    fixture_cache_ttl: int = Field(
        default=300,
        ge=30,
        alias="FIXTURE_CACHE_TTL",
        description="TTL (seconds) for upcoming:v2:* fixture keys.",
    )

    # Security
    secret_key: str = Field(default=_DEFAULT_SECRET, alias="SECRET_KEY")
    algorithm: str = Field(default="HS256")
    access_token_expire_minutes: int = Field(default=30, ge=5)
    enable_security_headers: bool = Field(default=True)
    # Use raw string to avoid pydantic-settings JSON parsing issues with List[str]
    allowed_hosts_raw: str = Field(
        default="localhost,127.0.0.1",
        alias="ALLOWED_HOSTS",
        description="Comma-separated list of allowed hosts"
    )
    # Render sets this automatically to the public service hostname (e.g. sabiscore-api-bav1.onrender.com)
    render_external_hostname: Optional[str] = Field(default=None, alias="RENDER_EXTERNAL_HOSTNAME")
    opta_api_key: Optional[str] = None
    betfair_app_key: Optional[str] = None
    betfair_session_token: Optional[str] = None
    pinnacle_api_key: Optional[str] = None
    fivethirtyeight_api_key: Optional[str] = None
    football_data_api_key: Optional[str] = Field(
        default=None,
        alias="FOOTBALL_DATA_API_KEY",
        description="X-Auth-Token for football-data.org (fixtures, standings, results).",
    )
    
    # App metadata (backwards-compat with legacy settings access in main.py)
    project_name: str = Field(default="SabiScore API", alias="APP_NAME")
    version: str = Field(default="1.0.0", alias="VERSION")
    app_version: str = Field(default="1.0.0", alias="APP_VERSION")
    api_v1_str: str = Field(default="/api/v1", alias="API_V1_STR")
    
    # Next.js Integration
    next_url: str = Field(
        default="http://localhost:3000",
        alias="NEXT_URL",
        description="Next.js frontend URL for ISR revalidation"
    )
    revalidate_secret: Optional[str] = Field(
        default=None,
        alias="REVALIDATE_SECRET", 
        description="Secret token for Next.js ISR revalidation API"
    )

    # Application
    app_env: str = Field(default="development", alias="APP_ENV")
    debug: bool = Field(default=False)
    mock_mode: bool = Field(default=False, alias="MOCK_MODE")
    enable_legacy_inference: bool = Field(default=False, alias="ENABLE_LEGACY_INFERENCE")
    log_level: str = Field(default="INFO")
    log_format: str = Field(default="json")
    enable_tracing: bool = Field(default=False)
    # ADR-0006: boolean gate above is necessary but not sufficient — tracing
    # only activates when an OTLP endpoint is also configured. Both no-op by
    # default; no observability backend is provisioned today.
    otel_exporter_otlp_endpoint: Optional[str] = Field(
        default=None, alias="OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    sentry_dsn: Optional[str] = Field(default=None, alias="SENTRY_DSN")
    rate_limit_delay: float = Field(default=1.0, ge=0.1)
    rate_limit_requests: int = Field(default=60, ge=1)
    rate_limit_window_seconds: int = Field(default=60, ge=1)

    # Feature Flags
    use_enhanced_models: bool = Field(
        default=True,
        alias="USE_ENHANCED_MODELS",
        description="Enable enhanced stacking ensemble with isotonic calibration"
    )
    use_enhanced_models_v7: bool = Field(
        default=False,
        alias="ENHANCED_MODELS_V7",
        description="Load v7 enhanced ensemble artifacts when available; falls back to legacy models"
    )
    use_optuna_v4: bool = Field(
        default=True,
        alias="USE_OPTUNA_V4",
        description="Master switch for v4_optuna model artifacts. "
                    "When False, only legacy _ensemble.pkl files are loaded.",
    )
    use_phase7_models: bool = Field(
        default=False,
        alias="USE_PHASE7_MODELS",
        description="Enable loading v5_phase7 model artifacts with 68-feature support.",
    )
    phase7_canary_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        alias="PHASE7_CANARY_PCT",
        description="Fraction of leagues routed to Phase 7 model artifacts.",
    )
    intelligence_synth_enabled: bool = Field(
        default=True,
        alias="INTELLIGENCE_SYNTH_ENABLED",
    )
    full_analysis_cache_ttl: int = Field(
        default=60,
        ge=5,
        alias="FULL_ANALYSIS_CACHE_TTL",
    )
    rl_gates_validated: bool = Field(
        default=False,
        alias="RL_GATES_VALIDATED",
    )
    use_bnn_member: bool = Field(
        default=False,
        alias="USE_BNN_MEMBER",
        description="Enable BNN member augmentation for uncertainty metadata.",
    )
    epistemic_threshold: float = Field(
        default=0.15,
        ge=0,
        le=1,
        alias="EPISTEMIC_THRESHOLD",
        description="Threshold used for low-confidence and abstention signals.",
    )
    bnn_mc_samples: int = Field(
        default=50,
        ge=1,
        le=500,
        alias="BNN_MC_SAMPLES",
    )
    bnn_lambda_reg: float = Field(
        default=0.001,
        ge=0,
        le=1,
        alias="BNN_LAMBDA_REG",
    )
    bnn_model_path: str = Field(
        default="backend/models/bnn_ensemble.pt",
        alias="BNN_MODEL_PATH",
    )
    rl_agent_path: str = Field(
        default="backend/models/rl_betting_agent.zip",
        alias="RL_AGENT_PATH",
    )
    rl_max_kelly_cap: float = Field(
        default=0.025,
        ge=0,
        le=1,
        alias="RL_MAX_KELLY_CAP",
    )
    rl_abstention_enabled: bool = Field(
        default=True,
        alias="RL_ABSTENTION_ENABLED",
    )
    optuna_v4_canary_pct: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        alias="OPTUNA_V4_CANARY_PCT",
        description="Fraction of leagues routed to v4_optuna models (0.0=0%, 1.0=100%). "
                    "Routing is deterministic per league via MD5 hash so the same league "
                    "always maps to the same model version for a given canary setting. "
                    "Rollout schedule: 0.10 → 0.50 → 1.0.",
    )
    brier_threshold: float = Field(
        default=0.13,
        alias="BRIER_THRESHOLD",
        description="Alert threshold for Brier score (lower is better)"
    )
    accuracy_threshold: float = Field(
        default=0.90,
        alias="ACCURACY_THRESHOLD",
        description="Minimum accuracy threshold for model health"
    )

    # Scraper networking
    scraper_ssl_verify: bool | str = Field(default=True, alias="SCRAPER_SSL_VERIFY")
    scraper_allow_insecure_fallback: bool = Field(
        default=False,
        alias="SCRAPER_ALLOW_INSECURE_FALLBACK",
        description="Allow retrying scraper requests without SSL verification after failures.",
    )

    # Performance & compression
    enable_gzip: bool = Field(default=True)
    enable_response_compression: bool = Field(default=True)

    # Scraping
    user_agent: str = Field(default="SabiScore/1.0 (+contact@sabiscore.com)")
    request_timeout: int = Field(default=10, ge=1)

    # CORS
    # Accept env CORS_ORIGINS as a simple CSV or JSON string without requiring JSON decoding at env source
    cors_origins_raw: Optional[str] = Field(
        default=None,
        alias="CORS_ORIGINS",
        description="Comma-separated or JSON list string of allowed CORS origins"
    )
    cors_allowed_origins: List[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:3001",
            "http://localhost:3002",
            "http://localhost:5173",
        ]
    )
    cors_origin_regex: Optional[str] = Field(
        default=None,
        alias="CORS_ORIGIN_REGEX",
        description=(
            "Optional regex for additional CORS origin matching. "
            "Used to allow Vercel preview URLs without listing each one explicitly. "
            "Example: https://sabiscore(-[a-z0-9]+)?\\.vercel\\.app"
        ),
    )

    # Paths
    models_path: Path = Field(
        default_factory=lambda: _PROJECT_ROOT / "models",
        alias="MODELS_PATH",
        description="Path to ML models directory"
    )
    data_path: Path = Field(default_factory=lambda: (_PROJECT_ROOT / "data" / "processed"))
    phase7_models_path: Path = Field(
        default_factory=lambda: _PROJECT_ROOT / "backend" / "models",
        alias="PHASE7_MODELS_PATH",
        description="Path containing v5_phase7 model artifacts.",
    )
    elo_parquet_path: Path = Field(
        default_factory=lambda: _PROJECT_ROOT / "data" / "processed" / "elo_ratings.parquet",
        alias="ELO_PARQUET_PATH",
    )
    elo_home_advantage: float = Field(
        default=100.0,
        alias="ELO_HOME_ADVANTAGE",
    )
    elo_k_base: float = Field(
        default=20.0,
        alias="ELO_K_BASE",
    )
    statsbomb_cache_path: Path = Field(
        default_factory=lambda: _PROJECT_ROOT / "data" / "processed" / "statsbomb_features_cache.parquet",
        alias="STATSBOMB_CACHE_PATH",
    )
    statsbomb_staleness_max_days: int = Field(
        default=7,
        ge=1,
        alias="STATSBOMB_STALENESS_MAX_DAYS",
    )
    causal_report_path: Path = Field(
        default_factory=lambda: _PROJECT_ROOT / "data" / "processed" / "causal_feature_report.json",
        alias="CAUSAL_REPORT_PATH",
        description="Path to the Phase 6-B causal feature report (read-only at inference).",
    )
    pi_ratings_parquet_path: Path = Field(
        default_factory=lambda: _PROJECT_ROOT / "data" / "processed" / "pi_ratings.parquet",
        alias="PI_RATINGS_PARQUET_PATH",
        description="Parquet artifact for Pi-rating system (Phase 8-5a). Mirrors elo_ratings.parquet pattern.",
    )
    berrar_ratings_parquet_path: Path = Field(
        default_factory=lambda: _PROJECT_ROOT / "data" / "processed" / "berrar_ratings.parquet",
        alias="BERRAR_RATINGS_PARQUET_PATH",
        description="Parquet artifact for Berrar rating system (Phase 8-5a.5).",
    )
    use_phase8_models: bool = Field(
        default=False,
        alias="USE_PHASE8_MODELS",
        description="Enable loading v6_phase8 model artifacts with 86-feature support.",
    )
    use_phase8_features: bool = Field(
        default=False,
        alias="USE_PHASE8_FEATURES",
        description="Enable Phase 8 feature enrichment and analytics endpoint responses.",
    )
    phase8_canary_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        alias="PHASE8_CANARY_PCT",
        description="Fraction of leagues routed to Phase 8 model artifacts (0.0=0%, 1.0=100%). "
                    "Start at 0.10 and advance after 7-day soak. Mirrors PHASE7_CANARY_PCT pattern.",
    )
    data_retention_days: int = Field(
        default=365,
        ge=0,
        alias="DATA_RETENTION_DAYS",
        description="Number of days to retain scraped match records before pruning",
    )

    # ── Sprint 4 enrichment and training configuration ────────────────────────
    odds_staleness_max_hours: int = Field(
        default=24,
        ge=1,
        alias="ODDS_STALENESS_MAX_HOURS",
        description="Hours after which an odds snapshot is considered stale. Market drift "
                    "features computed from snapshots older than this threshold are returned "
                    "as DATA_GAP rather than surfacing stale movement as live signal.",
    )
    phase8_enrichment_shadow: bool = Field(
        default=False,
        alias="PHASE8_ENRICHMENT_SHADOW",
        description="Shadow mode for Phase 8 enrichment. When True, live market drift and "
                    "match-context features are computed and logged but NOT served in API "
                    "responses — output remains DATA_GAP. Use for 48h quality soak before "
                    "canary promotion. Set False to enable live enrichment.",
    )
    use_catboost_learner: bool = Field(
        default=False,
        alias="USE_CATBOOST_LEARNER",
        description="Include CatBoost as a 4th base learner in the stacking ensemble. "
                    "Gated by per-league SHAP ablation — only enable after contribution "
                    "and diversity gain pass validation checklist.",
    )
    training_recency_halflife_seasons: float = Field(
        default=2.0,
        ge=0.5,
        le=10.0,
        alias="TRAINING_RECENCY_HALFLIFE_SEASONS",
        description="Half-life in seasons for exponential sample weighting during training. "
                    "sample_weight = exp(-ln(2) / halflife * match_age_in_seasons). "
                    "Default 2.0 preserves data volume while giving recency preference.",
    )
    use_two_stage_draw_model: bool = Field(
        default=False,
        alias="USE_TWO_STAGE_DRAW_MODEL",
        description="Enable two-stage draw model: Stage 1 trains binary win/loss classifiers, "
                    "Stage 2 derives draw probability as 1 - P(home_win) - P(away_win) with "
                    "isotonic/Platt overlay. Gated per league by draw-F1 improvement >= 0.03.",
    )
    edge_quality_abstain_threshold: float = Field(
        default=0.30,
        ge=0.0,
        le=1.0,
        alias="EDGE_QUALITY_ABSTAIN_THRESHOLD",
        description="edge_quality_score below this threshold triggers ABSTAIN in the "
                    "recommendation layer. ABSTAIN also fires when any market drift feature "
                    "is DATA_GAP (market family is always required for CLV computation).",
    )
    ensemble_correlation_prune_threshold: float = Field(
        default=0.92,
        ge=0.5,
        le=1.0,
        alias="ENSEMBLE_CORRELATION_PRUNE_THRESHOLD",
        description="Pairwise probability correlation above which a redundant base learner "
                    "is flagged for pruning — only when removal does not degrade draw-F1. "
                    "Pruning rationale must be logged in calibration_report_{league}.json.",
    )
    shap_prune_threshold: float = Field(
        default=0.002,
        ge=0.0,
        le=0.1,
        alias="SHAP_PRUNE_THRESHOLD",
        description="Mean |SHAP| below which a feature family is flagged for review in the "
                    "per-family ablation report. Families below threshold on 3+ leagues are "
                    "candidates for removal — never auto-removed without ATE invalidation.",
    )
    # ── Phase F: UCL soft-coverage and canary gates ──────────────────────────
    ucl_low_evidence_override: bool = Field(
        default=True,
        alias="UCL_LOW_EVIDENCE_OVERRIDE",
        description=(
            "Allow UCL requests when the model's confidence_tier is LOW_EVIDENCE. "
            "When True, predictions are served with an explicit soft-coverage caveat. "
            "When False, UCL requests at LOW_EVIDENCE tier return a 422 advisory. "
            "Gated by ACTIVE_LEAGUES.UCL.low_evidence_allowed in league_config.py."
        ),
    )

    live_threshold_seconds: int = Field(
        default=3600,
        ge=60,
        alias="LIVE_THRESHOLD_SECONDS",
        description="Threshold (seconds) for the edge_quality_score freshness linear decay: "
                    "freshness_score = max(0, 1 - staleness_seconds / live_threshold_seconds). "
                    "Features older than this threshold score 0.0 on freshness. "
                    "Default 3600 (1 hour) — matches typical pre-match enrichment window.",
    )

    # ── Phase 9 / V4 candidate data sources (shadow mode) ────────────────────
    use_phase9_candidate_features: bool = Field(
        default=False,
        alias="USE_PHASE9_CANDIDATE_FEATURES",
        description="Enable Phase 9 V4 candidate feature computation. When True, hybrid xG "
                    "and market-efficiency metadata are computed and appended to API "
                    "response metadata['phase9_candidate_features']. Never touches the model "
                    "input frame or probabilities — additive metadata only. Default False "
                    "(shadow off). Set True in staging before promoting to production.",
    )
    phase9_shadow_only: bool = Field(
        default=True,
        alias="PHASE9_SHADOW_ONLY",
        description="When True, Phase 9 candidate features are written only to response "
                    "metadata and logged — they do not influence predictions, value bets, "
                    "or any downstream consumer. Set False only after a 7-day production "
                    "soak and SHAP ablation gate passes.",
    )
    phase9_sources_path: str = Field(
        default="data/processed/v4_sources",
        alias="PHASE9_SOURCES_PATH",
        description="Local directory where backfill_v4_data_sources.py writes Parquet "
                    "snapshots and the JSON manifest. Never written to during live requests.",
    )
    enable_espn_provider: bool = Field(default=True, alias="ENABLE_ESPN_PROVIDER")
    enable_football_data_provider: bool = Field(default=True, alias="ENABLE_FOOTBALL_DATA_PROVIDER")
    enable_api_football_provider: bool = Field(default=False, alias="ENABLE_API_FOOTBALL_PROVIDER")
    enable_sportmonks_provider: bool = Field(default=False, alias="ENABLE_SPORTMONKS_PROVIDER")
    enable_the_odds_api_provider: bool = Field(default=False, alias="ENABLE_THE_ODDS_API_PROVIDER")
    provider_live_tests: bool = Field(default=False, alias="PROVIDER_LIVE_TESTS")
    provider_request_budget_enabled: bool = Field(default=True, alias="PROVIDER_REQUEST_BUDGET_ENABLED")

    # Backend-only provider credentials.
    # Canonical names follow the directive contract; old aliases retained for backward compat.
    sportmonks_api_key: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("SPORTMONKS_API_TOKEN", "SPORTMONKS_API_KEY"),
        description="Sportmonks API token for backend-only provider gateway calls.",
    )
    api_football_key: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("API_FOOTBALL_API_KEY", "API_FOOTBALL_KEY"),
        description="API-Football key for backend-only provider gateway calls.",
    )
    the_odds_api_key: Optional[str] = Field(
        default=None,
        # API integration guide suggests ODDS_API_KEY; directive canonical is THE_ODDS_API_KEY.
        # Accept both so users following either naming convention are covered.
        validation_alias=AliasChoices("THE_ODDS_API_KEY", "ODDS_API_KEY"),
        description="The Odds API key for backend-only provider gateway calls.",
    )

    # Per-provider daily/monthly request budgets (free-tier quota governance).
    # Unset = unlimited (no budget enforcement for that provider).
    football_data_daily_request_limit: Optional[int] = Field(
        default=None,
        alias="FOOTBALL_DATA_DAILY_REQUEST_LIMIT",
        description="Max requests per day for Football-Data.org.",
    )
    api_football_daily_request_limit: Optional[int] = Field(
        default=None,
        alias="API_FOOTBALL_DAILY_REQUEST_LIMIT",
        description="Max requests per day for API-Football.",
    )
    sportmonks_daily_request_limit: Optional[int] = Field(
        default=None,
        alias="SPORTMONKS_DAILY_REQUEST_LIMIT",
        description="Max requests per day for Sportmonks.",
    )
    the_odds_api_monthly_credit_limit: Optional[int] = Field(
        default=None,
        alias="THE_ODDS_API_MONTHLY_CREDIT_LIMIT",
        description="Max API credits per month for The Odds API.",
    )

    # Provider gateway operational settings.
    provider_request_timeout_seconds: int = Field(
        default=12,
        ge=1,
        alias="PROVIDER_REQUEST_TIMEOUT_SECONDS",
        description="Per-request timeout for provider HTTP calls.",
    )
    provider_max_retries: int = Field(
        default=2,
        ge=0,
        le=5,
        alias="PROVIDER_MAX_RETRIES",
        description="Max retry attempts per provider request (exponential backoff).",
    )
    provider_cache_enabled: bool = Field(
        default=True,
        alias="PROVIDER_CACHE_ENABLED",
        description="Enable response caching for provider gateway calls.",
    )
    provider_strict_quota_mode: bool = Field(
        default=True,
        alias="PROVIDER_STRICT_QUOTA_MODE",
        description="When True, suspend low-priority calls when quota is low.",
    )
    provider_fail_closed: bool = Field(
        default=True,
        alias="PROVIDER_FAIL_CLOSED",
        description="When True, missing provider data propagates as a structured gap (not a default).",
    )

    def _parse_cors_raw(self) -> List[str]:
        """Parse CORS_ORIGINS from raw env value (CSV or JSON string)."""
        value = self.cors_origins_raw
        if value is None:
            return self.cors_allowed_origins
        s = value.strip()
        if s == "":
            return []
        # Try JSON first if it looks like a JSON array
        if s.startswith("[") and s.endswith("]"):
            try:
                parsed = json.loads(s)
                if isinstance(parsed, list):
                    return [str(o).strip() for o in parsed if str(o).strip()]
            except Exception:
                # Fall back to CSV parsing
                pass
        # CSV fallback
        return [origin.strip() for origin in s.split(",") if origin.strip()]

    def _parse_allowed_hosts_raw(self) -> List[str]:
        """Parse ALLOWED_HOSTS from raw env value (CSV or JSON string)."""
        s = self.allowed_hosts_raw.strip() if self.allowed_hosts_raw else ""
        if s == "":
            return ["localhost", "127.0.0.1"]
        # Try JSON first if it looks like a JSON array
        if s.startswith("[") and s.endswith("]"):
            try:
                parsed = json.loads(s)
                if isinstance(parsed, list):
                    return [str(o).strip() for o in parsed if str(o).strip()]
            except Exception:
                pass
        # CSV fallback
        return [host.strip() for host in s.split(",") if host.strip()]

    @field_validator("database_url", mode="before")
    @classmethod
    def _coerce_empty_database_url(cls, v):
        if isinstance(v, str) and not v.strip():
            return "postgresql://sabi@localhost:5432/sabiscore"
        return v

    @field_validator(
        "models_path",
        "data_path",
        "phase7_models_path",
        "elo_parquet_path",
        "statsbomb_cache_path",
        "causal_report_path",
        "pi_ratings_parquet_path",
        "berrar_ratings_parquet_path",
        mode="before",
    )
    @classmethod
    def _ensure_path(cls, value):
        """Coerce to Path and anchor relative values to the project root.

        Every default above is already `_PROJECT_ROOT`-anchored, but a value
        supplied via .env/env-var arrives as a bare relative string and was
        previously resolved against the process CWD — which differs between
        pytest (backend/), uvicorn, Docker and Render. A CWD-relative artifact
        path therefore pointed at a directory that does not exist, and the
        consumers all fail *silently*: `_load_from_disk` skipped the missing
        directory and fell through to the legacy 86-feature artifacts in
        `<root>/models` (SCHEMA_MISMATCH → model_version="fallback" on every
        league, and no artifact at all for eredivisie), while EloEngine and
        StatsBombAggregator returned empty tables, pinning their features —
        including elo_difference, the highest-ATE feature in the registry — at
        registry defaults on every prediction.
        """
        if isinstance(value, (str, Path)):
            path = Path(value)
            return path if path.is_absolute() else _PROJECT_ROOT / path
        raise ValueError("Path fields must be str or Path instances")

    @field_validator("debug", mode="before")
    @classmethod
    def _coerce_debug_bool(cls, value):
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "prod", "production", "false", "0", "no", "off"}:
                return False
            if normalized in {"debug", "dev", "development", "true", "1", "yes", "on"}:
                return True
        return value

    @model_validator(mode="after")
    def _validate_environment(self) -> "Settings":
        env = self.app_env.lower()
        if env not in {"development", "staging", "production", "test"}:
            raise ValueError("app_env must be one of development, staging, production, test")

        if env == "production":
            if self.debug:
                raise ValueError("debug must be disabled in production")
            if self.secret_key == _DEFAULT_SECRET or len(self.secret_key) < 32:
                raise ValueError("SECRET_KEY must be provided and at least 32 characters in production")
            if not self.enable_security_headers:
                raise ValueError("Security headers must remain enabled in production")
            if self.scraper_allow_insecure_fallback:
                raise ValueError("SCRAPER_ALLOW_INSECURE_FALLBACK must be disabled in production")
            if self.allow_sqlite_fallback:
                raise ValueError("ALLOW_SQLITE_FALLBACK must be disabled in production")

        return self

    def model_post_init(self, __context) -> None:  # type: ignore[override]
        """Ensure important directories exist after settings load."""
        self.models_path.mkdir(parents=True, exist_ok=True)
        self.data_path.mkdir(parents=True, exist_ok=True)
        # Normalize CORS origins from raw env once model is initialized
        self.cors_allowed_origins = [
            str(o).rstrip("/") for o in self._parse_cors_raw()
        ]

    # Backwards-compat properties expected by legacy code paths
    @property
    def allowed_hosts(self) -> List[str]:
        """Parse allowed hosts from raw CSV string, auto-including Render's hostname."""
        hosts = self._parse_allowed_hosts_raw()
        if self.render_external_hostname and self.render_external_hostname not in hosts:
            hosts.append(self.render_external_hostname)
        return hosts

    @property
    def PROJECT_NAME(self) -> str:
        return self.project_name

    @property
    def VERSION(self) -> str:
        return self.version

    @property
    def API_V1_STR(self) -> str:
        return self.api_v1_str

    @property
    def ENV(self) -> str:
        return self.app_env

    @property
    def cors_origins(self) -> List[str]:
        """Expose unified accessor used across the app."""
        return self.cors_allowed_origins

    @property
    def phase8_enabled(self) -> bool:
        """Backward-compatible Phase 8 gate across legacy and current env flags."""
        return bool(self.use_phase8_models or self.use_phase8_features)

    @property
    def redis_host(self) -> Optional[str]:
        """Extract redis host from redis_url for backwards compat."""
        if not self.redis_url:
            return None
        # Parse redis://host:port or redis://user:pass@host:port
        try:
            from urllib.parse import urlparse
            parsed = urlparse(self.redis_url)
            return parsed.hostname
        except Exception:
            return None


# Global settings instance
settings = Settings()
