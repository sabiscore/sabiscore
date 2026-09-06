#!/usr/bin/env python3
"""Paired block-bootstrap CI on the candidate-minus-market RPS difference.

Why this exists
---------------
`certification_policy.PROMOTION_GATES["market_baseline"]` is a point comparison:
candidate mean RPS < market mean RPS, per league. It has no notion of how large
the sampling error on that comparison is. On the 2526 holdout the EPL margin is
0.0005 RPS over roughly 375 fixtures, which is small enough that "the candidate
beats the market in EPL" and "the candidate is indistinguishable from the market
in EPL" are both consistent with the same number.

This script answers which. It resamples the *paired* per-match difference, so
the question asked is "is candidate-minus-market reliably below zero", not "do
two independently-estimated means happen to be ordered this way".

Pairing under resampling is the whole point
-------------------------------------------
`block_bootstrap_ci` resamples row blocks and re-scores one probability matrix.
Passing candidate and market through it separately would draw *different* blocks
for each, destroying the pairing and inflating the interval by roughly the sum
of two independent variances instead of the variance of the difference.

So both matrices are stacked column-wise into one (n, 6) array and the metric
function splits them back apart. The bootstrap therefore draws one set of block
indices and applies it to both heads — the same fixtures, on every replicate.
This needs no change to `block_bootstrap_ci`.

Reading the result
------------------
RPS is lower-is-better, so a genuine candidate edge is a *negative* difference.
  ci_upper <  0  -> the candidate beats the market by more than sampling error
  ci spans   0   -> indistinguishable; the point estimate's sign is not evidence
  ci_lower >  0  -> the market beats the candidate

⚠️ Per-league intervals here are marginal, not simultaneous. Six leagues are
tested, so the family-wise error rate is well above the nominal 5%; a Bonferroni
column is reported alongside. Selecting the best-looking league after seeing all
six and then quoting its marginal interval is the multiple-comparison error this
column exists to prevent.

Usage:
    PYTHONPATH=. python scripts/compare_candidate_vs_incumbent.py \\
        --candidate-schema apex_v5_66 \\
        --per-match-output models/candidate/per_match_v10_gate7_hpo.npz \\
        --output models/candidate/comparison_report_v10_gate7_hpo.json

    PYTHONPATH=. python scripts/bootstrap_market_edge_ci.py \\
        --per-match models/candidate/per_match_v10_gate7_hpo.npz
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict

import numpy as np

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from scripts.train_on_real_matches import (  # noqa: E402
    ranked_probability_score as _rps_vectorized,
)
from src.models.evaluation.metrics import (  # noqa: E402
    block_bootstrap_ci,
    ranked_probability_score as _rps_scalar,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("bootstrap-ci")

N_CLASSES = 3


def _assert_scorers_agree() -> None:
    """Two RPS implementations live in this repository; use the authoritative one.

    `train_on_real_matches.ranked_probability_score` is vectorized and is what
    produced both the candidate figures and `baseline_rps_market`, so it is what
    this script must reuse -- scoring the comparison with a second
    implementation would make any disagreement look like a real effect. The
    scalar version in `models/evaluation/metrics` is checked against it here
    rather than assumed equal.
    """
    rng = np.random.default_rng(0)
    probs = rng.dirichlet([1.0, 1.0, 1.0], size=256)
    y = rng.integers(0, N_CLASSES, 256)
    scalar = float(np.mean([_rps_scalar(int(t), row) for t, row in zip(y, probs)]))
    if abs(_rps_vectorized(y, probs) - scalar) > 1e-12:
        raise AssertionError("the two RPS implementations disagree; refusing to score")


def _mean_rps(y_true: np.ndarray, probs: np.ndarray) -> float:
    """Mean RPS over rows, matching reports/evaluation/metric-contract.json."""
    return float(_rps_vectorized(y_true, probs))


def _paired_difference(y_true: np.ndarray, stacked: np.ndarray) -> float:
    """candidate RPS - market RPS on whichever rows the bootstrap drew."""
    return _mean_rps(y_true, stacked[:, :N_CLASSES]) - _mean_rps(
        y_true, stacked[:, N_CLASSES:]
    )


def _bonferroni_ci(
    y: np.ndarray, stacked: np.ndarray, n_leagues: int, **kwargs: Any
) -> Dict[str, Any]:
    """Same interval at a family-wise-corrected level for n_leagues tests."""
    return block_bootstrap_ci(
        y, stacked, _paired_difference, ci_level=1.0 - (0.05 / n_leagues), **kwargs
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-match", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--head",
        choices=("candidate", "incumbent"),
        default="candidate",
        help=(
            "Which head to compare against the market. `incumbent` asks the "
            "same question of the generation actually serving today."
        ),
    )
    parser.add_argument("--n-bootstrap", type=int, default=10_000)
    parser.add_argument("--block-size", type=int, default=10)
    parser.add_argument("--rng-seed", type=int, default=42)
    args = parser.parse_args()

    _assert_scorers_agree()

    data = np.load(args.per_match, allow_pickle=False)
    leagues = sorted({k.split("__")[0] for k in data.files if "__" in k})
    if not leagues:
        logger.error("%s contains no per-league arrays", args.per_match)
        return 1

    schema = str(data["candidate_schema"]) if "candidate_schema" in data else "unknown"
    season = str(data["holdout_season"]) if "holdout_season" in data else "unknown"
    logger.info(
        "candidate schema %s | holdout %s | %d leagues | %d replicates, block=%d",
        schema, season, len(leagues), args.n_bootstrap, args.block_size,
    )

    report: Dict[str, Any] = {
        "candidate_schema": schema,
        "holdout_season": season,
        "head": args.head,
        "metric": f"mean_rps_{args.head}_minus_market",
        "lower_is_better": True,
        "n_bootstrap": args.n_bootstrap,
        "block_size": args.block_size,
        "rng_seed": args.rng_seed,
        "family_size": len(leagues),
        "leagues": {},
    }

    header = (
        f"{'league':<12} {'n':>5} {'cand':>8} {'market':>8} {'diff':>9} "
        f"{'95% CI':>20} {'verdict':<22} {'Bonferroni CI':>20}"
    )
    logger.info("\n%s", header)
    logger.info("-" * len(header))

    for league in leagues:
        y = data[f"{league}__y"].astype(np.int64)
        cand = data[f"{league}__{args.head}"].astype(np.float64)
        market = data[f"{league}__market"].astype(np.float64)
        stacked = np.hstack([cand, market])

        kwargs = dict(
            n_bootstrap=args.n_bootstrap,
            block_size=args.block_size,
            rng_seed=args.rng_seed,
        )
        ci = block_bootstrap_ci(y, stacked, _paired_difference, **kwargs)
        bonf = _bonferroni_ci(y, stacked, len(leagues), **kwargs)

        lo, hi = ci["ci_lower"], ci["ci_upper"]
        # block_bootstrap_ci swallows a failing replicate with a bare
        # `except Exception: continue`. That is the shape that made
        # walk_forward_validate report "no valid folds" forever while the real
        # cause was a TypeError. A short count here means replicates are being
        # dropped, so it is an error rather than a quietly narrower interval.
        if ci["n_bootstrap"] != args.n_bootstrap:
            logger.error(
                "%s: only %d of %d replicates scored -- metric_fn is raising",
                league, ci["n_bootstrap"], args.n_bootstrap,
            )
            return 1
        if lo is None or hi is None:
            verdict = "no replicate scored"
        elif hi < 0:
            verdict = f"{args.head.upper()} BEATS MARKET"
        elif lo > 0:
            verdict = f"market beats {args.head}"
        else:
            verdict = "indistinguishable"

        report["leagues"][league] = {
            "n": int(len(y)),
            f"{args.head}_rps": round(_mean_rps(y, cand), 6),
            "market_rps": round(_mean_rps(y, market), 6),
            "paired_difference": ci["point_estimate"],
            "ci_95": {"lower": lo, "upper": hi},
            "ci_bonferroni": {
                "level": round(bonf["ci_level"], 4),
                "lower": bonf["ci_lower"],
                "upper": bonf["ci_upper"],
            },
            "excludes_zero": bool(lo is not None and hi is not None and (hi < 0 or lo > 0)),
            "verdict": verdict,
        }
        logger.info(
            "%-12s %5d %8.4f %8.4f %+9.5f  [%+.4f,%+.4f] %-22s [%+.4f,%+.4f]",
            league, len(y), _mean_rps(y, cand), _mean_rps(y, market),
            ci["point_estimate"], lo, hi, verdict,
            bonf["ci_lower"], bonf["ci_upper"],
        )

    beating = [
        lg for lg, r in report["leagues"].items()
        if r["verdict"] == f"{args.head.upper()} BEATS MARKET"
    ]
    report["leagues_beating_market_with_ci_excluding_zero"] = beating
    report["market_baseline_gate_supported_by_ci"] = len(beating) == len(leagues)

    logger.info("")
    logger.info(
        "Leagues where the 95%% CI excludes zero in the %s's favour: %d of %d%s",
        args.head,
        len(beating), len(leagues), f" ({', '.join(beating)})" if beating else "",
    )

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        logger.info("report -> %s", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
