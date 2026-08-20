"""Health check and readiness probe endpoints for orchestration and monitoring."""

import logging
import os
import re
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.cache import cache_manager
from ...core.config import settings
from ...db.session import get_async_session
from ...models.active_generation import ActiveGenerationError, load_active_generation

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)


def _release_sha() -> str | None:
    """Return an exact deploy SHA only when runtime metadata is trustworthy.

    Render injects ``RENDER_GIT_COMMIT`` for Git-backed services.  The explicit
    ``SABISCORE_RELEASE_SHA`` fallback supports non-Render/local release
    verification without ever inventing a revision.  Malformed/truncated values
    are UNKNOWN rather than being presented as exact parity evidence.
    """

    raw = os.getenv("RENDER_GIT_COMMIT") or os.getenv("SABISCORE_RELEASE_SHA")
    candidate = raw.strip() if raw else ""
    return candidate.lower() if _GIT_SHA_RE.fullmatch(candidate) else None


@lru_cache(maxsize=1)
def _validated_generation() -> Dict[str, Any]:
    """Hash-validate the committed generation once per process.

    The active generation is deployment-atomic and cannot legitimately change
    underneath a running process. Re-hashing every model artifact on every
    readiness probe would turn a cheap orchestration endpoint into repeated
    full-file I/O. Startup already enforces the same authority; this cached
    fallback keeps the endpoint independently truthful without a hot-path scan.
    """
    return load_active_generation()


@router.get("/health", status_code=status.HTTP_200_OK)
async def health_check() -> Dict[str, Any]:
    """Basic process-liveness probe.

    This endpoint deliberately does not claim dependency, model-performance, or
    provider health. Those belong to readiness/diagnostic surfaces backed by
    direct observations.
    """
    return {
        "status": "healthy",
        "service": "sabiscore-api",
        "version": settings.app_version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": settings.app_env,
        "release_sha": _release_sha(),
    }


def _model_readiness(request: Request) -> Dict[str, Any]:
    """Return hash-validated model runtime state without performance claims."""
    app_state = request.app.state
    runtime_loaded = bool(getattr(app_state, "models_loaded", False))
    loaded_models = getattr(app_state, "models", {}) or {}
    loaded_leagues = sorted(str(league) for league in loaded_models)

    try:
        generation = _validated_generation()
    except ActiveGenerationError as exc:
        return {
            "status": "unhealthy",
            "runtime_loaded": runtime_loaded,
            "manifest_valid": False,
            "loaded_leagues": loaded_leagues,
            "error": str(exc),
            "certification_state": "UNVERIFIED",
            "stake_permitted": False,
        }

    artifacts = generation.get("artifacts", {})
    required_leagues = sorted(
        league
        for league, entry in artifacts.items()
        if bool(entry.get("required", False))
    )
    missing_required = sorted(set(required_leagues) - set(loaded_leagues))
    runtime_ready = runtime_loaded and not missing_required
    certification_state = str(generation.get("certification_state") or "UNVERIFIED")

    return {
        "status": "healthy" if runtime_ready else "unhealthy",
        "runtime_loaded": runtime_loaded,
        "manifest_valid": True,
        "generation": generation.get("generation"),
        "active_version": generation.get("active_version"),
        "feature_schema_version": generation.get("feature_schema_version"),
        "certification_state": certification_state,
        "promotion_state": generation.get("promotion_state"),
        "required_leagues": required_leagues,
        "loaded_leagues": loaded_leagues,
        "missing_required_leagues": missing_required,
        "prediction_capability": "AVAILABLE" if runtime_ready else "BLOCKED",
        "stake_permitted": runtime_ready and certification_state == "CERTIFIED",
    }


@router.get("/ready", status_code=status.HTTP_200_OK)
async def readiness_check(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_async_session),
) -> Dict[str, Any]:
    """Readiness probe backed by direct dependency and runtime observations.

    Operational readiness is intentionally separate from model certification:
    an UNVERIFIED generation may be loaded for fail-closed research inference,
    while staking remains disabled. Missing/tampered model artifacts or required
    runtime models do fail readiness.
    """
    checks: Dict[str, Any] = {
        "database": {"status": "unknown", "latency_ms": None},
        "cache": {"status": "unknown", "latency_ms": None},
        "models": {"status": "unknown", "runtime_loaded": False},
    }

    critical_healthy = True

    try:
        start = datetime.now(timezone.utc)
        result = await db.execute(text("SELECT 1"))
        result.scalar()
        latency = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        checks["database"] = {
            "status": "healthy",
            "latency_ms": round(latency, 2),
        }
    except Exception as exc:
        logger.error("Database health check failed: %s", exc)
        checks["database"] = {"status": "unhealthy", "error": str(exc)}
        critical_healthy = False

    try:
        start = datetime.now(timezone.utc)
        test_key = "health:check"
        cache_manager.set(test_key, "ok", ttl=5)
        result = cache_manager.get(test_key)
        latency = (datetime.now(timezone.utc) - start).total_seconds() * 1000

        if result == "ok":
            checks["cache"] = {
                "status": "healthy",
                "latency_ms": round(latency, 2),
                "backend": "redis" if settings.redis_host else "memory",
            }
        else:
            checks["cache"] = {
                "status": "degraded",
                "message": "cache read/write mismatch",
            }
    except Exception as exc:
        logger.error("Cache health check failed: %s", exc)
        checks["cache"] = {"status": "degraded", "error": str(exc)}

    checks["models"] = _model_readiness(request)
    if checks["models"].get("status") != "healthy":
        critical_healthy = False

    if not critical_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        overall_status = "unhealthy"
    elif checks["cache"].get("status") == "degraded":
        overall_status = "degraded"
    else:
        overall_status = "healthy"

    return {
        "status": overall_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "release_sha": _release_sha(),
        "checks": checks,
        "ready": critical_healthy,
        "capabilities": {
            "prediction": checks["models"].get("prediction_capability", "BLOCKED"),
            "stake": "ENABLED" if checks["models"].get("stake_permitted") else "DISABLED",
        },
    }


@router.get("/metrics")
async def metrics_endpoint() -> Dict[str, Any]:
    """Explicitly report that request/model/cache counters are not instrumented.

    Returning literal zeros would falsely assert observed zero activity. Until a
    metrics backend owns these counters, absence is UNKNOWN rather than success.
    """
    return {
        "status": "not_instrumented",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": None,
        "predictions_total": None,
        "predictions_errors_total": None,
        "cache_hits_total": None,
        "cache_misses_total": None,
        "database_connections_active": None,
    }


@router.get("/startup")
async def startup_status(request: Request) -> Dict[str, Any]:
    """Expose startup/model initialization facts available from application state."""
    app_state = request.app.state
    models_loaded = bool(getattr(app_state, "models_loaded", False))
    model_load_in_progress = bool(getattr(app_state, "model_load_in_progress", False))
    model_error = getattr(app_state, "model_load_error_message", None)

    initialization: Dict[str, Any] = {
        "models_loaded": models_loaded,
        "model_load_in_progress": model_load_in_progress,
        "model_version": getattr(app_state, "model_version", None),
        "leagues_loaded": list(getattr(app_state, "leagues_loaded", []) or []),
        "model_load_error": model_error,
        # This endpoint does not perform dependency probes. Consumers requiring
        # DB/cache truth must use /ready instead of treating reachability as proof.
        "database_ready": "unknown_use_ready_probe",
        "cache_ready": "unknown_use_ready_probe",
    }

    startup_ready = models_loaded and not model_load_in_progress and model_error is None
    return {
        "status": "ready" if startup_ready else "initializing",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "release_sha": _release_sha(),
        "initialization": initialization,
    }
