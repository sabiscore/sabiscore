#!/usr/bin/env python3
"""Does epistemic dispersion across INDEPENDENTLY SEEDED ensembles rank error,
where dispersion across one forest's bootstrap trees does not?
(docs/DEBT.md item 50, Path A — timeboxed architectural spike.)

WHY
---
`UNCERTAINTY_GATES["error_association"]` fails in the wrong direction in all
five scoreable leagues, and three explanations are already closed: in-bag
scoring bias, the aleatoric confound (residualization rescued 1 of 5), and the
RPS outcome-mix artifact (explains 12%; `skill_gap` stayed negative 5 of 5).

The remaining structural suspicion is the **member basis itself**. Bootstrap
trees inside a single RandomForest share hyperparameters, split logic and
feature space; their disagreement measures variance *within one localized
hypothesis space*, not ignorance of the data-generating function. Genuine
epistemic uncertainty needs members that explore materially different
functional mappings while still fitting the training data.

WHAT CHANGES, AND WHAT DELIBERATELY DOES NOT
--------------------------------------------
Only the **definition of a member** changes. `dispersion_from_members()` — the
certified BALD decomposition — is called verbatim, so the math under test is
the shipped math. Nothing here touches `UNCERTAINTY_GATES`,
`uncertainty_policy.py`, or any artifact.

  incumbent member = one of ~300 bootstrap trees inside the shipped RF
  spike member     = one independently seeded RF+XGB+LGBM stack, trained on
                     its own bootstrap resample of the same pre-holdout rows,
                     aggregated by mean over its three learners

The mean-over-base-learners aggregation is not arbitrary: it is exactly what
`PredictionEngine._ensemble_predict_dict` serves at request time, and what
`train_league()` scores as `probs`. Replicas carry no meta-model or temperature
head, because the request path does not use one either.

Per-replica **resampling is deliberate, not incidental.** A 300-tree RF is
already an average, so seed variation alone barely moves a bagged predictor.
`uncertainty_policy.UNCERTAINTY_GATES["sufficient_members"]` states the
preference directly: "Bootstrap or resampling variants are preferred over
distinct algorithms: they vary the training sample, which is the sampling
uncertainty epistemic uncertainty is meant to capture."

`_TRAINING_SEED` is monkeypatched per replica rather than the learners being
rebuilt here, so every replica uses the *production* learner definitions from
`_instantiate()` and cannot drift from them.

DESIGN — PAIRED, SAME ROWS, SAME BUCKETING
------------------------------------------
Both member bases are measured on the identical holdout rows in one run, so the
comparison is paired rather than assembled from two sessions' numbers. Bucketing
is rank-based and equal-size, byte-identical to the gate's own test, and the
control is the same constant league-base-rate forecaster used to refute the
outcome-mix hypothesis:

    gap     = mean RPS(highest-epistemic bucket) - mean RPS(lowest)
    gap_ref = same for a constant base-rate forecaster  (pure outcome mix)
    skill   = gap - gap_ref                             (model-attributable)

The gate wants `gap > 0`. The spike succeeds only if `skill` flips positive —
passing on outcome mix alone would not be a real result.

RESULT (2026-09-03): **the independence hypothesis is REFUTED, and the apparent
win was a confound in this script's own first design.**

Two pre-declared ladders (seeds 1000 and 7000, N in 3/5/10/20/30) showed the
3-learner replica basis removing the systematic reversal and turning mean skill
positive in 9 of 10 points (block means +0.0056 and +0.0191, against a
deterministic tree baseline of -0.0190). That looked like a win.

It was not. The default replica is an RF+XGB+LGBM stack while the incumbent
basis is trees inside a single RandomForest, so the headline comparison moved
member **independence** and member **composition** at once. Re-running with
`--rf-only`, which changes only independence:

    trees (incumbent)           skill -0.0190             0/5
    RF-only  seed 1000   +0.0007 / -0.0246 / -0.0323   2/5, 1/5, 1/5
    RF-only  seed 7000   -0.0076 / -0.0212 / -0.0236   2/5, 1/5, 0/5

Independently seeded, independently resampled RandomForests reproduce the
reversal — 5 of 6 points negative, several *worse* than the incumbent. Seeding
and resampling independence buys nothing. The entire gain came from mixing
model classes.

⚠️ That is the member design `UNCERTAINTY_GATES["sufficient_members"]`
explicitly deprecates: "Bootstrap or resampling variants are preferred over
distinct algorithms ... whereas distinct algorithms vary only model class." So
the only configuration that moves the metric is the one the frozen policy calls
the less principled one, which is a reason to distrust the effect rather than
adopt it.

⚠️ **CERTIFIES NOTHING.** Measurement is always permitted; re-specifying a
threshold after observing that it blocks promotion is not (APEX §23). A
positive result here is evidence for an authorized decision, not a licence to
change the member basis in serving.

Usage:
    cd backend && PYTHONPATH=. python scripts/spike_independent_ensemble_uncertainty.py
    cd backend && PYTHONPATH=. python scripts/spike_independent_ensemble_uncertainty.py --replicas 3
"""
from __future__ import annotations

import argparse
import gc
import sys
import time
from pathlib import Path
from typing import Dict, List

import numpy as np

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
for _path in (str(_BACKEND_ROOT), str(_BACKEND_ROOT / "scripts")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from src.models.ensemble_uncertainty import dispersion_from_members  # noqa: E402
from src.models.uncertainty_policy import UNCERTAINTY_GATES  # noqa: E402

import train_on_real_matches as trainer  # noqa: E402
from train_on_real_matches import build_dataset, load_matches  # noqa: E402

# Bucketing, the control forecaster and the league/holdout iteration are shared
# with diagnose_error_association_outcome_mix.py — both must agree on them or
# their numbers cannot be compared to each other or to the gate.
from _error_association_common import (  # noqa: E402
    association,
    iter_league_holdouts,
    rps_rows,
)

# Same reuse rationale: `_score` routes the incumbent tree basis through the
# production dispersion path and handles the chunking that keeps peak RSS
# inside budget.
from diagnose_decoupled_uncertainty import _LEAGUE_SLUGS, _score  # noqa: E402

MIN_MEMBERS = int(UNCERTAINTY_GATES["sufficient_members"]["threshold"]["min_members"])


def train_replica(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_eval: np.ndarray,
    seed: int,
    *,
    rf_only: bool = False,
) -> np.ndarray:
    """One independently seeded, independently resampled ensemble member.

    Returns its (n_eval, 3) probability matrix — the mean over its three base
    learners, matching what the production request path serves.
    """
    rng = np.random.default_rng(seed)
    draw = rng.integers(0, len(y_train), size=len(y_train))
    X_boot, y_boot = X_train[draw], y_train[draw]

    # Monkeypatched so `_instantiate` builds the PRODUCTION learner definitions
    # with this replica's seed. Rebuilding the learners here would let the spike
    # silently diverge from what the pipeline actually trains.
    original = trainer._TRAINING_SEED
    try:
        trainer._TRAINING_SEED = seed
        models = {
            name: trainer._instantiate(name, dict(cfg))
            for name, cfg in trainer._BASE_PARAMS.items()
            # rf_only isolates the variable under test. The default replica is a
            # 3-learner stack while the incumbent basis is trees inside a single
            # RandomForest, so the headline comparison moves BOTH member
            # independence and member composition at once. Restricting to
            # random_forest changes only independence, and any effect that
            # survives is attributable to it rather than to learner diversity.
            if not rf_only or name == "random_forest"
        }
    finally:
        trainer._TRAINING_SEED = original

    for model in models.values():
        model.fit(X_boot, y_boot)
    return np.mean([m.predict_proba(X_eval) for m in models.values()], axis=0)


def run_ladder(ladder: List[int], *, seed_base: int, rf_only: bool = False) -> int:
    """Evaluate every member count in one pass, training max(ladder) replicas once.

    Each count is scored on a prefix of the same replica set, so the ladder is
    nested rather than independent — which is the point: it isolates the effect
    of member count from the effect of seed choice, and costs one training run
    instead of len(ladder).
    """
    ladder = sorted({n for n in ladder if n >= MIN_MEMBERS})
    if not ladder:
        print(f"ladder needs at least one value >= {MIN_MEMBERS}")
        return 2
    top = ladder[-1]

    dataset = build_dataset(load_matches(_BACKEND_ROOT / "data" / "cache"))
    print(f"Member-count ladder {ladder}, seed base {seed_base}. Pre-declared and "
          f"reported in full.\n")

    per_n: Dict[int, List[Dict[str, float]]] = {n: [] for n in ladder}
    trees_rows: List[Dict[str, float]] = []
    started = time.time()

    for holdout in iter_league_holdouts(dataset, _BACKEND_ROOT, _LEAGUE_SLUGS):
        tree_eval = _score(holdout.models_dict, holdout.X_eval, holdout.y_eval)
        gap_t, _, skill_t = association(
            tree_eval["u_epi"], tree_eval["rps"], holdout.rps_ref
        )
        trees_rows.append({"gap": gap_t, "skill": skill_t})
        del tree_eval
        gc.collect()

        members = [
            train_replica(
                holdout.X_train, holdout.y_train, holdout.X_eval,
                seed=seed_base + r, rf_only=rf_only,
            )
            for r in range(top)
        ]
        stacked = np.stack(members, axis=0)
        for n in ladder:
            prefix = stacked[:n]
            u_epi = np.array(
                [dispersion_from_members(list(prefix[:, i, :])).epistemic
                 for i in range(holdout.n_eval)],
                dtype=np.float64,
            )
            gap, _, skill = association(
                u_epi, rps_rows(prefix.mean(axis=0), holdout.y_eval), holdout.rps_ref
            )
            per_n[n].append({"gap": gap, "skill": skill, "u": float(u_epi.mean())})
        print(f"  {holdout.league} done ({time.time() - started:.0f}s)")
        del members, stacked
        gc.collect()

    total = len(trees_rows)
    if not total:
        print("no league met the evidence floor — nothing measured")
        return 1

    print(f"\n{'members':>8} {'mean gap':>10} {'mean skill':>11} {'mean u_epi':>11} "
          f"{'gap>0':>7} {'skill>0':>8}")
    print("-" * 60)
    print(f"{'trees':>8} {np.mean([r['gap'] for r in trees_rows]):>+10.4f} "
          f"{np.mean([r['skill'] for r in trees_rows]):>+11.4f} {'-':>11} "
          f"{sum(1 for r in trees_rows if r['gap'] > 0):>4}/{total} "
          f"{sum(1 for r in trees_rows if r['skill'] > 0):>5}/{total}")
    for n in ladder:
        rows = per_n[n]
        print(f"{n:>8} {np.mean([r['gap'] for r in rows]):>+10.4f} "
              f"{np.mean([r['skill'] for r in rows]):>+11.4f} "
              f"{np.mean([r['u'] for r in rows]):>11.4f} "
              f"{sum(1 for r in rows if r['gap'] > 0):>4}/{total} "
              f"{sum(1 for r in rows if r['skill'] > 0):>5}/{total}")
    print(f"\nelapsed {time.time() - started:.0f}s")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--replicas", type=int, default=5,
        help="independently seeded ensembles per league (spike default 5)",
    )
    parser.add_argument(
        "--ladder", type=str, default="",
        help=(
            "comma-separated member counts to evaluate in ONE pass, e.g. 3,5,10,20,30. "
            "Trains max(ladder) replicas once per league and scores each count as a "
            "prefix of them. Declare the whole ladder up front and report all of it — "
            "raising N until the result passes is goalpost-moving, a monotone trend "
            "across a pre-declared ladder is evidence."
        ),
    )
    parser.add_argument(
        "--rf-only", action="store_true",
        help=(
            "replicas use random_forest alone. Isolates member INDEPENDENCE from "
            "member COMPOSITION: the default 3-learner replica differs from the "
            "incumbent tree basis in both respects at once."
        ),
    )
    parser.add_argument(
        "--seed-base", type=int, default=1_000,
        help="first replica seed; vary it to confirm a result is not seed-luck",
    )
    args = parser.parse_args()
    if args.ladder:
        return run_ladder(
            [int(v) for v in args.ladder.split(",")],
            seed_base=args.seed_base, rf_only=args.rf_only,
        )
    if args.replicas < MIN_MEMBERS:
        print(f"--replicas must be >= {MIN_MEMBERS} (sufficient_members floor)")
        return 2

    dataset = build_dataset(load_matches(_BACKEND_ROOT / "data" / "cache"))

    print(f"error_association under two member bases  (N={args.replicas} replicas)")
    print("  trees = ~300 bootstrap trees inside the shipped RandomForest (incumbent)")
    print("  deep  = N independently seeded + resampled RF+XGB+LGBM stacks (spike)")
    print("gap>0 is what the gate wants; skill = gap - base-rate control.\n")

    header = (
        f"{'league':11} {'n':>4} | {'gap_trees':>9} {'skill_trees':>11} "
        f"{'u_epi_tr':>8} | {'gap_deep':>9} {'skill_deep':>10} {'u_epi_dp':>8}"
    )
    print(header)
    print("-" * len(header))

    rows: List[Dict[str, float]] = []
    started = time.time()
    for holdout in iter_league_holdouts(dataset, _BACKEND_ROOT, _LEAGUE_SLUGS):
        # --- incumbent basis: bootstrap trees within the shipped forest -------
        tree_eval = _score(holdout.models_dict, holdout.X_eval, holdout.y_eval)
        gap_t, _, skill_t = association(
            tree_eval["u_epi"], tree_eval["rps"], holdout.rps_ref
        )
        u_epi_trees = float(tree_eval["u_epi"].mean())
        del tree_eval
        gc.collect()

        # --- spike basis: independently seeded, independently resampled ------
        members = [
            train_replica(
                holdout.X_train, holdout.y_train, holdout.X_eval,
                seed=args.seed_base + r, rf_only=args.rf_only,
            )
            for r in range(args.replicas)
        ]
        stacked = np.stack(members, axis=0)          # (R, n_eval, 3)
        u_epi_deep = np.array(
            [dispersion_from_members(list(stacked[:, i, :])).epistemic
             for i in range(holdout.n_eval)],
            dtype=np.float64,
        )
        gap_d, _, skill_d = association(
            u_epi_deep,
            rps_rows(stacked.mean(axis=0), holdout.y_eval),
            holdout.rps_ref,
        )

        print(
            f"{holdout.league:11} {holdout.n_eval:>4} | {gap_t:>+9.4f} "
            f"{skill_t:>+11.4f} "
            f"{u_epi_trees:>8.4f} | {gap_d:>+9.4f} {skill_d:>+10.4f} "
            f"{float(u_epi_deep.mean()):>8.4f}"
        )
        rows.append({
            "gap_t": gap_t, "skill_t": skill_t, "u_t": u_epi_trees,
            "gap_d": gap_d, "skill_d": skill_d, "u_d": float(u_epi_deep.mean()),
        })
        del members, stacked
        gc.collect()

    if not rows:
        print("no league met the evidence floor — nothing measured")
        return 1

    print("-" * len(header))
    mean = {k: float(np.mean([r[k] for r in rows])) for k in rows[0]}
    print(
        f"{'MEAN':11} {'':>4} | {mean['gap_t']:>+9.4f} {mean['skill_t']:>+11.4f} "
        f"{mean['u_t']:>8.4f} | {mean['gap_d']:>+9.4f} {mean['skill_d']:>+10.4f} "
        f"{mean['u_d']:>8.4f}"
    )

    gate_pass = sum(1 for r in rows if r["gap_d"] > 0.0)
    skill_pass = sum(1 for r in rows if r["skill_d"] > 0.0)
    was = sum(1 for r in rows if r["skill_t"] > 0.0)
    n = len(rows)
    print(f"\nincumbent trees : gap>0 in {sum(1 for r in rows if r['gap_t'] > 0)}/{n}, "
          f"skill>0 in {was}/{n}")
    print(f"independent deep: gap>0 in {gate_pass}/{n}, skill>0 in {skill_pass}/{n}")
    print(f"mean epistemic magnitude: trees {mean['u_t']:.4f} -> deep {mean['u_d']:.4f} "
          f"({mean['u_d'] / mean['u_t']:.2f}x)" if mean["u_t"] else "")
    if skill_pass == n:
        print("\nVERDICT: reversal FLIPPED under independent seeding in every league.")
    elif skill_pass > was:
        print(f"\nVERDICT: partial — {skill_pass}/{n} leagues flipped (was {was}/{n}). "
              "Not a pass; UNCERTAINTY_REQUIRES_ALL_GATES needs all of them.")
    else:
        print("\nVERDICT: reversal PERSISTS under independent seeding. The member "
              "basis is not the cause.")
    print(f"elapsed {time.time() - started:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
