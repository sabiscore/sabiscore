"""Health probes must not drown the request log; real requests must be legible.

Render probes /health/ready every ~5 s. Each probe used to write a
content-free "request_completed" line (the fields sat in `extra`, which the
root formatter never prints), so the log was mostly probe noise.
"""

import logging

from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

from src.api.middleware import TimingMiddleware


def _client() -> TestClient:
    app = FastAPI()

    @app.get("/health/ready")
    async def ready(fail: bool = False) -> Response:
        return Response(status_code=503 if fail else 200)

    @app.get("/api/v1/fixtures/upcoming")
    async def fixtures() -> dict[str, list]:
        return {"fixtures": []}

    app.add_middleware(TimingMiddleware)
    return TestClient(app)


def _messages(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "src.api.middleware"]


def test_successful_health_probe_is_not_logged(caplog) -> None:
    caplog.set_level(logging.INFO, logger="src.api.middleware")
    _client().get("/health/ready")
    assert _messages(caplog) == []


def test_failing_health_probe_is_still_logged(caplog) -> None:
    caplog.set_level(logging.INFO, logger="src.api.middleware")
    _client().get("/health/ready", params={"fail": "true"})
    assert any("/health/ready 503" in m for m in _messages(caplog))


def test_request_line_names_method_path_and_status(caplog) -> None:
    caplog.set_level(logging.INFO, logger="src.api.middleware")
    _client().get("/api/v1/fixtures/upcoming")
    assert any(
        m.startswith("request_completed GET /api/v1/fixtures/upcoming 200 ")
        for m in _messages(caplog)
    )
