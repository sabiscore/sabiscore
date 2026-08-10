#!/usr/bin/env python3
"""Generate auditable train/serve availability without changing feature selection."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

_registry_spec = importlib.util.spec_from_file_location(
    "sabiscore_feature_registry", BACKEND_ROOT / "src" / "models" / "feature_registry.py"
)
if _registry_spec is None or _registry_spec.loader is None:
    raise RuntimeError("feature registry could not be loaded")
_registry = importlib.util.module_from_spec(_registry_spec)
_registry_spec.loader.exec_module(_registry)
APEX_FEATURES_68 = _registry.APEX_FEATURES_68


COMPETITIONS = {
    "EPL": "E0",
    "CHAMPIONSHIP": "E1",
    "LA_LIGA": "SP1",
    "SERIE_A": "I1",
    "BUNDESLIGA": "D1",
    "LIGUE_1": "F1",
    "EREDIVISIE": "N1",
}
MARKET_PREFIXES = ("market_", "ev_", "odds_", "log_odds_", "form_market_", "venue_market_", "h2h_market_")


def _finite(value: str | None) -> bool:
    try:
        return math.isfinite(float(value or "")) and float(value or "") > 1
    except ValueError:
        return False


def _coherent_market(row: dict[str, str]) -> bool:
    return any(
        all(_finite(row.get(column)) for column in columns)
        for columns in (("B365H", "B365D", "B365A"), ("PSH", "PSD", "PSA"))
    )


def _feature_family(feature: str) -> str:
    if feature.startswith(MARKET_PREFIXES) or feature in {"market_favorite", "draw_probability"}:
        return "market"
    if feature.startswith("h2h_"):
        return "head_to_head"
    if feature.startswith("home_venue_") or feature == "home_advantage_strength":
        return "home_venue"
    if feature.startswith("elo_"):
        return "elo"
    if any(token in feature for token in ("pressing", "carry", "shot_quality", "key_pass", "set_piece")):
        return "tactical"
    if feature in {"day_of_week", "is_weekend", "month", "season_phase"}:
        return "temporal"
    if feature.startswith("league_"):
        return "league"
    return "team_history"


def _coverage(cache_dir: Path, code: str) -> dict[str, Any]:
    files = sorted(cache_dir.glob(f"fd_{code}_*.csv"))
    rows: list[dict[str, str]] = []
    for path in files:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows.extend(dict(row) for row in csv.DictReader(handle))
    total = len(rows)
    teams: dict[str, int] = defaultdict(int)
    home_counts: dict[str, int] = defaultdict(int)
    pairs: dict[tuple[str, str], int] = defaultdict(int)
    counts = defaultdict(int)
    for row in rows:
        home = (row.get("HomeTeam") or "").strip()
        away = (row.get("AwayTeam") or "").strip()
        if row.get("Date"):
            counts["temporal"] += 1
        if _coherent_market(row):
            counts["market"] += 1
        if teams[home] >= 5 and teams[away] >= 5:
            counts["team_history"] += 1
        if home_counts[home] >= 5:
            counts["home_venue"] += 1
        pair = tuple(sorted((home, away)))
        if pairs[pair] >= 1:
            counts["head_to_head"] += 1
        if home and away:
            teams[home] += 1
            teams[away] += 1
            home_counts[home] += 1
            pairs[pair] += 1
    return {
        "files": [path.name for path in files],
        "rows": total,
        "coverage": {
            family: (counts[family] / total if total else 0.0)
            for family in ("market", "team_history", "home_venue", "head_to_head", "temporal")
        },
    }


def generate(cache_dir: Path) -> dict[str, Any]:
    matrix: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "feature_schema_changed": False,
        "settlement_gate": "BLOCKED_ZERO_SETTLED_PREDICTIONS",
        "competitions": {},
    }
    for competition, code in COMPETITIONS.items():
        evidence = _coverage(cache_dir, code)
        features = []
        for feature in APEX_FEATURES_68:
            family = _feature_family(feature)
            training_coverage = (
                1.0 if family == "league" and evidence["rows"] else
                0.0 if family in {"elo", "tactical"} else
                evidence["coverage"].get(family, 0.0)
            )
            if family == "market":
                serving_source = "fresh executable coherent market_snapshots"
                serving_coverage = 0.0
                gap_behavior = "critical market gap; no EV/value/stake"
            elif family in {"head_to_head", "home_venue", "team_history"}:
                serving_source = "canonical/legacy finished matches in PostgreSQL or cache"
                serving_coverage = evidence["coverage"].get(family, 0.0)
                gap_behavior = "explicit gap; confidence reduced or abstain"
            elif family in {"elo", "tactical"}:
                serving_source = "no reliable serving source"
                serving_coverage = 0.0
                gap_behavior = "explicit gap; never default to fabricated evidence"
            else:
                serving_source = "fixture and competition persistence"
                serving_coverage = training_coverage
                gap_behavior = "explicit missingness"
            features.append({
                "feature": feature,
                "family": family,
                "training_source": "football-data.co.uk committed chronological CSV" if evidence["rows"] else None,
                "serving_source": serving_source,
                "training_coverage": round(training_coverage, 6),
                "serving_projection_coverage": round(serving_coverage, 6),
                "missingness": round(1.0 - training_coverage, 6),
                "freshness": "historical" if evidence["rows"] else "unavailable",
                "variability": "observed" if training_coverage > 0 else "unavailable",
                "temporal_validity": "strictly-prior rolling history" if family in {"team_history", "head_to_head", "home_venue"} else "event-time keyed",
                "default_gap_behavior": gap_behavior,
            })
        matrix["competitions"][competition] = {**evidence, "features": features}
    return matrix


def _markdown(matrix: dict[str, Any]) -> str:
    lines = [
        "# APEX Feature Availability Matrix",
        "",
        f"Generated: `{matrix['generated_at']}`",
        "",
        "Settlement gate: `BLOCKED_ZERO_SETTLED_PREDICTIONS`. This evidence does not authorize feature or model changes.",
        "",
        "| Competition | Rows | Market | H2H | Home venue | Team history | Elo/tactical |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for competition, entry in matrix["competitions"].items():
        coverage = entry["coverage"]
        lines.append(
            f"| {competition} | {entry['rows']} | {coverage['market']:.1%} | "
            f"{coverage['head_to_head']:.1%} | {coverage['home_venue']:.1%} | "
            f"{coverage['team_history']:.1%} | 0.0% |"
        )
    lines.extend([
        "",
        "The JSON companion contains one record per active feature and competition, including sources, missingness, freshness, variability, temporal validity, and fail-closed gap behavior.",
        "Historical bookmaker rows are never projected as live executable market coverage.",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", type=Path, default=BACKEND_ROOT / "data" / "cache")
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--markdown-out", type=Path, required=True)
    args = parser.parse_args()
    matrix = generate(args.cache_dir)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(matrix, indent=2) + "\n", encoding="utf-8")
    args.markdown_out.write_text(_markdown(matrix), encoding="utf-8")


if __name__ == "__main__":
    main()
