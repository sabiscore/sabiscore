"""Snapshot calibration metrics for the active generation (Phase B, B2).

Reads live calibration metrics from the backend and persists them to
backend/models/calibration_baselines.json — one entry per generation, so
recalibration (B3) can be measured against a fixed prior.

Usage:
    python scripts/snapshot_calibration_baseline.py
    python scripts/snapshot_calibration_baseline.py --api-url https://sabiscore-api-bav1.onrender.com
    python scripts/snapshot_calibration_baseline.py --generation v5_phase7 --from-directive

Running this after every generation activation creates the per-generation
series the directive requires: reliability, resolution, ECE, Brier stored
so recalibration is measured against a fixed prior, not a moving target.

⚠️  --from-directive writes the known live telemetry from the directive
    (n=59, reliability=0.0326) without hitting the API.  Use this when
    you already have authoritative figures and the API is unavailable.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_BASELINES_FILE = (
    Path(__file__).resolve().parents[1] / "models" / "calibration_baselines.json"
)

# Live telemetry from Production Executive Directive v4 §2 (2026-09-08)
_DIRECTIVE_V4_TELEMETRY = {
    "n": 59,
    "reliability": 0.0326,
    "resolution": 0.0412,
    "uncertainty": 0.2159,
    "brier": 0.2088,
    "ece": 0.1343,
    "note": (
        "Live telemetry from Production Executive Directive v4 §2 (2026-09-08). "
        "Murphy decomposition: Brier = Reliability − Resolution + Uncertainty = "
        "0.0326 − 0.0412 + 0.2159. Reliability target for B3: ≤0.010."
    ),
}


def _fetch_from_api(api_url: str) -> dict:
    try:
        import httpx  # already in requirements.runtime.txt
    except ImportError:
        print("ERROR: httpx is required. pip install httpx", file=sys.stderr)
        sys.exit(1)
    url = f"{api_url.rstrip('/')}/api/v1/model-performance/calibration"
    resp = httpx.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _active_generation() -> str:
    """Read the generation name from active_generation.json."""
    gen_file = _BASELINES_FILE.parent / "active_generation.json"
    if gen_file.exists():
        data = json.loads(gen_file.read_text(encoding="utf-8"))
        return data.get("active_version") or data.get("generation") or "unknown"
    return "unknown"


def _load_baselines() -> dict:
    if _BASELINES_FILE.exists():
        return json.loads(_BASELINES_FILE.read_text(encoding="utf-8"))
    return {}


def _save_baselines(baselines: dict) -> None:
    _BASELINES_FILE.write_text(
        json.dumps(baselines, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Snapshot calibration baseline for active generation"
    )
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="Backend base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--generation",
        default=None,
        help="Generation name (auto-detected from active_generation.json if omitted)",
    )
    parser.add_argument(
        "--from-directive",
        action="store_true",
        help=(
            "Write the authoritative live telemetry from the Production Executive "
            "Directive v4 §2 without hitting the API. Only use when the API is "
            "unavailable and the figures are already known-authoritative."
        ),
    )
    args = parser.parse_args()

    generation = args.generation or _active_generation()

    if args.from_directive:
        entry = {
            "generation": generation,
            "measured_at": datetime.now(timezone.utc).isoformat(),
            **_DIRECTIVE_V4_TELEMETRY,
        }
    else:
        data = _fetch_from_api(args.api_url)
        if data.get("status") == "METRICS_UNAVAILABLE":
            print(
                f"ERROR: calibration endpoint returned METRICS_UNAVAILABLE: {data.get('reason')}\n"
                f"Tip: run with --from-directive if you have authoritative figures already.",
                file=sys.stderr,
            )
            return 1
        brier_decomp = data.get("brier_decomposition", {})
        entry = {
            "generation": generation,
            "measured_at": datetime.now(timezone.utc).isoformat(),
            "n": data.get("sample_size"),
            "reliability": brier_decomp.get("reliability"),
            "resolution": brier_decomp.get("resolution"),
            "uncertainty": brier_decomp.get("uncertainty"),
            "brier": brier_decomp.get("brier_score"),
            "ece": data.get("ece"),
        }

    baselines = _load_baselines()
    baselines[generation] = entry
    _save_baselines(baselines)

    print(f"Snapshotted calibration baseline for generation '{generation}':")
    print(
        f"  n={entry['n']}, reliability={entry['reliability']}, "
        f"resolution={entry['resolution']}, ECE={entry['ece']}, Brier={entry['brier']}"
    )
    print(f"  Written to {_BASELINES_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
