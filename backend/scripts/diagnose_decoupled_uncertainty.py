#!/usr/bin/env python3
"""Measure whether aleatoric-residualized epistemic uncertainty would satisfy
`error_association`, per league (ADR 0009 Addendum 3 / docs/DEBT.md item 50).

WHAT THIS ANSWERS
-----------------
`UNCERTAINTY_GATES["error_association"]` fails on raw epistemic in all five
scoreable leagues, and ADR 0009 Addendum 3 attributes most of that to an
aleatoric confound. The proposed remedy is to measure the association on the
*residual* `u_epi - f(u_alea)` within aleatoric strata instead. Before anyone
can decide whether to authorize that change to the frozen policy, somebody has
to measure whether it actually holds. That is all this script does.

⚠️ **THIS SCRIPT CERTIFIES NOTHING AND CHANGES NO GATE.** It writes no
artifacts and mutates no policy. `error_association` still measures raw
epistemic, still fails, and `MODEL_UNCERTAINTY_UNAVAILABLE` remains
unconditionally CRITICAL. Redefining the gate around this residual is a
deliberate, recorded authorization decision (APEX §23), and the whole point of
this script is to put real numbers in front of that decision rather than
assume them.

IN-SAMPLE vs OUT-OF-FOLD
------------------------
Both are reported, and the difference is the headline. Fitting `f` on the same
rows the residual is scored on decorrelates the residual from aleatoric *by
construction* on exactly that data, so an in-sample number is an upper bound
that partly measures the fit itself. The out-of-fold number fits `f` on
pre-holdout seasons and applies it to the holdout — disjoint data, the same
discipline `train_league()` uses for its calibration season. **Only the
out-of-fold column is evidence.**

Usage:
    PYTHONPATH=. python scripts/diagnose_decoupled_uncertainty.py
"""
from __future__ import annotations

import gc
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))
if str(_BACKEND_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT / "scripts"))

from src.models.ensemble_uncertainty import dispersion_from_members  # noqa: E402
from src.models.epistemic_residualizer import (  # noqa: E402
    MIN_FIT_ROWS,
    EpistemicResidualizer,
)
from src.models.evaluation.metrics import ranked_probability_score  # noqa: E402
from src.models.uncertainty_policy import UNCERTAINTY_EVIDENCE_FLOORS  # noqa: E402
from train_on_real_matches import build_dataset, load_matches  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger(__name__)

_LEAGUE_SLUGS = {
    "EPL": "epl",
    "LA_LIGA": "la_liga",
    "BUNDESLIGA": "bundesliga",
    "SERIE_A": "serie_a",
    "LIGUE_1": "ligue_1",
    "EREDIVISIE": "eredivisie",
}

#: Terciles, matching the stratification ADR 0009 Addendum 3 reported.
N_STRATA = 3
#: Below this a within-stratum rank correlation is noise.
MIN_STRATUM_ROWS = 30


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    """Rank correlation without a scipy dependency.

    scipy is not declared in requirements.txt (only numpy and scikit-learn are),
    and this codebase soft-imports it where used. Spearman is Pearson on ranks,
    so `np.corrcoef` over `argsort`-derived ranks is exact and dependency-free.
    Ties are averaged, matching scipy's default.
    """
    if x.size < 3:
        return float("nan")
    return float(np.corrcoef(_rank_average_ties(x), _rank_average_ties(y))[0, 1])


def _rank_average_ties(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(values.size, dtype=np.float64)
    ranks[order] = np.arange(values.size, dtype=np.float64)
    # Average ranks within tie groups so ties do not fabricate ordering.
    sorted_values = values[order]
    start = 0
    while start < sorted_values.size:
        stop = start + 1
        while stop < sorted_values.size and sorted_values[stop] == sorted_values[start]:
            stop += 1
        if stop - start > 1:
            ranks[order[start:stop]] = np.mean(ranks[order[start:stop]])
        start = stop
    return ranks


def _batched_members(models_dict: Dict[str, Any], X: np.ndarray) -> List[List[np.ndarray]]:
    """One `predict_proba` per tree over the whole matrix (vectorised)."""
    trees = getattr(models_dict.get("random_forest"), "estimators_", None)
    if not trees:
        return [[] for _ in range(X.shape[0])]
    stacked = np.stack(
        [np.asarray(tree.predict_proba(X), dtype=np.float64) for tree in trees], axis=0
    )
    out: List[List[np.ndarray]] = []
    for row in range(X.shape[0]):
        rows = stacked[:, row, :]
        totals = rows.sum(axis=1)
        out.append([r / t for r, t in zip(rows, totals) if t > 0])
    return out


#: Rows scored per pass. `_batched_members` materialises ~300 small ndarrays
#: per row, so scoring 2,196 fit rows in one go allocates ~660k objects and
#: pushed peak RSS to 400MB — over this repo's 350MB lean-environment budget.
#: Chunking caps the transient allocation while still routing every row through
#: the production `dispersion_from_members`.
_SCORE_CHUNK_ROWS = 256


def _score(models_dict: Dict[str, Any], X: np.ndarray, y: np.ndarray) -> Dict[str, np.ndarray]:
    u_alea = np.empty(X.shape[0], dtype=np.float64)
    u_epi = np.empty(X.shape[0], dtype=np.float64)
    rps = np.empty(X.shape[0], dtype=np.float64)

    for start in range(0, X.shape[0], _SCORE_CHUNK_ROWS):
        stop = min(start + _SCORE_CHUNK_ROWS, X.shape[0])
        members = _batched_members(models_dict, X[start:stop])
        for offset, member_set in enumerate(members):
            row = start + offset
            result = dispersion_from_members(member_set)
            u_alea[row] = result.aleatoric
            u_epi[row] = result.epistemic
            rps[row] = ranked_probability_score(
                int(y[row]), list(np.mean(np.stack(member_set), axis=0))
            )
        del members
        gc.collect()

    return {"u_alea": u_alea, "u_epi": u_epi, "rps": rps}


def _stratified_correlations(
    u_alea: np.ndarray, u_epi_signal: np.ndarray, rps: np.ndarray
) -> Tuple[bool, List[Optional[float]], List[int]]:
    """corr(signal, RPS) inside each aleatoric tercile. Passes only if every
    stratum is strictly positive — an undersized or NaN stratum fails."""
    cuts = np.quantile(u_alea, np.linspace(0.0, 1.0, N_STRATA + 1)[1:-1])
    masks = [u_alea <= cuts[0]]
    for i in range(len(cuts) - 1):
        masks.append((u_alea > cuts[i]) & (u_alea <= cuts[i + 1]))
    masks.append(u_alea > cuts[-1])

    correlations: List[Optional[float]] = []
    counts: List[int] = []
    passed = True
    for mask in masks:
        count = int(mask.sum())
        counts.append(count)
        if count < MIN_STRATUM_ROWS:
            correlations.append(None)
            passed = False
            continue
        corr = _spearman(u_epi_signal[mask], rps[mask])
        correlations.append(None if np.isnan(corr) else corr)
        if np.isnan(corr) or corr <= 0.0:
            passed = False
    return passed, correlations, counts


def _fmt(correlations: List[Optional[float]]) -> str:
    return " ".join("  n/a  " if c is None else f"{c:+.3f}" for c in correlations)


def main() -> int:
    dataset = build_dataset(load_matches(_BACKEND_ROOT / "data" / "cache"))
    floor = int(UNCERTAINTY_EVIDENCE_FLOORS["min_validation_rows"])

    print("Aleatoric-residualized error_association — per league, terciles of u_alea")
    print("Only the OUT-OF-FOLD column is evidence; IN-SAMPLE is an upper bound.\n")
    print(f"{'league':12} {'n':>5}  {'raw epistemic':^23}  {'residual (in-sample)':^23}  "
          f"{'residual (out-of-fold)':^23}")
    print(f"{'':12} {'':>5}  {'S1     S2     S3':^23}  {'S1     S2     S3':^23}  "
          f"{'S1     S2     S3':^23}")

    verdicts: Dict[str, Dict[str, Any]] = {}
    for league, slug in _LEAGUE_SLUGS.items():
        artifact = _BACKEND_ROOT / "models" / f"{slug}_ensemble_v5_phase7.pkl"
        data = dataset.get(league)
        if not artifact.exists() or not data:
            print(f"{league:12} {'-':>5}  SKIP — artifact or corpus rows missing")
            continue

        raw = joblib.load(artifact)
        holdout_season = raw["model_metadata"]["holdout_season"]
        models_dict = raw["models"]

        seasons = np.asarray(data["seasons"])
        X_all = np.asarray(data["X_incumbent"], dtype=np.float64)
        y_all = np.asarray(data["y"])
        eval_mask = seasons == holdout_season
        fit_mask = ~eval_mask

        if int(eval_mask.sum()) < floor:
            print(f"{league:12} {int(eval_mask.sum()):>5}  SKIP — below the {floor}-row "
                  f"evidence floor in declared holdout {holdout_season}")
            del raw, models_dict
            gc.collect()
            continue

        evaluation = _score(models_dict, X_all[eval_mask], y_all[eval_mask])
        n_eval = evaluation["u_alea"].size

        raw_pass, raw_corr, counts = _stratified_correlations(
            evaluation["u_alea"], evaluation["u_epi"], evaluation["rps"]
        )

        in_sample = EpistemicResidualizer().fit_transform(
            evaluation["u_alea"], evaluation["u_epi"]
        )
        in_pass, in_corr, _ = _stratified_correlations(
            evaluation["u_alea"], in_sample, evaluation["rps"]
        )

        oof_pass: Optional[bool] = None
        oof_corr: List[Optional[float]] = [None] * (N_STRATA)
        if int(fit_mask.sum()) >= MIN_FIT_ROWS:
            fit_rows = _score(models_dict, X_all[fit_mask], y_all[fit_mask])
            residualizer = EpistemicResidualizer().fit(fit_rows["u_alea"], fit_rows["u_epi"])
            oof = residualizer.transform(evaluation["u_alea"], evaluation["u_epi"])
            oof_pass, oof_corr, _ = _stratified_correlations(
                evaluation["u_alea"], oof, evaluation["rps"]
            )
            del fit_rows

        print(f"{league:12} {n_eval:>5}  {_fmt(raw_corr):^23}  {_fmt(in_corr):^23}  "
              f"{_fmt(oof_corr):^23}")

        verdicts[league] = {
            "n_eval": n_eval,
            "stratum_counts": counts,
            "raw_pass": raw_pass,
            "in_sample_pass": in_pass,
            "out_of_fold_pass": oof_pass,
        }
        # Release this league's feature matrix as well as its artifact: the
        # dataset holds every league's rows simultaneously, and holding all of
        # them alongside a loaded ensemble is the other half of the memory bill.
        del raw, models_dict, evaluation, X_all, y_all
        dataset.pop(league, None)
        gc.collect()

    print()
    if not verdicts:
        print("No league met the evidence floor — nothing measured.")
        return 1

    for label, key in (
        ("raw epistemic (what the gate measures today)", "raw_pass"),
        ("residual, in-sample fit (upper bound, NOT evidence)", "in_sample_pass"),
        ("residual, out-of-fold fit (the real question)", "out_of_fold_pass"),
    ):
        passing = [lg for lg, v in verdicts.items() if v[key] is True]
        print(f"{label:52} {len(passing)}/{len(verdicts)} leagues pass"
              f"{'  ->  ' + ', '.join(sorted(passing)) if passing else ''}")

    print("\nA gate change requires ALL leagues passing out-of-fold, plus an explicit,")
    print("versioned authorization recorded against the frozen policy. This script")
    print("does not take that decision and has changed nothing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
