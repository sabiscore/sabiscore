#!/usr/bin/env python3
"""G16 empirical uncertainty harness over the *actual* PredictionEngine path.

Unlike the stale research script, this adapter calls PredictionEngine._run_inference
for every row. That path includes the stacked meta-model, the fitted calibrator,
and the optional post-calibration overlay exactly as serving does. The harness
fails closed if the loaded artifact does not report calibration_applied=True.

The conformal wrapper is therefore a measurement adapter, not a second model.
Calibration/conformalization uses the earlier temporal half of the declared
holdout; coverage is measured only on the later half.

Memory controls: feature matrices are float32, inference is one row at a time,
MAPIE receives only the calibration/test slices, and explicit GC runs between
leagues.
"""
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
DEFAULT_HOLDOUT_SEASON = "2526"


def _git_sha() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True, stderr=subprocess.DEVNULL, timeout=3).strip()
    except Exception:
        return os.getenv("SABISCORE_GIT_SHA")


class ServedPredictionAdapter:
    """sklearn-compatible adapter around the exact production inference path."""

    _estimator_type = "classifier"
    classes_ = np.arange(3, dtype=np.int8)

    def __init__(self, engine: Any, bundle: Any, league: str, *, require_calibration: bool = True) -> None:
        self.engine = engine
        self.bundle = bundle
        self.league = league
        self.require_calibration = require_calibration
        self.observed: set[tuple[str, str]] = set()

    def predict_proba(self, X: Any) -> np.ndarray:
        arr = np.asarray(X, dtype=np.float32)
        if arr.ndim != 2:
            raise ValueError(f"expected 2D feature matrix, got {arr.shape}")
        output = np.empty((len(arr), 3), dtype=np.float32)
        for i, row in enumerate(arr):
            result = self.engine._run_inference(self.bundle, row, self.league)
            if result.model_version == "fallback":
                raise RuntimeError(f"served path fell back for {self.league} at row {i}")
            if self.require_calibration and not bool(result.calibration_applied):
                raise RuntimeError(
                    f"served path is not calibrated for {self.league}: method={result.calibration_method!r}"
                )
            method = str(result.calibration_method)
            self.observed.add((method, str(result.generation or "unknown")))
            output[i] = (result.home_win, result.draw, result.away_win)
        if not np.isfinite(output).all() or np.any(output < 0) or not np.allclose(output.sum(axis=1), 1.0, atol=1e-5):
            raise RuntimeError("served path returned an invalid probability simplex")
        return output

    def predict(self, X: Any) -> np.ndarray:
        return self.predict_proba(X).argmax(axis=1)


def _load_dataset(cache: Path) -> dict[str, dict[str, Any]]:
    from train_on_real_matches import build_dataset, load_matches
    matches = load_matches(cache)
    return build_dataset(matches)


def _load_engine() -> Any:
    from src.models.prediction import PredictionEngine
    return PredictionEngine()


async def _bundle(engine: Any, league: str) -> Any:
    return await engine.get_artifact_bundle(league)


def _evaluate_league(engine: Any, league: str, payload: dict[str, Any], season: str) -> dict[str, Any]:
    from mapie.classification import SplitConformalClassifier

    X = np.asarray(payload["X"], dtype=np.float32)
    y = np.asarray(payload["y"], dtype=np.int8)
    seasons = np.asarray([str(s) for s in payload["seasons"]])
    dates = np.asarray(payload["dates"], dtype="datetime64[ns]")
    mask = seasons == season
    if int(mask.sum()) < 50:
        raise RuntimeError(f"{league}: only {int(mask.sum())} rows in holdout season {season}")
    X, y, dates = X[mask], y[mask], dates[mask]
    order = np.argsort(dates)
    X, y, dates = X[order], y[order], dates[order]
    split = len(y) // 2
    if split < 20 or len(y) - split < 20:
        raise RuntimeError(f"{league}: temporal conformal split would be too small")

    bundle = asyncio.run(_bundle(engine, league))
    if bundle is None:
        raise RuntimeError(f"{league}: PredictionEngine could not load the active artifact")
    adapter = ServedPredictionAdapter(engine, bundle, league, require_calibration=True)
    # One probe establishes the calibration provenance before MAPIE is allowed
    # to consume the adapter. This prevents a raw fallback from being silently
    # conformalized and misreported as served-path evidence.
    _ = adapter.predict_proba(X[:1])

    X_cal, y_cal = X[:split], y[:split]
    X_test, y_test = X[split:], y[split:]
    conformal = SplitConformalClassifier(
        estimator=adapter,
        confidence_level=[0.80, 0.90],
        conformity_score="lac",
        prefit=True,
    )
    conformal.conformalize(X_cal, y_cal)
    _, sets = conformal.predict_set(X_test)

    levels: dict[str, Any] = {}
    for i, nominal in enumerate((0.80, 0.90)):
        pred_set = sets[:, :, i]
        covered = pred_set[np.arange(len(y_test)), y_test].astype(bool)
        sizes = pred_set.sum(axis=1)
        levels[f"{nominal:.2f}"] = {
            "nominal_coverage": nominal,
            "empirical_marginal_coverage": float(covered.mean()),
            "coverage_gap": float(covered.mean() - nominal),
            "n": int(len(y_test)),
            "mean_set_size": float(sizes.mean()),
            "set_size_distribution": {str(k): int((sizes == k).sum()) for k in range(4)},
        }
    return {
        "league": league,
        "holdout_season": season,
        "n_holdout": int(len(y)),
        "n_conformalize": int(len(y_cal)),
        "n_test": int(len(y_test)),
        "calibration_methods": sorted({m for m, _ in adapter.observed}),
        "generations": sorted({g for _, g in adapter.observed}),
        "test_date_range": [str(dates[split]), str(dates[-1])],
        "levels": levels,
    }


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="G16 served-path MAPIE empirical coverage")
    p.add_argument("--cache-dir", type=Path, default=BACKEND / "data" / "cache")
    p.add_argument("--holdout-season", default=DEFAULT_HOLDOUT_SEASON)
    p.add_argument("--output", type=Path, default=None)
    return p


def main() -> int:
    args = _parser().parse_args()
    generated = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        import mapie
        engine = _load_engine()
        dataset = _load_dataset(args.cache_dir)
        results: list[dict[str, Any]] = []
        errors: dict[str, str] = {}
        for league, payload in sorted(dataset.items()):
            try:
                results.append(_evaluate_league(engine, league, payload, args.holdout_season))
            except Exception as exc:
                errors[league] = str(exc)
            finally:
                gc.collect()
        if not results:
            raise RuntimeError(f"no league produced served-path evidence: {errors}")
        total = sum(r["n_test"] for r in results)
        pooled: dict[str, Any] = {}
        for nominal in (0.80, 0.90):
            key = f"{nominal:.2f}"
            covered = sum(r["levels"][key]["empirical_marginal_coverage"] * r["n_test"] for r in results)
            pooled[key] = {"nominal_coverage": nominal, "empirical_marginal_coverage": covered / total, "n": total}
        result = {
            "report_version": "v7.3-harness-1",
            "generated_at": generated,
            "repository": {"name": "sabiscore/sabiscore", "commit_sha": _git_sha(), "branch": None, "working_tree_clean": None},
            "deployment": {"backend_sha": None, "frontend_sha": None, "schema_version": None, "migration_revision": None, "compatibility_status": "NOT_EVALUATED"},
            "model": {"generation_id": sorted({g for r in results for g in r["generations"]}), "model_family": "PredictionEngine served path", "feature_contract": None, "artifact_hash": None, "schema_version": None, "status": "EVALUATION_ONLY", "calibration": {"required": True, "methods": sorted({m for r in results for m in r["calibration_methods"]})}},
            "data": {"dataset_snapshot": str(args.cache_dir), "temporal_window": args.holdout_season, "coverage": {"pooled": pooled, "leagues": results, "errors": errors}, "provenance_status": "SERVED_PATH", "leakage_status": "TEMPORAL_SPLIT", "forecast_authenticity": "SERVED_PREDICTION_ENGINE"},
            "policy": {"policy_version": None, "policy_sha256": None, "metric_convention": "LAC split conformal; marginal empirical coverage", "class_order": list(CLASS_NAMES)},
            "metrics": {"conformal": {"pooled": pooled, "mapie_version": getattr(mapie, "__version__", "unknown"), "conformity_score": "lac"}},
            "gates": {"G16": {"status": "PASS" if not errors and all(pooled[k]["empirical_marginal_coverage"] >= float(k) for k in pooled) else "FAIL", "criterion": "empirical marginal coverage >= nominal at 80% and 90%", "evidence_rows": total}},
            "operator_gates": {}, "risks": ["Marginal coverage does not identify which individual prediction will be wrong.", "Adaptive conformal scores are intentionally not used without a demonstrated difficulty signal."],
            "changes": [], "validation": {"served_path": "PredictionEngine._run_inference", "calibration_required": True, "memory_strategy": "float32 + row-wise inference + explicit GC", "executed": True},
            "decision": "PASS" if not errors and all(pooled[k]["empirical_marginal_coverage"] >= float(k) for k in pooled) else "FAIL",
        }
    except Exception as exc:
        result = {"report_version": "v7.3-harness-1", "generated_at": generated, "repository": {"name": "sabiscore/sabiscore", "commit_sha": _git_sha()}, "gates": {"G16": {"status": "BLOCKED", "errors": [str(exc)]}}, "decision": "BLOCKED"}
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2
    out = args.output or REPO_ROOT / "artifacts" / "certification" / f"g16_uncertainty_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["decision"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
