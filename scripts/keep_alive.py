"""
Ping backend /health/ready to reduce cold starts and emit structured latency telemetry.

Usage:
  BACKEND_URL=https://your-backend.example.com python scripts/keep_alive.py

Exit codes:
  0  — ready (HTTP 2xx, models_loaded=true)
  1  — unhealthy / timeout
  2  — misconfigured (BACKEND_URL not set)

Environment:
  BACKEND_URL            Required. Server-side secret — never use a public NEXT_PUBLIC_ var.
  COLD_START_THRESHOLD_S Optional. Float seconds above which to log a cold-start warning
                         (default: 5.0).
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any

import httpx


BACKEND_URL: str = os.environ.get("BACKEND_URL", "").strip()
COLD_START_THRESHOLD_S: float = float(
    os.environ.get("COLD_START_THRESHOLD_S", "5.0")
)
TIMEOUT_S: float = 35.0  # slightly above Render's 30-s socket timeout


def _log(level: str, msg: str, **fields: Any) -> None:
    """Emit a structured log line to stdout or stderr."""
    extra = " ".join(f"{k}={v}" for k, v in fields.items())
    line = f"[keep-alive] {level} {msg}" + (f" {extra}" if extra else "")
    if level == "ERROR":
        print(line, file=sys.stderr)
    else:
        print(line)


def ping() -> int:
    if not BACKEND_URL:
        _log("ERROR", "BACKEND_URL is required")
        return 2

    url = BACKEND_URL.rstrip("/") + "/health/ready"

    started = time.perf_counter()
    try:
        with httpx.Client(timeout=TIMEOUT_S, follow_redirects=True) as client:
            resp = client.get(url)
        latency = time.perf_counter() - started

        body: dict = {}
        try:
            body = resp.json()
        except Exception:
            pass

        models_loaded = bool(body.get("models_loaded", False))
        leagues_loaded = body.get("leagues_loaded", [])
        model_error = body.get("model_error")
        readiness_status = body.get("status", "")

        cold_start = latency >= COLD_START_THRESHOLD_S

        if cold_start:
            _log(
                "WARN",
                "cold-start detected",
                status=resp.status_code,
                latency_s=f"{latency:.3f}",
                threshold_s=COLD_START_THRESHOLD_S,
            )

        _log(
            "INFO",
            "ping",
            status=resp.status_code,
            latency_s=f"{latency:.3f}",
            readiness=readiness_status,
            models_loaded=models_loaded,
            leagues=",".join(leagues_loaded) if leagues_loaded else "none",
            cold_start=cold_start,
        )

        if model_error:
            _log("ERROR", "model_error", detail=model_error)

        if resp.status_code >= 500:
            return 1
        if not models_loaded and resp.status_code == 503:
            return 1
        return 0

    except httpx.TimeoutException as exc:
        latency = time.perf_counter() - started
        _log("ERROR", "timeout", url=url, latency_s=f"{latency:.3f}", exc=str(exc))
        return 1
    except Exception as exc:  # pragma: no cover - network/runtime safety
        latency = time.perf_counter() - started
        _log("ERROR", "error", url=url, latency_s=f"{latency:.3f}", exc=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(ping())
