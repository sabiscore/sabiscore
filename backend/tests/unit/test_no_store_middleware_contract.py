"""Public evidence and decision responses must never be intermediary-cached."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.middleware import (
    ErrorHandlingMiddleware,
    TimingMiddleware,
    _requires_no_store,
)


def test_evidence_and_decision_paths_require_no_store() -> None:
    for path in (
        "/api/v1/betting-intelligence/match-1",
        "/api/v1/fixtures/upcoming",
        "/api/v1/full-analysis/match-1",
        "/api/v1/model-performance",
        "/api/v1/model-performance/summary",
        "/api/v1/predict",
        "/api/v1/predictions/match-1",
        "/api/v1/providers/evidence",
        "/api/v1/release/data-authority",
        "/api/v1/release/semantic-identity-review",
        "/api/v1/value-bet-scan",
    ):
        assert _requires_no_store(path), path


def test_health_and_discovery_paths_are_not_forced_no_store() -> None:
    for path in (
        "/health/live",
        "/health/ready",
        "/api/v1/providers",
        "/api/v1/providers/health",
    ):
        assert not _requires_no_store(path), path


def test_timing_middleware_sets_no_store_on_evidence_response() -> None:
    app = FastAPI()

    @app.get("/api/v1/providers/evidence")
    async def evidence() -> dict[str, str]:
        return {"status": "UNKNOWN"}

    app.add_middleware(TimingMiddleware)

    response = TestClient(app).get("/api/v1/providers/evidence")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"


def test_error_middleware_keeps_evidence_failures_non_cacheable() -> None:
    app = FastAPI()

    @app.get("/api/v1/model-performance")
    async def performance() -> dict[str, str]:
        raise RuntimeError("test failure")

    app.add_middleware(TimingMiddleware)
    app.add_middleware(ErrorHandlingMiddleware)

    response = TestClient(app).get("/api/v1/model-performance")

    assert response.status_code == 500
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["error_code"] == "INTERNAL_ERROR"
