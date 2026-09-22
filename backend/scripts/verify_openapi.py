"""Generate and validate the canonical FastAPI OpenAPI surface without network calls."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("MOCK_MODE", "false")
os.environ.setdefault("ENABLE_LEGACY_INFERENCE", "false")
os.environ.setdefault("ALLOW_SQLITE_FALLBACK", "true")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./.openapi-check.db")


def _import_app():
    # SIGALRM is not available on Windows; use a threading-based timeout instead.
    if sys.platform == "win32":
        import threading

        _result: list = []
        _exc: list = []

        def _target():
            try:
                from src.api.main import app as imported_app

                _result.append(imported_app)
            except Exception as e:
                _exc.append(e)

        t = threading.Thread(target=_target, daemon=True)
        t.start()
        t.join(timeout=90)
        if t.is_alive():
            raise TimeoutError("FastAPI application import exceeded 90 seconds")
        if _exc:
            raise _exc[0]
        return _result[0]

    # Unix path — use SIGALRM for a clean timeout.
    import signal

    def _timeout(_signum, _frame):
        raise TimeoutError("FastAPI application import exceeded 60 seconds")

    previous = signal.signal(signal.SIGALRM, _timeout)
    signal.alarm(60)
    try:
        from src.api.main import app as imported_app

        return imported_app
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


REQUIRED_PATHS = {
    "/api/v1/betting-intelligence/analyze",
    "/api/v1/betting-intelligence/analyze/single",
    "/api/v1/betting-intelligence/policy",
    "/api/v1/betting-intelligence/health",
    "/api/v1/fixtures/upcoming",
    "/api/v1/providers",
    "/api/v1/providers/health",
    "/api/v1/providers/capabilities",
    "/api/v1/providers/quota",
}


def main() -> int:
    app = _import_app()
    schema = app.openapi()
    paths = set(schema.get("paths", {}))
    missing = sorted(REQUIRED_PATHS - paths)
    if missing:
        raise SystemExit(f"OpenAPI is missing required paths: {missing}")
    if schema.get("openapi") is None or schema.get("info", {}).get("title") is None:
        raise SystemExit("OpenAPI metadata is incomplete")

    output = Path("artifacts/openapi.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")
    print(f"OpenAPI verified: {len(paths)} paths; artifact={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
