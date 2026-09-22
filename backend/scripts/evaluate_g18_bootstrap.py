#!/usr/bin/env python3
"""G18 candidate-vs-market RPS evidence harness.

The evaluation is downstream of the repository's historical data pipeline:
football-data/soccerdata match rows provide results/odds and the candidate
forecast artifact provides pre-match probabilities. Understat/xG remains
feature-generation provenance when present; it is never substituted for
bookmaker odds. Complete coherent 1X2 prices are de-vigged with Shin's method
(the designated G18 baseline); ``--devig proportional`` reproduces the legacy
convention for comparison.

The paired circular moving-block bootstrap is exactly 10,000 replicates per
reported scope, processed in small batches with float32 arrays and explicit GC.
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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTCOMES = ("home_win", "draw", "away_win")
ODDS_TIERS = (
    ("B365H", "B365D", "B365A", "bet365"),
    ("bet365_home", "bet365_draw", "bet365_away", "bet365"),
    ("PSH", "PSD", "PSA", "pinnacle"),
    ("pinnacle_home", "pinnacle_draw", "pinnacle_away", "pinnacle"),
)


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


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_date(value: str) -> datetime | None:
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(value.strip()[:19], fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def rps(y: np.ndarray, p: np.ndarray) -> np.ndarray:
    truth = np.zeros_like(p, dtype=np.float32)
    truth[np.arange(len(y)), y] = 1.0
    return np.mean(
        (
            np.cumsum(p.astype(np.float32), axis=1)[:, :2]
            - np.cumsum(truth, axis=1)[:, :2]
        )
        ** 2,
        axis=1,
        dtype=np.float32,
    )


def _load_market_baseline() -> Any:
    """Load the canonical de-vig module without importing the `src` package.

    `src/models/__init__.py` opens a database connection at import time
    (`docs/DEBT.md` item 7), which an offline evidence harness must never do.
    `market_baseline` is deliberately stdlib-only so it can be loaded by path,
    the same pattern `scripts/verify_active_artifacts.py` uses for the build
    gate. Registering it in `sys.modules` is required: `dataclass` resolves
    `cls.__module__` through it.
    """
    import importlib.util
    import sys

    path = (
        REPO_ROOT / "backend" / "src" / "models" / "evaluation" / "market_baseline.py"
    )
    spec = importlib.util.spec_from_file_location("sabiscore_market_baseline", path)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging guard
        raise RuntimeError(f"cannot load market baseline module at {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_MB = _load_market_baseline()

# Counts every rejection by cause so the report can state what the baseline
# declined rather than silently thinning the sample.
DEVIG_REJECTIONS: dict[str, int] = {}
SHIN_Z: list[float] = []


def devig(odds: tuple[float, float, float], method: str = "shin") -> np.ndarray:
    """De-vig one coherent 1X2 book into the designated baseline probabilities."""
    try:
        result = _MB.devig(odds, method=method)
    except _MB.MarketBaselineError as exc:
        DEVIG_REJECTIONS[exc.reason] = DEVIG_REJECTIONS.get(exc.reason, 0) + 1
        raise ValueError(f"market rejected: {exc.reason}") from exc
    if result.shin_z is not None:
        SHIN_Z.append(float(result.shin_z))
    return np.asarray(result.probabilities, dtype=np.float32)


def market_probs(
    row: dict[str, Any], method: str = "shin"
) -> tuple[np.ndarray, str] | None:
    for h, d, a, book in ODDS_TIERS:
        try:
            odds = (float(row.get(h, "")), float(row.get(d, "")), float(row.get(a, "")))
        except (TypeError, ValueError):
            continue
        if all(math.isfinite(x) and x > 1.0 for x in odds):
            try:
                return devig(odds, method), book
            except ValueError:
                # A book this tier rejects (bad overround, malformed price) must
                # not silently promote the next bookmaker to "the market" for
                # this fixture; drop the row instead.
                return None
    try:
        odds = tuple(
            float(row.get(k, "")) for k in ("home_odds", "draw_odds", "away_odds")
        )
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(x) and x > 1.0 for x in odds):
        return None
    try:
        return devig(odds, method), str(row.get("bookmaker") or "unknown")
    except ValueError:
        return None


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


def load(
    path: Path, start: datetime, end: datetime, method: str = "shin"
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    candidates: list[tuple[float, float, float]] = []
    markets: list[tuple[float, float, float]] = []
    truths: list[int] = []
    dates: list[datetime] = []
    leagues: list[str] = []
    books: dict[str, int] = {}
    skipped = 0
    for raw in iter_rows(path):
        date = parse_date(str(raw.get("date") or raw.get("Date") or ""))
        if date is None or not start <= date < end:
            continue
        try:
            p = np.asarray(
                [
                    float(raw["home_win_prob"]),
                    float(raw["draw_prob"]),
                    float(raw["away_win_prob"]),
                ],
                dtype=np.float32,
            )
            total = float(p.sum())
            if not np.isfinite(p).all() or np.any(p < 0) or total <= 0:
                raise ValueError
            p /= np.float32(total)
        except (KeyError, TypeError, ValueError):
            skipped += 1
            continue
        market = market_probs(raw, method)
        outcome = {"H": 0, "D": 1, "A": 2}.get(
            str(raw.get("result") or raw.get("FTR") or "").strip().upper()
        )
        if market is None or outcome is None:
            skipped += 1
            continue
        candidates.append(tuple(p.tolist()))
        markets.append(tuple(market[0].tolist()))
        truths.append(outcome)
        dates.append(date)
        leagues.append(str(raw.get("league") or raw.get("League") or "UNKNOWN"))
        books[market[1]] = books.get(market[1], 0) + 1
    if len(truths) < 50:
        raise RuntimeError(
            f"G18 requires >=50 complete holdout rows; found {len(truths)}"
        )
    order = np.argsort(np.asarray(dates, dtype="datetime64[ns]"))
    meta = {
        "n": len(truths),
        "skipped": skipped,
        "leagues": sorted(set(leagues)),
        "league_rows": {k: leagues.count(k) for k in sorted(set(leagues))},
        "bookmakers": books,
    }
    return (
        np.asarray(candidates, dtype=np.float32)[order],
        np.asarray(markets, dtype=np.float32)[order],
        np.asarray(truths, dtype=np.int8)[order],
        np.asarray(leagues, dtype=object)[order],
        meta,
    )


def bootstrap(
    delta: np.ndarray, reps: int, block: int, batch: int, seed: int
) -> tuple[float, float]:
    n = len(delta)
    block = min(block, n)
    n_blocks = int(math.ceil(n / block))
    rng = np.random.default_rng(seed)
    boot = np.empty(reps, dtype=np.float32)
    offsets = np.arange(block, dtype=np.int32)
    for lo in range(0, reps, batch):
        count = min(batch, reps - lo)
        starts = rng.integers(0, n, size=(count, n_blocks), dtype=np.int32)
        sums = np.zeros(count, dtype=np.float64)
        for j in range(n_blocks):
            idx = (starts[:, j, None] + offsets[None, :]) % n
            sums += delta[idx].sum(axis=1, dtype=np.float64)
        boot[lo : lo + count] = (sums / float(n_blocks * block)).astype(np.float32)
        del starts, idx, sums
        gc.collect()
    return tuple(float(x) for x in np.percentile(boot, [2.5, 97.5]))


def evaluate_scope(
    y: np.ndarray,
    candidate: np.ndarray,
    market: np.ndarray,
    *,
    reps: int,
    block: int,
    batch: int,
    seed: int,
) -> dict[str, Any]:
    candidate_rps = rps(y, candidate)
    market_rps = rps(y, market)
    delta = (candidate_rps - market_rps).astype(np.float32, copy=False)
    low, high = bootstrap(delta, reps, block, batch, seed)
    return {
        "n": int(len(y)),
        "candidate_rps": float(candidate_rps.mean()),
        "market_rps": float(market_rps.mean()),
        "difference_candidate_minus_market": float(delta.mean()),
        "block_bootstrap_ci_95": [low, high],
        "bootstrap_replicates": reps,
        "block_length": min(block, len(delta)),
        "seed": seed,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="G18 10,000-replicate paired block bootstrap"
    )
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output", type=Path)
    ap.add_argument("--holdout-start", default="2025-08-01")
    ap.add_argument("--holdout-end", default="2026-08-01")
    ap.add_argument("--bootstrap-reps", type=int, default=10_000)
    ap.add_argument("--block-length", type=int, default=10)
    ap.add_argument("--batch-size", type=int, default=250)
    ap.add_argument("--seed", type=int, default=20260914)
    ap.add_argument(
        "--devig",
        choices=("shin", "proportional"),
        default="shin",
        help="Market de-vig convention. Shin is the designated G18 baseline; "
        "proportional reproduces the pre-2026-09-20 convention.",
    )
    args = ap.parse_args()
    if args.bootstrap_reps != 10_000:
        raise SystemExit("v7.3 G18 requires exactly 10,000 bootstrap replicates")
    start, end = parse_date(args.holdout_start), parse_date(args.holdout_end)
    generated = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        if start is None or end is None or start >= end:
            raise ValueError("invalid holdout interval")
        candidate, market, y, leagues, meta = load(args.input, start, end, args.devig)
        pooled = evaluate_scope(
            y,
            candidate,
            market,
            reps=10_000,
            block=args.block_length,
            batch=args.batch_size,
            seed=args.seed,
        )
        by_league: dict[str, Any] = {}
        for league in sorted(set(leagues.tolist())):
            mask = leagues == league
            if int(mask.sum()) < 50:
                by_league[league] = {
                    "status": "INSUFFICIENT_EVIDENCE",
                    "n": int(mask.sum()),
                }
            else:
                by_league[league] = evaluate_scope(
                    y[mask],
                    candidate[mask],
                    market[mask],
                    reps=10_000,
                    block=args.block_length,
                    batch=args.batch_size,
                    seed=args.seed,
                )
            gc.collect()
        league_pass = bool(by_league) and all(
            v.get("block_bootstrap_ci_95", [1.0, 1.0])[1] < 0.0
            for v in by_league.values()
        )
        passed = pooled["block_bootstrap_ci_95"][1] < 0.0 and league_pass
        result = {
            "report_version": "v7.3-harness-2",
            "generated_at": generated,
            "repository": {"name": "sabiscore/sabiscore", "commit_sha": git_sha()},
            "deployment": {"compatibility_status": "NOT_EVALUATED"},
            "model": {"status": "EVALUATION_ONLY"},
            "data": {
                "dataset_snapshot": str(args.input),
                "snapshot_sha256": file_sha256(args.input),
                "temporal_window": [args.holdout_start, args.holdout_end],
                "coverage": meta,
                "provenance_status": "INPUT_ARTIFACT_REQUIRED",
                "forecast_authenticity": "REQUIRES_PREMATCH_FORECAST_ARTIFACT",
            },
            "policy": {
                "metric_convention": f"3-class RPS; lower is better; {args.devig} de-vig",
                "devig_method": args.devig,
                "devig_reference": "Shin (1993), Zenith Journal; inverted per Strumbelj (2014) IJF",
                "shin_z_mean": (float(np.mean(SHIN_Z)) if SHIN_Z else None),
                "shin_z_median": (float(np.median(SHIN_Z)) if SHIN_Z else None),
                "market_rejections_by_reason": dict(DEVIG_REJECTIONS),
            },
            "metrics": {"rps": {"pooled": pooled, "by_league": by_league}},
            "gates": {
                "G18": {
                    "status": "PASS" if passed else "FAIL",
                    "criterion": "candidate RPS improvement CI upper bound < 0; every reported league passes",
                    "evidence_rows": int(len(y)),
                }
            },
            "operator_gates": {},
            "risks": [
                "Market evidence is valid only when the coherent 1X2 snapshot predates evaluation_at.",
                "Understat/xG is feature provenance, not a substitute for market odds.",
            ],
            "changes": [],
            "validation": {
                "executed": True,
                "memory_strategy": "float32 + batched bootstrap + explicit gc",
                "bootstrap_replicates_per_scope": 10000,
            },
            "decision": "PASS" if passed else "FAIL",
        }
    except Exception as exc:
        result = {
            "report_version": "v7.3-harness-2",
            "generated_at": generated,
            "repository": {"name": "sabiscore/sabiscore", "commit_sha": git_sha()},
            "gates": {"G18": {"status": "BLOCKED", "errors": [str(exc)]}},
            "decision": "BLOCKED",
        }
    out = (
        args.output
        or REPO_ROOT
        / "artifacts/certification"
        / f"g18_bootstrap_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["decision"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
