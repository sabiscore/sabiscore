"""Provider CLI public-contract tests."""

from __future__ import annotations

import json
from typing import Iterable

from click.testing import CliRunner

from src.cli import providers as provider_cli
from src.cli.providers import (
    ALLOWED_LIVE_VALIDATION_STATES,
    ALLOWED_PROVIDER_CLI_STATUSES,
    providers_cli,
)
from src.providers.base import ProviderHealth, ProviderQuota, ProviderStatus, TrustTier


def _health(
    status: ProviderStatus,
    *,
    provider: str = "fake",
    enabled: bool = True,
    configured: bool = True,
    remaining: int | None = None,
) -> ProviderHealth:
    return ProviderHealth(
        provider=provider,
        enabled=enabled,
        configured=configured,
        status=status,
        trust_tier=TrustTier.OFFICIAL_AUTHENTICATED,
        quota=ProviderQuota(remaining=remaining),
    )


class _FakeProvider:
    provider_id = "fake"

    def __init__(self, health: ProviderHealth) -> None:
        self._health = health
        self.live_tests = False

    async def health(self) -> ProviderHealth:
        return self._health


class _FakeRegistry:
    def __init__(self, providers: Iterable[_FakeProvider]) -> None:
        self._providers = list(providers)

    def list(self) -> list[_FakeProvider]:
        return self._providers

    def get(self, provider_id: str) -> _FakeProvider:
        for provider in self._providers:
            if provider.provider_id == provider_id:
                return provider
        raise KeyError(provider_id)


def _payload(result) -> dict:
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_provider_cli_status_mapping() -> None:
    cases = {
        "configured": _health(ProviderStatus.CONFIGURED_UNVERIFIED),
        "missing": _health(ProviderStatus.UNCONFIGURED, configured=False),
        "invalid": _health(ProviderStatus.INVALID),
        "quota_exhausted": _health(ProviderStatus.VERIFIED, remaining=0),
        "temporarily_unavailable": _health(ProviderStatus.CIRCUIT_OPEN),
    }

    for expected, health in cases.items():
        assert provider_cli._provider_cli_status(health) == expected
        assert expected in ALLOWED_PROVIDER_CLI_STATUSES


def test_provider_doctor_uses_only_public_status_contract(monkeypatch) -> None:
    fake = _FakeProvider(_health(ProviderStatus.CONFIGURED_UNVERIFIED))
    monkeypatch.setattr(provider_cli, "build_provider_registry", lambda: _FakeRegistry([fake]))

    payload = _payload(CliRunner().invoke(providers_cli, ["doctor"]))

    assert payload == {
        "providers": [
            {
                "provider": "fake",
                "status": "configured",
                "live_validation": "not_run",
            }
        ]
    }
    assert fake.live_tests is False


def test_provider_status_uses_same_public_status_contract(monkeypatch) -> None:
    fake = _FakeProvider(_health(ProviderStatus.RATE_LIMITED))
    monkeypatch.setattr(provider_cli, "build_provider_registry", lambda: _FakeRegistry([fake]))

    payload = _payload(CliRunner().invoke(providers_cli, ["status", "--provider", "fake"]))

    assert payload == {"providers": [{"provider": "fake", "status": "quota_exhausted"}]}


def test_provider_doctor_live_validation_is_explicit(monkeypatch) -> None:
    fake = _FakeProvider(_health(ProviderStatus.CONFIGURED_UNVERIFIED))
    monkeypatch.setattr(provider_cli, "build_provider_registry", lambda: _FakeRegistry([fake]))

    payload = _payload(
        CliRunner().invoke(
            providers_cli,
            ["doctor", "--provider", "fake", "--validate-live"],
        )
    )

    assert fake.live_tests is True
    assert payload["providers"][0]["live_validation"] == "failed"
    assert payload["providers"][0]["live_validation"] in ALLOWED_LIVE_VALIDATION_STATES


def test_provider_doctor_live_validation_passes_only_after_verified_probe(
    monkeypatch,
) -> None:
    fake = _FakeProvider(_health(ProviderStatus.VERIFIED))
    monkeypatch.setattr(provider_cli, "build_provider_registry", lambda: _FakeRegistry([fake]))

    payload = _payload(
        CliRunner().invoke(
            providers_cli,
            ["doctor", "--provider", "fake", "--validate-live"],
        )
    )

    assert payload["providers"][0]["status"] == "configured"
    assert payload["providers"][0]["live_validation"] == "passed"
