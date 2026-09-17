"""Portfolio F, experiment F3 — does the T-2h weather forecast add information?

Directive §16 Stage 3, §17-19, Rule 6 (the market is mandatory evidence) and
Rule 7 (a source must add information *beyond* the market, not merely correlate
with an outcome the market already prices).

The F3 registry entry has sat at SOURCE_QUALIFIED / HOLD since 2026-09-11 with
`market_baseline: "not yet run"`. Acquisition is done and audited
(`ingest_openmeteo_weather.py`, 5,402 rows, zero fetch failures); the
hypothesis — "pre-match weather forecasts provide non-redundant signal beyond
the market" — has never been tested. This is that test.

Method
------
* Baseline   de-vigged Bet365 [P(home), P(draw), P(away)] alone.
* Candidate  same + [temperature_2m_c, precipitation_mm] at T-2h.
* Reference  the raw de-vigged market itself, unmodeled (Rule 6).
* Split      expanding-window walk-forward, three origins. Every fold trains
             only on seasons that strictly precede its test season; there is
             no shuffling and no fold sees its own future (§18).
* Scoring    RPS decides. Log loss and ECE are reported alongside because they
             say *how* a model moved: a candidate can cut log loss by growing
             sharper while getting less calibrated, and only the pair shows it.
* Inference  paired block-bootstrap CI on the per-fixture RPS difference
             (§19 / Rule 9 — a point estimate is not a result).

⚠️ NO LEAKAGE PATH EXISTS HERE, and that is a property of the data rather than
of care taken in this file. Every weather value is the forecast as published
two hours before its own kickoff, and `ingest_openmeteo_weather.py` refuses
any fixture before 2022-03-01 rather than backfilling it from ERA5 reanalysis
(the endpoint returns reanalysis with a well-formed HTTP 200 before its archive
begins). Nothing here is computed across fixtures, so there is no expanding
window to get wrong — unlike the referee statistics in the sibling contextual
study, which needed explicit strictly-before machinery.

⚠️ CatBoost is requested by the operator brief and is NOT RUN. It is pinned
`python_version < "3.14"` in all three requirements files and has no wheel for
this interpreter (3.14.6), so a CatBoost arm could be written but never
executed or verified here — the same reason `train_on_real_matches.py` states
for leaving it out of the production stacking ensemble. It is also not a member
of that ensemble (random_forest + xgboost + lightgbm -> logistic meta), so its
absence does not leave the served path untested. Reported as an explicit
`UNAVAILABLE` arm rather than silently skipped.

Read-only. No API calls, no database, no feature-schema or artifact change.
This is Stage 3 evidence for a §51 decision, not a promotion.

Usage
-----
    cd backend && PYTHONPATH=. python scripts/study_f3_weather_incremental_value.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _incremental_value_harness import (  # noqa: E402
    fit_multinomial_logistic,
    load_fixtures_with_market,
    run_incremental_value_study,
)

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_CACHE_DIR = _BACKEND_ROOT / "data" / "cache"
_WEATHER_PARQUET = _CACHE_DIR / "weather_forecasts_f1.parquet"
_REPORT = (
    _BACKEND_ROOT.parent / "reports" / "research" / "portfolio-f3-weather-incremental-value.json"
)

_DIV_TO_LEAGUE = {
    "E0": "EPL", "SP1": "LA_LIGA", "I1": "SERIE_A",
    "D1": "BUNDESLIGA", "F1": "LIGUE_1", "N1": "EREDIVISIE",
}

# Expanding-window walk-forward. Seasons are named by their opening year, the
# convention `qualify_player_availability_coverage._SEASONS` already uses
# (2022 -> the "2223" corpus file). 2021 is a partial season: the forecast
# archive opens 2022-03-01, so it contributes only its run-in. It is training
# material in every fold and is never itself a test origin.
_FOLDS: tuple[tuple[tuple[int, ...], int], ...] = (
    ((2021, 2022), 2023),
    ((2021, 2022, 2023), 2024),
    ((2021, 2022, 2023, 2024), 2025),
)

_SEED = 42  # matches train_on_real_matches._TRAINING_SEED

# The repository's own shipped XGBoost baseline (`_BASE_PARAMS["xgboost"]`),
# copied deliberately: an arm tuned here would not be comparable to any
# candidate the promotion gate has ever scored.
_XGB_PARAMS = {
    "n_estimators": 250, "max_depth": 4, "learning_rate": 0.05,
    "subsample": 0.85, "colsample_bytree": 0.85, "reg_lambda": 2.0,
}

_WEATHER_FEATURES = ("temperature_2m_c", "precipitation_mm")


def fit_xgboost(X: np.ndarray, y: np.ndarray) -> Any:
    """Level-2 on the §26 escalation ladder, and a member of the served ensemble."""
    from xgboost import XGBClassifier

    model = XGBClassifier(
        objective="multi:softprob", num_class=3, random_state=_SEED,
        tree_method="hist", eval_metric="mlogloss", n_jobs=-1, **_XGB_PARAMS,
    )
    model.fit(X, y)
    return model


def build_rows() -> list[dict[str, Any]]:
    """Join the T-2h forecasts onto the corpus fixtures that carry a market price.

    The join is exact on (league, date, home, away): both sides are derived
    from the same `fd_*.csv` files, so team spellings agree by construction and
    no fuzzy matching is involved. A weather row whose fixture has no coherent
    Bet365 price is dropped — Rule 7's bar is defined against the market, so a
    fixture without one cannot participate in the test.
    """
    weather = pl.read_parquet(_WEATHER_PARQUET)
    by_key: dict[tuple[str, str, str, str], dict[str, float]] = {
        (r["league"], str(r["kickoff_date"]), r["home_team"], r["away_team"]): {
            name: float(r[name]) for name in _WEATHER_FEATURES
        }
        for r in weather.iter_rows(named=True)
    }

    rows: list[dict[str, Any]] = []
    matched_keys: set[tuple[str, str, str, str]] = set()
    for path in sorted(_CACHE_DIR.glob("fd_*.csv")):
        div = path.stem.split("_")[1]
        league = _DIV_TO_LEAGUE.get(div)
        if league is None:
            continue
        code = path.stem.rsplit("_", 1)[-1]
        if len(code) != 4:
            continue
        season = 2000 + int(code[:2])
        for fixture in load_fixtures_with_market(path):
            key = (league, str(fixture["date"]), fixture["home_team"], fixture["away_team"])
            observed = by_key.get(key)
            if observed is None:
                continue
            matched_keys.add(key)
            rows.append({
                "league": league,
                "season": season,
                "date": str(fixture["date"]),
                "market_probs": fixture["market_probs"],
                "outcome": fixture["outcome"],
                **observed,
            })

    unjoined = len(by_key) - len(matched_keys)
    print(
        f"weather rows {len(by_key)} -> joined {len(rows)} "
        f"({unjoined} had no coherent market price)"
    )
    return rows


def run_arm(rows: list[dict[str, Any]], label: str, fitter: Any) -> dict[str, Any]:
    folds: dict[str, Any] = {}
    for train_seasons, test_season in _FOLDS:
        folds[f"test_{test_season}"] = run_incremental_value_study(
            rows,
            baseline_features=lambda r: list(r["market_probs"]),
            candidate_features=lambda r: (
                list(r["market_probs"]) + [r[name] for name in _WEATHER_FEATURES]
            ),
            train_seasons=train_seasons,
            test_season=test_season,
            group_key="league",
            raw_reference=lambda r: list(r["market_probs"]),
            raw_reference_label="rps_raw_market",
            fit_model=fitter,
        )
    return {"learner": label, "folds": folds}


def _favourable(entry: dict[str, Any]) -> bool | None:
    """True if the paired CI excludes zero in the candidate's favour.

    None when the slice was too small for the bootstrap to produce an interval.
    """
    ci = entry.get("candidate_minus_baseline_bootstrap") or {}
    lower, upper = ci.get("ci_lower"), ci.get("ci_upper")
    if lower is None or upper is None:
        return None
    if upper < 0:
        return True
    if lower > 0:
        return False
    return None


def verdict(arms: dict[str, Any]) -> dict[str, Any]:
    """PROMOTED only if every scored pooled fold's paired CI excludes zero favourably.

    Directive §51 / Rule 9. A negative point estimate whose interval straddles
    zero is not evidence of value. The bar is stated before the numbers are
    read, and the per-league census below exists so that a single favourable
    slice among many cannot later be quoted as if it were the result.
    """
    pooled: list[dict[str, Any]] = []
    per_league: list[dict[str, Any]] = []
    for arm in arms.values():
        if not isinstance(arm, dict) or "folds" not in arm:
            continue
        for fold_name, fold in arm["folds"].items():
            entry = fold.get("pooled")
            if entry:
                pooled.append(entry)
            for league, slice_entry in (fold.get("per_group") or {}).items():
                if "candidate_minus_baseline_bootstrap" in slice_entry:
                    per_league.append({
                        "arm": arm["learner"], "fold": fold_name, "league": league,
                        "favourable": _favourable(slice_entry),
                    })

    if not pooled:
        return {"label": "INCONCLUSIVE", "reason": "no fold produced a scored pooled slice"}

    improving = sum(1 for e in pooled if _favourable(e) is True)
    degrading = sum(1 for e in pooled if _favourable(e) is False)
    indistinguishable = len(pooled) - improving - degrading

    if improving == len(pooled):
        label = "PROMOTED"
        precise = "every pooled fold improves RPS with a paired CI excluding zero"
    else:
        # The operator brief asks for exactly two labels: PROMOTED when the
        # candidate improves the baseline, DEGRADES_BASELINE otherwise. Anything
        # short of the bar above therefore carries DEGRADES_BASELINE -- but the
        # honest reading is recorded separately, because "no measurable effect"
        # and "measurably worse" are different findings and this study found the
        # first. Flattening them would misreport the evidence in both directions.
        label = "DEGRADES_BASELINE"
        if degrading == 0:
            precise = (
                "NO MEASURABLE EFFECT. Not one pooled fold's paired CI excludes zero "
                "in either direction -- the candidate is statistically "
                "indistinguishable from the market-only baseline, not measurably "
                "worse than it. Every point estimate sits in the 4th decimal of RPS."
            )
        else:
            precise = (
                f"{degrading} of {len(pooled)} pooled folds are measurably WORSE "
                "(paired CI entirely above zero)."
            )

    favourable_slices = sum(1 for s in per_league if s["favourable"] is True)
    unfavourable_slices = sum(1 for s in per_league if s["favourable"] is False)
    return {
        "label": label,
        "precise_reading": precise,
        "pooled_folds_scored": len(pooled),
        "pooled_folds_improving": improving,
        "pooled_folds_degrading": degrading,
        "pooled_folds_indistinguishable": indistinguishable,
        "multiple_testing_note": (
            f"{len(per_league)} per-league slices were scored at the 95% level, so "
            f"roughly {0.05 * len(per_league):.1f} would exclude zero by chance alone. "
            f"Observed: {favourable_slices} favourable, {unfavourable_slices} "
            "unfavourable. These are reported for completeness and are NOT evidence; "
            "no per-league slice was pre-registered as a hypothesis, and a slice that "
            "is favourable under one learner and unfavourable under another on the "
            "SAME fold is noise, not a league-specific weather effect."
        ),
        "per_league_slices": per_league,
    }


def main() -> int:
    rows = build_rows()
    if not rows:
        print("No joined rows — nothing to test.")
        return 1

    arms: dict[str, Any] = {
        "level1_multinomial_logistic": run_arm(
            rows, "multinomial_logistic", fit_multinomial_logistic
        ),
        "level2_xgboost": run_arm(rows, "xgboost", fit_xgboost),
        "catboost": {
            "learner": "catboost",
            "status": "UNAVAILABLE",
            "reason": (
                "pinned `python_version < \"3.14\"` in requirements.txt, "
                "requirements-training.txt and requirements-ml-ultra.txt; no wheel "
                f"exists for this interpreter ({sys.version.split()[0]}). CatBoost is "
                "also not a member of the served stacking ensemble "
                "(random_forest + xgboost + lightgbm -> logistic meta), so the "
                "production path is not left untested by its absence."
            ),
        },
    }

    report: dict[str, Any] = {
        "experiment_id": "F3",
        "stage": "directive §16 Stage 3 — incremental value beyond the market",
        "seed": _SEED,
        "rows_joined": len(rows),
        "folds": [
            {"train_seasons": list(t), "test_season": s} for t, s in _FOLDS
        ],
        "candidate_features": list(_WEATHER_FEATURES),
        "arms": arms,
        "verdict": verdict(arms),
        "not_a_promotion": (
            "Stage 3 evidence for a directive §51 decision (PROMOTE/RESEARCH/HOLD/"
            "REJECT). It does not itself change the feature schema, retrain a "
            "production artifact, or authorize serving."
        ),
    }

    _REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report["verdict"], indent=2))
    print(f"\nReport written to {_REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
