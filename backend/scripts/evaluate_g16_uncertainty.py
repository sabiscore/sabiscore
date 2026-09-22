#!/usr/bin/env python3
"""G16 served-path MAPIE evidence with explicit leakage controls."""

from __future__ import annotations

import argparse
import asyncio
import gc
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

SCRIPTS = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS.parents[1]
BACKEND = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(SCRIPTS))
CLASS_NAMES = ("home_win", "draw", "away_win")


def git_sha() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=3,
        ).strip()
    except Exception:
        return os.getenv("SABISCORE_GIT_SHA")


class ServedPredictionAdapter:
    """sklearn-compatible facade over PredictionEngine._run_inference."""

    _estimator_type = "classifier"
    classes_ = np.arange(3, dtype=np.int8)

    def __init__(self, engine: Any, bundle: Any, league: str) -> None:
        self.engine, self.bundle, self.league = engine, bundle, league
        self.observed: set[tuple[str, str, str | None, str | None]] = set()

    def predict_proba(self, X: Any) -> np.ndarray:
        arr = np.asarray(X, dtype=np.float32)
        if arr.ndim != 2:
            raise ValueError(f"expected 2D matrix, got {arr.shape}")
        # float64, not float32: the served path sums a base-ensemble average
        # through a per-class sigmoid calibrator then renormalises -- several
        # float32 operations deep -- so each row's raw sum carries up to 1e-4
        # of accumulated rounding error (measured directly against 301 real
        # BUNDESLIGA holdout rows; docs/DEBT.md item 127). MAPIE's own
        # SplitConformalClassifier validates its input probabilities sum to 1
        # at rtol=1e-05, atol=0 -- tighter than float32 precision supports and
        # not a tolerance this adapter can loosen from the outside, since it
        # lives inside the mapie package. Fix the cause instead of the
        # threshold: renormalise every row to sum to exactly 1 in float64,
        # which is well within MAPIE's tolerance (float64 machine epsilon is
        # ~1e-16). This does not touch the served prediction path itself --
        # only how this evaluation adapter packages its output for MAPIE.
        output = np.empty((len(arr), 3), dtype=np.float64)
        for i, row in enumerate(arr):
            result = self.engine._run_inference(self.bundle, row, self.league)
            if result.model_version == "fallback":
                raise RuntimeError(
                    f"{self.league}: served path returned fallback at row {i}"
                )
            if not bool(result.calibration_applied):
                raise RuntimeError(
                    f"{self.league}: calibration provenance failed; method={result.calibration_method!r}"
                )
            output[i] = (result.home_win, result.draw, result.away_win)
            self.observed.add(
                (
                    str(result.calibration_method),
                    str(result.generation or "unknown"),
                    result.feature_schema_version,
                    result.artifact_sha256,
                )
            )
        if not np.isfinite(output).all() or np.any(output < 0):
            raise RuntimeError(
                f"{self.league}: served path returned an invalid probability simplex"
            )
        row_sums = output.sum(axis=1, keepdims=True)
        if np.any(row_sums <= 0) or not np.allclose(row_sums, 1.0, atol=0.05):
            raise RuntimeError(
                f"{self.league}: served path returned an invalid probability simplex"
            )
        return output / row_sums

    def predict(self, X: Any) -> np.ndarray:
        return self.predict_proba(X).argmax(axis=1)


def load_dataset(cache: Path) -> dict[str, dict[str, Any]]:
    from train_on_real_matches import build_dataset, load_matches

    return build_dataset(load_matches(cache))


async def load_bundle(engine: Any, league: str) -> Any:
    return await engine.get_artifact_bundle(league)


def evaluate_league(
    engine: Any,
    league: str,
    payload: dict[str, Any],
    season: str,
    training_cutoff: np.datetime64,
) -> dict[str, Any]:
    from mapie.classification import SplitConformalClassifier

    X = np.asarray(payload["X"], dtype=np.float32)
    y = np.asarray(payload["y"], dtype=np.int8)
    seasons = np.asarray([str(s) for s in payload["seasons"]])
    dates = np.asarray(payload["dates"], dtype="datetime64[ns]")
    mask = seasons == season
    if int(mask.sum()) < 50:
        raise RuntimeError(f"{league}: holdout has only {int(mask.sum())} rows")
    X, y, dates = X[mask], y[mask], dates[mask]
    order = np.argsort(dates, kind="mergesort")
    X, y, dates = X[order], y[order], dates[order]
    if dates[0] <= training_cutoff:
        raise RuntimeError(
            f"{league}: holdout begins {dates[0]} but training cutoff is {training_cutoff}; leakage boundary is invalid"
        )
    split = len(y) // 2
    if split < 20 or len(y) - split < 20:
        raise RuntimeError(f"{league}: temporal conformal/test split is too small")

    bundle = asyncio.run(load_bundle(engine, league))
    if bundle is None:
        raise RuntimeError(f"{league}: active artifact bundle unavailable")
    adapter = ServedPredictionAdapter(engine, bundle, league)
    adapter.predict_proba(X[:1])

    X_cal, y_cal = X[:split], y[:split]
    X_test, y_test = X[split:], y[split:]
    conformal = SplitConformalClassifier(
        estimator=adapter,
        confidence_level=[0.80, 0.90],
        conformity_score="lac",
        prefit=True,
    )
    conformal.conformalize(X_cal, y_cal)
    _, prediction_sets = conformal.predict_set(X_test)

    levels: dict[str, Any] = {}
    for index, nominal in enumerate((0.80, 0.90)):
        sets = prediction_sets[:, :, index]
        covered = sets[np.arange(len(y_test)), y_test]
        sizes = sets.sum(axis=1)
        levels[f"{nominal:.2f}"] = {
            "nominal_coverage": nominal,
            "empirical_marginal_coverage": float(covered.mean()),
            "coverage_gap": float(covered.mean() - nominal),
            "n": int(len(y_test)),
            "mean_set_size": float(sizes.mean()),
            "set_size_distribution": {
                str(k): int((sizes == k).sum()) for k in range(4)
            },
        }
    provenance = sorted(adapter.observed)
    return {
        "league": league,
        "holdout_season": season,
        "n_holdout": int(len(y)),
        "n_conformalize": int(len(y_cal)),
        "n_test": int(len(y_test)),
        "calibration_methods": sorted({x[0] for x in provenance}),
        "generations": sorted({x[1] for x in provenance}),
        "feature_schema_versions": sorted({x[2] for x in provenance if x[2]}),
        "artifact_hashes": sorted({x[3] for x in provenance if x[3]}),
        "test_date_range": [str(dates[split]), str(dates[-1])],
        "levels": levels,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="G16 served-path MAPIE empirical coverage")
    ap.add_argument("--cache-dir", type=Path, default=BACKEND / "data" / "cache")
    ap.add_argument("--holdout-season", default="2526")
    ap.add_argument(
        "--training-cutoff",
        required=True,
        help="Last date allowed in model training, YYYY-MM-DD",
    )
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    generated = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        cutoff = np.datetime64(args.training_cutoff, "ns")
        import mapie

        engine = __import__(
            "src.models.prediction", fromlist=["PredictionEngine"]
        ).PredictionEngine()
        dataset = load_dataset(args.cache_dir)
        results: list[dict[str, Any]] = []
        errors: dict[str, str] = {}
        for league, payload in sorted(dataset.items()):
            try:
                results.append(
                    evaluate_league(
                        engine, league, payload, args.holdout_season, cutoff
                    )
                )
            except Exception as exc:
                errors[league] = str(exc)
            finally:
                gc.collect()
        if errors or not results:
            raise RuntimeError(f"G16 served-path evaluation incomplete: {errors}")
        total = sum(r["n_test"] for r in results)
        pooled: dict[str, Any] = {}
        for nominal in (0.80, 0.90):
            key = f"{nominal:.2f}"
            covered = sum(
                r["levels"][key]["empirical_marginal_coverage"] * r["n_test"]
                for r in results
            )
            pooled[key] = {
                "nominal_coverage": nominal,
                "empirical_marginal_coverage": covered / total,
                "n": total,
            }
        passed = all(
            pooled[k]["empirical_marginal_coverage"] >= float(k) for k in pooled
        )
        result = {
            "report_version": "v7.3-harness-2",
            "generated_at": generated,
            "repository": {"name": "sabiscore/sabiscore", "commit_sha": git_sha()},
            "deployment": {"compatibility_status": "NOT_EVALUATED"},
            "model": {
                "generation_id": sorted({g for r in results for g in r["generations"]}),
                "model_family": "PredictionEngine served path",
                "feature_contract": sorted(
                    {s for r in results for s in r["feature_schema_versions"]}
                ),
                "artifact_hash": sorted(
                    {h for r in results for h in r["artifact_hashes"]}
                ),
                "status": "EVALUATION_ONLY",
                "calibration": {
                    "required": True,
                    "methods": sorted(
                        {m for r in results for m in r["calibration_methods"]}
                    ),
                },
            },
            "data": {
                "dataset_snapshot": str(args.cache_dir),
                "temporal_window": args.holdout_season,
                "training_cutoff": args.training_cutoff,
                "coverage": {"pooled": pooled, "leagues": results, "errors": errors},
                "provenance_status": "SERVED_PATH",
                "leakage_status": "EXPLICIT_TRAINING_CUTOFF_AND_TEMPORAL_SPLIT",
                "forecast_authenticity": "SERVED_PREDICTION_ENGINE",
            },
            "policy": {
                "metric_convention": "LAC split conformal; marginal empirical coverage",
                "class_order": list(CLASS_NAMES),
            },
            "metrics": {
                "conformal": {
                    "pooled": pooled,
                    "mapie_version": getattr(mapie, "__version__", "unknown"),
                    "conformity_score": "lac",
                }
            },
            "gates": {
                "G16": {
                    "status": "PASS" if passed else "FAIL",
                    "criterion": "served-path empirical marginal coverage >= nominal at 80% and 90% with explicit pre-holdout training cutoff",
                    "evidence_rows": total,
                }
            },
            "operator_gates": {},
            "risks": [
                "Marginal coverage is population-level empirical evidence, not an individual-outcome probability.",
                "The harness deliberately does not substitute MC Dropout or probability-derived variance for empirical uncertainty.",
            ],
            "changes": [],
            "validation": {
                "served_path": "PredictionEngine._run_inference",
                "calibration_required": True,
                "training_cutoff": args.training_cutoff,
                "memory_strategy": "float32 + row-wise inference + explicit GC",
                "executed": True,
            },
            "decision": "PASS" if passed else "FAIL",
        }
    except Exception as exc:
        result = {
            "report_version": "v7.3-harness-2",
            "generated_at": generated,
            "repository": {"name": "sabiscore/sabiscore", "commit_sha": git_sha()},
            "gates": {"G16": {"status": "BLOCKED", "errors": [str(exc)]}},
            "decision": "BLOCKED",
        }
    out = (
        args.output
        or REPO_ROOT
        / "artifacts/certification"
        / f"g16_uncertainty_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["decision"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
