#!/usr/bin/env python3
"""Rolling-origin temporal evaluation (certification Stage 7).

WHY THIS EXISTS
---------------
``compare_candidate_vs_incumbent.py`` scores a candidate on ONE holdout season.
That answers "is the candidate better than the incumbent on the most recent
season", which is the promotion question. It does not answer the certification
question: **is the model's probability quality temporally robust**, or did one
season happen to suit it?

This script re-trains from scratch at each origin and scores the season that
follows, so every reported number is genuinely out-of-sample:

    train 1920..2021  ->  test 2122
    train 1920..2122  ->  test 2223
    train 1920..2223  ->  test 2324
    ...

Nothing here is a promotion gate. It produces auditable evidence; the gates live
in ``certification_policy.py`` and are applied elsewhere.

NO NEW METRIC IMPLEMENTATIONS
-----------------------------
Every metric is imported from the canonical module. The metric contract
(``reports/evaluation/metric-contract.json``) names one implementation per
concept, and adding a second here — however convenient — is the exact defect
that put three different Brier scales on one response field.

Usage:
    PYTHONPATH=. python scripts/temporal_evaluation.py [--out reports/certification/temporal-evaluation.json]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

_SPEC = importlib.util.spec_from_file_location(
    "sabiscore_train_on_real_matches", _BACKEND_ROOT / "scripts" / "train_on_real_matches.py"
)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("cannot load the training pipeline")
train_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(train_mod)

from src.models.calibration import _compute_brier_multiclass  # noqa: E402
from src.models.evaluation.metrics import (  # noqa: E402
    accuracy_and_per_class,
    block_bootstrap_ci,
    brier_score_decomposition,
    expected_calibration_error,
    log_loss_multiclass,
    ranked_probability_score,
)
from src.models.training_manifest import (  # noqa: E402
    dataset_fingerprint,
    environment_fingerprint,
    git_commit,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("temporal-eval")

#: An origin needs enough prior history for train_league's own floors
#: (300 core + 50 calibration rows) to be satisfiable.
_MIN_PRIOR_SEASONS = 3


def _rps_vector(y_true: np.ndarray, probs: np.ndarray) -> np.ndarray:
    """Per-row RPS from the canonical scalar scorer."""
    return np.asarray(
        [ranked_probability_score(int(t), [float(v) for v in p]) for t, p in zip(y_true, probs)],
        dtype=float,
    )


def _rps_mean(y_true: np.ndarray, probs: np.ndarray) -> float:
    """Mean RPS in the (y_true, y_proba) -> float shape block_bootstrap_ci wants."""
    return float(_rps_vector(y_true, probs).mean())


def _baselines(y_train: np.ndarray, y_test: np.ndarray, n_classes: int = 3) -> Dict[str, float]:
    """Reference forecasts every candidate must be read against.

    `league_prior` is fitted on the TRAINING slice only — using the test
    season's own class balance would give the baseline information the model
    never had, and flatter the model by comparison.
    """
    n = len(y_test)
    uniform = np.full((n, n_classes), 1.0 / n_classes)
    counts = np.bincount(y_train, minlength=n_classes).astype(float)
    prior = np.tile((counts / counts.sum())[None, :], (n, 1))
    home = np.tile(np.array([[0.60, 0.25, 0.15]]), (n, 1))
    return {
        "uniform": float(_rps_vector(y_test, uniform).mean()),
        "league_prior": float(_rps_vector(y_test, prior).mean()),
        "home_bias": float(_rps_vector(y_test, home).mean()),
    }


def _score(y_true: np.ndarray, probs: np.ndarray, y_train: np.ndarray) -> Dict[str, Any]:
    """One fully-specified evaluation record for a single origin."""
    rps_rows = _rps_vector(y_true, probs)
    acc = accuracy_and_per_class(y_true, probs)
    counts = np.bincount(y_true, minlength=3).astype(int)
    return {
        "n": int(len(y_true)),
        "class_distribution": {
            "home_win": int(counts[0]),
            "draw": int(counts[1]),
            "away_win": int(counts[2]),
            "fractions": [round(float(c / max(len(y_true), 1)), 4) for c in counts],
        },
        "rps": round(float(rps_rows.mean()), 6),
        "rps_ci": block_bootstrap_ci(y_true, probs, _rps_mean),
        "log_loss": round(log_loss_multiclass(y_true, probs), 6),
        "multiclass_brier": round(_compute_brier_multiclass(y_true, probs), 6),
        "ece": expected_calibration_error(y_true, probs),
        "accuracy_and_per_class": acc,
        "reliability": brier_score_decomposition(y_true, probs),
        "baselines": _baselines(y_train, y_true),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir", type=Path, default=_BACKEND_ROOT / "data" / "cache")
    ap.add_argument(
        "--out",
        type=Path,
        default=_BACKEND_ROOT / "reports" / "certification" / "temporal-evaluation.json",
    )
    ap.add_argument("--league", default=None, help="restrict to one league (faster)")
    args = ap.parse_args()

    matches = train_mod.load_matches(args.cache_dir)
    if not matches:
        logger.error("no matches parsed")
        return 1
    dataset = train_mod.build_dataset(matches)
    feature_names = list(train_mod.APEX_FEATURES_68)

    report: Dict[str, Any] = {
        "schema": "sabiscore_temporal_evaluation_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit(),
        "design": (
            "rolling-origin: for each origin season, the model is retrained from "
            "scratch on every strictly-earlier season and scored on the origin. "
            "No random splitting anywhere."
        ),
        "metric_contract": "reports/evaluation/metric-contract.json",
        "promotion_claim": "NONE — this is evidence, not a gate",
        "dataset": {
            k: v
            for k, v in dataset_fingerprint(args.cache_dir).items()
            if k != "files"
        },
        "environment": environment_fingerprint(),
        "leagues": {},
    }

    leagues = [args.league] if args.league else sorted(dataset)
    for league in leagues:
        bundle = dataset.get(league)
        if not bundle or not bundle["y"]:
            continue
        seasons = np.asarray(bundle["seasons"])
        dates = np.asarray(bundle["dates"])
        ordered = sorted(set(seasons.tolist()), key=lambda s: max(dates[seasons == s]))
        origins = ordered[_MIN_PRIOR_SEASONS:]
        if not origins:
            logger.info("%s: only %d seasons — no valid origin", league, len(ordered))
            continue

        league_rows: List[Dict[str, Any]] = []
        for origin in origins:
            keep = np.asarray(
                [s in set(ordered[: ordered.index(origin) + 1]) for s in seasons], dtype=bool
            )
            sliced = {
                "X": [row for row, k in zip(bundle["X"], keep) if k],
                "X_incumbent": [row for row, k in zip(bundle["X_incumbent"], keep) if k],
                "y": [v for v, k in zip(bundle["y"], keep) if k],
                "seasons": [v for v, k in zip(bundle["seasons"], keep) if k],
                "dates": [v for v, k in zip(bundle["dates"], keep) if k],
            }
            try:
                trained = train_mod.train_league(
                    league, sliced, origin, feature_names=feature_names
                )
            except ValueError as exc:
                logger.warning("  %s @ %s: %s", league, origin, exc)
                continue
            if trained is None:
                logger.info("  %s @ %s: split floors not met — skipped", league, origin)
                continue

            X = np.asarray(sliced["X"], dtype=np.float32)
            y = np.asarray(sliced["y"], dtype=int)
            season_arr = np.asarray(sliced["seasons"])
            test = season_arr == origin
            probs = train_mod._build_meta_features(trained["models"], X[test])
            probs = trained["meta_model"].predict_proba(probs)

            record = _score(y[test], np.asarray(probs, dtype=float), y[~test])
            record["origin_season"] = origin
            record["train_rows"] = int((~test).sum())
            record["training_seasons"] = ordered[: ordered.index(origin)]
            league_rows.append(record)
            logger.info(
                "  %-12s @ %s  train=%5d test=%4d  rps=%.4f [%.4f, %.4f]  ll=%.4f  market_free_best_baseline=%.4f",
                league, origin, record["train_rows"], record["n"], record["rps"],
                record["rps_ci"]["ci_lower"], record["rps_ci"]["ci_upper"],
                record["log_loss"], min(record["baselines"].values()),
            )

        if not league_rows:
            continue
        rps_series = [r["rps"] for r in league_rows]
        beat = sum(1 for r in league_rows if r["rps"] < min(r["baselines"].values()))
        report["leagues"][league] = {
            "origins": league_rows,
            "summary": {
                "origin_count": len(league_rows),
                "rps_mean": round(float(np.mean(rps_series)), 6),
                "rps_std": round(float(np.std(rps_series)), 6),
                "rps_min": round(float(np.min(rps_series)), 6),
                "rps_max": round(float(np.max(rps_series)), 6),
                "origins_beating_best_non_market_baseline": beat,
            },
        }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    logger.info("\nWrote %s", args.out)
    logger.info("This is evidence, not a promotion decision.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
