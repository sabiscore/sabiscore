#!/usr/bin/env python3
"""G11/G15 calibration harness using adaptive equal-mass bins.

The repository's legacy estimator uses fixed-width probability bins. This script
implements the v7.3 estimator directly: rows are sorted by predicted confidence
and partitioned into approximately equal-count bins. Ties at bin boundaries are
kept deterministic; empty bins are never emitted.

For multiclass forecasts the primary ECE is confidence ECE (max predicted
probability versus correctness), while classwise ECE is also emitted. The same
adaptive partition is used for a Murphy-style multiclass Brier decomposition:
Brier = reliability - resolution + uncertainty.

Input CSV/Parquet columns:
    home_win_prob, draw_prob, away_win_prob, result
where result is H/D/A or 0/1/2.
"""
from __future__ import annotations

import argparse
import csv
import gc
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
CLASS_NAMES = ("home_win", "draw", "away_win")


def _git_sha() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True, stderr=subprocess.DEVNULL, timeout=3).strip()
    except Exception:
        return os.getenv("SABISCORE_GIT_SHA")


def _rows(path: Path) -> Iterable[dict[str, Any]]:
    if path.suffix.lower() in {".parquet", ".pq"}:
        import pandas as pd
        frame = pd.read_parquet(path)
        try:
            yield from frame.to_dict(orient="records")
        finally:
            del frame
            gc.collect()
        return
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle)


def load(path: Path) -> tuple[np.ndarray, np.ndarray]:
    probs: list[tuple[float, float, float]] = []
    y: list[int] = []
    for raw in _rows(path):
        try:
            p = np.asarray([float(raw["home_win_prob"]), float(raw["draw_prob"]), float(raw["away_win_prob"])], dtype=np.float32)
        except (KeyError, TypeError, ValueError):
            continue
        if not np.isfinite(p).all() or np.any(p < 0) or float(p.sum()) <= 0:
            continue
        p /= np.float32(p.sum())
        result = str(raw.get("result") or raw.get("FTR") or "").strip().upper()
        target = {"H": 0, "D": 1, "A": 2, "0": 0, "1": 1, "2": 2}.get(result)
        if target is None:
            continue
        probs.append(tuple(p.tolist()))
        y.append(target)
    if len(y) < 50:
        raise RuntimeError(f"G11/G15 requires >=50 valid forecast rows; found {len(y)}")
    return np.asarray(probs, dtype=np.float32), np.asarray(y, dtype=np.int8)


def equal_mass_bins(confidence: np.ndarray, n_bins: int) -> list[np.ndarray]:
    n = len(confidence)
    if n_bins < 1 or n_bins > n:
        raise ValueError("n_bins must be in [1,n]")
    order = np.argsort(confidence, kind="mergesort")
    # np.array_split guarantees balanced counts (difference <= 1). This is
    # genuinely equal-mass and avoids quantile interpolation producing empty or
    # highly imbalanced bins when confidence values have ties.
    return [part for part in np.array_split(order, min(n_bins, n)) if len(part)]


def adaptive_ece(probs: np.ndarray, y: np.ndarray, n_bins: int) -> dict[str, Any]:
    pred = probs.argmax(axis=1)
    confidence = probs[np.arange(len(y)), pred]
    correct = (pred == y).astype(np.float32)
    bins = equal_mass_bins(confidence, n_bins)
    rows: list[dict[str, Any]] = []
    ece = 0.0
    classwise = np.zeros(3, dtype=np.float64)
    for i, idx in enumerate(bins, 1):
        conf = float(confidence[idx].mean())
        acc = float(correct[idx].mean())
        weight = len(idx) / len(y)
        gap = abs(acc - conf)
        ece += weight * gap
        rows.append({"bin": i, "n": int(len(idx)), "mass": weight, "confidence_mean": conf, "accuracy": acc, "absolute_gap": gap, "min_confidence": float(confidence[idx].min()), "max_confidence": float(confidence[idx].max())})
        for c in range(3):
            class_idx = idx[probs[idx, c].argsort(kind="mergesort")] if len(idx) else idx
            # Classwise calibration is evaluated on the same observations,
            # against the binary event y==c; no second binning is introduced.
            class_gap = abs(float(probs[idx, c].mean()) - float((y[idx] == c).mean()))
            classwise[c] += weight * class_gap
    return {"estimator": "adaptive_equal_mass", "n_bins_requested": n_bins, "n_bins_used": len(bins), "ece": float(ece), "classwise_ece": {CLASS_NAMES[c]: float(classwise[c]) for c in range(3)}, "bins": rows}


def brier_murphy(probs: np.ndarray, y: np.ndarray, bins: list[np.ndarray]) -> dict[str, float]:
    one_hot = np.zeros_like(probs, dtype=np.float32)
    one_hot[np.arange(len(y)), y] = 1.0
    brier = float(np.mean(np.sum((probs - one_hot) ** 2, axis=1), dtype=np.float64))
    climatology = one_hot.mean(axis=0, dtype=np.float64)
    uncertainty = float(np.sum(climatology * (1.0 - climatology)))
    reliability = 0.0
    resolution = 0.0
    for idx in bins:
        w = len(idx) / len(y)
        p_bar = probs[idx].mean(axis=0, dtype=np.float64)
        y_bar = one_hot[idx].mean(axis=0, dtype=np.float64)
        reliability += w * float(np.sum((p_bar - y_bar) ** 2))
        resolution += w * float(np.sum((y_bar - climatology) ** 2))
    reconstructed = reliability - resolution + uncertainty
    return {"brier": brier, "reliability": float(reliability), "resolution": float(resolution), "uncertainty": uncertainty, "reconstructed_brier": float(reconstructed), "decomposition_error": float(brier - reconstructed)}


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Adaptive equal-mass ECE + multiclass Brier decomposition")
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, default=None)
    p.add_argument("--bins", type=int, default=10)
    return p


def main() -> int:
    args = _parser().parse_args()
    generated = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        probs, y = load(args.input)
        ece = adaptive_ece(probs, y, args.bins)
        confidence = probs.max(axis=1)
        bins = equal_mass_bins(confidence, args.bins)
        brier = brier_murphy(probs, y, bins)
        result = {
            "report_version": "v7.3-harness-1",
            "generated_at": generated,
            "repository": {"name": "sabiscore/sabiscore", "commit_sha": _git_sha(), "branch": None, "working_tree_clean": None},
            "deployment": {"backend_sha": None, "frontend_sha": None, "schema_version": None, "migration_revision": None, "compatibility_status": "NOT_EVALUATED"},
            "model": {"generation_id": None, "model_family": "forecast artifact supplied by input", "feature_contract": None, "artifact_hash": None, "schema_version": None, "status": "EVALUATION_ONLY", "calibration": None},
            "data": {"dataset_snapshot": str(args.input), "temporal_window": None, "coverage": {"n": int(len(y))}, "provenance_status": "INPUT_ARTIFACT_REQUIRED", "leakage_status": "NOT_ESTABLISHED_BY_HARNESS", "forecast_authenticity": "REQUIRES_PREMATCH_FORECAST_ARTIFACT"},
            "policy": {"policy_version": None, "policy_sha256": None, "metric_convention": "adaptive equal-mass confidence ECE; multiclass Murphy Brier decomposition", "class_order": list(CLASS_NAMES)},
            "metrics": {"ece": ece, "brier": brier},
            "gates": {"G11": {"status": "MEASURED", "criterion": "adaptive equal-mass ECE <= policy threshold", "value": ece["ece"]}, "G15": {"status": "MEASURED", "criterion": "Murphy Brier decomposition identity", "value": brier["decomposition_error"]}},
            "operator_gates": {}, "risks": ["This harness reports measured metrics; the final PASS/FAIL threshold is owned by certification_policy.py."],
            "changes": [], "validation": {"binning": "stable equal-count partition after confidence sort", "executed": True},
            "decision": "MEASURED",
        }
    except Exception as exc:
        result = {"report_version": "v7.3-harness-1", "generated_at": generated, "repository": {"name": "sabiscore/sabiscore", "commit_sha": _git_sha()}, "gates": {"G11": {"status": "BLOCKED", "errors": [str(exc)]}, "G15": {"status": "BLOCKED", "errors": [str(exc)]}}, "decision": "BLOCKED"}
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2
    out = args.output or REPO_ROOT / "artifacts" / "certification" / f"g11_ece_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
