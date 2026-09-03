"""Shared scaffolding for the `error_association` diagnostics (docs/DEBT.md item 50).

Two scripts interrogate the same gate from different angles —
`diagnose_error_association_outcome_mix.py` (is the reversal an RPS outcome-mix
artifact?) and `spike_independent_ensemble_uncertainty.py` (is it the member
basis?). They must agree on bucketing, on the control forecaster and on which
rows count, or their numbers cannot be compared to each other or to the gate.

Everything here is the *measurement scaffolding* both share. The thing under
test in each script stays in that script.

⚠️ Bucketing is rank-based and equal-size, byte-identical to the gate's own
test (`test_uncertainty_contract.py`), which uses `argsort` with equal slices
rather than quantile thresholds. Quantile cuts give different membership under
ties and do NOT reproduce the published per-league numbers — that exact
reproduction is the control which proves a diagnostic is measuring the gate's
quantity and not a lookalike.
"""
from __future__ import annotations

import gc
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple

import joblib
import numpy as np

from src.models.evaluation.metrics import ranked_probability_score
from src.models.uncertainty_policy import UNCERTAINTY_EVIDENCE_FLOORS, UNCERTAINTY_GATES

N_BUCKETS = int(UNCERTAINTY_GATES["error_association"]["threshold"]["buckets"])
MIN_ROWS_PER_BUCKET = int(UNCERTAINTY_EVIDENCE_FLOORS["min_rows_per_error_bucket"])
MIN_VALIDATION_ROWS = int(UNCERTAINTY_EVIDENCE_FLOORS["min_validation_rows"])


def bucket_indices(u_epi: np.ndarray, n: int = N_BUCKETS) -> List[np.ndarray]:
    """Rank-based equal-size buckets, byte-identical to the gate's own test."""
    order = np.argsort(u_epi)
    size = len(order) // n
    return [
        order[i * size : (i + 1) * size] if i < n - 1 else order[i * size :]
        for i in range(n)
    ]


def rps_rows(probs: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Per-row RPS for a (n, 3) probability matrix."""
    return np.array(
        [ranked_probability_score(int(o), list(p)) for p, o in zip(probs, y)],
        dtype=np.float64,
    )


def rps_fixed(prob: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Per-row RPS for ONE constant probability vector — the control forecaster."""
    p = list(np.asarray(prob, dtype=np.float64))
    return np.array([ranked_probability_score(int(o), p) for o in y], dtype=np.float64)


def association(
    u_epi: np.ndarray, rps_model: np.ndarray, rps_ref: np.ndarray
) -> Tuple[float, float, float]:
    """`(gap, gap_ref, skill)` for one league.

    `gap` is the gate's own quantity: mean RPS of the highest-epistemic bucket
    minus the lowest. `gap_ref` is the same for a forecaster that knows nothing
    about any individual fixture, so it is pure outcome mix. `skill` is the
    remainder — the part attributable to the model rather than to which
    outcomes happened to land in which bucket.
    """
    buckets = bucket_indices(u_epi)
    if any(len(b) < MIN_ROWS_PER_BUCKET for b in buckets):
        return float("nan"), float("nan"), float("nan")
    low, high = buckets[0], buckets[-1]
    gap = float(rps_model[high].mean() - rps_model[low].mean())
    gap_ref = float(rps_ref[high].mean() - rps_ref[low].mean())
    return gap, gap_ref, gap - gap_ref


@dataclass
class LeagueHoldout:
    """One league's holdout evaluation slice, plus its control forecaster."""

    league: str
    models_dict: Dict[str, Any]
    X_eval: np.ndarray
    y_eval: np.ndarray
    X_train: np.ndarray
    y_train: np.ndarray
    #: Per-row RPS of a constant base-rate forecaster fitted on pre-holdout rows
    #: only, so it never sees the rows it is scored on.
    rps_ref: np.ndarray

    @property
    def n_eval(self) -> int:
        return int(len(self.y_eval))


def iter_league_holdouts(
    dataset: Dict[str, dict], backend_root: Path, league_slugs: Dict[str, str]
) -> Iterator[LeagueHoldout]:
    """Yield each scoreable league's holdout slice, skipping what cannot be scored.

    Skips a league whose artifact or corpus rows are missing, or whose declared
    holdout season falls below the policy's `min_validation_rows` floor. The
    caller is handed the loaded `models_dict` and is responsible for releasing
    it; this generator drops its own reference after each yield.
    """
    for league, slug in league_slugs.items():
        artifact = backend_root / "models" / f"{slug}_ensemble_v5_phase7.pkl"
        data = dataset.get(league)
        if not artifact.exists() or not data:
            continue

        raw = joblib.load(artifact)
        holdout_season = raw["model_metadata"]["holdout_season"]
        models_dict = raw["models"]

        seasons = np.asarray(data["seasons"])
        X_all = np.asarray(data["X_incumbent"], dtype=np.float64)
        y_all = np.asarray(data["y"])
        eval_mask = seasons == holdout_season
        if int(eval_mask.sum()) < MIN_VALIDATION_ROWS:
            del raw, models_dict
            gc.collect()
            continue

        y_train = y_all[~eval_mask]
        base = np.array([(y_train == k).mean() for k in (0, 1, 2)], dtype=np.float64)
        y_eval = y_all[eval_mask]

        yield LeagueHoldout(
            league=league,
            models_dict=models_dict,
            X_eval=X_all[eval_mask],
            y_eval=y_eval,
            X_train=X_all[~eval_mask],
            y_train=y_train,
            rps_ref=rps_fixed(base, y_eval),
        )
        del raw, models_dict
        gc.collect()
