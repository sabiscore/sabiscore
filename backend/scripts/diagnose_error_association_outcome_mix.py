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

Bucketing, the control forecaster and the league/holdout iteration live in
`_error_association_common` and are shared with
`spike_independent_ensemble_uncertainty.py`. Bucketing there is rank-based and
equal-size, byte-identical to the gate's own test, which is why `gap_model`
reproduces the published per-league numbers exactly rather than approximately.
That exact reproduction is the control: if it ever stops matching, this script
is measuring something else and its conclusion does not hold.

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
import math
import sys
from pathlib import Path
from typing import List, Tuple

import numpy as np

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
for _path in (str(_BACKEND_ROOT), str(_BACKEND_ROOT / "scripts")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from train_on_real_matches import build_dataset, load_matches  # noqa: E402

# Bucketing, the control forecaster and the league/holdout iteration are shared
# with spike_independent_ensemble_uncertainty.py — both must agree on them or
# their numbers cannot be compared to each other or to the gate.
from _error_association_common import (  # noqa: E402
    N_BUCKETS,
    association,
    bucket_indices,
    iter_league_holdouts,
)

# Reused rather than re-implemented: `_score` routes every row through the
# production `dispersion_from_members` and already handles the chunking that
# keeps peak RSS inside this repo's lean-environment budget.
from diagnose_decoupled_uncertainty import _LEAGUE_SLUGS, _score  # noqa: E402


def main() -> int:
    dataset = build_dataset(load_matches(_BACKEND_ROOT / "data" / "cache"))

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

    rows: List[Tuple[str, float, float, float]] = []
    for holdout in iter_league_holdouts(dataset, _BACKEND_ROOT, _LEAGUE_SLUGS):
        evaluation = _score(holdout.models_dict, holdout.X_eval, holdout.y_eval)
        u_epi = evaluation["u_epi"]
        gap_model, gap_ref, skill_gap = association(
            u_epi, evaluation["rps"], holdout.rps_ref
        )
        if math.isnan(gap_model):
            del evaluation
            gc.collect()
            continue

        buckets = bucket_indices(u_epi)
        low, high = buckets[0], buckets[-1]
        print(
            f"{holdout.league:11} {holdout.n_eval:>4} {gap_model:>+10.4f} "
            f"{gap_ref:>+9.4f} {skill_gap:>+10.4f}  "
            f"{(holdout.y_eval[low] == 1).mean():>7.1%} "
            f"{(holdout.y_eval[high] == 1).mean():>7.1%}"
        )
        rows.append((holdout.league, gap_model, gap_ref, skill_gap))
        del evaluation
        gc.collect()

    if not rows:
        print("no league met the evidence floor — nothing measured")
        return 1

    print("-" * len(header))
    mean_model = float(np.mean([r[1] for r in rows]))
    mean_ref = float(np.mean([r[2] for r in rows]))
    mean_skill = float(np.mean([r[3] for r in rows]))
    print(
        f"{'MEAN':11} {'':>4} {mean_model:>+10.4f} {mean_ref:>+9.4f} "
        f"{mean_skill:>+10.4f}"
    )

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
