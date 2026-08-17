"""Shared provider gateway primitives.

All request-time provider access goes through these contracts so credentials,
quota state, freshness, and provenance are handled in one backend-only layer.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from datetime import datetime, timezone
from enum import Enum
from functools import wraps
from typing import Any, Awaitable, Callable, Concatenate, Mapping, ParamSpec, Protocol, TypeVar

import httpx
from pydantic import BaseModel, Field

from ..core.redaction import (
    redact_mapping,
    redact_text,
    redact_url,
)

logger = logging.getLogger(__name__)


class ProviderStatus(str, Enum):
    VERIFIED = "VERIFIED"
    CONFIGURED_UNVERIFIED = "CONFIGURED_UNVERIFIED"
    UNCONFIGURED = "UNCONFIGURED"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    RATE_LIMITED = "RATE_LIMITED"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    INVALID = "INVALID"
    CONFLICTING = "CONFLICTING"


class TrustTier(str, Enum):
    OFFICIAL_AUTHENTICATED = "OFFICIAL_AUTHENTICATED"
    OFFICIAL_OPEN = "OFFICIAL_OPEN"
    OPEN_DATA = "OPEN_DATA"
    UNOFFICIAL_PUBLIC = "UNOFFICIAL_PUBLIC"
    USER_CONFIRMED = "USER_CONFIRMED"


class ProviderQuota(BaseModel):
    limit: int | None = None
    remaining: int | None = None
    reset_at: datetime | None = None
    cost: int | None = None


class ProviderCapability(BaseModel):
    provider: str
    competition: str
    season: str | None = None
    fixtures: bool = False
    standings: bool = False
    lineups: bool = False
    injuries: bool = False
    team_statistics: bool = False
    player_statistics: bool = False
    odds: bool = False
    xg: bool = False
    provider_predictions: bool = False
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    notes: list[str] = Field(default_factory=list)


class ProviderHealth(BaseModel):
    provider: str
    enabled: bool
    configured: bool
    status: ProviderStatus
    trust_tier: TrustTier
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    warnings: list[str] = Field(default_factory=list)
    error_code: str | None = None
    quota: ProviderQuota = Field(default_factory=ProviderQuota)


class ProviderResult(BaseModel):
    provider: str
    operation: str
    status: ProviderStatus
    trust_tier: TrustTier
    acquired_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    provider_timestamp: datetime | None = None
    records: list[dict[str, Any]] = Field(default_factory=list)
    quota: ProviderQuota = Field(default_factory=ProviderQuota)
    warnings: list[str] = Field(default_factory=list)
    error_code: str | None = None
    raw_snapshot_id: str | None = None


class ProviderObservationSink(Protocol):
    """Persistence boundary for provider evidence.

    Implementations must be best-effort: an observability outage must never
    change the provider result returned to the caller.
    """

    async def record_result(
        self,
        result: ProviderResult,
        *,
        duration_ms: float,
        circuit_open: bool,
    ) -> bool: ...

    async def record_exception(
        self,
        *,
        provider: str,
        operation: str,
        trust_tier: TrustTier,
        error: Exception,
        duration_ms: float,
        circuit_open: bool,
    ) -> bool: ...


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class CircuitBreaker:
    """Small in-memory circuit breaker for provider parse/HTTP failures."""

    def __init__(self, failure_threshold: int = 3, open_seconds: int = 300) -> None:
        self.failure_threshold = failure_threshold
        self.open_seconds = open_seconds
        self.failures = 0
        self.opened_at: datetime | None = None

    @property
    def open(self) -> bool:
        if self.opened_at is None:
            return False
        age = (utc_now() - self.opened_at).total_seconds()
        if age > self.open_seconds:
            self.failures = 0
            self.opened_at = None
            return False
        return True

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.opened_at = utc_now()


class BaseProvider:
    provider_id = "base"
    display_name = "Base Provider"
    trust_tier = TrustTier.OPEN_DATA
    requires_key = False
    enabled = False
    timeout_seconds = 8.0
    max_retries = 2

    def __init__(
        self,
        *,
        api_key: str | None = None,
        enabled: bool = False,
        live_tests: bool = False,
        http_client: httpx.AsyncClient | None = None,
        observation_sink: ProviderObservationSink | None = None,
    ) -> None:
        self.api_key = api_key
        self.enabled = enabled
        self.live_tests = live_tests
        self.breaker = CircuitBreaker()
        # Lifespan-owned client when injected by the registry; falls back to a
        # per-call client only when constructed directly (e.g. unit tests).
        self._http_client = http_client
        self._observation_sink = observation_sink

    @property
    def configured(self) -> bool:
        return bool(self.api_key) if self.requires_key else True

    async def health(self) -> ProviderHealth:
        warnings: list[str] = []
        if not self.enabled:
            status = ProviderStatus.UNAVAILABLE
            warnings.append("provider_disabled")
        elif self.requires_key and not self.api_key:
            status = ProviderStatus.UNCONFIGURED
            warnings.append("missing_backend_credential")
        elif self.breaker.open:
            status = ProviderStatus.CIRCUIT_OPEN
            warnings.append("circuit_breaker_open")
        elif self.live_tests:
            status = await self.probe()
        else:
            status = ProviderStatus.CONFIGURED_UNVERIFIED
            warnings.append("live_probe_not_run")
        return ProviderHealth(
            provider=self.provider_id,
            enabled=self.enabled,
            configured=self.configured,
            status=status,
            trust_tier=self.trust_tier,
            warnings=warnings,
        )

    async def probe(self) -> ProviderStatus:
        """Provider-specific live probes should return VERIFIED only after network validation."""
        return ProviderStatus.CONFIGURED_UNVERIFIED

    async def capabilities(self) -> list[ProviderCapability]:
        return []

    async def quota(self) -> ProviderQuota:
        return ProviderQuota()

    async def doctor(self) -> dict[str, Any]:
        health = await self.health()
        capabilities = await self.capabilities()
        quota = await self.quota()
        return {
            "provider": self.provider_id,
            "display_name": self.display_name,
            "health": health.model_dump(mode="json"),
            "capability_count": len(capabilities),
            "quota": quota.model_dump(mode="json"),
            "configuration": redact_mapping(
                {
                    "enabled": self.enabled,
                    "requires_key": self.requires_key,
                    "api_key_configured": bool(self.api_key),
                    "live_probe_enabled": self.live_tests,
                }
            ),
        }

    async def _observe_result(self, result: ProviderResult, duration_ms: float) -> None:
        sink = self._observation_sink
        if sink is None:
            return
        try:
            await sink.record_result(
                result,
                duration_ms=duration_ms,
                circuit_open=self.breaker.open,
            )
        except Exception as exc:  # pragma: no cover - defensive isolation
            logger.warning(
                "provider_observation_failed provider=%s operation=%s error=%s",
                self.provider_id,
                result.operation,
                redact_text(exc),
            )

    async def _observe_exception(
        self,
        operation: str,
        error: Exception,
        duration_ms: float,
    ) -> None:
        sink = self._observation_sink
        if sink is None:
            return
        try:
            await sink.record_exception(
                provider=self.provider_id,
                operation=operation,
                trust_tier=self.trust_tier,
                error=error,
                duration_ms=duration_ms,
                circuit_open=self.breaker.open,
            )
        except Exception as exc:  # pragma: no cover - defensive isolation
            logger.warning(
                "provider_exception_observation_failed provider=%s operation=%s error=%s",
                self.provider_id,
                operation,
                redact_text(exc),
            )

    async def _get_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> tuple[Any, httpx.Headers]:
        if self.breaker.open:
            raise RuntimeError(f"{self.provider_id} circuit breaker is open")
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                if self._http_client is not None:
                    response = await self._http_client.get(
                        url,
                        headers=dict(headers or {}),
                        params=params,
                        timeout=httpx.Timeout(self.timeout_seconds),
                    )
                else:
                    async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout_seconds)) as client:
                        response = await client.get(url, headers=dict(headers or {}), params=params)
                if response.status_code == 429:
                    self.breaker.record_failure()
                    raise RuntimeError("rate_limited")
                response.raise_for_status()
                self.breaker.record_success()
                return response.json(), response.headers
            except Exception as exc:  # pragma: no cover - network path
                last_exc = exc
                self.breaker.record_failure()
                if attempt < self.max_retries:
                    await self._sleep_with_jitter(attempt)
        safe_url = redact_url(url)
        # httpx exception messages embed the full request URL (with query string) —
        # scrub them before they reach any log sink.
        safe_error = redact_text(str(last_exc)) if last_exc else None
        logger.warning("provider_request_failed provider=%s url=%s error=%s", self.provider_id, safe_url, safe_error)
        raise last_exc or RuntimeError("provider_request_failed")

    async def _sleep_with_jitter(self, attempt: int) -> None:
        import asyncio

        await asyncio.sleep(min(2.0, 0.25 * (2**attempt)) + random.random() * 0.1)


_P = ParamSpec("_P")
_R = TypeVar("_R")


def observed_provider_call(
    func: Callable[Concatenate[BaseProvider, _P], Awaitable[_R]],
) -> Callable[Concatenate[BaseProvider, _P], Awaitable[_R]]:
    """Observe a public provider operation without changing its semantics.

    Normal ProviderResult outcomes, including disabled/unconfigured/rate-limited
    results, are persisted through the configured sink. Truly unexpected
    exceptions are observed and then re-raised exactly as before. Failure of the
    observation sink itself is swallowed by BaseProvider so telemetry can never
    poison the evidence request path.
    """

    @wraps(func)
    async def wrapper(self: BaseProvider, *args: _P.args, **kwargs: _P.kwargs) -> _R:
        started = time.perf_counter()
        try:
            result = await func(self, *args, **kwargs)
        except Exception as exc:
            await self._observe_exception(
                func.__name__,
                exc,
                (time.perf_counter() - started) * 1000,
            )
            raise

        if isinstance(result, ProviderResult):
            await self._observe_result(
                result,
                (time.perf_counter() - started) * 1000,
            )
        return result

    return wrapper
