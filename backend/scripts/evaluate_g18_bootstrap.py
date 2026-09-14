#!/usr/bin/env python3
"""G18 candidate-vs-market RPS evidence harness.

CPU/memory bounded for an 8GB Windows research workstation. The script never
changes certification policy and never labels missing evidence as PASS.

Input contract (CSV or Parquet):
    league, season, date, home_team, away_team, home_win_prob, draw_prob,
    away_win_prob, home_odds, draw_odds, away_odds

The default odds mapping follows the repository's established football-data
cache convention: B365H/B365D/B365A first, then Pinnacle PSH/PSD/PSA. A
complete 1X2 snapshot is required; the harness never mixes bookmakers.
Candidate probabilities must be generated before match outcome and closing
market information and must therefore be supplied as a forecast artifact.

Usage:
    python backend/scripts/evaluate_g18_bootstrap.py --input artifacts/g18.csv
"""
from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

OUTCOMES = ("home_win", "draw", "away_win")
ODDS_TIERS = (
    ("B365H", "B365D", "B365A", "bet365"),
    ("bet365_home", "bet365_draw", "bet365_away", "bet365"),
    ("PSH", "PSD", "PSA", "pinnacle"),
    ("pinnacle_home", "pinnacle_draw", "pinnacle_away", "pinnacle"),
)
DIVISION_TO_LEAGUE = {
    "E0": "EPL", "SP1": "LA_LIGA", "D1": "BUNDESLIGA",
    "I1": "SERIE_A", "F1": "LIGUE_1", "N1": "EREDIVISIE",
}


def _git_sha() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True,
            stderr=subprocess.DEVNULL, timeout=3,
        ).strip()
    except Exception:
        return os.getenv("SABISCORE_GIT_SHA")


def _parse_date(value: str) -> datetime | None:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value.strip()[:19], fmt).replace(tzinfo=UTC)
        except ValueError:
            pass
    return None


def _rps(y: np.ndarray, p: np.ndarray) -> np.ndarray:
    """Per-row 3-class Ranked Probability Score, lower is better."""
    p = np.asarray(p, dtype=np.float32)
    y = np.asarray(y, dtype=np.int8)
    if p.ndim != 2 or p.shape[1] != 3:
        raise ValueError(f"probability matrix must be (n,3), got {p.shape}")
    cdf = np.cumsum(p, axis=1, dtype=np.float32)
    truth = np.zeros_like(p, dtype=np.float32)
    truth[np.arange(len(y)), y] = 1.0
    tcdf = np.cumsum(truth, axis=1, dtype=np.float32)
    return np.mean((cdf[:, :2] - tcdf[:, :2]) ** 2, axis=1, dtype=np.float32)


def _de_vig(odds: tuple[float, float, float]) -> np.ndarray:
    inv = np.asarray([1.0 / x for x in odds], dtype=np.float32)
    total = float(inv.sum())
    if not math.isfinite(total) or total <= 0.0:
        raise ValueError("invalid implied-probability total")
    return (inv / total).astype(np.float32, copy=False)


def _complete_odds(row: dict[str, str]) -> tuple[np.ndarray, str] | None:
    for h, d, a, book in ODDS_TIERS:
        try:
            values = (float(row.get(h, "")), float(row.get(d, "")), float(row.get(a, "")))
        except (TypeError, ValueError):
            continue
        if all(math.isfinite(v) and v > 1.0 for v in values):
            return _de_vig(values), book
    generic = (row.get("home_odds"), row.get("draw_odds"), row.get("away_odds"))
    try:
        values = tuple(float(x) for x in generic)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if all(math.isfinite(v) and v > 1.0 for v in values):
        return _de_vig(values), str(row.get("bookmaker") or "unknown")
    return None


def _iter_rows(path: Path) -> Iterable[dict[str, Any]]:
    if path.suffix.lower() in {".parquet", ".pq"}:
        try:
            import pandas as pd
        except ImportError as exc:
            raise SystemExit("Parquet input requires pandas/pyarrow in the research environment") from exc
        frame = pd.read_parquet(path)
        yield from frame.to_dict(orient="records")
        del frame
        gc.collect()
        return
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle)


def load_evidence(path: Path, *, holdout_start: str, holdout_end: str) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    start = _parse_date(holdout_start)
    end = _parse_date(holdout_end)
    if start is None or end is None:
        raise ValueError("holdout bounds must be ISO dates")
    candidate: list[tuple[float, float, float]] = []
    market: list[tuple[float, float, float]] = []
    truth: list[int] = []
    dates: list[datetime] = []
    books: dict[str, int] = {}
    skipped = 0
    for raw in _iter_rows(path):
        row = {str(k): raw[k] for k in raw if raw[k] is not None}
        date = _parse_date(str(row.get("date") or row.get("Date") or ""))
        if date is None or date < start or date >= end:
            continue
        season = str(row.get("season") or "")
        if season and season not in {"2526", "2025-26", "2025/26", "2025_26"}:
            continue
        try:
            p = np.asarray([float(row["home_win_prob"]), float(row["draw_prob"]), float(row["away_win_prob"])], dtype=np.float32)
        except (KeyError, TypeError, ValueError):
            skipped += 1
            continue
        if not np.all(np.isfinite(p)) or np.any(p < 0) or float(p.sum()) <= 0:
            skipped += 1
            continue
        p /= np.float32(p.sum())
        odds = _complete_odds(row)
        if odds is None:
            skipped += 1
            continue
        result = str(row.get("result") or row.get("FTR") or "").upper()
        y = {"H": 0, "D": 1, "A": 2}.get(result)
        if y is None:
            skipped += 1
            continue
        candidate.append(tuple(p.tolist()))
        market.append(tuple(odds[0].tolist()))
        truth.append(y)
        dates.append(date)
        books[odds[1]] = books.get(odds[1], 0) + 1
    if len(truth) < 50:
        raise RuntimeError(f"G18 requires >=50 complete holdout rows; found {len(truth)}")
    order = np.argsort(np.asarray(dates, dtype="datetime64[ns]"))
    cand = np.asarray(candidate, dtype=np.float32)[order]
    mkt = np.asarray(market, dtype=np.float32)[order]
    y = np.asarray(truth, dtype=np.int8)[order]
    meta = {"n": int(len(y)), "skipped": int(skipped), "bookmakers": books,
            "holdout_start": start.date().isoformat(), "holdout_end_exclusive": end.date().isoformat()}
    return cand, mkt, {**meta, "y": y}


def _block_starts(n: int, block: int) -> np.ndarray:
    return np.arange(0, n, block, dtype=np.int32)


def bootstrap(delta: np.ndarray, *, reps: int, block: int, batch_size: int, seed: int) -> np.ndarray:
    """Circular moving-block bootstrap over paired per-match RPS deltas."""
    n = len(delta)
    if block < 1 or block > n:
        raise ValueError("block length must be in [1,n]")
    starts = _block_starts(n, block)
    rng = np.random.default_rng(seed)
    out = np.empty(reps, dtype=np.float32)
    # Batch only the integer index matrix. At 10,000 x 10,000 this remains
    # bounded by batch_size * ceil(n/block) * 4 bytes.
    for lo in range(0, reps, batch_size):
        count = min(batch_size, reps - lo)
        chosen = rng.integers(0, len(starts), size=(count, len(starts)), dtype=np.int32)
        sums = np.zeros(count, dtype=np.float64)
        for j, start_index in enumerate(starts):
            starts_for_batch = starts[chosen[:, j]]
            # Circular block: construct only one small block at a time.
            offsets = np.arange(block, dtype=np.int32)
            idx = (starts_for_batch[:, None] + offsets[None, :]) % n
            sums += delta[idx].sum(axis=1, dtype=np.float64)
        out[lo:lo + count] = (sums / float(len(starts) * block)).astype(np.float32)
        del chosen, sums
        gc.collect()
    return out


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="G18 10,000-replicate block bootstrap against de-vigged market")
    p.add_argument("--input", type=Path, required=True, help="forecast/outcome/odds CSV or Parquet")
    p.add_argument("--output", type=Path, default=None)
    p.add_argument("--holdout-start", default="2025-08-01")
    p.add_argument("--holdout-end", default="2026-08-01")
    p.add_argument("--bootstrap-reps", type=int, default=10_000)
    p.add_argument("--block-length", type=int, default=10)
    p.add_argument("--batch-size", type=int, default=250)
    p.add_argument("--seed", type=int, default=20260914)
    return p


def main() -> int:
    args = _parser().parse_args()
    if args.bootstrap_reps != 10_000:
        raise SystemExit("G18 certification requires exactly --bootstrap-reps 10000")
    generated = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        candidate, market, meta = load_evidence(args.input, holdout_start=args.holdout_start, holdout_end=args.holdout_end)
        y = meta.pop("y")
        candidate_rps = _rps(y, candidate).astype(np.float32, copy=False)
        market_rps = _rps(y, market).astype(np.float32, copy=False)
        delta = (candidate_rps - market_rps).astype(np.float32, copy=False)
        observed = float(delta.mean())
        boot = bootstrap(delta, reps=args.bootstrap_reps, block=args.block_length, batch_size=args.batch_size, seed=args.seed)
        ci_low, ci_high = np.percentile(boot, [2.5, 97.5]).tolist()
        result = {
            "report_version": "v7.3-harness-1",
            "generated_at": generated,
            "repository": {"name": "sabiscore/sabiscore", "commit_sha": _git_sha(), "branch": None, "working_tree_clean": None},
            "deployment": {"backend_sha": None, "frontend_sha": None, "schema_version": None, "migration_revision": None, "compatibility_status": "NOT_EVALUATED"},
            "model": {"generation_id": None, "model_family": "served-candidate", "feature_contract": None, "artifact_hash": None, "schema_version": None, "status": "EVALUATION_ONLY", "calibration": None},
            "data": {"dataset_snapshot": str(args.input), "temporal_window": [args.holdout_start, args.holdout_end], "coverage": meta, "provenance_status": "INPUT_ARTIFACT_REQUIRED", "leakage_status": "NOT_ESTABLISHED_BY_HARNESS", "forecast_authenticity": "REQUIRES_PREMATCH_FORECAST_ARTIFACT"},
            "policy": {"policy_version": None, "policy_sha256": None, "metric_convention": "3-class RPS; lower is better; proportional de-vig", "class_order": list(OUTCOMES)},
            "metrics": {"rps": {"candidate": float(candidate_rps.mean()), "market": float(market_rps.mean()), "difference_candidate_minus_market": observed, "block_bootstrap_ci_95": [float(ci_low), float(ci_high)], "bootstrap_replicates": args.bootstrap_reps, "block_length": args.block_length, "seed": args.seed}},
            "gates": {"G18": {"status": "PASS" if ci_high < 0.0 else "FAIL", "criterion": "candidate RPS improvement CI upper bound < 0", "evidence_rows": int(len(y))}},
            "operator_gates": {}, "risks": ["A PASS here is not a release decision; policy and forecast provenance must be supplied to the final certification report."],
            "changes": [], "validation": {"memory_strategy": "float32 arrays + batched bootstrap + explicit gc.collect()", "executed": True},
            "decision": "PASS" if ci_high < 0.0 else "FAIL",
        }
    except Exception as exc:
        result = {"report_version": "v7.3-harness-1", "generated_at": generated, "repository": {"name": "sabiscore/sabiscore", "commit_sha": _git_sha()}, "gates": {"G18": {"status": "BLOCKED", "errors": [str(exc)]}}, "decision": "BLOCKED"}
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2
    out = args.output or REPO_ROOT / "artifacts" / "certification" / f"g18_bootstrap_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["decision"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
