"""Shared provider gateway primitives.

All request-time provider access goes through these contracts so credentials,
quota state, freshness, and provenance are handled in one backend-only layer.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from enum import Enum
from typing import Any, Mapping, Protocol

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


class ProviderTransportKind(str, Enum):
    """Sanitized failure classes at the shared HTTP boundary."""

    TIMEOUT = "TIMEOUT"
    NETWORK = "NETWORK"
    RATE_LIMITED = "RATE_LIMITED"
    AUTHENTICATION = "AUTHENTICATION"
    CLIENT_ERROR = "CLIENT_ERROR"
    SERVER_ERROR = "SERVER_ERROR"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"


class ProviderTransportError(RuntimeError):
    """Typed provider transport failure without credential-bearing request data.

    The exception intentionally carries only normalized status metadata. Request
    URLs, headers, response bodies, and credentials never become exception
    attributes, so callers may safely convert it into durable provider evidence.
    """

    def __init__(
        self,
        kind: ProviderTransportKind,
        *,
        status_code: int | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        self.kind = kind
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds
        super().__init__(self.safe_message)

    @property
    def error_code(self) -> str:
        return f"TRANSPORT_{self.kind.value}"

    @property
    def provider_status(self) -> ProviderStatus:
        if self.kind is ProviderTransportKind.RATE_LIMITED:
            return ProviderStatus.RATE_LIMITED
        if self.kind is ProviderTransportKind.CIRCUIT_OPEN:
            return ProviderStatus.CIRCUIT_OPEN
        return ProviderStatus.UNAVAILABLE

    @property
    def safe_message(self) -> str:
        parts = [f"provider_transport:{self.kind.value.lower()}"]
        if self.status_code is not None:
            parts.append(f"status={self.status_code}")
        if self.retry_after_seconds is not None:
            parts.append(f"retry_after={self.retry_after_seconds:.3f}s")
        return " ".join(parts)

    def warning_tokens(self) -> list[str]:
        tokens = [f"transport_kind:{self.kind.value}"]
        if self.status_code is not None:
            tokens.append(f"http_status:{self.status_code}")
        if self.retry_after_seconds is not None:
            tokens.append(f"retry_after_seconds:{self.retry_after_seconds:.3f}")
        return tokens


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


def parse_retry_after_seconds(
    value: str | None,
    *,
    now: datetime | None = None,
) -> float | None:
    """Parse Retry-After delta-seconds or HTTP-date into a non-negative delay."""
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(raw)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        reference = now or utc_now()
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        seconds = (retry_at.astimezone(timezone.utc) - reference.astimezone(timezone.utc)).total_seconds()
    if seconds < 0:
        return None
    return seconds


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
    # Match the existing football-data.org safety ceiling while allowing each
    # provider to override the bound if a tighter request-time budget is needed.
    max_retry_after_seconds = 60.0
    # A rate-limit retry is deliberately single-shot. Repeated 429 responses
    # return control to the caller rather than multiplying provider wait time.
    max_rate_limit_retries = 1

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

    def _http_failure(self, response: httpx.Response) -> ProviderTransportError | None:
        status = response.status_code
        if 200 <= status < 300:
            return None
        if status == 429:
            return ProviderTransportError(
                ProviderTransportKind.RATE_LIMITED,
                status_code=status,
                retry_after_seconds=parse_retry_after_seconds(response.headers.get("Retry-After")),
            )
        if status in (401, 403):
            return ProviderTransportError(ProviderTransportKind.AUTHENTICATION, status_code=status)
        if 400 <= status < 500 or 300 <= status < 400:
            return ProviderTransportError(ProviderTransportKind.CLIENT_ERROR, status_code=status)
        if status >= 500:
            return ProviderTransportError(ProviderTransportKind.SERVER_ERROR, status_code=status)
        return ProviderTransportError(ProviderTransportKind.INVALID_RESPONSE, status_code=status)

    @staticmethod
    def _counts_toward_breaker(error: ProviderTransportError) -> bool:
        return error.kind in {
            ProviderTransportKind.TIMEOUT,
            ProviderTransportKind.NETWORK,
            ProviderTransportKind.RATE_LIMITED,
            ProviderTransportKind.AUTHENTICATION,
            ProviderTransportKind.SERVER_ERROR,
            ProviderTransportKind.INVALID_RESPONSE,
        }

    def _record_transport_failure(self, error: ProviderTransportError) -> None:
        if self._counts_toward_breaker(error):
            self.breaker.record_failure()

    def _should_retry_transport_failure(self, error: ProviderTransportError, attempt: int) -> bool:
        if self.breaker.open:
            return False
        if error.kind in {
            ProviderTransportKind.TIMEOUT,
            ProviderTransportKind.NETWORK,
            ProviderTransportKind.SERVER_ERROR,
        }:
            return attempt < self.max_retries
        if error.kind is ProviderTransportKind.RATE_LIMITED:
            retry_after = error.retry_after_seconds
            return (
                attempt < self.max_rate_limit_retries
                and retry_after is not None
                and retry_after <= self.max_retry_after_seconds
            )
        return False

    async def _sleep_for_transport_failure(self, error: ProviderTransportError, attempt: int) -> None:
        if error.kind is ProviderTransportKind.RATE_LIMITED and error.retry_after_seconds is not None:
            await asyncio.sleep(error.retry_after_seconds)
            return
        await self._sleep_with_jitter(attempt)

    def _log_transport_failure(self, url: str, error: ProviderTransportError) -> None:
        logger.warning(
            "provider_request_failed provider=%s url=%s error=%s",
            self.provider_id,
            redact_url(url),
            error.safe_message,
        )

    async def _get_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> tuple[Any, httpx.Headers]:
        if self.breaker.open:
            raise ProviderTransportError(ProviderTransportKind.CIRCUIT_OPEN)

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
            except httpx.TimeoutException:
                error = ProviderTransportError(ProviderTransportKind.TIMEOUT)
            except httpx.TransportError:
                error = ProviderTransportError(ProviderTransportKind.NETWORK)
            except httpx.RequestError:
                error = ProviderTransportError(ProviderTransportKind.NETWORK)
            else:
                error = self._http_failure(response)
                if error is None:
                    try:
                        payload = response.json()
                    except (json.JSONDecodeError, ValueError):
                        error = ProviderTransportError(
                            ProviderTransportKind.INVALID_RESPONSE,
                            status_code=response.status_code,
                        )
                    else:
                        self.breaker.record_success()
                        return payload, response.headers

            self._record_transport_failure(error)
            if self._should_retry_transport_failure(error, attempt):
                await self._sleep_for_transport_failure(error, attempt)
                continue
            self._log_transport_failure(url, error)
            raise error

        # Every retry branch either returns or raises. Keep an explicit fail-closed
        # guard so future loop edits cannot accidentally return an untyped value.
        raise ProviderTransportError(ProviderTransportKind.NETWORK)

    def _transport_failure_result(self, operation: str, error: Exception) -> ProviderResult:
        """Convert typed transport failures to a stable public ProviderResult."""
        if isinstance(error, ProviderTransportError):
            return ProviderResult(
                provider=self.provider_id,
                operation=operation,
                status=error.provider_status,
                trust_tier=self.trust_tier,
                warnings=error.warning_tokens(),
                error_code=error.error_code,
            )
        return ProviderResult(
            provider=self.provider_id,
            operation=operation,
            status=ProviderStatus.UNAVAILABLE,
            trust_tier=self.trust_tier,
            error_code=type(error).__name__,
        )

    @staticmethod
    def _transport_status(error: Exception) -> ProviderStatus:
        if isinstance(error, ProviderTransportError):
            return error.provider_status
        return ProviderStatus.UNAVAILABLE

    async def _sleep_with_jitter(self, attempt: int) -> None:
        await asyncio.sleep(min(2.0, 0.25 * (2**attempt)) + random.random() * 0.1)
