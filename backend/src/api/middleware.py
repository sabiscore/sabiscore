from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware
import logging
import time
import json
import uuid
from typing import Dict
from datetime import datetime, timezone

from ..core.cache import cache
from ..core.config import settings

logger = logging.getLogger(__name__)

_NO_STORE_PATH_PREFIXES = (
    "/api/v1/betting-intelligence",
    "/api/v1/fixtures",
    "/api/v1/full-analysis",
    "/api/v1/model-performance",
    "/api/v1/predict",
    "/api/v1/providers/evidence",
    "/api/v1/release/data-authority",
    "/api/v1/release/semantic-identity-review",
    "/api/v1/value-bet-scan",
)


def _requires_no_store(path: str) -> bool:
    """Return whether a public evidence or decision response is non-cacheable."""

    return path.startswith(_NO_STORE_PATH_PREFIXES)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Redis-backed fixed-window rate limiting."""

    def __init__(self, app, requests_per_window: int, window_seconds: int):
        super().__init__(app)
        self.requests_per_window = requests_per_window
        self.window_seconds = window_seconds
        self._memory_fallback: Dict[str, Dict[int, int]] = {}

    async def dispatch(self, request: Request, call_next):
        client_ip = (request.client.host if request.client else "unknown") or "unknown"
        window_start = int(time.time() // self.window_seconds * self.window_seconds)

        if self._is_rate_limited(client_ip, window_start):
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Too many requests",
                    "error_code": "RATE_LIMIT_EXCEEDED",
                },
            )

        return await call_next(request)

    def _is_rate_limited(self, client_ip: str, window_start: int) -> bool:
        redis_client = getattr(cache, "redis_client", None)

        if redis_client:
            key = f"ratelimit:{client_ip}:{window_start}"
            try:
                count = redis_client.incr(key)
                if count == 1:
                    redis_client.expire(key, self.window_seconds)
                return count > self.requests_per_window
            except Exception as exc:  # pragma: no cover - fallback path
                logger.warning("Redis rate limit fallback engaged: %s", exc)

        bucket = self._memory_fallback.setdefault(client_ip, {})
        bucket[window_start] = bucket.get(window_start, 0) + 1

        # prune old windows
        for ts in list(bucket.keys()):
            if ts < window_start:
                bucket.pop(ts, None)

        return bucket[window_start] > self.requests_per_window

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers when enabled."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        if settings.enable_security_headers:
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            response.headers.setdefault("X-Frame-Options", "DENY")
            response.headers.setdefault("X-XSS-Protection", "1; mode=block")
            response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")

            if settings.app_env != "development":
                response.headers.setdefault(
                    "Strict-Transport-Security",
                    "max-age=31536000; includeSubDomains",
                )
                response.headers.setdefault(
                    "Content-Security-Policy",
                    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'",
                )
            else:
                response.headers.setdefault(
                    "Content-Security-Policy",
                    "default-src 'self'; "
                    "script-src 'self' 'unsafe-inline' 'unsafe-eval' http://localhost:3000 http://127.0.0.1:3000; "
                    "style-src 'self' 'unsafe-inline'; "
                    "connect-src 'self' ws://localhost:3000 ws://127.0.0.1:3000 http://localhost:8000 http://127.0.0.1:8000;",
                )

        return response


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Attach a stable correlation ID to each request."""

    async def dispatch(self, request: Request, call_next):
        request_id = (
            request.headers.get("X-Request-ID")
            or request.headers.get("X-Correlation-ID")
            or str(uuid.uuid4())
        )
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class TimingMiddleware(BaseHTTPMiddleware):
    """Request timing and structured logging middleware."""

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time

        if request.url.path.startswith("/api/v1/predict") or request.url.path.startswith("/api/v1/predictions"):
            body = getattr(request.state, "prediction_result", {}) or {}
            record = {
                "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "request_id": getattr(request.state, "request_id", str(uuid.uuid4())),
                "match_id": body.get("match_id"),
                "league": body.get("league"),
                "predicted_outcome": body.get("predicted_outcome"),
                "confidence": body.get("confidence"),
                "edge_pct": body.get("edge_pct"),
                "feature_quality": body.get("feature_quality"),
                "model_version": body.get("model_version"),
                "value_bet": body.get("value_bet"),
                "latency_ms": round(process_time * 1000, 1),
                "status_code": response.status_code,
            }
            print(json.dumps(record), flush=True)

        logger.info(
            "request_completed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(process_time * 1000, 2),
                "request_id": getattr(request.state, "request_id", None),
            },
        )

        if _requires_no_store(request.url.path):
            response.headers.setdefault("Cache-Control", "no-store")
        response.headers["X-Process-Time"] = f"{process_time:.6f}"
        return response


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """Global error handling middleware emitting structured errors."""

    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            return response
        except Exception:  # pragma: no cover - safety net
            logger.exception("Unhandled application error", extra={"path": request.url.path})
            response = JSONResponse(
                status_code=500,
                content={
                    "detail": "Internal server error",
                    "error_code": "INTERNAL_ERROR",
                    "request_id": getattr(request.state, "request_id", None),
                    "timestamp": time.time(),
                },
            )
            if _requires_no_store(request.url.path):
                response.headers["Cache-Control"] = "no-store"
            return response


def setup_middleware(app):
    """Setup all middleware for the FastAPI app"""

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.cors_origin_regex or None,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    # Trusted hosts (only in production or when explicitly configured).
    # If `allowed_hosts` is left as the default development list, skip enabling
    # TrustedHostMiddleware to avoid rejecting valid production Host headers
    # (e.g. Render/Cloudflare domains) when the operator hasn't configured
    # ALLOWED_HOSTS for the deployment.
    if settings.app_env == "production" and settings.allowed_hosts:
        default_hosts = ["localhost", "127.0.0.1"]
        if settings.allowed_hosts == default_hosts:
            logger.warning(
                "TrustedHostMiddleware not enabled: ALLOWED_HOSTS is default localhost. "
                "Set allowed_hosts environment variable to your production host to enable.")
        else:
            app.add_middleware(
                TrustedHostMiddleware,
                allowed_hosts=settings.allowed_hosts,
            )

    # Rate limiting
    app.add_middleware(
        RateLimitMiddleware,
        requests_per_window=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )

    # Security headers
    app.add_middleware(SecurityHeadersMiddleware)

    # Request correlation
    app.add_middleware(CorrelationIdMiddleware)

    # Response compression
    if settings.enable_response_compression:
        app.add_middleware(GZipMiddleware, minimum_size=500)

    # Timing and logging
    app.add_middleware(TimingMiddleware)

    # Error handling
    app.add_middleware(ErrorHandlingMiddleware)
