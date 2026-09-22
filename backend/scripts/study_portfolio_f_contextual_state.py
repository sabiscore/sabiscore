"""Portfolio F — contextual state (rest, congestion, referee).

Directive: `docs/PRODUCTION_EXECUTIVE_DIRECTIVE.md` §10 (Portfolio F), §16
Stage 1-3, Rule 6/7. §10 sets the prior explicitly: "intentionally lower
priority... must prove information value before engineering investment...
likely weaker than player availability, team state, tactical interaction,
and information-arrival signals." This study tests that prior rather than
assuming it.

**Zero acquisition cost.** Every feature here is derived from
`backend/data/cache/fd_*.csv`, already on disk: fixture dates give rest and
congestion, and a populated `Referee` column gives officiating context.

Features
--------
* `rest_diff`      — home days since previous fixture minus away's.
* `congestion_diff`— home fixtures in the prior 14 days minus away's.
* `referee_home_bias` — the referee's home-win rate MINUS the league base
  rate, shrunk toward zero for small samples.

⚠️ LEAKAGE, the real risk in this study and the reason for the shrinkage
machinery below. A referee's home-win rate computed over the whole corpus
would include the very fixtures being predicted — a textbook target leak
that would manufacture a spectacular, entirely fake result. Every referee
statistic here is computed from fixtures strictly BEFORE the fixture being
scored (expanding window, chronological pass), with an empirical-Bayes
shrinkage toward the league base rate so a referee with two prior matches
does not get treated as carrying a real signal. `test_portfolio_f_contextual.py`
pins the strictly-before rule directly.

Rest and congestion carry no such risk: both depend only on the dates of
that team's own earlier fixtures.

Read-only. No API calls, no database, no feature-schema or artifact change.

Usage
-----
    cd backend
    PYTHONPATH=. python scripts/study_portfolio_f_contextual_state.py
"""

from __future__ import annotations

import glob
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _incremental_value_harness import devig, run_incremental_value_study  # noqa: E402
from qualify_player_availability_coverage import (
    _CACHE_DIR,
    _LEAGUE_TO_DIVISION,
    _SEASONS,
)  # noqa: E402

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_REPORT_DIR = _BACKEND_ROOT.parent / "reports" / "research"
_OUTCOME_CODE = {"H": 0, "D": 1, "A": 2}
_TRAIN_SEASONS = (2022, 2023)
_TEST_SEASON = 2024

# Empirical-Bayes shrinkage weight: a referee needs this many prior matches
# before their observed home-win rate is trusted at half weight. Deliberately
# conservative -- an unshrunk rate over 3 matches is noise wearing a signal's
# clothes.
_REFEREE_SHRINKAGE_PRIOR = 20
_CONGESTION_WINDOW_DAYS = 14


def _load_raw_fixtures() -> list[dict[str, Any]]:
    """Every corpus fixture with date, teams, result and de-vigged odds."""
    import pandas as pd

    rows: list[dict[str, Any]] = []
    for league, division in _LEAGUE_TO_DIVISION.items():
        for season, suffix in _SEASONS.items():
            paths = glob.glob(str(_CACHE_DIR / f"fd_{division}_{suffix}.csv"))
            if not paths:
                continue
            frame = pd.read_csv(paths[0], encoding="utf-8", on_bad_lines="skip")
            col = {
                "home": "HomeTeam" if "HomeTeam" in frame.columns else "home_team",
                "away": "AwayTeam" if "AwayTeam" in frame.columns else "away_team",
                "date": "Date" if "Date" in frame.columns else "date",
                "result": "FTR" if "FTR" in frame.columns else "result",
                "oh": "B365H" if "B365H" in frame.columns else "bet365_home",
                "od": "B365D" if "B365D" in frame.columns else "bet365_draw",
                "oa": "B365A" if "B365A" in frame.columns else "bet365_away",
            }
            if any(c not in frame.columns for c in col.values()):
                continue
            has_referee = "Referee" in frame.columns
            for _, row in frame.iterrows():
                parsed = pd.to_datetime(
                    row[col["date"]], errors="coerce", dayfirst=False
                )
                result = str(row[col["result"]]).strip().upper()
                try:
                    oh, od, oa = (
                        float(row[col["oh"]]),
                        float(row[col["od"]]),
                        float(row[col["oa"]]),
                    )
                except (TypeError, ValueError):
                    continue
                if (
                    pd.isna(parsed)
                    or result not in _OUTCOME_CODE
                    or min(oh, od, oa) <= 1.0
                ):
                    continue
                referee = str(row["Referee"]).strip() if has_referee else ""
                rows.append(
                    {
                        "league": league,
                        "season": season,
                        "date": parsed.date(),
                        "home_team": str(row[col["home"]]).strip(),
                        "away_team": str(row[col["away"]]).strip(),
                        "referee": referee
                        if referee and referee.lower() != "nan"
                        else None,
                        "market_probs": devig(oh, od, oa),
                        "outcome": _OUTCOME_CODE[result],
                    }
                )
    return rows


def enrich_contextual(fixtures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add rest, congestion and leak-free referee features.

    Single chronological pass: every statistic for a fixture is computed from
    state accumulated by fixtures STRICTLY EARLIER than it, then that fixture
    updates the state. A fixture can therefore never see itself or its own
    future, which is the whole leakage guard.
    """
    ordered = sorted(fixtures, key=lambda f: (f["date"], f["league"], f["home_team"]))

    # Keyed by (league, SEASON, team): without the season component a team's
    # "previous fixture" carries across the summer break, producing ~357-day
    # rest values at every season opener. Caught in the Stage 1 descriptive
    # output (rest_diff spanned +/-357 days), not by a test -- which is the
    # argument for always reading the descriptive stats before the headline.
    last_played: dict[tuple[str, int, str], date] = {}
    recent_dates: dict[tuple[str, int, str], list[date]] = defaultdict(list)
    ref_prior: dict[str, list[int]] = defaultdict(
        lambda: [0, 0]
    )  # [home_wins, matches]
    league_prior: dict[str, list[int]] = defaultdict(lambda: [0, 0])

    enriched: list[dict[str, Any]] = []
    for fx in ordered:
        league, fx_date, season = fx["league"], fx["date"], fx["season"]

        def _rest(team: str) -> float:
            previous = last_played.get((league, season, team))
            # No prior fixture (season opener / promoted club): use the
            # window cap rather than a fabricated "fully rested" extreme.
            return (
                float((fx_date - previous).days)
                if previous
                else float(_CONGESTION_WINDOW_DAYS)
            )

        def _congestion(team: str) -> int:
            return sum(
                1
                for d in recent_dates[(league, season, team)]
                if 0 < (fx_date - d).days <= _CONGESTION_WINDOW_DAYS
            )

        home_rest, away_rest = _rest(fx["home_team"]), _rest(fx["away_team"])
        home_cong, away_cong = (
            _congestion(fx["home_team"]),
            _congestion(fx["away_team"]),
        )

        # Referee home bias, shrunk toward the league base rate. Both the
        # referee's record and the league base rate come only from fixtures
        # already consumed by this loop -- i.e. strictly before fx_date.
        lg_wins, lg_matches = league_prior[league]
        league_rate = (lg_wins / lg_matches) if lg_matches else 0.0
        referee = fx.get("referee")
        if referee:
            r_wins, r_matches = ref_prior[referee]
            if r_matches:
                observed = r_wins / r_matches
                weight = r_matches / (r_matches + _REFEREE_SHRINKAGE_PRIOR)
                referee_bias = weight * (observed - league_rate)
            else:
                referee_bias = 0.0
        else:
            referee_bias = 0.0

        enriched.append(
            {
                **fx,
                "home_rest": home_rest,
                "away_rest": away_rest,
                "rest_diff": home_rest - away_rest,
                "congestion_diff": float(home_cong - away_cong),
                "referee_home_bias": float(referee_bias),
                "referee_prior_matches": ref_prior[referee][1] if referee else 0,
            }
        )

        # --- state update happens AFTER the fixture is scored, never before ---
        is_home_win = 1 if fx["outcome"] == 0 else 0
        last_played[(league, season, fx["home_team"])] = fx_date
        last_played[(league, season, fx["away_team"])] = fx_date
        recent_dates[(league, season, fx["home_team"])].append(fx_date)
        recent_dates[(league, season, fx["away_team"])].append(fx_date)
        league_prior[league][0] += is_home_win
        league_prior[league][1] += 1
        if referee:
            ref_prior[referee][0] += is_home_win
            ref_prior[referee][1] += 1

    return enriched


def descriptive(rows: list[dict[str, Any]]) -> dict[str, Any]:
    import statistics

    test = [r for r in rows if r["season"] == _TEST_SEASON]
    rest_diffs = [r["rest_diff"] for r in test]
    with_ref = [r for r in test if r["referee_prior_matches"] > 0]
    return {
        "n_test": len(test),
        "rest_diff": {
            "mean": round(statistics.fmean(rest_diffs), 3),
            "stdev": round(statistics.pstdev(rest_diffs), 3),
            "min": min(rest_diffs),
            "max": max(rest_diffs),
        },
        "congestion_diff_nonzero_share": round(
            sum(1 for r in test if r["congestion_diff"] != 0) / len(test), 3
        ),
        "fixtures_with_referee_history": len(with_ref),
        "referee_history_coverage_pct": round(100.0 * len(with_ref) / len(test), 2),
        "referee_coverage_by_league": {
            lg: round(
                100.0
                * sum(
                    1
                    for r in test
                    if r["league"] == lg and r["referee_prior_matches"] > 0
                )
                / max(1, sum(1 for r in test if r["league"] == lg)),
                1,
            )
            for lg in sorted({r["league"] for r in test})
        },
        "referee_coverage_note": (
            "Only 7 of 36 corpus files carry a Referee column and all are E0 "
            "(EPL). Referee studies below are therefore EPL-scoped; pooling them "
            "across leagues without the data produced a spurious null."
        ),
    }


def main() -> int:
    fixtures = _load_raw_fixtures()
    if len(fixtures) < 100:
        print(f"Only {len(fixtures)} usable fixtures — corpus columns missing.")
        return 1
    rows = enrich_contextual(fixtures)
    print(f"Enriched {len(rows)} fixtures with rest/congestion/referee context.")

    common = dict(
        train_seasons=_TRAIN_SEASONS,
        test_season=_TEST_SEASON,
        group_key="league",
        raw_reference=lambda r: list(r["market_probs"]),
        raw_reference_label="rps_raw_market",
    )
    report: dict[str, Any] = {
        "portfolio": "F — contextual state (rest, congestion, referee)",
        "directive": "§10, §16 Stage 1-3, Rule 6, Rule 7",
        "leakage_guard": (
            "Referee statistics are computed in a single chronological pass from "
            "fixtures strictly earlier than the one being scored, then shrunk "
            "toward the contemporaneous league base rate. A whole-corpus referee "
            "rate would leak the target and manufacture a fake result."
        ),
        "stage1_descriptive": descriptive(rows),
        "f1_rest_and_congestion_beyond_market": run_incremental_value_study(
            rows,
            baseline_features=lambda r: list(r["market_probs"]),
            candidate_features=lambda r: (
                list(r["market_probs"]) + [r["rest_diff"], r["congestion_diff"]]
            ),
            **common,
        ),
        # Referee is EPL-only in this corpus (7 of 36 files carry the column,
        # all E0). Running it pooled across five leagues diluted a genuine
        # single-league signal into a fake null on the first pass -- scoped
        # here instead, with the coverage limitation stated in the report.
        "f2_referee_beyond_market_EPL_ONLY": run_incremental_value_study(
            [r for r in rows if r["league"] == "EPL"],
            baseline_features=lambda r: list(r["market_probs"]),
            candidate_features=lambda r: (
                list(r["market_probs"]) + [r["referee_home_bias"]]
            ),
            train_seasons=_TRAIN_SEASONS,
            test_season=_TEST_SEASON,
            group_key=None,
            raw_reference=lambda r: list(r["market_probs"]),
            raw_reference_label="rps_raw_market",
        ),
        "f3_rest_congestion_and_referee_EPL_ONLY": run_incremental_value_study(
            [r for r in rows if r["league"] == "EPL"],
            baseline_features=lambda r: list(r["market_probs"]),
            candidate_features=lambda r: (
                list(r["market_probs"])
                + [r["rest_diff"], r["congestion_diff"], r["referee_home_bias"]]
            ),
            train_seasons=_TRAIN_SEASONS,
            test_season=_TEST_SEASON,
            group_key=None,
            raw_reference=lambda r: list(r["market_probs"]),
            raw_reference_label="rps_raw_market",
        ),
        "not_a_promotion": (
            "Stage 3 evidence for a directive §51 decision. Does not change the "
            "feature schema, retrain an artifact, or authorize serving."
        ),
    }

    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = _REPORT_DIR / "portfolio-f-contextual-state-report.json"
    out.write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report["stage1_descriptive"], indent=2, default=str))
    for key in (
        "f1_rest_and_congestion_beyond_market",
        "f2_referee_beyond_market_EPL_ONLY",
        "f3_rest_congestion_and_referee_EPL_ONLY",
    ):
        pooled = report[key].get("pooled") or {}
        boot = pooled.get("candidate_minus_baseline_bootstrap", {})
        print(
            f"{key}: base={pooled.get('rps_baseline_model')} cand={pooled.get('rps_candidate_model')} "
            f"diff={boot.get('point_estimate')} CI=[{boot.get('ci_lower')}, {boot.get('ci_upper')}]"
        )
    print(f"\nReport written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
