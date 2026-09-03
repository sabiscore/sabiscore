#!/usr/bin/env python3
"""Is `error_association`'s reversal an outcome-mix artifact of RPS, or a
genuinely reversed epistemic signal? (docs/DEBT.md item 50, hypothesis 3)

WHAT THIS ANSWERS
-----------------
`UNCERTAINTY_GATES["error_association"]` requires the highest-epistemic bucket
to show *worse* mean RPS than the lowest. It fails in all five scoreable
leagues, in the wrong direction. Two explanations were already closed:
in-bag/out-of-bag scoring bias (hypothesis 2, ruled out) and the aleatoric
confound (hypothesis 1, substantially explained but residualization only
rescued 1 of 5 leagues).

This script tests a third, previously unexamined confound. ADR 0009 Addendum 3
analysed the aleatoric confound in *prediction* space; this one lives in
*realised-outcome* space:

Ordered RPS over [home, draw, away] is not symmetric across outcomes. For a
prediction ``p`` a DRAW costs ``(p_h^2 + p_a^2)/2`` while a HOME costs
``((p_h-1)^2 + (p_h+p_d-1)^2)/2``. For a typical ``p=[.45,.27,.28]`` that is
0.140 (draw) vs 0.190 (home) vs 0.360 (away) — **draws are structurally cheap
in RPS.** If high-epistemic fixtures (trees disagree -> evenly matched sides)
draw more often, the top bucket earns a mechanical discount unrelated to the
quality of the uncertainty signal.

METHOD
------
Score a FIXED reference forecaster — the league base rate computed on the
pre-holdout seasons, which knows nothing about any individual fixture — on the
same holdout rows, bucketed the same way. Any bucket-to-bucket difference it
shows is *pure outcome mix*, because the forecaster is constant.

    gap_model     = mean RPS_model(Q4) - mean RPS_model(Q1)   <- the gate's number
    gap_reference = mean RPS_ref(Q4)   - mean RPS_ref(Q1)     <- pure outcome mix
    skill_gap     = gap_model - gap_reference                 <- model-attributable

Bucketing is rank-based and equal-size, byte-identical to the gate's own test
(`test_uncertainty_contract.py`), which is why `gap_model` reproduces the
published per-league numbers exactly rather than approximately. That exact
reproduction is the control: if it ever stops matching, this script is
measuring something else and its conclusion does not hold.

RESULT (2026-09-03): HYPOTHESIS REFUTED. Outcome mix explains ~12% of the mean
gap; `skill_gap` stays negative in 5 of 5 leagues. See docs/DEBT.md item 50.

⚠️ **THIS SCRIPT CERTIFIES NOTHING AND CHANGES NO GATE.** It writes no
artifacts and mutates no policy. Measurement is always permitted; re-specifying
a threshold after observing that it blocks promotion is not (APEX §23).

Usage:
    cd backend && PYTHONPATH=. python scripts/diagnose_error_association_outcome_mix.py
"""
from __future__ import annotations

import gc
import sys
from pathlib import Path
from typing import List

import joblib
import numpy as np

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
for _path in (str(_BACKEND_ROOT), str(_BACKEND_ROOT / "scripts")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from src.models.evaluation.metrics import ranked_probability_score  # noqa: E402
from src.models.uncertainty_policy import (  # noqa: E402
    UNCERTAINTY_EVIDENCE_FLOORS,
    UNCERTAINTY_GATES,
)
from train_on_real_matches import build_dataset, load_matches  # noqa: E402

# Reused rather than re-implemented: `_score` routes every row through the
# production `dispersion_from_members` and already handles the chunking that
# keeps peak RSS inside this repo's lean-environment budget. Duplicating it
# would risk the two diagnostics silently diverging — the exact failure mode
# this codebase has repeatedly been bitten by.
from diagnose_decoupled_uncertainty import _LEAGUE_SLUGS, _score  # noqa: E402

N_BUCKETS = int(UNCERTAINTY_GATES["error_association"]["threshold"]["buckets"])
MIN_ROWS_PER_BUCKET = int(UNCERTAINTY_EVIDENCE_FLOORS["min_rows_per_error_bucket"])


def bucket_indices(u_epi: np.ndarray, n: int) -> List[np.ndarray]:
    """Rank-based equal-size buckets, matching the gate's own test exactly.

    The gate uses `argsort` with equal-size slices, not quantile thresholds.
    Quantile cuts give slightly different bucket membership under ties and
    would not reproduce the published numbers.
    """
    order = np.argsort(u_epi)
    size = len(order) // n
    return [
        order[i * size : (i + 1) * size] if i < n - 1 else order[i * size :]
        for i in range(n)
    ]


def rps_of_fixed_forecaster(probs: np.ndarray, y: np.ndarray) -> np.ndarray:
    """The gate's own scorer, applied to one constant probability vector."""
    p = list(np.asarray(probs, dtype=np.float64))
    return np.array([ranked_probability_score(int(o), p) for o in y], dtype=np.float64)


def main() -> int:
    dataset = build_dataset(load_matches(_BACKEND_ROOT / "data" / "cache"))
    floor = int(UNCERTAINTY_EVIDENCE_FLOORS["min_validation_rows"])

    print("error_association: outcome-mix artifact, or a genuinely reversed signal?")
    print(f"Buckets = {N_BUCKETS} (rank-based, gate-identical), holdout season only.")
    print("gap_ref is what a constant league-base-rate forecaster scores on the same")
    print("rows — it knows nothing about any fixture, so it is pure outcome mix.\n")

    header = (
        f"{'league':11} {'n':>4} {'gap_model':>10} {'gap_ref':>9} {'skill_gap':>10}  "
        f"{'draw% Q1':>8} {'draw% Q4':>8}"
    )
    print(header)
    print("-" * len(header))

    rows = []
    for league, slug in _LEAGUE_SLUGS.items():
        artifact = _BACKEND_ROOT / "models" / f"{slug}_ensemble_v5_phase7.pkl"
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

        if int(eval_mask.sum()) < floor:
            del raw, models_dict
            gc.collect()
            continue

        evaluation = _score(models_dict, X_all[eval_mask], y_all[eval_mask])
        y_eval = y_all[eval_mask]
        u_epi, rps_model = evaluation["u_epi"], evaluation["rps"]

        # Reference forecaster: base rate over the PRE-HOLDOUT seasons only, so
        # it never sees the rows it is scored on.
        y_fit = y_all[~eval_mask]
        base = np.array([(y_fit == k).mean() for k in (0, 1, 2)], dtype=np.float64)
        rps_ref = rps_of_fixed_forecaster(base, y_eval)

        buckets = bucket_indices(u_epi, N_BUCKETS)
        if any(len(b) < MIN_ROWS_PER_BUCKET for b in buckets):
            del raw, models_dict, evaluation
            gc.collect()
            continue

        low, high = buckets[0], buckets[-1]
        gap_model = float(rps_model[high].mean() - rps_model[low].mean())
        gap_ref = float(rps_ref[high].mean() - rps_ref[low].mean())
        skill_gap = gap_model - gap_ref

        print(
            f"{league:11} {int(eval_mask.sum()):>4} {gap_model:>+10.4f} "
            f"{gap_ref:>+9.4f} {skill_gap:>+10.4f}  "
            f"{(y_eval[low] == 1).mean():>7.1%} {(y_eval[high] == 1).mean():>7.1%}"
        )
        rows.append((league, gap_model, gap_ref, skill_gap))

        del raw, models_dict, evaluation
        gc.collect()

    if not rows:
        print("no league met the evidence floor — nothing measured")
        return 1

    print("-" * len(header))
    mean_model = float(np.mean([r[1] for r in rows]))
    mean_ref = float(np.mean([r[2] for r in rows]))
    mean_skill = float(np.mean([r[3] for r in rows]))
    print(f"{'MEAN':11} {'':>4} {mean_model:>+10.4f} {mean_ref:>+9.4f} {mean_skill:>+10.4f}")

    rescued = sum(1 for r in rows if r[3] >= 0.0)
    share = (mean_ref / mean_model * 100.0) if mean_model else float("nan")
    print(
        f"\nOutcome mix explains {share:.0f}% of the mean gap. "
        f"skill_gap >= 0 in {rescued}/{len(rows)} leagues."
    )
    print(
        "Verdict: the reversal is NOT an outcome-mix artifact — it survives removal "
        "of the mechanical effect."
        if rescued < len(rows)
        else "Verdict: the reversal is fully explained by outcome mix."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
