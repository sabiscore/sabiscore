"""Truthfulness regressions for health/readiness surfaces."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.api.endpoints.health import (
    _model_readiness,
    _release_sha,
    metrics_endpoint,
)


def _request(*, models_loaded: bool, loaded_leagues: list[str]):
    state = SimpleNamespace(
        models_loaded=models_loaded,
        models={league: object() for league in loaded_leagues},
        model_load_in_progress=False,
        model_load_error_message=None,
        model_version="v5_phase7",
        leagues_loaded=loaded_leagues,
    )
    return SimpleNamespace(app=SimpleNamespace(state=state))


def _generation(*, certification_state: str = "UNVERIFIED") -> dict:
    return {
        "generation": "candidate-generation",
        "active_version": "v5_phase7",
        "feature_schema_version": "phase7_68",
        "certification_state": certification_state,
        "promotion_state": "ACTIVE_FAIL_CLOSED",
        "artifacts": {
            "epl": {"required": True},
            "la_liga": {"required": True},
            "eredivisie": {"required": False},
        },
    }


def test_release_sha_prefers_render_runtime_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    render_sha = "2beb31e0d4ed8c340fa55ea0063af93daae1d4f7"
    fallback_sha = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    monkeypatch.setenv("RENDER_GIT_COMMIT", render_sha.upper())
    monkeypatch.setenv("SABISCORE_RELEASE_SHA", fallback_sha)

    assert _release_sha() == render_sha


def test_release_sha_uses_explicit_fallback_when_render_metadata_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fallback_sha = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    monkeypatch.setenv("SABISCORE_RELEASE_SHA", fallback_sha)

    assert _release_sha() == fallback_sha


def test_release_sha_rejects_truncated_or_malformed_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RENDER_GIT_COMMIT", "abc123")
    monkeypatch.delenv("SABISCORE_RELEASE_SHA", raising=False)

    assert _release_sha() is None


def test_unverified_generation_can_be_runtime_ready_but_never_stake_permitted() -> None:
    request = _request(models_loaded=True, loaded_leagues=["epl", "la_liga"])

    with patch("src.api.endpoints.health._validated_generation", return_value=_generation()):
        result = _model_readiness(request)

    assert result["status"] == "healthy"
    assert result["prediction_capability"] == "AVAILABLE"
    assert result["certification_state"] == "UNVERIFIED"
    assert result["stake_permitted"] is False


def test_missing_required_runtime_model_fails_readiness() -> None:
    request = _request(models_loaded=True, loaded_leagues=["epl"])

    with patch("src.api.endpoints.health._validated_generation", return_value=_generation()):
        result = _model_readiness(request)

    assert result["status"] == "unhealthy"
    assert result["prediction_capability"] == "BLOCKED"
    assert result["missing_required_leagues"] == ["la_liga"]
    assert result["stake_permitted"] is False


def test_certified_generation_requires_runtime_readiness_before_stake_permission() -> None:
    request = _request(models_loaded=False, loaded_leagues=["epl", "la_liga"])

    with patch(
        "src.api.endpoints.health._validated_generation",
        return_value=_generation(certification_state="CERTIFIED"),
    ):
        result = _model_readiness(request)

    assert result["status"] == "unhealthy"
    assert result["stake_permitted"] is False


@pytest.mark.asyncio
async def test_uninstrumented_metrics_are_unknown_not_fabricated_zeroes() -> None:
    result = await metrics_endpoint()

    assert result["status"] == "not_instrumented"
    for key in (
        "uptime_seconds",
        "predictions_total",
        "predictions_errors_total",
        "cache_hits_total",
        "cache_misses_total",
        "database_connections_active",
    ):
        assert result[key] is None
