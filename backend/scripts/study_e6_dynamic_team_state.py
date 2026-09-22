"""Experiment E6 — dynamic team state (state-space vs fixed-K Elo).

Directive: `docs/PRODUCTION_EXECUTIVE_DIRECTIVE.md` §43 E6, §16 Stage 1-3,
§18, Rules 6/7/8/9.

    "Hypothesis: latent team strength changes faster than current Elo/rating
     representation. Candidate: lightweight state-space model."

The candidate is `src/features/dynamic_team_state.py` — a local-level
(random-walk) rating whose Kalman gain grows with the gap since a team last
played. It keeps the incumbent's expectation function byte-for-byte and is
calibrated in closed form so its STEADY-STATE gain equals the incumbent's
fixed K. The two arms therefore differ in exactly one thing: adaptivity to
staleness. That is the experiment.

Zero acquisition cost: every input is `backend/data/cache/fd_*.csv`, already
on disk. No API calls, no database, no feature-schema or artifact change.

PRE-DECLARED BEFORE ANY RESULT WAS SEEN (§18)
---------------------------------------------
Three tests, one family:

  H1  elo_diff                    vs  elo_diff + dynamic_diff
      — does the state-space strength estimate add beyond the incumbent?
  H2  elo_diff                    vs  elo_diff + dynamic_diff + dynamic_uncertainty
      — does the uncertainty channel, which Elo structurally cannot express,
        add anything further?
  H3  de-vigged market            vs  market + dynamic_diff
      — Rule 7: does it add beyond what the market already prices?

Multiple-testing protocol, fixed in advance: a finding counts as positive only
if its 95% paired block-bootstrap CI excludes zero AND the Bonferroni-adjusted
CI for a family of three (98.33%) also excludes zero. Both are computed and
reported for every test regardless of outcome, so the rule cannot be chosen
after the fact.

Decision rule (§51): PROMOTE only on a positive by the rule above. REJECT on a
tight null (CI narrow and centred on zero — positive evidence of absence).
HOLD on a wide null (consistent sign, underpowered).

WARM-UP, AND WHY IT MATTERS
---------------------------
Ratings are replayed over the ENTIRE corpus chronologically (7 seasons), but
scored only on the same 2223/2324 → 2425 window Portfolios B, E and F used.
Both arms therefore enter the evaluation window with mature state, and the
result stays comparable with the other three studies. Scoring a rating system
during its own burn-in would measure convergence speed, not information.

Usage
-----
    cd backend
    PYTHONPATH=. python scripts/study_e6_dynamic_team_state.py
"""

from __future__ import annotations

import importlib.util
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _incremental_value_harness import (  # noqa: E402
    devig,
    paired_rps_diff_bootstrap,
    run_incremental_value_study,
)

from src.core.config import settings  # noqa: E402
from src.features.dynamic_team_state import (  # noqa: E402
    DynamicTeamStateReplay,
    calibrate_observation_noise_scale,
)
from src.features.elo_replay import default_fast_elo_replay  # noqa: E402

_REPORT_DIR = _BACKEND_ROOT.parent / "reports" / "research"
_CACHE_DIR = _BACKEND_ROOT / "data" / "cache"
_TRAIN_SEASONS = ("2223", "2324")
_TEST_SEASON = "2425"
_FAMILY_SIZE = 3
#: Bonferroni for a family of three: 1 - 0.05/3.
_ADJUSTED_CI_LEVEL = 1.0 - (0.05 / _FAMILY_SIZE)


def _load_training_module() -> Any:
    """`scripts/train_on_real_matches.py` is not a package.

    Loaded by path — the same pattern `temporal_evaluation.py` and
    `tests/unit/test_calibration_selection.py` already use — so this study
    reuses that file's corpus loader and odds parser rather than writing a
    third copy of either.
    """
    spec = importlib.util.spec_from_file_location(
        "train_on_real_matches",
        Path(__file__).resolve().parent / "train_on_real_matches.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the training pipeline")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_rows() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Replay both rating systems over the whole corpus; return scored rows.

    A single chronological pass drives both arms, so neither can benefit from
    a different traversal order. Context is read BEFORE the update for both,
    so no match informs its own row.
    """
    training = _load_training_module()
    matches = training.load_matches(_CACHE_DIR)

    elo = default_fast_elo_replay()
    dynamic = DynamicTeamStateReplay(
        home_advantage=float(settings.elo_home_advantage),
        observation_noise_scale=calibrate_observation_noise_scale(
            k_elo=float(settings.elo_k_base)
        ),
    )

    rows: list[dict[str, Any]] = []
    elo_moves: list[float] = []
    dynamic_moves: list[float] = []
    gaps: list[int] = []
    skipped_self_play = 0
    without_odds = 0

    for match in matches:
        home, away = match["home"], match["away"]
        league, season, when = match["league"], match["season"], match["date"]
        if home == away:
            skipped_self_play += 1
            continue

        elo_ctx = elo.get_context(home, away, league, season)
        dyn_ctx = dynamic.get_context(home, away, league, when)

        odds = match.get("odds")
        if odds is None:
            without_odds += 1
        else:
            home_goals, away_goals = int(match["hg"]), int(match["ag"])
            outcome = (
                0 if home_goals > away_goals else (1 if home_goals == away_goals else 2)
            )
            rows.append(
                {
                    "league": league,
                    "season": season,
                    "date": when,
                    "outcome": outcome,
                    "market_probs": devig(*odds),
                    "elo_diff": elo_ctx.elo_difference,
                    "elo_momentum_cross": elo_ctx.elo_momentum_cross,
                    "dynamic_diff": dyn_ctx.strength_diff,
                    "dynamic_uncertainty": dyn_ctx.uncertainty,
                    "both_resolved": elo_ctx.resolved and dyn_ctx.resolved,
                }
            )

        # Stage 1 instrumentation: how far each arm actually moves per match,
        # and how stale the estimates are when it moves them.
        home_before = dyn_ctx.home_strength
        elo_home_before = elo_ctx.home_elo
        state = dynamic._state(home, league)  # noqa: SLF001 — diagnostic only
        if state.last_played is not None:
            observed = when.date() if isinstance(when, datetime) else when
            gaps.append(max((observed - state.last_played).days, 0))

        elo.update(home, away, league, season, int(match["hg"]), int(match["ag"]))
        dynamic.update(home, away, league, when, int(match["hg"]), int(match["ag"]))

        dynamic_moves.append(
            abs(
                dynamic.get_context(home, away, league, when).home_strength
                - home_before
            )
        )
        elo_moves.append(
            abs(elo.get_context(home, away, league, season).home_elo - elo_home_before)
        )

    descriptives = {
        "corpus_matches": len(matches),
        "scored_rows": len(rows),
        "skipped_self_play": skipped_self_play,
        "rows_without_parseable_odds": without_odds,
        "seasons": sorted({r["season"] for r in rows}),
        "leagues": sorted({r["league"] for r in rows}),
        # The control, measured rather than assumed: if these diverge the
        # study is confounded (see calibrate_observation_noise_scale).
        "mean_abs_rating_move": {
            "incumbent_elo": round(statistics.fmean(elo_moves), 3),
            "state_space": round(statistics.fmean(dynamic_moves), 3),
        },
        # Does the adaptivity mechanism ever actually fire? If almost every
        # gap is a routine 3-10 days, the two arms are near-identical in
        # practice and that is the honest explanation for any null.
        "days_since_last_played": {
            "n": len(gaps),
            "median": statistics.median(gaps) if gaps else None,
            "p90": (sorted(gaps)[int(0.90 * len(gaps))] if gaps else None),
            "p99": (sorted(gaps)[int(0.99 * len(gaps))] if gaps else None),
            "max": max(gaps) if gaps else None,
            "share_over_30_days": (
                round(sum(1 for g in gaps if g > 30) / len(gaps), 4) if gaps else None
            ),
        },
    }
    return rows, descriptives


def _redundancy(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Stage 2: is the candidate simply a re-encoding of the incumbent?

    A near-unit correlation would mean any Stage 3 null is uninformative — the
    two arms would be carrying the same information in different units, and
    the honest headline becomes "redundant", not "no signal".
    """
    elo_values = [r["elo_diff"] for r in rows]
    dynamic_values = [r["dynamic_diff"] for r in rows]
    return {
        "n": len(rows),
        "pearson_elo_vs_dynamic": round(
            statistics.correlation(elo_values, dynamic_values), 4
        ),
        "stdev_elo_diff": round(statistics.stdev(elo_values), 2),
        "stdev_dynamic_diff": round(statistics.stdev(dynamic_values), 2),
        "mean_abs_uncertainty": round(
            statistics.fmean([r["dynamic_uncertainty"] for r in rows]), 2
        ),
    }


def _with_adjusted_ci(
    result: dict[str, Any],
    rows: list[dict[str, Any]],
    baseline_fn: Any,
    candidate_fn: Any,
) -> dict[str, Any]:
    """Attach the pre-declared Bonferroni-adjusted CI to a harness result.

    Recomputed from the same paired per-fixture differences at the adjusted
    level, so both intervals describe one set of predictions.
    """
    import numpy as np

    from _incremental_value_harness import fit_multinomial_logistic

    train = [r for r in rows if r["season"] in _TRAIN_SEASONS]
    test = [r for r in rows if r["season"] == _TEST_SEASON]
    y_train = np.array([r["outcome"] for r in train])
    baseline_model = fit_multinomial_logistic(
        np.array([baseline_fn(r) for r in train]), y_train
    )
    candidate_model = fit_multinomial_logistic(
        np.array([candidate_fn(r) for r in train]), y_train
    )

    y_true = np.array([r["outcome"] for r in test])
    result["pooled"]["candidate_minus_baseline_bootstrap_bonferroni"] = (
        paired_rps_diff_bootstrap(
            y_true,
            candidate_model.predict_proba(np.array([candidate_fn(r) for r in test])),
            baseline_model.predict_proba(np.array([baseline_fn(r) for r in test])),
            ci_level=_ADJUSTED_CI_LEVEL,
        )
    )
    return result


def main() -> int:
    rows, descriptives = build_rows()
    print("── Stage 1: descriptives ─────────────────────────────────────────")
    print(json.dumps(descriptives, indent=2, default=str))

    redundancy = _redundancy(rows)
    print("\n── Stage 2: redundancy against the incumbent ─────────────────────")
    print(json.dumps(redundancy, indent=2))

    def market(row: dict[str, Any]) -> list[float]:
        return list(row["market_probs"])

    tests: dict[str, dict[str, Any]] = {}
    specs = {
        "H1_beyond_elo": (
            lambda r: [r["elo_diff"]],
            lambda r: [r["elo_diff"], r["dynamic_diff"]],
        ),
        "H2_beyond_elo_with_uncertainty": (
            lambda r: [r["elo_diff"]],
            lambda r: [r["elo_diff"], r["dynamic_diff"], r["dynamic_uncertainty"]],
        ),
        "H3_beyond_market": (
            market,
            lambda r: [*market(r), r["dynamic_diff"]],
        ),
    }

    print("\n── Stage 3: incremental value ────────────────────────────────────")
    for name, (baseline_fn, candidate_fn) in specs.items():
        result = run_incremental_value_study(
            rows,
            baseline_features=baseline_fn,
            candidate_features=candidate_fn,
            train_seasons=_TRAIN_SEASONS,
            test_season=_TEST_SEASON,
            season_key="season",
            group_key="league",
            raw_reference=market,
        )
        if "error" not in result:
            result = _with_adjusted_ci(result, rows, baseline_fn, candidate_fn)
        tests[name] = result
        pooled = result.get("pooled") or {}
        boot = pooled.get("candidate_minus_baseline_bootstrap", {})
        adjusted = pooled.get("candidate_minus_baseline_bootstrap_bonferroni", {})
        print(
            f"{name:32s} n={pooled.get('n')} "
            f"delta={boot.get('point_estimate')} "
            f"95% CI [{boot.get('ci_lower')}, {boot.get('ci_upper')}] "
            f"| {_ADJUSTED_CI_LEVEL:.4f} CI "
            f"[{adjusted.get('ci_lower')}, {adjusted.get('ci_upper')}]"
        )

    payload = {
        "experiment": "E6_dynamic_team_state",
        "generated_at": datetime.now().astimezone().isoformat(),
        "train_seasons": list(_TRAIN_SEASONS),
        "test_season": _TEST_SEASON,
        "multiple_testing": {
            "family_size": _FAMILY_SIZE,
            "adjusted_ci_level": _ADJUSTED_CI_LEVEL,
            "protocol": "pre-declared in the module docstring before any result was computed",
        },
        "stage_1_descriptives": descriptives,
        "stage_2_redundancy": redundancy,
        "stage_3_tests": tests,
    }
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = _REPORT_DIR / "e6-dynamic-team-state.json"
    out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
