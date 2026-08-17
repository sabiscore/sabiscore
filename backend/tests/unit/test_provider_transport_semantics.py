"""Deterministic transport semantics for the canonical provider gateway."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import AsyncMock

import httpx
import pytest

from src.providers.base import (
    BaseProvider,
    ProviderStatus,
    ProviderTransportError,
    ProviderTransportKind,
    TrustTier,
    parse_retry_after_seconds,
)
from src.providers.the_odds_api import TheOddsAPIProvider
from src.services.provider_evidence_service import ProviderEvidenceRecorder


async def _close(provider: BaseProvider) -> None:
    if provider._http_client is not None:
        await provider._http_client.aclose()


def _provider(handler) -> BaseProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return BaseProvider(enabled=True, http_client=client)


async def test_timeout_is_retried_with_bounded_attempts_and_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise httpx.ReadTimeout("timed out", request=request)
        return httpx.Response(200, json={"ok": True}, request=request)

    provider = _provider(handler)
    monkeypatch.setattr(provider, "_sleep_with_jitter", AsyncMock())
    try:
        payload, _ = await provider._get_json("https://provider.test/data")
    finally:
        await _close(provider)

    assert payload == {"ok": True}
    assert calls == 3
    assert provider.breaker.failures == 0
    assert provider.breaker.open is False


async def test_5xx_is_retried_but_client_4xx_is_not(monkeypatch: pytest.MonkeyPatch) -> None:
    server_calls = 0

    def server_handler(request: httpx.Request) -> httpx.Response:
        nonlocal server_calls
        server_calls += 1
        status = 503 if server_calls < 3 else 200
        return httpx.Response(status, json={"ok": status == 200}, request=request)

    provider = _provider(server_handler)
    monkeypatch.setattr(provider, "_sleep_with_jitter", AsyncMock())
    try:
        payload, _ = await provider._get_json("https://provider.test/data")
    finally:
        await _close(provider)
    assert payload == {"ok": True}
    assert server_calls == 3

    client_calls = 0

    def client_handler(request: httpx.Request) -> httpx.Response:
        nonlocal client_calls
        client_calls += 1
        return httpx.Response(400, json={"error": "bad request"}, request=request)

    client_provider = _provider(client_handler)
    client_provider._sleep_with_jitter = AsyncMock()  # type: ignore[method-assign]
    try:
        with pytest.raises(ProviderTransportError) as caught:
            await client_provider._get_json("https://provider.test/data")
    finally:
        await _close(client_provider)

    assert caught.value.kind is ProviderTransportKind.CLIENT_ERROR
    assert caught.value.status_code == 400
    assert client_calls == 1
    assert client_provider.breaker.failures == 0
    client_provider._sleep_with_jitter.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.parametrize("status_code", [401, 403])
async def test_authentication_failures_are_typed_and_never_retried(
    status_code: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status_code, json={"error": "auth"}, request=request)

    provider = _provider(handler)
    sleeper = AsyncMock()
    monkeypatch.setattr(provider, "_sleep_with_jitter", sleeper)
    try:
        with pytest.raises(ProviderTransportError) as caught:
            await provider._get_json("https://provider.test/private?apiKey=do-not-persist")
    finally:
        await _close(provider)

    error = caught.value
    assert error.kind is ProviderTransportKind.AUTHENTICATION
    assert error.status_code == status_code
    assert error.error_code == "TRANSPORT_AUTHENTICATION"
    assert "do-not-persist" not in str(error)
    assert calls == 1
    assert provider.breaker.failures == 1
    sleeper.assert_not_awaited()


async def test_429_honors_retry_after_once_without_double_counting(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "2"}, json={}, request=request)
        return httpx.Response(200, json={"ok": True}, request=request)

    provider = _provider(handler)
    slept: list[tuple[ProviderTransportKind, float | None, int]] = []

    async def capture_sleep(error: ProviderTransportError, attempt: int) -> None:
        slept.append((error.kind, error.retry_after_seconds, attempt))

    monkeypatch.setattr(provider, "_sleep_for_transport_failure", capture_sleep)
    failure_calls = 0
    original_record_failure = provider.breaker.record_failure

    def count_failure() -> None:
        nonlocal failure_calls
        failure_calls += 1
        original_record_failure()

    monkeypatch.setattr(provider.breaker, "record_failure", count_failure)
    try:
        payload, _ = await provider._get_json("https://provider.test/data")
    finally:
        await _close(provider)

    assert payload == {"ok": True}
    assert calls == 2
    assert failure_calls == 1
    assert slept == [(ProviderTransportKind.RATE_LIMITED, 2.0, 0)]
    assert provider.breaker.failures == 0


async def test_429_without_bounded_retry_after_fails_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "120"}, json={}, request=request)

    provider = _provider(handler)
    sleeper = AsyncMock()
    monkeypatch.setattr(provider, "_sleep_for_transport_failure", sleeper)
    try:
        with pytest.raises(ProviderTransportError) as caught:
            await provider._get_json("https://provider.test/data")
    finally:
        await _close(provider)

    assert caught.value.kind is ProviderTransportKind.RATE_LIMITED
    assert caught.value.retry_after_seconds == 120.0
    assert calls == 1
    assert provider.breaker.failures == 1
    sleeper.assert_not_awaited()


def test_retry_after_parser_supports_delta_seconds_and_http_date() -> None:
    now = datetime(2026, 8, 17, 16, 0, tzinfo=timezone.utc)
    retry_at = now + timedelta(seconds=45)

    assert parse_retry_after_seconds("3.5", now=now) == pytest.approx(3.5)
    assert parse_retry_after_seconds(format_datetime(retry_at, usegmt=True), now=now) == pytest.approx(45.0)
    assert parse_retry_after_seconds("not-a-date", now=now) is None
    assert parse_retry_after_seconds("-1", now=now) is None


async def test_breaker_opens_at_threshold_and_short_circuits_next_request() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, json={}, request=request)

    provider = _provider(handler)
    provider.max_retries = 0
    try:
        for _ in range(provider.breaker.failure_threshold):
            with pytest.raises(ProviderTransportError) as caught:
                await provider._get_json("https://provider.test/data")
            assert caught.value.kind is ProviderTransportKind.SERVER_ERROR

        assert provider.breaker.open is True
        with pytest.raises(ProviderTransportError) as caught:
            await provider._get_json("https://provider.test/data")
    finally:
        await _close(provider)

    assert caught.value.kind is ProviderTransportKind.CIRCUIT_OPEN
    assert calls == provider.breaker.failure_threshold


async def test_odds_adapter_preserves_rate_limited_status_without_string_matching() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={}, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = TheOddsAPIProvider(api_key="test", enabled=True, http_client=client)
    try:
        result = await provider.odds(competition="EPL")
    finally:
        await client.aclose()

    assert result.status is ProviderStatus.RATE_LIMITED
    assert result.error_code == "TRANSPORT_RATE_LIMITED"
    assert "transport_kind:RATE_LIMITED" in result.warnings
    assert "http_status:429" in result.warnings


async def test_exception_recorder_uses_typed_transport_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = ProviderEvidenceRecorder()
    persist = AsyncMock(return_value=True)
    monkeypatch.setattr(recorder, "_persist", persist)
    error = ProviderTransportError(
        ProviderTransportKind.RATE_LIMITED,
        status_code=429,
        retry_after_seconds=7.0,
    )

    persisted = await recorder.record_exception(
        provider="test_provider",
        operation="fixtures",
        trust_tier=TrustTier.OFFICIAL_AUTHENTICATED,
        error=error,
        duration_ms=12.0,
        circuit_open=False,
    )

    assert persisted is True
    result = persist.await_args.args[0]
    assert result.status is ProviderStatus.RATE_LIMITED
    assert result.error_code == "TRANSPORT_RATE_LIMITED"
    assert result.warnings == [
        "transport_kind:RATE_LIMITED",
        "http_status:429",
        "retry_after_seconds:7.000",
    ]
