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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cached",
    [
        {"status": "OK"},
        '{"status": "OK"}',
        b'{"status": "OK"}',
    ],
)
async def test_calibration_endpoint_reads_serialized_cache_payloads(cached) -> None:
    from src.db.session import get_async_session

    class StubCache:
        def get(self, _key):
            return cached

    mock_db = AsyncMock()
    app.dependency_overrides[get_async_session] = lambda: mock_db
    try:
        transport = ASGITransport(app=app)
        with (
            patch("src.api.endpoints.performance.cache", StubCache()),
            patch("src.api.endpoints.performance.active_model_version", return_value="test"),
            patch("src.api.endpoints.performance.get_settled_predictions", new=AsyncMock()) as get_records,
        ):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/v1/model-performance/calibration")

        assert response.status_code == 200
        assert response.json() == {"status": "OK"}
        get_records.assert_not_awaited()
    finally:
        app.dependency_overrides.pop(get_async_session, None)


@pytest.mark.asyncio
async def test_calibration_endpoint_caches_result_without_double_encoding() -> None:
    from src.db.session import get_async_session

    class StubCache:
        def __init__(self):
            self.value = None

        def get(self, _key):
            return None

        def set(self, _key, value, ttl):
            self.value = (value, ttl)

    cache_stub = StubCache()
    records = [
        {"outcome": 0, "probs": [0.6, 0.25, 0.15], "date": "2026-08-01T15:00:00"}
        for _ in range(12)
    ]
    mock_db = AsyncMock()
    app.dependency_overrides[get_async_session] = lambda: mock_db
    try:
        transport = ASGITransport(app=app)
        with (
            patch("src.api.endpoints.performance.cache", cache_stub),
            patch("src.api.endpoints.performance.active_model_version", return_value="test"),
            patch(
                "src.api.endpoints.performance.get_settled_predictions",
                new=AsyncMock(return_value=records),
            ),
        ):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/v1/model-performance/calibration")

        assert response.status_code == 200
        assert cache_stub.value is not None
        cached_value, _ = cache_stub.value
        assert isinstance(cached_value, dict)
        assert cached_value == response.json()
    finally:
        app.dependency_overrides.pop(get_async_session, None)
