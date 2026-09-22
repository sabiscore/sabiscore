from __future__ import annotations

import pytest

from src.core import telemetry
from src.core.config import settings


def test_setup_telemetry_noop_when_tracing_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "enable_tracing", False)
    monkeypatch.setattr(
        settings, "otel_exporter_otlp_endpoint", "https://collector.example/v1/traces"
    )

    telemetry.setup_telemetry()  # must not raise or import the SDK

    assert telemetry._tracer_provider is None


def test_setup_telemetry_noop_when_endpoint_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "enable_tracing", True)
    monkeypatch.setattr(settings, "otel_exporter_otlp_endpoint", None)

    telemetry.setup_telemetry()

    assert telemetry._tracer_provider is None


def test_shutdown_telemetry_noop_without_a_registered_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(telemetry, "_tracer_provider", None)

    telemetry.shutdown_telemetry()  # must not raise
