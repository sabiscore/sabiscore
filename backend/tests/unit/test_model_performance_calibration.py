"""Unit tests for the calibration endpoint's sample-floor honesty and cache.

Sibling coverage lives in ``test_model_performance_calibration_endpoint.py``
(pure-function OK-path assertions and the empty-records 503 fallback). This
file covers the three additions from the calibration-honesty fix: the
below-floor signal, empty-bin fail-closed nulls, and the 6h cache.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.endpoints.performance import (
    MIN_RECORDS_FOR_DECOMPOSITION,
    _compute_calibration_metrics,
)
from src.api.main import app

# Fixed per-outcome probability triples: home_win probs cycle {0.5, 0.3, 0.2},
# draw probs cycle {0.3, 0.5, 0.3}, away_win probs cycle {0.2, 0.2, 0.5} across
# the i % 3 outcome rotation. None of the three classes ever produces a
# probability above 0.6, so with n_bins=5 the (0.6, 0.8] bin (index 3) is
# guaranteed empty for every class — deterministic, no reliance on RNG.
_PROBS_BY_OUTCOME = {0: [0.5, 0.3, 0.2], 1: [0.3, 0.5, 0.2], 2: [0.2, 0.3, 0.5]}


def _records(n: int) -> list[dict]:
    return [
        {
            "outcome": i % 3,
            "probs": _PROBS_BY_OUTCOME[i % 3],
            "date": "2026-08-01T15:00:00",
        }
        for i in range(n)
    ]


def test_below_floor_reports_meets_sample_floor_false() -> None:
    records = _records(5)  # < MIN_RECORDS_FOR_DECOMPOSITION
    metrics = _compute_calibration_metrics(records, n_bins=10, league="EPL", model_version="v5_phase7")

    assert metrics["status"] == "OK"
    assert metrics["sample_size"] == 5
    assert metrics["minimum_sample_size"] == MIN_RECORDS_FOR_DECOMPOSITION
    assert MIN_RECORDS_FOR_DECOMPOSITION == 10
    assert metrics["meets_sample_floor"] is False


def test_at_or_above_floor_reports_meets_sample_floor_true() -> None:
    records = _records(12)  # >= MIN_RECORDS_FOR_DECOMPOSITION
    metrics = _compute_calibration_metrics(records, n_bins=5, league="EPL", model_version="v5_phase7")

    assert metrics["sample_size"] == 12
    assert metrics["meets_sample_floor"] is True


def test_empty_bin_is_null_not_fabricated() -> None:
    records = _records(12)
    metrics = _compute_calibration_metrics(records, n_bins=5, league="EPL", model_version="v5_phase7")

    for cls_name in ("home_win", "draw", "away_win"):
        empty_bin = metrics["curves"][cls_name][3]  # (0.6, 0.8], guaranteed empty
        assert empty_bin["count"] == 0
        assert empty_bin["empirical_frequency"] is None
        assert empty_bin["predicted_mean"] is None

        occupied_bin = metrics["curves"][cls_name][2]  # (0.4, 0.6], has data
        assert occupied_bin["count"] > 0
        assert occupied_bin["empirical_frequency"] is not None
        assert occupied_bin["predicted_mean"] is not None


@pytest.mark.asyncio
async def test_calibration_endpoint_cache_hit_skips_recompute(monkeypatch) -> None:
    from src.db.session import get_async_session
    import src.api.endpoints.performance as endpoint

    store: dict = {}
    monkeypatch.setattr(endpoint.cache, "get", lambda key: store.get(key))
    monkeypatch.setattr(
        endpoint.cache, "set", lambda key, value, ttl=None: store.__setitem__(key, value)
    )

    mock_get_settled = AsyncMock(return_value=_records(15))
    mock_db = AsyncMock()
    app.dependency_overrides[get_async_session] = lambda: mock_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with patch(
                "src.api.endpoints.performance.get_settled_predictions", new=mock_get_settled
            ):
                first = await client.get("/api/v1/model-performance/calibration")
                second = await client.get("/api/v1/model-performance/calibration")
    finally:
        app.dependency_overrides.pop(get_async_session, None)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    # The DB/heavy-compute path only ran once — the second call was a cache hit.
    assert mock_get_settled.await_count == 1
    assert len(store) == 1
