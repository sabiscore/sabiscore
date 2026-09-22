"""Experiment E6 follow-up — the 2x2 ablation its own limitations section named.

`reports/research/e6-dynamic-team-state.md` §8 recorded the gap plainly:

    "Elo's season-carryover regression was removed, not ablated. The study
     does not separate 'state-space gain helped' from 'dropping the 50%
     summer regression helped'. A 2x2 ablation would, and was not run."

E6 compared cell A against cell D and therefore changed two things at once:

                        fixed-K gain          adaptive (Kalman) gain
    carryover ON        A  incumbent Elo      B  never tested
    carryover OFF       C                     D  E6's candidate

Three contrasts against the incumbent decompose it:

    B - A   adaptive gain alone, carryover held
    C - A   dropping carryover alone, gain held
    D - A   both together (E6's headline, -0.0012)

plus the interaction  (D-A) - (B-A) - (C-A), which is ~0 if the two factors
are additive and non-zero if they interact — the case that matters, because
E6's HOLD could be masking two real effects cancelling.

ONE IMPLEMENTATION PER ARM, NOT FOUR
------------------------------------
All four cells come from the two replays that already exist, each given a
`season_carryover` flag, rather than a fourth copy of the rating math. Cell A
is `FastEloReplay` in its default configuration — the actual incumbent, still
cross-verified against `EloEngine` by its own test — so the ablation's
baseline is the production rating system rather than a look-alike.

SUBSTITUTION, NOT INCREMENT — DO NOT COMPARE THESE NUMBERS TO E6's H1
---------------------------------------------------------------------
E6's H1 asked an incremental question: `[elo]` vs `[elo, dynamic]`. This
study asks a substitution question: each cell is fitted as the SAME model
class on a SINGLE rating input, so the contrast is between rating systems
rather than between feature sets. That is the right frame for attributing a
rating system's quality to its parts, but it means the deltas here are not
on the same footing as E6's and must not be read against them.

STATISTICAL STANDING, STATED HONESTLY UP FRONT
----------------------------------------------
E6 already spent a pre-declared family of three tests on this holdout and
found nothing. This is a SECOND pass over the SAME test season, so its
p-values do not carry the same weight: its purpose is to ATTRIBUTE an
already-null result between two factors, not to search again for
significance. Pre-declared accordingly:

  * Bonferroni for this family of three contrasts (98.33%) is reported
    alongside the 95% interval, as in E6.
  * Any contrast whose CI excludes zero is reported as REQUIRING CONFIRMATION
    ON FRESH DATA, never as a finding, precisely because it emerged from a
    second look at a holdout that has already been used.

Read-only. No API calls, no database, no feature-schema or artifact change.

Usage
-----
    cd backend
    PYTHONPATH=. python scripts/study_e6_ablation_2x2.py
"""

from __future__ import annotations

import importlib.util
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _incremental_value_harness import (  # noqa: E402
    devig,
    run_incremental_value_study,
)

from src.core.config import settings  # noqa: E402
from src.data.elo_engine import EloEngine  # noqa: E402
from src.features.dynamic_team_state import (  # noqa: E402
    DynamicTeamStateReplay,
    calibrate_observation_noise_scale,
)
from src.features.elo_replay import FastEloReplay  # noqa: E402

_REPORT_DIR = _BACKEND_ROOT.parent / "reports" / "research"
_CACHE_DIR = _BACKEND_ROOT / "data" / "cache"
_TRAIN_SEASONS = ("2223", "2324")
_TEST_SEASON = "2425"
_FAMILY_SIZE = 3
_ADJUSTED_CI_LEVEL = 1.0 - (0.05 / _FAMILY_SIZE)

#: (label, gain, carryover) for each cell of the 2x2.
_CELLS = {
    "A_fixed_carryover": ("fixed", True),
    "B_adaptive_carryover": ("adaptive", True),
    "C_fixed_no_carryover": ("fixed", False),
    "D_adaptive_no_carryover": ("adaptive", False),
}


def _load_training_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "train_on_real_matches",
        Path(__file__).resolve().parent / "train_on_real_matches.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the training pipeline")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_elo(carryover: bool) -> FastEloReplay:
    return FastEloReplay(
        home_advantage=float(settings.elo_home_advantage),
        k_base=float(settings.elo_k_base),
        league_importance=EloEngine.LEAGUE_IMPORTANCE,
        season_carryover=carryover,
    )


def _make_dynamic(carryover: bool) -> DynamicTeamStateReplay:
    return DynamicTeamStateReplay(
        home_advantage=float(settings.elo_home_advantage),
        observation_noise_scale=calibrate_observation_noise_scale(
            k_elo=float(settings.elo_k_base)
        ),
        season_carryover=carryover,
    )


def build_rows() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """One chronological pass driving all four cells side by side.

    Four separate loops would let a subtle ordering difference become part of
    the result; one loop cannot.
    """
    training = _load_training_module()
    matches = training.load_matches(_CACHE_DIR)

    replays: dict[str, Any] = {}
    for label, (gain, carryover) in _CELLS.items():
        replays[label] = (
            _make_elo(carryover) if gain == "fixed" else _make_dynamic(carryover)
        )

    rows: list[dict[str, Any]] = []
    moves: dict[str, list[float]] = {label: [] for label in _CELLS}
    skipped_self_play = 0

    for match in matches:
        home, away = match["home"], match["away"]
        league, season, when = match["league"], match["season"], match["date"]
        if home == away:
            skipped_self_play += 1
            continue

        diffs: dict[str, float] = {}
        befores: dict[str, float] = {}
        for label, (gain, _carryover) in _CELLS.items():
            replay = replays[label]
            if gain == "fixed":
                ctx = replay.get_context(home, away, league, season)
                diffs[label] = ctx.elo_difference
                befores[label] = ctx.home_elo
            else:
                ctx = replay.get_context(home, away, league, when, season=season)
                diffs[label] = ctx.strength_diff
                befores[label] = ctx.home_strength

        odds = match.get("odds")
        if odds is not None:
            hg, ag = int(match["hg"]), int(match["ag"])
            rows.append(
                {
                    "league": league,
                    "season": season,
                    "outcome": 0 if hg > ag else (1 if hg == ag else 2),
                    "market_probs": devig(*odds),
                    **{f"diff_{label}": diffs[label] for label in _CELLS},
                }
            )

        for label, (gain, _carryover) in _CELLS.items():
            replay = replays[label]
            if gain == "fixed":
                replay.update(
                    home, away, league, season, int(match["hg"]), int(match["ag"])
                )
                after = replay.get_context(home, away, league, season).home_elo
            else:
                replay.update(
                    home,
                    away,
                    league,
                    when,
                    int(match["hg"]),
                    int(match["ag"]),
                    season=season,
                )
                after = replay.get_context(
                    home, away, league, when, season=season
                ).home_strength
            moves[label].append(abs(after - befores[label]))

    descriptives = {
        "corpus_matches": len(matches),
        "scored_rows": len(rows),
        "skipped_self_play": skipped_self_play,
        "mean_abs_rating_move": {
            label: round(statistics.fmean(values), 3) for label, values in moves.items()
        },
        "pearson_vs_incumbent": {
            label: round(
                statistics.correlation(
                    [r["diff_A_fixed_carryover"] for r in rows],
                    [r[f"diff_{label}"] for r in rows],
                ),
                4,
            )
            for label in _CELLS
            if label != "A_fixed_carryover"
        },
    }
    return rows, descriptives


def _contrast(rows: list[dict[str, Any]], cell: str, ci_level: float) -> dict[str, Any]:
    """Score one cell against the incumbent, same model class, single input."""

    def feature(label: str) -> Callable[[dict[str, Any]], list[float]]:
        return lambda row: [row[f"diff_{label}"]]

    result = run_incremental_value_study(
        rows,
        baseline_features=feature("A_fixed_carryover"),
        candidate_features=feature(cell),
        train_seasons=_TRAIN_SEASONS,
        test_season=_TEST_SEASON,
        season_key="season",
        group_key="league",
        raw_reference=lambda row: list(row["market_probs"]),
    )
    if "error" in result:
        return result

    import numpy as np

    from _incremental_value_harness import (
        fit_multinomial_logistic,
        paired_rps_diff_bootstrap,
    )

    train = [r for r in rows if r["season"] in _TRAIN_SEASONS]
    test = [r for r in rows if r["season"] == _TEST_SEASON]
    y_train = np.array([r["outcome"] for r in train])
    base_fn, cand_fn = feature("A_fixed_carryover"), feature(cell)
    base_model = fit_multinomial_logistic(
        np.array([base_fn(r) for r in train]), y_train
    )
    cand_model = fit_multinomial_logistic(
        np.array([cand_fn(r) for r in train]), y_train
    )
    result["pooled"]["candidate_minus_baseline_bootstrap_bonferroni"] = (
        paired_rps_diff_bootstrap(
            np.array([r["outcome"] for r in test]),
            cand_model.predict_proba(np.array([cand_fn(r) for r in test])),
            base_model.predict_proba(np.array([base_fn(r) for r in test])),
            ci_level=ci_level,
        )
    )
    return result


def main() -> int:
    rows, descriptives = build_rows()
    print("── Stage 1: descriptives ─────────────────────────────────────────")
    print(json.dumps(descriptives, indent=2, default=str))

    print("\n── 2x2 contrasts against the incumbent (cell A) ──────────────────")
    contrasts: dict[str, Any] = {}
    for cell in (
        "B_adaptive_carryover",
        "C_fixed_no_carryover",
        "D_adaptive_no_carryover",
    ):
        result = _contrast(rows, cell, _ADJUSTED_CI_LEVEL)
        contrasts[cell] = result
        pooled = result.get("pooled") or {}
        boot = pooled.get("candidate_minus_baseline_bootstrap", {})
        adj = pooled.get("candidate_minus_baseline_bootstrap_bonferroni", {})
        print(
            f"{cell:26s} rps={pooled.get('rps_candidate_model')} "
            f"delta={boot.get('point_estimate')} "
            f"95% CI [{boot.get('ci_lower')}, {boot.get('ci_upper')}] "
            f"| {_ADJUSTED_CI_LEVEL:.4f} CI [{adj.get('ci_lower')}, {adj.get('ci_upper')}]"
        )

    def _delta(cell: str) -> float | None:
        pooled = contrasts[cell].get("pooled") or {}
        boot = pooled.get("candidate_minus_baseline_bootstrap", {})
        value = boot.get("point_estimate")
        return float(value) if value is not None else None

    b, c, d = (
        _delta("B_adaptive_carryover"),
        _delta("C_fixed_no_carryover"),
        _delta("D_adaptive_no_carryover"),
    )
    interaction = None if None in (b, c, d) else round(d - b - c, 6)
    print(
        f"\ninteraction (D-A) - (B-A) - (C-A) = {interaction}"
        "   [~0 means the two factors are additive]"
    )

    baseline_rps = (contrasts["B_adaptive_carryover"].get("pooled") or {}).get(
        "rps_baseline_model"
    )
    market_rps = (contrasts["B_adaptive_carryover"].get("pooled") or {}).get(
        "rps_raw_reference"
    )
    print(f"incumbent (cell A) RPS = {baseline_rps}   de-vigged market = {market_rps}")

    payload = {
        "experiment": "E6_ablation_2x2",
        "generated_at": datetime.now().astimezone().isoformat(),
        "supersedes_limitation": "reports/research/e6-dynamic-team-state.md section 8",
        "frame": "substitution (one rating input per cell), NOT E6's incremental H1",
        "statistical_standing": (
            "second pass over a holdout E6 already used; any CI excluding zero "
            "requires confirmation on fresh data and is not reported as a finding"
        ),
        "train_seasons": list(_TRAIN_SEASONS),
        "test_season": _TEST_SEASON,
        "multiple_testing": {
            "family_size": _FAMILY_SIZE,
            "adjusted_ci_level": _ADJUSTED_CI_LEVEL,
        },
        "cells": {
            label: {"gain": g, "season_carryover": c}
            for label, (g, c) in _CELLS.items()
        },
        "stage_1_descriptives": descriptives,
        "contrasts": contrasts,
        "interaction_point_estimate": interaction,
        "incumbent_rps": baseline_rps,
        "market_rps": market_rps,
    }
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = _REPORT_DIR / "e6-ablation-2x2.json"
    out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
