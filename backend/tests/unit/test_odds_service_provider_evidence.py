"""Regression coverage for OddsService provider-observation wiring."""

from __future__ import annotations

from types import SimpleNamespace

from src.providers.registry import build_provider_registry
from src.providers.the_odds_api import TheOddsAPIProvider
from src.services.odds_service import OddsService
from src.services.provider_evidence_service import ProviderEvidenceRecorder


class _NullCache:
    def get(self, _key: str):
        return None

    def set(self, _key: str, _value, ttl: int | None = None) -> None:
        return None


def test_default_odds_service_uses_instrumented_observed_provider() -> None:
    service = OddsService(cache_backend=_NullCache())

    assert isinstance(service.provider, TheOddsAPIProvider)
    assert getattr(service.provider, "_provider_evidence_instrumented", False) is True
    assert isinstance(
        getattr(service.provider, "_observation_sink", None),
        ProviderEvidenceRecorder,
    )


def test_injected_provider_identity_is_preserved() -> None:
    sink = SimpleNamespace(record_result=None, record_exception=None)
    provider = build_provider_registry(observation_sink=sink).get("the_odds_api")

    service = OddsService(cache_backend=_NullCache(), provider=provider)  # type: ignore[arg-type]

    assert service.provider is provider
    assert getattr(service.provider, "_provider_evidence_instrumented", False) is True
