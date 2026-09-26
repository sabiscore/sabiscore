"""Portfolio F, experiment F3b — do wind and heavy rain add information?

Pre-registered: `reports/research/f3b-weather-wind-rain-protocol.json`, frozen
and committed before any F3b data was fetched. This script refuses to run if
its constants disagree with that file, and records the file's sha256 in the
report, so the result can be tied to the exact protocol it was judged by.

F3 tested temperature and precipitation amount and was null. F3b tests what F3
left out: wind speed, gusts, and rain as a threshold. Everything else is F3's
machinery unchanged (same market baseline, folds, bootstrap and bar), imported
from `study_f3_weather_incremental_value.py` rather than copied.

Usage
-----
    cd backend && PYTHONPATH=. python scripts/study_f3b_wind_rain_incremental_value.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _incremental_value_harness import fit_multinomial_logistic  # noqa: E402
from study_f3_weather_incremental_value import (  # noqa: E402
    _FOLDS,
    _SEED,
    build_rows,
    run_arm,
    verdict,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = _REPO_ROOT / "reports" / "research" / "f3b-weather-wind-rain-protocol.json"
PARQUET = _REPO_ROOT / "backend" / "data" / "cache" / "weather_forecasts_f3b.parquet"
REPORT = _REPO_ROOT / "reports" / "research" / "portfolio-f3b-weather-incremental-value.json"

FEATURES = ("wind_speed_10m_kmh", "wind_gusts_10m_kmh", "heavy_rain")
HEAVY_RAIN_MM = 2.5  # the protocol's frozen value; never tuned


def derive(row: dict[str, Any]) -> dict[str, float | None]:
    precip = row.get("precipitation_mm")
    return {
        "wind_speed_10m_kmh": row.get("wind_speed_10m_kmh"),
        "wind_gusts_10m_kmh": row.get("wind_gusts_10m_kmh"),
        "heavy_rain": None if precip is None else float(precip >= HEAVY_RAIN_MM),
    }


def check_protocol(protocol: dict[str, Any]) -> None:
    """The code must be the protocol. A drift aborts rather than being reported."""
    if tuple(protocol["candidate_features"]) != FEATURES:
        raise SystemExit(f"feature drift: protocol {list(protocol['candidate_features'])}")
    if f">= {HEAVY_RAIN_MM}" not in protocol["candidate_features"]["heavy_rain"]:
        raise SystemExit("heavy_rain threshold drift from the protocol")
    folds = [(tuple(f["train_seasons"]), f["test_season"]) for f in protocol["split"]["folds"]]
    if folds != list(_FOLDS):
        raise SystemExit("fold drift from the protocol")


def decision(result: dict[str, Any]) -> str:
    """ADOPT only when every pooled fold clears the F3 bar; otherwise REJECT."""
    return "ADOPT" if result.get("label") == "PROMOTED" else "REJECT"


def main() -> int:
    raw = PROTOCOL.read_bytes()
    protocol = json.loads(raw)
    check_protocol(protocol)
    if not PARQUET.exists():
        print(f"missing {PARQUET}; run the acquisition command in the protocol first")
        return 1

    rows = build_rows(PARQUET, FEATURES, derive)
    if not rows:
        print("No joined rows — nothing to test.")
        return 1

    arms = {
        "level1_multinomial_logistic": run_arm(
            rows, "multinomial_logistic", fit_multinomial_logistic, FEATURES
        )
    }
    result = verdict(arms)
    heavy = int(sum(r["heavy_rain"] for r in rows))  # a 0/1 indicator; no float equality
    report: dict[str, Any] = {
        "experiment_id": "F3b",
        "protocol_path": "reports/research/f3b-weather-wind-rain-protocol.json",
        "protocol_sha256": hashlib.sha256(raw).hexdigest(),
        "seed": _SEED,
        "rows_joined": len(rows),
        "heavy_rain_rows": heavy,
        "folds": [{"train_seasons": list(t), "test_season": s} for t, s in _FOLDS],
        "candidate_features": list(FEATURES),
        "arms": arms,
        "verdict": result,
        "decision_under_protocol": decision(result),
        "not_a_promotion": (
            "Stage 3 evidence under a pre-registered protocol. ADOPT would make "
            "weather a candidate for the gated route (directive v9 §2.5 W3), not "
            "a served feature."
        ),
    }
    REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("rows_joined", "heavy_rain_rows", "decision_under_protocol")}, indent=2))
    print(json.dumps(result, indent=2)[:1500])
    print(f"\nReport written to {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
