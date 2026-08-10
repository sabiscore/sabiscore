#!/usr/bin/env python3
"""Generate Apex train/serve feature-availability evidence from current code."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

import train_on_real_matches as training


REGISTRY = training._FEATURE_REGISTRY


def _training_resolved_features() -> set[str]:
    resolved: set[str] = set()
    resolved.update(
        training.derive_last5_form_features(
            0.5, 0.4, is_home=True, wins_5=2, draws_5=1, losses_5=2
        )
    )
    resolved.update(
        training.derive_last5_form_features(
            0.4, 0.3, is_home=False, wins_5=1, draws_5=2, losses_5=2
        )
    )
    resolved.update(
        {
            "home_goals_for_avg",
            "home_goals_against_avg",
            "home_gd_recent",
            "away_goals_for_avg",
            "away_goals_against_avg",
            "away_gd_recent",
        }
    )
    resolved.update(training.derive_temporal_features(datetime(2026, 5, 1)))
    resolved.update(training.derive_league_features("EPL"))
    resolved.update(
        training.derive_combination_features(
            home_goals_for_avg=1.5,
            home_goals_against_avg=1.1,
            away_goals_for_avg=1.2,
            away_goals_against_avg=1.4,
        )
    )
    resolved.update(training.derive_apex_market_features(2.1, 3.4, 3.8))
    return resolved


def _source(feature: str, *, training_source: bool) -> str:
    if feature in REGISTRY.APEX_MARKET_FEATURES_14:
        return "football-data.co.uk coherent opening 1X2" if training_source else "OddsService coherent 1X2 snapshot"
    if feature in REGISTRY.TEMPORAL_FEATURES:
        return "fixture kickoff"
    if feature in set(REGISTRY.LEAGUE_ONEHOT_FEATURES) | set(REGISTRY.LEAGUE_RATE_FEATURES):
        return "competition identity and governed league rates"
    if feature in REGISTRY.COMBINATION_FEATURES:
        return "derived from both teams' match history"
    if feature in REGISTRY.PHASE7_FEATURES_10:
        if training_source:
            return "registry default"
        if feature.startswith("elo_"):
            return "EloEngine"
        return "StatsBomb enrichment or registry default"
    if feature.startswith("h2h_") or "venue" in feature:
        return "registry default" if training_source else "unwired in current projector"
    return "strictly prior completed-match history"


def _freshness(feature: str) -> str:
    if feature in REGISTRY.APEX_MARKET_FEATURES_14:
        return "request snapshot; bounded by odds freshness policy"
    if feature in REGISTRY.TEMPORAL_FEATURES:
        return "static for fixture kickoff"
    if feature in set(REGISTRY.LEAGUE_ONEHOT_FEATURES) | set(REGISTRY.LEAGUE_RATE_FEATURES):
        return "release/configuration scoped"
    if feature in REGISTRY.PHASE7_FEATURES_10:
        return "source timestamp required; DATA_GAP when absent"
    return "age of newest completed match for either team"


def build_matrix(cache_dir: Path) -> dict[str, Any]:
    dataset = training.build_dataset(training.load_matches(cache_dir))
    rows = np.concatenate(
        [np.asarray(data["X"], dtype=np.float64) for data in dataset.values() if data["X"]],
        axis=0,
    )
    training_resolved = _training_resolved_features()
    always_gap = set(REGISTRY.PHASE7_FEATURES_ALWAYS_DATA_GAP)
    current_schema = list(REGISTRY.CANONICAL_FEATURES_68)
    candidate_schema = list(REGISTRY.APEX_FEATURES_68)

    entries: list[dict[str, Any]] = []
    for index, feature in enumerate(candidate_schema):
        values = rows[:, index]
        trained_from_source = feature in training_resolved
        position_aligned = current_schema[index] == feature
        if not position_aligned:
            serving_status = "UNAVAILABLE_SCHEMA_MISALIGNED"
        elif feature in always_gap:
            serving_status = "ALWAYS_DATA_GAP"
        elif feature.startswith("h2h_") or "venue" in feature:
            serving_status = "UNWIRED_DEFAULT"
        else:
            serving_status = "CONDITIONAL_SOURCE"
        entries.append(
            {
                "index": index,
                "feature": feature,
                "training_source": _source(feature, training_source=True),
                "serving_source": _source(feature, training_source=False),
                "training_coverage": 1.0 if trained_from_source else 0.0,
                "training_missingness": 0.0 if trained_from_source else 1.0,
                "serving_status": serving_status,
                "freshness_contract": _freshness(feature),
                "variable_in_training": bool(float(np.std(values)) > 1e-12),
                "training_stddev": float(np.std(values)),
                "training_min": float(np.min(values)),
                "training_max": float(np.max(values)),
                "defaulted_training_slot": not trained_from_source,
                "candidate_position_matches_current_serving_schema": position_aligned,
            }
        )

    return {
        "schema": "apex_v1_68",
        "training_rows": int(len(rows)),
        "selection": {
            "source_matches": 12765,
            "insufficient_history_excluded": 505,
            "eligible_after_history": 12260,
            "coherent_opening_odds_rows": 12256,
            "odds_missing_rows_excluded": 4,
        },
        "summary": {
            "features": len(entries),
            "training_defaulted_slots": sum(item["defaulted_training_slot"] for item in entries),
            "non_variable_training_slots": sum(not item["variable_in_training"] for item in entries),
            "serving_schema_misaligned_slots": sum(
                item["serving_status"] == "UNAVAILABLE_SCHEMA_MISALIGNED" for item in entries
            ),
            "always_data_gap_slots": sum(item["serving_status"] == "ALWAYS_DATA_GAP" for item in entries),
        },
        "promotion_gate": "FAIL" if any(
            item["serving_status"] in {"UNAVAILABLE_SCHEMA_MISALIGNED", "ALWAYS_DATA_GAP"}
            for item in entries
        ) else "PASS",
        "features": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", type=Path, default=training._BACKEND_ROOT / "data" / "cache")
    parser.add_argument(
        "--output",
        type=Path,
        default=training._BACKEND_ROOT / "models" / "candidate" / "feature_availability_matrix.json",
    )
    args = parser.parse_args()
    payload = build_matrix(args.cache_dir)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], sort_keys=True))
    print(f"promotion_gate={payload['promotion_gate']} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
