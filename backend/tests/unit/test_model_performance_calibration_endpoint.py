"""Unit tests for public trust calibration metrics and reliability curve endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
import pytest
from httpx import ASGITransport, AsyncClient

from src.api.endpoints.performance import _compute_calibration_metrics
from src.api.main import app


def test_compute_calibration_metrics_brier_and_ece() -> None:
    # 60 synthetic settled predictions
    records = []
    for i in range(60):
        outcome = i % 3
        # Well-behaved probabilities
        if outcome == 0:
            probs = [0.6, 0.25, 0.15]
        elif outcome == 1:
            probs = [0.2, 0.55, 0.25]
        else:
            probs = [0.15, 0.25, 0.6]
        records.append({"outcome": outcome, "probs": probs, "date": "2026-08-01T15:00:00"})

    metrics = _compute_calibration_metrics(records, n_bins=5, league="EPL", model_version="v5_phase7")

    assert metrics["status"] == "OK"
    assert metrics["league"] == "EPL"
    assert metrics["model_version"] == "v5_phase7"
    assert metrics["sample_size"] == 60
    assert "ece" in metrics
    assert "mean" in metrics["ece"]
    assert "brier_decomposition" in metrics
    assert "curves" in metrics
    assert "home_win" in metrics["curves"]
    assert "draw" in metrics["curves"]
    assert "away_win" in metrics["curves"]
    assert len(metrics["curves"]["home_win"]) == 5
    assert "confidence_intervals" in metrics
    assert "rps" in metrics["confidence_intervals"]
    assert "brier_score" in metrics["confidence_intervals"]


@pytest.mark.asyncio
async def test_calibration_endpoint_empty_fallback() -> None:
    from src.db.session import get_async_session

    mock_db = AsyncMock()
    app.dependency_overrides[get_async_session] = lambda: mock_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with patch("src.api.endpoints.performance.get_settled_predictions", new=AsyncMock(return_value=[])):
                response = await client.get("/api/v1/model-performance/calibration")
                assert response.status_code == 503
                data = response.json()
                assert data["status"] == "METRICS_UNAVAILABLE"
                assert data["reason"] == "insufficient_settled_predictions"
    finally:
        app.dependency_overrides.pop(get_async_session, None)
