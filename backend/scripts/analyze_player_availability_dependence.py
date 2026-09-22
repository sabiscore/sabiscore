"""Portfolio B Phase 4, Stage 1-2 — descriptive + dependence analysis.

Directive: `docs/PRODUCTION_EXECUTIVE_DIRECTIVE.md` §16 (Information Value
Testing). Phase 3 (`qualify_player_availability_coverage.py`) proved the
data crosswalks to real fixtures at ~92% coverage. That says nothing yet
about whether the signal is *informative*. Stage 1 (descriptive) and Stage 2
(dependence) come before Stage 3 (incremental forecasting) by design —
"these are diagnostic tools, not promotion criteria" (§16). This script
does NOT train a model, does NOT touch the feature schema, and its result
cannot promote or reject the signal on its own.

Question: does `availability_diff` (home unavailable-player count minus
away) show ANY association with match outcome, at a real, honestly-computed
effect size and confidence interval — before any heavier investment
(feature engineering, walk-forward model comparison) is justified?

Reuses `qualify_player_availability_coverage.py`'s resolver and corpus
constants (imported, not re-copied — that script's docstring already
explains why it does not import `services/team_identity` itself: no DB
reachable). Re-fetches injuries fresh (does not reuse Phase 3's manifest,
which recorded aggregates only, not the raw per-record crosswalk needed to
build a per-fixture join).

Usage
-----
    cd backend
    PYTHONPATH=. python scripts/analyze_player_availability_dependence.py
"""

from __future__ import annotations

import asyncio
import glob
import json
import statistics
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx  # noqa: E402

from qualify_player_availability_coverage import (  # noqa: E402
    _LEAGUE_TO_DIVISION,
    _SEASONS,
    _CACHE_DIR,
    resolve_against_roster,
)

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND_ROOT))
from src.core.config import settings  # noqa: E402
from src.providers.api_football import APIFootballProvider  # noqa: E402

_REPORT_DIR = _BACKEND_ROOT.parent / "reports" / "research"

_OUTCOME_VALUE = {"H": 1, "D": 0, "A": -1}  # home-perspective outcome scale


def load_fixtures(division: str, suffix: str) -> list[dict[str, Any]]:
    """Full fixture rows for one division/season: home, away, date, result."""
    import pandas as pd

    paths = glob.glob(str(_CACHE_DIR / f"fd_{division}_{suffix}.csv"))
    if not paths:
        return []
    frame = pd.read_csv(paths[0], encoding="utf-8", on_bad_lines="skip")
    home_col = "HomeTeam" if "HomeTeam" in frame.columns else "home_team"
    away_col = "AwayTeam" if "AwayTeam" in frame.columns else "away_team"
    date_col = "Date" if "Date" in frame.columns else "date"
    result_col = "FTR" if "FTR" in frame.columns else "result"
    if any(c not in frame.columns for c in (home_col, away_col, date_col, result_col)):
        return []

    fixtures: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        parsed = pd.to_datetime(row[date_col], errors="coerce", dayfirst=False)
        result = str(row[result_col]).strip().upper()
        if pd.isna(parsed) or result not in _OUTCOME_VALUE:
            continue
        fixtures.append(
            {
                "home_team": str(row[home_col]).strip(),
                "away_team": str(row[away_col]).strip(),
                "date": parsed.date(),
                "result": result,
            }
        )
    return fixtures


async def collect_unavailable_counts(
    provider: APIFootballProvider, league: str, roster: set[str], season: int
) -> dict[tuple[str, date], set[Any]]:
    """{(resolved_team, fixture_date): {distinct player_ids reported unavailable}}."""
    counts: dict[tuple[str, date], set[Any]] = {}
    result = await provider.injuries(competition=league, season=season)
    if result.status.name != "VERIFIED":
        return counts
    for record in result.records:
        if not record.get("coherent"):
            continue
        resolved = resolve_against_roster(record.get("team_name", ""), league, roster)
        if resolved is None:
            continue
        fixture_date_raw = record.get("fixture_date")
        if not fixture_date_raw:
            continue
        try:
            record_date = datetime.fromisoformat(str(fixture_date_raw)).date()
        except ValueError:
            continue
        key = (resolved, record_date)
        # Deduplicate by player_id: the same player can appear more than once
        # in a broad league+season query (e.g. re-listed across gameweeks for
        # a long injury) -- counting records, not distinct players, would
        # inflate the signal for players out longest rather than reflecting
        # how many DIFFERENT players were actually missing for that match.
        player_id = record.get("player_id") or record.get("player_name")
        counts.setdefault(key, set()).add(player_id)
    return counts


def _pearson_with_ci(xs: list[float], ys: list[float]) -> dict[str, Any]:
    """Pearson r, with a 95% CI via Fisher z-transform -- no scipy dependency."""
    import math

    n = len(xs)
    if n < 3:
        return {"n": n, "r": None, "ci95": None, "note": "insufficient_sample"}
    mean_x, mean_y = statistics.fmean(xs), statistics.fmean(ys)
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x == 0 or var_y == 0:
        return {"n": n, "r": 0.0, "ci95": None, "note": "zero_variance"}
    r = cov / math.sqrt(var_x * var_y)
    r_clamped = max(-0.999999, min(0.999999, r))
    z = 0.5 * math.log((1 + r_clamped) / (1 - r_clamped))
    se = 1 / math.sqrt(n - 3)
    lo, hi = z - 1.96 * se, z + 1.96 * se
    ci = (math.tanh(lo), math.tanh(hi))
    return {"n": n, "r": round(r, 4), "ci95": (round(ci[0], 4), round(ci[1], 4))}


async def main() -> int:
    if not settings.api_football_key:
        print("No api_football credential configured — nothing to analyze.")
        return 1

    joined: list[dict[str, Any]] = []
    missing_both_sides = 0
    total_fixtures = 0

    async with httpx.AsyncClient(timeout=30.0) as client:
        provider = APIFootballProvider(
            api_key=settings.api_football_key,
            enabled=True,
            live_tests=True,
            http_client=client,
        )
        for league, division in _LEAGUE_TO_DIVISION.items():
            for season, suffix in _SEASONS.items():
                fixtures = load_fixtures(division, suffix)
                if not fixtures:
                    continue
                roster = {f["home_team"] for f in fixtures} | {
                    f["away_team"] for f in fixtures
                }
                counts = await collect_unavailable_counts(
                    provider, league, roster, season
                )
                await asyncio.sleep(1.0)  # same burst-throttle pacing as Phase 3

                for fx in fixtures:
                    total_fixtures += 1
                    home_n = len(counts.get((fx["home_team"], fx["date"]), set()))
                    away_n = len(counts.get((fx["away_team"], fx["date"]), set()))
                    if home_n == 0 and away_n == 0:
                        missing_both_sides += 1
                        continue
                    joined.append(
                        {
                            "league": league,
                            "season": season,
                            "home_unavailable": home_n,
                            "away_unavailable": away_n,
                            "availability_diff": home_n - away_n,
                            "result": fx["result"],
                            "outcome_value": _OUTCOME_VALUE[fx["result"]],
                        }
                    )
                print(
                    f"{league:<12} {season}  fixtures={len(fixtures):>4}  "
                    f"with_signal={sum(1 for j in joined if j['league'] == league and j['season'] == season):>4}"
                )

    # ---- Stage 1: descriptive ----
    coverage_pct = (
        round(100.0 * (total_fixtures - missing_both_sides) / total_fixtures, 2)
        if total_fixtures
        else 0.0
    )
    diffs = [j["availability_diff"] for j in joined]
    stage1 = {
        "total_fixtures": total_fixtures,
        "fixtures_with_any_signal": len(joined),
        "fixtures_with_zero_signal_both_sides": missing_both_sides,
        "fixture_level_coverage_pct": coverage_pct,
        "availability_diff_distribution": {
            "mean": round(statistics.fmean(diffs), 3) if diffs else None,
            "median": statistics.median(diffs) if diffs else None,
            "stdev": round(statistics.pstdev(diffs), 3) if len(diffs) > 1 else None,
            "min": min(diffs) if diffs else None,
            "max": max(diffs) if diffs else None,
        },
    }

    # ---- Stage 2: dependence ----
    outcomes = [j["outcome_value"] for j in joined]
    correlation = _pearson_with_ci(diffs, outcomes) if joined else {"note": "no_data"}

    # Tercile group means: does home-favourable outcome rate fall as the home
    # side gets MORE depleted relative to the away side?
    tercile_report: dict[str, Any] = {}
    if len(joined) >= 30:
        ordered = sorted(joined, key=lambda j: j["availability_diff"])
        third = len(ordered) // 3
        groups = {
            "home_less_depleted (bottom tercile of diff)": ordered[:third],
            "middle_tercile": ordered[third : 2 * third],
            "home_more_depleted (top tercile of diff)": ordered[2 * third :],
        }
        for label, group in groups.items():
            tercile_report[label] = {
                "n": len(group),
                "mean_availability_diff": round(
                    statistics.fmean(j["availability_diff"] for j in group), 3
                ),
                "home_win_rate": round(
                    sum(1 for j in group if j["result"] == "H") / len(group), 3
                ),
                "away_win_rate": round(
                    sum(1 for j in group if j["result"] == "A") / len(group), 3
                ),
            }

    # Robustness (§18): a pooled correlation can hide Simpson's-paradox-style
    # heterogeneity -- one league driving the whole effect while others show
    # nothing, or disagree in sign. Report per-league correlations, not just
    # the aggregate, before treating this as real evidence.
    per_league: dict[str, Any] = {}
    for league in _LEAGUE_TO_DIVISION:
        league_rows = [j for j in joined if j["league"] == league]
        if len(league_rows) < 30:
            per_league[league] = {"n": len(league_rows), "note": "insufficient_sample"}
            continue
        league_diffs = [j["availability_diff"] for j in league_rows]
        league_outcomes = [j["outcome_value"] for j in league_rows]
        per_league[league] = _pearson_with_ci(league_diffs, league_outcomes)

    report = {
        "stage": "1-2 (descriptive + dependence) -- diagnostic only, per directive §16",
        "not_authorized": "This result alone does not authorize a feature-schema "
        "change, model training, or promotion decision. Stage 3 (incremental "
        "forecasting against incumbent + market, walk-forward, paired) is separate.",
        "stage1_descriptive": stage1,
        "stage2_pearson_availability_diff_vs_outcome_pooled": correlation,
        "stage2_pearson_per_league": per_league,
        "stage2_tercile_group_means": tercile_report,
    }

    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = _REPORT_DIR / "portfolio-b-stage1-2-dependence-report.json"
    out.write_text(json.dumps(report, indent=2, default=str))

    # Persist the raw per-fixture join too -- Stage 3 (incremental forecasting)
    # needs exactly this table, and Rule 4 (raw retention) means it should not
    # only exist as an aggregate. Re-deriving it would cost another ~18 live
    # requests against a 100/day free-tier quota for no new information.
    raw_out = _REPORT_DIR / "portfolio-b-availability-outcome-joined.json"
    raw_out.write_text(json.dumps(joined, indent=2, default=str))

    print("\n" + "=" * 70)
    print(json.dumps(report, indent=2, default=str))
    print("=" * 70)
    print(f"\nReport written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
