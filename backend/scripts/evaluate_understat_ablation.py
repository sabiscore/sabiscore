#!/usr/bin/env python3
"""V23 Task 2 - Understat prior-only rolling ablation (Candidate-U).

Measures whether the prior-only Understat xG rolling family adds out-of-sample
information on top of the Tier-A market-independent baseline, and whether the
resulting Candidate-U reaches the frozen closing-market benchmark (Gate 7), across
two consecutive rolling-origin seasons (2024/25 and 2025/26) and against both the
mixed-book and Pinnacle-only closing cohorts.

MEASURE-ONLY. Writes exactly one report (reports/research/v21-understat-ablation.json)
holding only values this script computes. It never edits active_generation.json,
certification_state, promotion_state, a threshold or a frozen protocol. A measured
win is research evidence; promotion additionally requires the full gate suite and
the live C6 milestone, neither satisfied here, so the incumbent v5_phase7 stays
ACTIVE_FAIL_CLOSED regardless of this result.

Anti-fabrication: the committed corpus carries xG for/against and goals only. The
observable rolling family is xG-for, xG-against and the xG-derived finishing
efficiency. xA, true (shot-count) shot efficiency and xPTS are NOT in the corpus
and are reported as explicit data gaps, never filled.

Run:
    cd backend && PYTHONPATH=. python scripts/evaluate_understat_ablation.py
    cd backend && PYTHONPATH=. python scripts/evaluate_understat_ablation.py --audit-join
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = BACKEND_ROOT.parent / "reports"
SOURCES_DIR = BACKEND_ROOT / "data" / "processed" / "v4_sources"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts._resource_guard import ResourceGuard  # noqa: E402
from scripts.evaluate_v21_tier_a_candidates import (  # noqa: E402
    _score,
    _week_cluster_ci,
    extract_features,
    load_all_fixtures,
    rps_3class,
)
from src.data.understat_corpus import load_corpus_matches  # noqa: E402
from src.features.understat_join import (  # noqa: E402
    CORPUS_UNAVAILABLE_FAMILIES,
    ROLLING_WINDOW,
    UNDERSTAT_ROLLING_FEATURES,
    build_join_index,
    compute_prior_rolling,
    load_team_aliases,
    understat_features_for_fixture,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("understat_ablation")

TIER_A: list[str] = ["elo_diff", "rest_diff", "form_diff", "attack_defense_diff"]
CANDIDATE_U: list[str] = TIER_A + UNDERSTAT_ROLLING_FEATURES

# Rolling-origin splits: train on everything before the calibration season, calibrate
# on the season immediately before the evaluation season, evaluate on the eval season.
# This keeps calibration independent of the untouched evaluation season (V21 sec 19).
SPLITS: list[dict[str, Any]] = [
    {"name": "2425", "train": {"1920", "2021", "2122", "2223"}, "cal": {"2324"}, "eval": {"2425"}},
    {"name": "2526", "train": {"1920", "2021", "2122", "2223", "2324"}, "cal": {"2425"}, "eval": {"2526"}},
]
ECE_TOLERANCE: float = 0.005  # a candidate may not be promoted if it degrades ECE beyond this


def _attach_understat(data: list[dict[str, Any]]) -> dict[str, Any]:
    """Join prior-only Understat rolling features onto each Tier-A feature row.

    Sets ``d[feature]`` for every covered row (so the matrix builder reads them
    uniformly) and ``d["_covered"]`` when a unique Understat match with full
    ``window`` history exists. Returns coverage diagnostics.
    """
    corpus = load_corpus_matches(SOURCES_DIR)
    rolling = compute_prior_rolling(corpus, window=ROLLING_WINDOW)
    index = build_join_index(corpus)
    aliases = load_team_aliases()

    per_season_total: dict[str, int] = defaultdict(int)
    per_season_joined: dict[str, int] = defaultdict(int)
    per_season_covered: dict[str, int] = defaultdict(int)
    for d in data:
        season = d["season"]
        per_season_total[season] += 1
        feats = understat_features_for_fixture(d, index, rolling, aliases)
        if feats is None:
            d["_covered"] = False
            continue
        per_season_joined[season] += 1
        if any(bool(np.isnan(float(v))) for v in feats.values()):
            d["_covered"] = False
            continue
        for name, value in feats.items():
            d[name] = float(value)
        d["_covered"] = True
        per_season_covered[season] += 1

    return {
        "corpus_matches": int(len(corpus)),
        "corpus_leagues": sorted(corpus["sabi_league"].str.upper().unique().tolist()),
        "corpus_seasons": sorted(int(s) for s in corpus["sabi_season"].unique().tolist()),
        "aliases_loaded": len(aliases),
        "per_season": {
            s: {
                "fixtures": per_season_total[s],
                "joined": per_season_joined.get(s, 0),
                "covered_full_history": per_season_covered.get(s, 0),
            }
            for s in sorted(per_season_total)
        },
    }


def _matrix(rows: list[dict[str, Any]], cols: list[str]) -> np.ndarray:
    return np.array([[float(d[c]) for c in cols] for d in rows], dtype=np.float64)


def _fit_calibrate_predict(
    train_rows: list[dict[str, Any]],
    cal_rows: list[dict[str, Any]],
    eval_rows: list[dict[str, Any]],
    cols: list[str],
) -> list[tuple[float, float, float]]:
    """Fit an LR on train, isotonic-calibrate per class on cal, predict on eval.

    The calibrator sees only the calibration rows; the evaluation rows are never
    used for fitting (no leakage).
    """
    y_train = [d["outcome"] for d in train_rows]
    clf = LogisticRegression(max_iter=1000, solver="lbfgs")
    clf.fit(_matrix(train_rows, cols), y_train)

    raw_cal = clf.predict_proba(_matrix(cal_rows, cols))
    y_cal = [d["outcome"] for d in cal_rows]
    raw_eval = clf.predict_proba(_matrix(eval_rows, cols))

    iso_eval = np.zeros_like(raw_eval)
    for c in range(3):
        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(raw_cal[:, c], [1.0 if y == c else 0.0 for y in y_cal])
        iso_eval[:, c] = iso.transform(raw_eval[:, c])
    row_sums = np.sum(iso_eval, axis=1, keepdims=True)
    row_sums[row_sums <= 0.0] = 1.0
    iso_eval = iso_eval / row_sums
    return [tuple(iso_eval[i]) for i in range(len(eval_rows))]


def _paired_vs(
    cand_rps: np.ndarray,
    other_rps: np.ndarray,
    dates: list[Any],
    market_rps: float | None = None,
    candidate_rps: float | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ci = _week_cluster_ci(cand_rps - other_rps, dates)
    if market_rps is not None:
        ci["reference_rps"] = float(market_rps)
    if candidate_rps is not None:
        ci["candidate_rps"] = float(candidate_rps)
    if extra:
        ci.update(extra)
    return ci


def _evaluate_split(split: dict[str, Any], data: list[dict[str, Any]]) -> dict[str, Any]:
    train = [d for d in data if d["season"] in split["train"]]
    cal = [d for d in data if d["season"] in split["cal"]]
    eval_all = [d for d in data if d["season"] in split["eval"] and d["close_devig"] is not None]

    covered_train = [d for d in train if d["_covered"]]
    covered_cal = [d for d in cal if d["_covered"]]
    covered_eval = [d for d in eval_all if d["_covered"]]

    if len(covered_eval) < 50 or len(covered_train) < 200 or len(covered_cal) < 50:
        return {
            "status": "INSUFFICIENT_COVERED_SAMPLE",
            "covered_train": len(covered_train),
            "covered_cal": len(covered_cal),
            "covered_eval": len(covered_eval),
        }

    y_eval = [d["outcome"] for d in covered_eval]
    dates = [d["date"] for d in covered_eval]

    # Like-for-like: both models scored on the identical covered-eval fixtures.
    base_preds = _fit_calibrate_predict(train, cal, covered_eval, TIER_A)
    cand_preds = _fit_calibrate_predict(covered_train, covered_cal, covered_eval, CANDIDATE_U)

    base_score = _score(base_preds, y_eval)
    cand_score = _score(cand_preds, y_eval)

    base_rps = np.array([rps_3class(base_preds[i], y_eval[i]) for i in range(len(y_eval))])
    cand_rps = np.array([rps_3class(cand_preds[i], y_eval[i]) for i in range(len(y_eval))])
    close_rps = np.array([rps_3class(d["close_devig"], d["outcome"]) for d in covered_eval])

    # Incremental value of the Understat family over the Tier-A baseline.
    vs_baseline = _paired_vs(
        cand_rps, base_rps, dates,
        candidate_rps=float(np.mean(cand_rps)),
        market_rps=float(np.mean(base_rps)),
        extra={"comparison": "candidate_u_minus_tier_a_baseline"},
    )

    # Candidate-U vs the closing market, mixed cohort.
    vs_close_mixed = _paired_vs(
        cand_rps, close_rps, dates,
        candidate_rps=float(np.mean(cand_rps)),
        market_rps=float(np.mean(close_rps)),
        extra={
            "comparison": "candidate_u_minus_closing_market",
            "cohort": "mixed_book",
            "close_book_counts": {
                book: sum(1 for d in covered_eval if d["close_book"] == book)
                for book in ("pinnacle", "bet365")
            },
        },
    )

    # Candidate-U vs the closing market, Pinnacle-only cohort.
    pinn = [i for i, d in enumerate(covered_eval) if d["close_book"] == "pinnacle"]
    if pinn:
        vs_close_pinnacle = _paired_vs(
            cand_rps[pinn], close_rps[pinn], [dates[i] for i in pinn],
            candidate_rps=float(np.mean(cand_rps[pinn])),
            market_rps=float(np.mean(close_rps[pinn])),
            extra={"comparison": "candidate_u_minus_closing_market", "cohort": "pinnacle_only"},
        )
    else:
        vs_close_pinnacle = {"n": 0, "cohort": "pinnacle_only", "note": "no Pinnacle closes in covered cohort"}

    # Baseline vs close, for reference (does the Understat family even move us toward the close?).
    base_vs_close_mixed = _paired_vs(
        base_rps, close_rps, dates,
        candidate_rps=float(np.mean(base_rps)),
        market_rps=float(np.mean(close_rps)),
        extra={"comparison": "tier_a_baseline_minus_closing_market", "cohort": "mixed_book"},
    )

    def _gate(ci: dict[str, Any]) -> str:
        bounds = ci.get("ci_98_33")
        if not bounds:
            return "UNEVALUATED"
        return "PASS" if bounds[1] < 0.0 else "FAIL"

    return {
        "status": "MEASURED",
        "population": {
            "covered_train": len(covered_train),
            "covered_cal": len(covered_cal),
            "covered_eval": len(covered_eval),
            "eval_with_close": len(eval_all),
        },
        "scores": {"tier_a_baseline": base_score, "candidate_u": cand_score},
        "ece_delta_candidate_minus_baseline": float(cand_score["ece"] - base_score["ece"]),
        "benchmarks": {
            "candidate_u_vs_tier_a_baseline": vs_baseline,
            "candidate_u_vs_close_mixed": vs_close_mixed,
            "candidate_u_vs_close_pinnacle": vs_close_pinnacle,
            "tier_a_baseline_vs_close_mixed": base_vs_close_mixed,
        },
        "gates": {
            "candidate_beats_baseline": _gate(vs_baseline),
            "candidate_beats_close_mixed": _gate(vs_close_mixed),
            "candidate_beats_close_pinnacle": _gate(vs_close_pinnacle),
        },
    }


def _input_hashes() -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(SOURCES_DIR.glob("understat_matches_*.parquet")):
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    alias_path = BACKEND_ROOT / "src" / "services" / "understat" / "team_aliases.json"
    if alias_path.exists():
        hashes[alias_path.name] = hashlib.sha256(alias_path.read_bytes()).hexdigest()
    return hashes


def run_ablation() -> dict[str, Any]:
    logger.info("Loading fixtures and Tier-A features...")
    fixtures = load_all_fixtures()
    data = extract_features(fixtures)
    coverage = _attach_understat(data)
    logger.info("Understat coverage: %s", coverage["per_season"])

    splits: dict[str, Any] = {}
    for split in SPLITS:
        logger.info("Evaluating split eval=%s ...", split["name"])
        splits[split["name"]] = {
            "train_seasons": sorted(split["train"]),
            "cal_season": sorted(split["cal"]),
            "eval_season": sorted(split["eval"]),
            **_evaluate_split(split, data),
        }

    measured = [s for s in splits.values() if s.get("status") == "MEASURED"]
    beats_close_all = bool(measured) and all(
        s["gates"]["candidate_beats_close_mixed"] == "PASS"
        and s["gates"]["candidate_beats_close_pinnacle"] == "PASS"
        for s in measured
    )
    ece_ok_all = all(s["ece_delta_candidate_minus_baseline"] <= ECE_TOLERANCE for s in measured)
    promote = bool(measured) and len(measured) >= 2 and beats_close_all and ece_ok_all

    git_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=BACKEND_ROOT, capture_output=True, text=True
    ).stdout.strip()

    result = {
        "document": "SABISCORE_V23_UNDERSTAT_ROLLING_ABLATION",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": git_sha or None,
        "command": "python backend/scripts/evaluate_understat_ablation.py",
        "input_sha256": _input_hashes(),
        "candidate": {
            "track": "Candidate-U",
            "model": "multinomial logistic regression + per-class isotonic calibration (fit on the calibration season)",
            "features": CANDIDATE_U,
            "baseline_features": TIER_A,
            "understat_rolling_features": UNDERSTAT_ROLLING_FEATURES,
            "rolling_window": ROLLING_WINDOW,
            "market_inputs": False,
            "serialized": False,
        },
        "corpus_feature_coverage": {
            "observed_families": ["xg_for", "xg_against", "finishing_efficiency_goals_over_xg"],
            "corpus_unavailable_families": list(CORPUS_UNAVAILABLE_FAMILIES),
            "note": (
                "The committed Understat corpus carries xG for/against and goals only. "
                "xA, true shot-count shot efficiency and xPTS are not present and are "
                "reported here as data gaps rather than fabricated."
            ),
        },
        "join": {
            "key": "(canonical league, kickoff date +/- 1 day, home_goals, away_goals) narrowed to a unique match by both-team name agreement",
            "alias_table": "backend/src/services/understat/team_aliases.json",
            **coverage,
        },
        "splits": splits,
        "decision": {
            "promote_candidate_u": promote,
            "rule": (
                "promote only if candidate RPS < closing RPS with a 98.33% ISO-week CI "
                "strictly below 0 on BOTH the mixed and Pinnacle cohorts, across >=2 "
                "consecutive seasons, with no ECE degradation beyond "
                f"{ECE_TOLERANCE}"
            ),
            "beats_close_all_splits": beats_close_all,
            "ece_non_degrading_all_splits": ece_ok_all,
            "outcome": "PROMOTE" if promote else "RETAIN_INCUMBENT",
            "incumbent": "v5_phase7",
            "certifies": False,
            "why_not_certifying": (
                "Gate 7 is one of several gates; promotion also requires the frozen "
                "60-gate suite and the live C6 milestone (N_live < 200). This script "
                "measures only; it never writes active_generation.json."
            ),
        },
    }
    out = REPORTS_ROOT / "research" / "v21-understat-ablation.json"
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    logger.info("Wrote %s", out)
    return result


def audit_join() -> None:
    """Print per-season join coverage (no report written). Use to maintain the alias table."""
    fixtures = load_all_fixtures()
    data = extract_features(fixtures)
    coverage = _attach_understat(data)
    print(json.dumps({"join_audit": coverage}, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Understat rolling ablation (Candidate-U).")
    parser.add_argument("--audit-join", action="store_true", help="Print join coverage and exit.")
    args = parser.parse_args()
    if args.audit_join:
        audit_join()
        return
    result = run_ablation()
    logger.info("Decision: %s", result["decision"]["outcome"])


if __name__ == "__main__":
    # Heavy job (LR fits + isotonic + multiple 10,000-replicate ISO-week bootstraps):
    # single-lane under the 3072 MB workstation ceiling.
    with ResourceGuard():
        main()
