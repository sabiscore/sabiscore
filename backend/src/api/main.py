import asyncio
import json
from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI
import logging
from .middleware import setup_middleware
from . import api_router
from .endpoints.monitoring import router as monitoring_router_root
from .websocket import router as ws_router
from ..core.config import settings
from ..core.redaction import redact_text
from ..core.cache import cache
from ..core.model_fetcher import DEFAULT_LEAGUES, load_ensemble_per_league
from ..models.active_generation import load_active_generation
from ..db.session import init_db, close_db
from ..providers import build_provider_registry
from ..services.odds_service import OddsService
import os
from datetime import datetime, timezone

# Sentry integration for error tracking
if settings.sentry_dsn:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
    
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        integrations=[
            FastApiIntegration(),
            SqlalchemyIntegration(),
        ],
        traces_sample_rate=0.1,  # 10% of requests for performance monitoring
        profiles_sample_rate=0.1,  # 10% for profiling
        environment=settings.app_env,
        release=f"sabiscore@{os.getenv('APP_VERSION', '1.0.0')}",
        before_send=lambda event, hint: _filter_sentry_event(event, hint),
    )
    logging.info("Sentry error tracking initialized")

def _filter_sentry_event(event, hint):
    """Filter Sentry events to reduce noise and redact secrets."""
    sensitive = ("token", "secret", "api_key", "apikey", "authorization", "password", "key")

    def _redact(value):
        if isinstance(value, dict):
            return {
                k: ("[REDACTED]" if any(s in str(k).lower() for s in sensitive) else _redact(v))
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [_redact(item) for item in value]
        if isinstance(value, str):
            return redact_text(value)
        return value

    # Skip 404 errors
    if event.get('exception'):
        for exception in event['exception']['values']:
            if '404' in str(exception.get('value', '')):
                return None
    return _redact(event)

# OpenTelemetry (ADR-0006): no-op unless enable_tracing AND an OTLP endpoint
# are both configured. Registered before router mounts, alongside the other
# module-level integration setup (Sentry, above).
from ..core.telemetry import setup_telemetry, shutdown_telemetry  # noqa: E402

setup_telemetry()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Global model instance
model_instance = None
# Simple flag to avoid concurrent background loads
model_load_in_progress = False

# Custom JSON encoder that handles various non-serializable types
class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if hasattr(obj, 'isoformat') and callable(getattr(obj, 'isoformat')):
            return obj.isoformat()
        if hasattr(obj, '__dict__'):
            return {k: v for k, v in obj.__dict__.items() if not k.startswith('_')}
        if hasattr(obj, 'dict') and callable(getattr(obj, 'dict')):
            return obj.dict()
        if hasattr(obj, 'model_dump') and callable(getattr(obj, 'model_dump')):
            return obj.model_dump()
        return str(obj)  # Fallback to string representation

# Fixtures enter the sync window as each league's season opens, so this must keep
# running rather than seeding once. 7 requests per tick every 6h is ~0.008 req/min
# against football-data.org's 10 req/min free tier. The cadence exists for recovery,
# not freshness: a boot-time 429 previously left the platform with zero fixtures
# until the next deploy (observed in production 2026-08-08).
_FIXTURE_SYNC_INTERVAL_SECONDS = 21600


async def _background_fixture_sync() -> None:
    """Backfill match history once, then seed upcoming fixtures periodically.

    The backfill runs first and only on the boot tick: it reads committed CSVs off
    local disk (no provider quota) and establishes the richer team vocabulary that
    fixture sync then resolves its provider names against, so the two datasets share
    Team ids rather than minting parallel rows for the same club. It is idempotent,
    so a redeploy re-checks cheaply and a partially-applied previous run completes.

    Without it `matches` holds no finished rows at all, `_get_team_stats()` returns
    None for both sides of every fixture, and every prediction is suppressed as
    synthetic (measured in production 2026-08-08: 0 of 49 fixtures publishable).

    Both calls swallow their own errors, so a failed tick is logged and recorded in
    metrics without breaking the loop.
    """
    from ..services.fixture_sync_service import run_fixture_sync
    from ..services.historical_backfill_service import run_historical_backfill

    first_tick = True
    while True:
        if first_tick:
            try:
                await run_historical_backfill()
            except Exception:
                logger.exception("Historical backfill failed")
            first_tick = False
        try:
            await run_fixture_sync()
        except Exception:
            logger.exception("Background fixture sync failed")
        await asyncio.sleep(_FIXTURE_SYNC_INTERVAL_SECONDS)


# 7 requests/tick (one per competition, same shape as the fixture-sync loop) at an
# hourly cadence averages ~0.12 req/min against football-data.org's 10 req/min free
# tier — large headroom. Hourly means a finished match is visible in settled_join
# telemetry within ~1h of full time; this is a model-evaluation signal, not a live
# score feed, so there is no lower-latency obligation to beat (docs/adr/0003).
_SETTLEMENT_SYNC_INTERVAL_SECONDS = 3600


async def _background_settlement_sync() -> None:
    """Matches finish all through a matchday, not just at boot. Sleeps first so
    the initial tick never collides with fixture-sync's own boot-time request
    burst — both hit football-data.org's shared 10 req/min free-tier quota."""
    from ..services.settlement_service import run_settlement_pass

    while True:
        await asyncio.sleep(_SETTLEMENT_SYNC_INTERVAL_SECONDS)
        try:
            await run_settlement_pass()
        except Exception:
            logger.exception("Background settlement sync failed")


# docs/adr/0004-clv-capture.md: a kickoff that passes uncaptured is
# unrecoverable, so this polls far tighter than settlement's hourly cadence —
# the capture window itself is only ~10 minutes wide (clv_capture_service).
_CLV_CAPTURE_INTERVAL_SECONDS = 300


async def _background_clv_capture(provider) -> None:
    """Genuinely periodic, same shape as settlement sync — must keep polling
    across a matchday, not just seed once at boot."""
    from ..services.clv_capture_service import run_clv_capture_pass

    while True:
        await asyncio.sleep(_CLV_CAPTURE_INTERVAL_SECONDS)
        try:
            await run_clv_capture_pass(provider=provider)
        except Exception:
            logger.exception("Background CLV capture failed")


# Lifespan context manager for modern FastAPI startup/shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Modern lifespan handler for startup and shutdown events."""
    global model_instance, model_load_in_progress
    
    # === STARTUP ===
    logger.info("Starting SabiScore API...")
    
    # Initialize cache and model state
    app.state.cache = cache
    app.state.model_instance = None
    app.state.models = {}
    app.state.models_loaded = False
    app.state.model_version = None
    app.state.leagues_loaded = []
    app.state.model_load_error_message = None
    app.state.model_load_in_progress = True
    app.state.model_load_attempts = 0

    # Provider gateway: one lifespan-owned httpx client + registry, shared by
    # every request instead of opened per-call (CLAUDE.md provider gateway rule).
    app.state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(8.0),
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )
    app.state.provider_registry = build_provider_registry(http_client=app.state.http_client)
    app.state.odds_service = OddsService(
        cache_backend=app.state.cache,
        provider=app.state.provider_registry.get("the_odds_api"),
    )

    # Initialize async database
    try:
        await init_db()
        logger.info("Async database initialized")
    except Exception:
        logger.exception("Startup: failed to initialize async database")

    # Seed upcoming fixtures in the background so the intelligence dashboard
    # has data immediately after first deploy, then re-seed on a slow cadence.
    # Handle stored so it cancels cleanly on shutdown, same as the two below.
    app.state.fixture_sync_task = asyncio.create_task(_background_fixture_sync())

    # Periodic settlement pass: settle finished fixtures, then run walk-forward
    # validation against whatever's settled. Handle stored (not fire-and-forget
    # like the one-shot task above) so it can be cancelled cleanly on shutdown.
    app.state.settlement_task = asyncio.create_task(_background_settlement_sync())

    # Periodic CLV capture: closing 1X2 snapshot per fixture near kickoff.
    # Same handle-stored/cancel-on-shutdown shape as settlement, above.
    app.state.clv_capture_task = asyncio.create_task(
        _background_clv_capture(app.state.provider_registry.get("the_odds_api"))
    )

    # Strict model initialization (blocking) - startup must fail if models are unavailable.
    try:
        _startup_load_models_strict(app)
    except Exception:
        logger.exception("Startup: strict model initialization failed")
        try:
            await close_db()
        except Exception:
            logger.exception("Startup rollback: failed to close async database")
        raise RuntimeError("Startup aborted: model initialization failed")
    
    # V4 / Phase 9 source registry — informational startup log
    try:
        from ..connectors.source_registry import registry_summary as _v4_registry_summary
        logger.info("V4 source registry: %s", _v4_registry_summary(settings))
    except Exception as _v4_exc:
        logger.debug("V4 source registry unavailable at startup: %s", _v4_exc)

    logger.info("SabiScore API startup complete")
    
    yield  # Server is running
    
    # === SHUTDOWN ===
    logger.info("Shutting down SabiScore API...")

    # All three background loops run forever — cancel them explicitly or every
    # redeploy logs an asyncio "task destroyed while pending" warning.
    for task_name in ("fixture_sync_task", "settlement_task", "clv_capture_task"):
        task = getattr(app.state, task_name, None)
        if task is not None:
            task.cancel()

    try:
        await close_db()
        logger.info("Async database closed")
    except Exception:
        logger.exception("Shutdown: failed to close async database")

    try:
        await app.state.http_client.aclose()
        logger.info("Provider HTTP client closed")
    except Exception:
        logger.exception("Shutdown: failed to close provider HTTP client")

    # Last, so any span/metric emitted by the teardown steps above still flushes.
    shutdown_telemetry()

    logger.info("SabiScore API shutdown complete")

def _resolve_active_leagues() -> tuple[str, ...]:
    raw = (os.environ.get("ACTIVE_LEAGUES") or "").strip()
    if not raw:
        return DEFAULT_LEAGUES

    leagues = tuple(
        part.strip().lower()
        for part in raw.split(",")
        if part.strip()
    )
    return leagues or DEFAULT_LEAGUES


def _prime_prediction_service_cache(models: dict) -> None:
    """Prime class-level prediction cache with eagerly loaded league models."""
    try:
        from ..services.prediction import PredictionService as MatchPredictionService

        now_ts = datetime.now(timezone.utc).timestamp()
        with MatchPredictionService._cache_lock:
            MatchPredictionService._ensemble_cache = dict(models)
            MatchPredictionService._metadata_cache = {
                league: (model.model_metadata or {}) for league, model in models.items()
            }
            MatchPredictionService._cache_access_times = {
                league: now_ts for league in models
            }
    except Exception as exc:
        logger.warning("Startup: could not prime prediction cache: %s", exc)


def _startup_load_models_strict(app: FastAPI) -> None:
    """Load one validated ensemble per league before serving requests."""
    global model_instance, model_load_in_progress

    app.state.model_load_in_progress = True
    app.state.model_load_attempts = int(getattr(app.state, "model_load_attempts", 0)) + 1
    model_load_in_progress = True

    model_version = (os.environ.get("ACTIVE_BASELINE_VERSION") or "v5_phase7").strip() or "v5_phase7"
    leagues = _resolve_active_leagues()

    generation = load_active_generation()
    manifest_version = str(generation.get("active_version") or "").strip()
    if manifest_version != model_version:
        raise RuntimeError(
            "ACTIVE_BASELINE_VERSION does not match the hash-validated active generation"
        )
    missing_leagues = sorted(set(leagues) - set(generation["artifacts"]))
    if missing_leagues:
        raise RuntimeError(
            "Active generation does not contain every required league: "
            + ", ".join(missing_leagues)
        )

    # Promotion and rollback are commit-atomic: startup may load only files whose
    # artifact and metadata hashes were validated by the committed manifest.
    # MODEL_BASE_URL remains available to offline fetch tooling, but cannot replace
    # an active production generation with an unmanifested remote payload.
    local_dirs = [generation["manifest_path"].parent]

    models = load_ensemble_per_league(
        model_base_url=None,
        version=model_version,
        local_model_dirs=local_dirs,
        leagues=leagues,
        fetch_token=None,
    )

    if not models:
        raise RuntimeError("No league models loaded during startup")

    app.state.models = dict(models)
    app.state.leagues_loaded = sorted(models.keys())
    app.state.model_version = model_version
    app.state.model_generation = generation["generation"]
    app.state.model_manifest_sha256 = generation["manifest_sha256"]
    app.state.models_loaded = True
    app.state.model_load_error_message = None
    app.state.model_load_in_progress = False

    default_league = "epl" if "epl" in models else app.state.leagues_loaded[0]
    model_instance = models[default_league]
    app.state.model_instance = model_instance
    model_load_in_progress = False

    _prime_prediction_service_cache(models)
    logger.info(
        "Startup: strict model initialization complete (%s, leagues=%s)",
        model_version,
        ", ".join(app.state.leagues_loaded),
    )

# Create FastAPI app with custom JSON encoder and lifespan
app = FastAPI(
    title="SabiScore API",
    description="AI-Powered Football Betting Intelligence Platform",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# Apply custom JSON encoder to the app
app.json_encoder = CustomJSONEncoder

# OpenTelemetry (ADR-0006): instrumentation is only mounted when tracing is
# actually configured — the OTel API itself is a safe no-op without a
# provider, but skipping instrument_app() entirely when unconfigured avoids
# even the inert middleware hop on the free-tier dyno (ADR-0006 "Cost").
if settings.enable_tracing and settings.otel_exporter_otlp_endpoint:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app)


def load_model_if_needed(start_background: bool = True):
    """Deprecated lazy-loader shim.

    Models are now loaded eagerly at startup through strict readiness gates.
    """
    del start_background  # no-op
    instance = getattr(app.state, "model_instance", None)
    if instance is not None and getattr(instance, "is_trained", False):
        return instance

    logger.warning("load_model_if_needed called but strict startup model load is incomplete")
    return None

# Setup middleware
setup_middleware(app)

# Provide helper to access loaded model without creating circular imports
def get_loaded_model(default=None):
    models = getattr(app.state, "models", {}) or {}
    if "epl" in models and getattr(models["epl"], "is_trained", False):
        return models["epl"]

    instance = getattr(app.state, "model_instance", None)
    if instance is not None and getattr(instance, "is_trained", False):
        return instance
    if model_instance is not None and getattr(model_instance, "is_trained", False):
        return model_instance
    return default

# Include routers
app.include_router(api_router, prefix=getattr(settings, 'API_V1_STR', '/api/v1'), tags=["API"])
app.include_router(ws_router, tags=["WebSocket"])

# Include monitoring/health check routes at root level for container orchestration
# Use monitoring router which has /health, /health/live, /health/ready, /metrics
app.include_router(monitoring_router_root, tags=["monitoring"])


@app.get("/")
async def root():
    return {
        "message": "Welcome to SabiScore API",
        "version": os.getenv("APP_VERSION", "1.0.0"),
        "docs": "/docs",
        "health": "/health",
        "ready": "/ready",
        "startup": "/startup",
    }
