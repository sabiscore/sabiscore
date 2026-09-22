"""Portfolio E — market microstructure / information arrival.

Directive: `docs/PRODUCTION_EXECUTIVE_DIRECTIVE.md` §9 (Portfolio E), §16
Stage 1-3, §17-19, Rule 6 (the market is mandatory evidence) and Rule 7
(a source that primarily reconstructs bookmaker probability is not
independent signal).

**Zero acquisition cost.** Unlike Portfolios B and D, this needs no new
source: `backend/data/cache/fd_*.csv` already carries both an early/opening
quote (`bet365_home/draw/away`, `pinnacle_*`, `avg_*`, `max_*`) and a
closing quote (`B365CH/CD/CA`, `pinnacle_closing_*`, `AvgC*`, `MaxC*`) for
every fixture. Rule 2 ("look before you write") applied to sources: the
information-arrival question is answerable today, from data already on disk.

Four questions, in order:

Q1 — Efficiency (descriptive, no model). Is the closing quote actually a
     better forecast than the opening quote? Scored as raw de-vigged RPS on
     both. Establishes whether the two columns carry the temporal structure
     the rest of this study assumes.

Q2 — Does open->close DRIFT add information BEYOND the closing quote?
     This is the strong Rule 7 test. If the close is efficient, drift
     should add nothing: the movement's information is already IN the
     closing price. A null here is a real, publishable negative result.

Q3 — Does cross-book DISPERSION at close (max vs average available price,
     a market-disagreement proxy) add information beyond the consensus
     close?

Q4 — Does drift add information beyond the OPENING quote? Informative about
     whether the movement carries anything the open lacks -- but see the
     serving-window caveat below before reading this as a product
     opportunity.

⚠️ SERVING-WINDOW CAVEAT, stated up front because it governs how any
positive result here may be used. A closing quote is only knowable at
kickoff. SabiScore's primary surface shows fixtures hours-to-days ahead, so
a model consuming closing odds (or drift, which only completes at close) is
NOT deployable on that surface -- structurally the same constraint
Portfolio B found for confirmed lineups (that study's §2b). Any Q2/Q4
finding is therefore evidence about market behaviour first, and a product
input only within a near-kickoff window that does not currently exist.

Read-only. No API calls, no database, no feature-schema or artifact change.

Usage
-----
    cd backend
    PYTHONPATH=. python scripts/study_portfolio_e_market_microstructure.py
"""

from __future__ import annotations

import glob
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _incremental_value_harness import (  # noqa: E402
    devig,
    mean_rps,
    run_incremental_value_study,
)
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

# Column families. Non-`C` = early/opening quote, `C` = closing quote --
# football-data.co.uk's own convention. Both spellings of each are accepted
# because the corpus files are not uniform (the same duality
# qualify_venue_locations.py documents for team-name columns).
_COLS = {
    "date": ("Date", "date"),
    "home": ("HomeTeam", "home_team"),
    "away": ("AwayTeam", "away_team"),
    "result": ("FTR", "result"),
    "open_h": ("B365H", "bet365_home"),
    "open_d": ("B365D", "bet365_draw"),
    "open_a": ("B365A", "bet365_away"),
    "close_h": ("B365CH", "B365CH"),
    "close_d": ("B365CD", "B365CD"),
    "close_a": ("B365CA", "B365CA"),
    "max_close_h": ("MaxCH", "MaxCH"),
    "max_close_d": ("MaxCD", "MaxCD"),
    "max_close_a": ("MaxCA", "MaxCA"),
    "avg_close_h": ("AvgCH", "AvgCH"),
    "avg_close_d": ("AvgCD", "AvgCD"),
    "avg_close_a": ("AvgCA", "AvgCA"),
}


def _resolve_columns(frame: Any) -> dict[str, str] | None:
    resolved: dict[str, str] = {}
    for key, candidates in _COLS.items():
        for candidate in candidates:
            if candidate in frame.columns:
                resolved[key] = candidate
                break
        else:
            return None
    return resolved


def load_rows() -> list[dict[str, Any]]:
    """One row per fixture with opening quote, closing quote and dispersion."""
    import pandas as pd

    rows: list[dict[str, Any]] = []
    for league, division in _LEAGUE_TO_DIVISION.items():
        for season, suffix in _SEASONS.items():
            paths = glob.glob(str(_CACHE_DIR / f"fd_{division}_{suffix}.csv"))
            if not paths:
                continue
            frame = pd.read_csv(paths[0], encoding="utf-8", on_bad_lines="skip")
            cols = _resolve_columns(frame)
            if cols is None:
                continue
            for _, row in frame.iterrows():
                result = str(row[cols["result"]]).strip().upper()
                if result not in _OUTCOME_CODE:
                    continue
                try:
                    quotes = {
                        k: float(row[cols[k]])
                        for k in cols
                        if k not in ("date", "home", "away", "result")
                    }
                except (TypeError, ValueError):
                    continue
                if any(v <= 1.0 or not np.isfinite(v) for v in quotes.values()):
                    continue

                open_probs = devig(quotes["open_h"], quotes["open_d"], quotes["open_a"])
                close_probs = devig(
                    quotes["close_h"], quotes["close_d"], quotes["close_a"]
                )
                # Dispersion: how far the best available price sits above the
                # cross-book average, per outcome. Larger = more disagreement
                # between books about that outcome.
                dispersion = [
                    quotes["max_close_h"] / quotes["avg_close_h"] - 1.0,
                    quotes["max_close_d"] / quotes["avg_close_d"] - 1.0,
                    quotes["max_close_a"] / quotes["avg_close_a"] - 1.0,
                ]
                rows.append(
                    {
                        "league": league,
                        "season": season,
                        "home_team": str(row[cols["home"]]).strip(),
                        "away_team": str(row[cols["away"]]).strip(),
                        "open_probs": open_probs,
                        "close_probs": close_probs,
                        "drift": [c - o for c, o in zip(close_probs, open_probs)],
                        "dispersion": dispersion,
                        "outcome": _OUTCOME_CODE[result],
                    }
                )
    return rows


def q1_efficiency(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Raw de-vigged RPS of the opening vs the closing quote. No model."""
    test = [r for r in rows if r["season"] == _TEST_SEASON]
    if not test:
        return {"error": "no_test_rows"}
    y_true = np.array([r["outcome"] for r in test])
    rps_open = mean_rps(y_true, np.array([r["open_probs"] for r in test]))
    rps_close = mean_rps(y_true, np.array([r["close_probs"] for r in test]))
    per_league = {}
    for league in sorted({r["league"] for r in test}):
        slice_rows = [r for r in test if r["league"] == league]
        y = np.array([r["outcome"] for r in slice_rows])
        per_league[league] = {
            "n": len(slice_rows),
            "rps_opening_quote": round(
                mean_rps(y, np.array([r["open_probs"] for r in slice_rows])), 5
            ),
            "rps_closing_quote": round(
                mean_rps(y, np.array([r["close_probs"] for r in slice_rows])), 5
            ),
        }
    return {
        "n": len(test),
        "rps_opening_quote": round(rps_open, 5),
        "rps_closing_quote": round(rps_close, 5),
        "closing_minus_opening": round(rps_close - rps_open, 5),
        "interpretation": (
            "Negative means the closing quote is the better forecast (lower RPS "
            "is better). A materially negative value is the classic market-"
            "efficiency result and also means any 'did SabiScore beat the "
            "market' claim must state WHICH quote it was measured against."
        ),
        "per_league": per_league,
    }


def main() -> int:
    rows = load_rows()
    if len(rows) < 100:
        print(
            f"Only {len(rows)} usable rows — corpus odds columns missing or unparseable."
        )
        return 1
    print(f"Loaded {len(rows)} fixtures with both opening and closing quotes.")

    report: dict[str, Any] = {
        "portfolio": "E — market microstructure / information arrival",
        "directive": "§9, §16 Stage 1-3, Rule 6, Rule 7",
        "serving_window_caveat": (
            "A closing quote is knowable only at kickoff. SabiScore's primary "
            "surface serves fixtures hours-to-days ahead, so any model consuming "
            "closing odds or open->close drift is not deployable there — the same "
            "structural constraint Portfolio B found for confirmed lineups (§2b of "
            "that study). Q2/Q4 findings are evidence about market behaviour first, "
            "and a product input only inside a near-kickoff window that does not "
            "currently exist."
        ),
        "n_fixtures": len(rows),
        "q1_efficiency_opening_vs_closing": q1_efficiency(rows),
        "q2_drift_beyond_closing": run_incremental_value_study(
            rows,
            baseline_features=lambda r: list(r["close_probs"]),
            candidate_features=lambda r: list(r["close_probs"]) + list(r["drift"]),
            train_seasons=_TRAIN_SEASONS,
            test_season=_TEST_SEASON,
            group_key="league",
            raw_reference=lambda r: list(r["close_probs"]),
            raw_reference_label="rps_raw_closing_quote",
        ),
        "q3_dispersion_beyond_closing": run_incremental_value_study(
            rows,
            baseline_features=lambda r: list(r["close_probs"]),
            candidate_features=lambda r: list(r["close_probs"]) + list(r["dispersion"]),
            train_seasons=_TRAIN_SEASONS,
            test_season=_TEST_SEASON,
            group_key="league",
            raw_reference=lambda r: list(r["close_probs"]),
            raw_reference_label="rps_raw_closing_quote",
        ),
        "q4_drift_beyond_opening": run_incremental_value_study(
            rows,
            baseline_features=lambda r: list(r["open_probs"]),
            candidate_features=lambda r: list(r["open_probs"]) + list(r["drift"]),
            train_seasons=_TRAIN_SEASONS,
            test_season=_TEST_SEASON,
            group_key="league",
            raw_reference=lambda r: list(r["open_probs"]),
            raw_reference_label="rps_raw_opening_quote",
        ),
        "not_a_promotion": (
            "Stage 3 evidence for a directive §51 decision. Does not change the "
            "feature schema, retrain an artifact, or authorize serving."
        ),
    }

    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = _REPORT_DIR / "portfolio-e-market-microstructure-report.json"
    out.write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))
    print(f"\nReport written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
