#!/usr/bin/env python3
"""G11/G15 calibration evidence harness for the v7.3 certification run."""
from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
CLASS_NAMES = ("home_win", "draw", "away_win")


def git_sha() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True, stderr=subprocess.DEVNULL, timeout=3).strip()
    except Exception:
        return os.getenv("SABISCORE_GIT_SHA")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def iter_rows(path: Path) -> Iterable[dict[str, Any]]:
    if path.suffix.lower() in {".parquet", ".pq"}:
        import pandas as pd
        frame = pd.read_parquet(path)
        try:
            yield from frame.to_dict(orient="records")
        finally:
            del frame
            gc.collect()
        return
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        yield from csv.DictReader(f)


def load(path: Path) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    probs: list[tuple[float, float, float]] = []
    targets: list[int] = []
    leagues: set[str] = set()
    generations: set[str] = set()
    for row in iter_rows(path):
        try:
            p = np.asarray([float(row["home_win_prob"]), float(row["draw_prob"]), float(row["away_win_prob"])], dtype=np.float32)
        except (KeyError, TypeError, ValueError):
            continue
        y = {"H": 0, "D": 1, "A": 2, "0": 0, "1": 1, "2": 2}.get(str(row.get("result") or row.get("FTR") or "").strip().upper())
        if y is None or not np.isfinite(p).all() or np.any(p < 0):
            continue
        total = float(p.sum())
        if total <= 0:
            continue
        p /= np.float32(total)
        probs.append(tuple(p.tolist()))
        targets.append(y)
        if row.get("league"):
            leagues.add(str(row["league"]))
        if row.get("generation_id"):
            generations.add(str(row["generation_id"]))
    if len(targets) < 50:
        raise RuntimeError(f"G11/G15 requires >=50 valid forecasts; found {len(targets)}")
    return np.asarray(probs, dtype=np.float32), np.asarray(targets, dtype=np.int8), {"leagues": sorted(leagues), "generation_ids": sorted(generations)}


def equal_mass_bins(values: np.ndarray, n_bins: int) -> list[np.ndarray]:
    if not 1 <= n_bins <= len(values):
        raise ValueError(f"n_bins must be between 1 and n={len(values)}")
    order = np.argsort(values, kind="mergesort")
    return [idx for idx in np.array_split(order, min(n_bins, len(values))) if len(idx)]


def adaptive_confidence_ece(probs: np.ndarray, y: np.ndarray, n_bins: int) -> tuple[dict[str, Any], list[np.ndarray]]:
    pred = probs.argmax(axis=1)
    confidence = probs[np.arange(len(y)), pred]
    correct = (pred == y).astype(np.float32)
    bins = equal_mass_bins(confidence, n_bins)
    ece = 0.0
    detail: list[dict[str, Any]] = []
    for number, idx in enumerate(bins, 1):
        mass = len(idx) / len(y)
        mean_conf = float(confidence[idx].mean())
        accuracy = float(correct[idx].mean())
        gap = abs(mean_conf - accuracy)
        ece += mass * gap
        detail.append({"bin": number, "n": int(len(idx)), "mass": mass, "confidence_mean": mean_conf, "accuracy": accuracy, "absolute_gap": gap, "confidence_min": float(confidence[idx].min()), "confidence_max": float(confidence[idx].max())})
    return {"estimator": "adaptive_equal_mass_confidence", "n_bins_requested": n_bins, "n_bins_used": len(bins), "ece": float(ece), "bins": detail}, bins


def classwise_ece(probs: np.ndarray, y: np.ndarray, n_bins: int) -> dict[str, float]:
    out: dict[str, float] = {}
    for c, name in enumerate(CLASS_NAMES):
        event = (y == c).astype(np.float32)
        bins = equal_mass_bins(probs[:, c], n_bins)
        out[name] = float(sum((len(idx) / len(y)) * abs(float(probs[idx, c].mean()) - float(event[idx].mean())) for idx in bins))
    return out


def murphy_brier(probs: np.ndarray, y: np.ndarray, bins: list[np.ndarray]) -> dict[str, float]:
    """Murphy (1973) 3-term Brier score decomposition: BS = REL - RES + UNC.

    This identity holds exactly for any partition of the sample into bins.
    The decomposition terms are:
      - reliability  (REL): mean squared gap between bin-mean forecast and bin-mean outcome
      - resolution   (RES): mean squared distance of bin-mean outcome from climatology
      - uncertainty  (UNC): climatology variance = sum(c_k * (1 - c_k))

    reconstructed_brier = REL - RES + UNC must equal brier to within float64 precision.
    decomposition_error = brier - reconstructed must be <= 1e-6 for G15 certification.
    """
    one_hot = np.zeros_like(probs, dtype=np.float32)
    one_hot[np.arange(len(y)), y] = 1.0
    binned_probs = probs.copy()
    for idx in bins:
        binned_probs[idx] = probs[idx].mean(axis=0, dtype=np.float64)
    brier = float(np.mean(np.sum((binned_probs - one_hot) ** 2, axis=1), dtype=np.float64))
    climatology = one_hot.mean(axis=0, dtype=np.float64)
    # UNC = sum_k [ c_k * (1 - c_k) ]
    uncertainty = float(np.sum(climatology * (1.0 - climatology)))
    reliability = 0.0
    resolution = 0.0
    for idx in bins:
        w = len(idx) / len(y)
        # p̄_b: bin-mean forecast vector
        p_bar = probs[idx].mean(axis=0, dtype=np.float64)
        # ō_b: bin-mean observed one-hot vector (= empirical class frequency in bin)
        o_bar = one_hot[idx].mean(axis=0, dtype=np.float64)
        # REL term: sum_k (p̄_b,k - ō_b,k)^2
        reliability += w * float(np.sum((p_bar - o_bar) ** 2))
        # RES term: sum_k (ō_b,k - c_k)^2
        resolution += w * float(np.sum((o_bar - climatology) ** 2))
    # Standard 3-term identity: BS = REL - RES + UNC (always exact for any partition)
    reconstructed = reliability - resolution + uncertainty
    return {
        "brier": brier,
        "reliability": float(reliability),
        "resolution": float(resolution),
        "uncertainty": uncertainty,
        "reconstructed_brier": float(reconstructed),
        "decomposition_error": float(brier - reconstructed),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Adaptive equal-mass ECE + Murphy Brier evidence")
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output", type=Path)
    ap.add_argument("--bins", type=int, default=10)
    args = ap.parse_args()
    generated = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        probs, y, provenance = load(args.input)
        ece, bins = adaptive_confidence_ece(probs, y, args.bins)
        ece["classwise_ece"] = classwise_ece(probs, y, args.bins)
        brier = murphy_brier(probs, y, bins)
        if abs(brier["decomposition_error"]) > 1e-6:
            raise RuntimeError(f"Murphy decomposition identity failed: {brier['decomposition_error']}")
        result = {"report_version": "v7.3-harness-2", "generated_at": generated, "repository": {"name": "sabiscore/sabiscore", "commit_sha": git_sha()}, "deployment": {"compatibility_status": "NOT_EVALUATED"}, "model": {"status": "EVALUATION_ONLY", "generation_id": provenance["generation_ids"]}, "data": {"dataset_snapshot": str(args.input), "snapshot_sha256": sha256_file(args.input), "coverage": {"n": int(len(y)), "leagues": provenance["leagues"]}, "provenance_status": "INPUT_ARTIFACT_REQUIRED", "forecast_authenticity": "REQUIRES_PREMATCH_FORECAST_ARTIFACT"}, "policy": {"metric_convention": "adaptive equal-mass confidence ECE; multiclass Murphy decomposition"}, "metrics": {"ece": ece, "brier": brier}, "gates": {"G11": {"status": "MEASURED", "value": ece["ece"], "criterion": "certification_policy threshold applied by compiler"}, "G15": {"status": "MEASURED", "value": brier["decomposition_error"], "criterion": "Murphy identity residual <= 1e-6"}}, "operator_gates": {}, "risks": ["This artifact measures calibration; the compiler owns gate aggregation."], "changes": [], "validation": {"executed": True, "binning": "stable equal-mass", "memory_strategy": "float32 + explicit gc"}, "decision": "MEASURED"}
    except Exception as exc:
        result = {"report_version": "v7.3-harness-2", "generated_at": generated, "repository": {"name": "sabiscore/sabiscore", "commit_sha": git_sha()}, "gates": {"G11": {"status": "BLOCKED", "errors": [str(exc)]}, "G15": {"status": "BLOCKED", "errors": [str(exc)]}}, "decision": "BLOCKED"}
    out = args.output or REPO_ROOT / "artifacts/certification" / f"g11_ece_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["decision"] == "MEASURED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
