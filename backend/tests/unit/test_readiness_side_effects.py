"""Readiness probes must never execute prediction/provider evidence paths."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import Response

from src.api.endpoints import monitoring


def _ready_request() -> SimpleNamespace:
    model = SimpleNamespace(is_trained=True)
    leagues = monitoring._resolve_required_leagues()
    models = {league: model for league in leagues}
    state = SimpleNamespace(
        models=models,
        models_loaded=True,
        leagues_loaded=leagues,
        model_version="test-generation",
        model_load_error_message=None,
        model_load_in_progress=False,
    )
    return SimpleNamespace(app=SimpleNamespace(state=state))


async def test_readiness_is_side_effect_free_when_core_gates_are_green() -> None:
    request = _ready_request()
    db = AsyncMock()
    odds_lookup = AsyncMock()
    persist_prediction = AsyncMock()

    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value.execute.return_value = None

    with (
        patch.object(monitoring, "get_engine", return_value=mock_engine),
        patch.object(
            monitoring,
            "_check_alembic_revision",
            return_value={"status": "ready", "head": "0003", "applied": "0003"},
        ),
        patch.object(monitoring.cache, "production_ready", return_value=True),
        patch.object(
            monitoring.cache,
            "metrics_snapshot",
            return_value={
                "tier1_redis_enabled": True,
                "tier1_redis_available": True,
            },
        ),
        patch.object(
            monitoring,
            "_discover_model_artifacts",
            return_value={"count": 6, "artifact_names": ["model.joblib"]},
        ),
        patch(
            "src.services.elo_state_service.elo_state_health",
            new=AsyncMock(
                return_value={
                    "authority": "postgres",
                    "rows": 25522,
                    "unique_teams": 159,
                    "last_match_date": "2026-05-24T15:00:00",
                }
            ),
        ),
        patch(
            "src.services.odds_service.OddsService.get_match_odds",
            new=odds_lookup,
        ),
        patch(
            "src.services.prediction_log_service.persist_prediction_log",
            new=persist_prediction,
        ),
    ):
        first_response = Response()
        first = await monitoring.readiness_check(request, first_response, db)
        second_response = Response()
        second = await monitoring.readiness_check(request, second_response, db)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first["status"] == second["status"] == "ok"
    assert first["capability"]["status"] == "not_probed_by_readiness"
    assert first["capability"]["external_io"] is False
    assert first["capability"]["evidence_write"] is False
    assert second["capability"]["status"] == "not_probed_by_readiness"
    odds_lookup.assert_not_awaited()
    persist_prediction.assert_not_awaited()
    assert not hasattr(monitoring, "_compute_capability")
    assert not hasattr(monitoring, "_check_capability")


async def test_readiness_preserves_core_503_semantics_without_capability_probe() -> None:
    request = _ready_request()
    db = AsyncMock()
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value.execute.return_value = None

    with (
        patch.object(monitoring, "get_engine", return_value=mock_engine),
        patch.object(
            monitoring,
            "_check_alembic_revision",
            return_value={"status": "ready", "head": "0003", "applied": "0003"},
        ),
        patch.object(monitoring.cache, "production_ready", return_value=False),
        patch.object(
            monitoring.cache,
            "metrics_snapshot",
            return_value={
                "tier1_redis_enabled": True,
                "tier1_redis_available": False,
            },
        ),
        patch.object(
            monitoring,
            "_discover_model_artifacts",
            return_value={"count": 6, "artifact_names": ["model.joblib"]},
        ),
        patch(
            "src.services.elo_state_service.elo_state_health",
            new=AsyncMock(return_value={"authority": "postgres"}),
        ),
    ):
        response = Response()
        payload = await monitoring.readiness_check(request, response, db)

    assert response.status_code == 503
    assert payload["status"] == "not_ready"
    assert payload["capability"]["status"] == "skipped_not_ready"
    assert payload["capability"]["external_io"] is False
    assert payload["capability"]["evidence_write"] is False
