"""Portfolio B Phase 4, Stage 3 — incremental forecasting test.

Directive: `docs/PRODUCTION_EXECUTIVE_DIRECTIVE.md` §16 Stage 3, §17-19. Stage
2 (`analyze_player_availability_dependence.py`) found a real, CI-excluding-
zero pooled correlation between `availability_diff` and match outcome
(r=-0.079, 95% CI [-0.106, -0.052], n=5,232), but heterogeneous across
leagues (3/5 significant and correctly signed, EPL directionally consistent
but not significant, LA_LIGA showing no effect). Stage 2 is diagnostic only
-- it says nothing about whether the signal survives once the market's own
information is already in the model (Rule 7: a source must add information
*beyond* the market, not merely correlate with an outcome the market already
prices).

This is the actual test: does `availability_diff` reduce out-of-sample RPS
when added to a market-only baseline, under a genuine temporal split, with a
paired block-bootstrap confidence interval on the difference -- not a point
estimate (Rule 9).

Method
------
* Baseline: multinomial logistic regression on de-vigged Bet365
  [P(home), P(draw), P(away)] alone. This is Rule 7's own bar -- if the
  candidate can't beat a model that already sees the market, it is not
  independent information.
* Candidate: same + `availability_diff`.
* Reference: the raw de-vigged market probabilities themselves, unmodeled --
  the more fundamental Rule 6 comparison.
* Split: train on seasons 2022+2023, test on 2024 -- the only genuine
  walk-forward split available with 3 seasons of corpus history (train
  strictly precedes test; no random shuffling, per §18).
* Scoring: mean RPS (`src.models.evaluation.metrics.ranked_probability_score`,
  reused rather than reimplemented) on the held-out 2024 season, pooled and
  per-league (heterogeneity already found in Stage 2 -- must not be hidden
  by pooling again).
* Significance: `block_bootstrap_ci` (same module) on the *paired*
  per-fixture RPS difference (candidate - baseline; negative means the
  candidate is better), non-overlapping block resampling for temporal
  dependence, 1000 replicates.

This is diagnostic evidence for a Phase 4 decision (PROMOTE / RESEARCH /
HOLD / REJECT, directive §51) -- it does NOT itself change the feature
schema, retrain a production artifact, or authorize serving. That would be
Phase 5+ and needs its own explicit authorization regardless of this
result.

Usage
-----
    cd backend
    PYTHONPATH=. python scripts/test_player_availability_incremental_value.py
"""

from __future__ import annotations

import asyncio
import glob
import json
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
from _incremental_value_harness import (  # noqa: E402
    devig,
    run_incremental_value_study,
)

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND_ROOT))
from src.core.config import settings  # noqa: E402
from src.providers.api_football import APIFootballProvider  # noqa: E402

_REPORT_DIR = _BACKEND_ROOT.parent / "reports" / "research"
_OUTCOME_CODE = {
    "H": 0,
    "D": 1,
    "A": 2,
}  # matches ranked_probability_score's own convention
_TRAIN_SEASONS = (2022, 2023)
_TEST_SEASON = 2024


def load_fixtures_with_odds(division: str, suffix: str) -> list[dict[str, Any]]:
    import pandas as pd

    paths = glob.glob(str(_CACHE_DIR / f"fd_{division}_{suffix}.csv"))
    if not paths:
        return []
    frame = pd.read_csv(paths[0], encoding="utf-8", on_bad_lines="skip")
    cols = {
        "home": "HomeTeam" if "HomeTeam" in frame.columns else "home_team",
        "away": "AwayTeam" if "AwayTeam" in frame.columns else "away_team",
        "date": "Date" if "Date" in frame.columns else "date",
        "result": "FTR" if "FTR" in frame.columns else "result",
        "oh": "B365H" if "B365H" in frame.columns else "bet365_home",
        "od": "B365D" if "B365D" in frame.columns else "bet365_draw",
        "oa": "B365A" if "B365A" in frame.columns else "bet365_away",
    }
    if any(c not in frame.columns for c in cols.values()):
        return []

    rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        parsed = pd.to_datetime(row[cols["date"]], errors="coerce", dayfirst=False)
        result = str(row[cols["result"]]).strip().upper()
        try:
            oh, od, oa = (
                float(row[cols["oh"]]),
                float(row[cols["od"]]),
                float(row[cols["oa"]]),
            )
        except (TypeError, ValueError):
            continue
        if pd.isna(parsed) or result not in _OUTCOME_CODE or min(oh, od, oa) <= 1.0:
            continue
        rows.append(
            {
                "home_team": str(row[cols["home"]]).strip(),
                "away_team": str(row[cols["away"]]).strip(),
                "date": parsed.date(),
                "result": result,
                "market_probs": devig(oh, od, oa),
            }
        )
    return rows


async def collect_unavailable_counts(
    provider: APIFootballProvider, league: str, roster: set[str], season: int
) -> dict[tuple[str, date], set[Any]]:
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
        player_id = record.get("player_id") or record.get("player_name")
        counts.setdefault((resolved, record_date), set()).add(player_id)
    return counts


async def build_dataset() -> list[dict[str, Any]]:
    joined: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        provider = APIFootballProvider(
            api_key=settings.api_football_key,
            enabled=True,
            live_tests=True,
            http_client=client,
        )
        for league, division in _LEAGUE_TO_DIVISION.items():
            for season, suffix in _SEASONS.items():
                fixtures = load_fixtures_with_odds(division, suffix)
                if not fixtures:
                    continue
                roster = {f["home_team"] for f in fixtures} | {
                    f["away_team"] for f in fixtures
                }
                counts = await collect_unavailable_counts(
                    provider, league, roster, season
                )
                await asyncio.sleep(1.0)

                for fx in fixtures:
                    home_n = len(counts.get((fx["home_team"], fx["date"]), set()))
                    away_n = len(counts.get((fx["away_team"], fx["date"]), set()))
                    joined.append(
                        {
                            "league": league,
                            "season": season,
                            "home_team": fx["home_team"],
                            "away_team": fx["away_team"],
                            "date": str(fx["date"]),
                            "market_probs": fx["market_probs"],
                            "availability_diff": home_n - away_n,
                            "outcome": _OUTCOME_CODE[fx["result"]],
                        }
                    )
                print(f"{league:<12} {season}  fixtures={len(fixtures):>4}")
    return joined


def evaluate(joined: list[dict[str, Any]]) -> dict[str, Any]:
    """Baseline = de-vigged market alone; candidate adds availability_diff.

    Rule 7's bar: a signal that cannot beat a model already seeing the
    market is not independent information. `raw_reference` scores the
    unmodeled de-vigged market itself, the more fundamental Rule 6
    comparison.
    """
    return run_incremental_value_study(
        joined,
        baseline_features=lambda r: list(r["market_probs"]),
        candidate_features=lambda r: list(r["market_probs"]) + [r["availability_diff"]],
        train_seasons=_TRAIN_SEASONS,
        test_season=_TEST_SEASON,
        group_key="league",
        raw_reference=lambda r: list(r["market_probs"]),
        raw_reference_label="rps_raw_market",
    )


async def main() -> int:
    raw_out = _REPORT_DIR / "portfolio-b-stage3-dataset.json"

    # Re-use an already-fetched dataset when present -- the evaluation step
    # below is local/no-network; re-fetching to debug it would spend live
    # api_football quota (100/day free tier) for identical data.
    if "--refetch" not in sys.argv and raw_out.exists():
        print(
            f"Loading cached dataset from {raw_out} (pass --refetch to re-query live)."
        )
        joined = json.loads(raw_out.read_text())
    else:
        if not settings.api_football_key:
            print("No api_football credential configured — nothing to test.")
            return 1
        joined = await build_dataset()
        raw_out.write_text(json.dumps(joined, indent=2, default=str))

    result = evaluate(joined)
    result["not_a_promotion"] = (
        "This is Stage 3 evidence for a directive §51 decision (PROMOTE/RESEARCH/"
        "HOLD/REJECT). It does not itself change the feature schema, retrain a "
        "production artifact, or authorize serving."
    )

    out = _REPORT_DIR / "portfolio-b-stage3-incremental-value-report.json"
    out.write_text(json.dumps(result, indent=2, default=str))

    print("\n" + "=" * 70)
    print(json.dumps(result, indent=2, default=str))
    print("=" * 70)
    print(f"\nReport written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
