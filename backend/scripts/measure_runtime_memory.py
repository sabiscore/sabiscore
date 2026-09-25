"""Directive v8 S2: measure serving memory on the production target.

Run inside ``python:3.11.9-slim`` with ``requirements.runtime.txt`` installed
(the Render build). Prints one JSON document:

- RSS after the interpreter starts, after ``import src.api.main``, and after
  every served artifact is loaded;
- peak RSS during one walk-forward bootstrap (the heaviest request-path job);
- the RSS each heavy library adds, imported alone in a fresh interpreter.

``ru_maxrss`` is Linux-only (KiB there), so this is not meant for Windows.
"""

from __future__ import annotations

import json
import platform
import random
import resource
import subprocess
import sys

import psutil

_MB = 1024 * 1024
_LIBRARIES = (
    "numpy", "pandas", "scipy", "sklearn", "xgboost", "lightgbm", "sqlalchemy",
    "fastapi", "pydantic", "httpx", "aiohttp", "redis", "boto3", "lxml", "bs4",
    "cloudscraper", "sentry_sdk", "opentelemetry.sdk", "prometheus_client",
)


def _rss() -> float:
    return round(psutil.Process().memory_info().rss / _MB, 1)


def _peak() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)


def _library_cost(name: str) -> float | None:
    code = (
        "import psutil;p=psutil.Process();b=p.memory_info().rss;"
        f"import {name};print((p.memory_info().rss-b)/{_MB})"
    )
    try:
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=120
        )
        return round(float(out.stdout.strip()), 1)
    except (ValueError, subprocess.TimeoutExpired):
        return None


def main() -> None:
    report: dict = {"python": sys.version.split()[0], "platform": platform.platform()}
    report["baseline_mb"] = _rss()

    import src.api.main  # noqa: F401  (the whole app, as uvicorn imports it)

    report["after_app_import_mb"] = _rss()

    from src.models.active_generation import load_active_generation
    from src.models.prediction import PredictionEngine

    engine = PredictionEngine()
    bundles = [
        engine._load_from_disk(slug) for slug in load_active_generation()["artifacts"]
    ]
    report["artifacts_loaded"] = sum(b is not None for b in bundles)
    report["after_models_mb"] = _rss()

    from src.models.model_registry import get_walk_forward_registry

    rng = random.Random(0)
    records = []
    for i in range(300):
        p = [rng.random() + 0.2 for _ in range(3)]
        records.append(
            {
                "date": f"2026-{1 + i // 28 % 12:02d}-{1 + i % 28:02d}",
                "outcome": rng.randrange(3),
                "probs": [x / sum(p) for x in p],
            }
        )
    peak_before = _peak()
    get_walk_forward_registry().walk_forward_validate(records)
    report["bootstrap_records"] = len(records)
    report["peak_before_bootstrap_mb"] = peak_before
    report["peak_after_bootstrap_mb"] = _peak()
    report["after_bootstrap_mb"] = _rss()

    report["library_import_mb"] = {name: _library_cost(name) for name in _LIBRARIES}
    report["heavy_modules_loaded_by_app"] = sorted(
        name for name in _LIBRARIES if name in sys.modules
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
