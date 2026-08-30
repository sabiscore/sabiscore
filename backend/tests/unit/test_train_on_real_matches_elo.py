"""docs/DEBT.md item 48: build_dataset() must train on REAL replayed Elo,
not the constant registry default every prior candidate (including the
served v5_phase7 generation) trained on.

Not a package (pytest.ini excludes scripts/ from collection and pythonpath
only covers src/), so the module is loaded by inserting its directory onto
sys.path directly — same pattern as test_train_on_real_matches_market_block.py.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import train_on_real_matches  # noqa: E402

_LEAGUE = "EPL"
_KICKOFF = datetime(2026, 1, 1, 15, 0, 0)
_ELO_DIFF_IDX = train_on_real_matches.APEX_FEATURES_68.index("elo_difference")
_ELO_ADJ_IDX = train_on_real_matches.APEX_FEATURES_68.index("elo_league_adjusted")


def _row(i: int, league: str, season: str, home: str, away: str, hg: int, ag: int) -> dict:
    return {
        "league": league, "season": season, "date": _KICKOFF + timedelta(days=i),
        "home": home, "away": away, "hg": hg, "ag": ag,
        # build_dataset() only appends a row when market_features resolves
        # (WP-A: opening-odds gate) — an arbitrary, valid, coherent-tier
        # 1X2 triple, not real market evidence.
        "odds": (2.00, 3.20, 3.80),
    }


def _synthetic_corpus() -> list[dict]:
    """Team A wins 5 straight warm-ups; Team B loses 5 straight warm-ups; then
    A meets B once both sides have >=5 prior matches (TeamHistory's gate) —
    both sides' Elo ratings are now real and divergent."""
    matches = []
    i = 0
    for opp in ("X1", "X2", "X3", "X4", "X5"):
        matches.append(_row(i, _LEAGUE, "2526", "Team A", opp, 3, 0))
        i += 1
    for opp in ("Y1", "Y2", "Y3", "Y4", "Y5"):
        matches.append(_row(i, _LEAGUE, "2526", opp, "Team B", 3, 0))
        i += 1
    matches.append(_row(i, _LEAGUE, "2526", "Team A", "Team B", 1, 1))
    return matches


def test_build_dataset_trains_on_real_nonconstant_elo() -> None:
    dataset = train_on_real_matches.build_dataset(_synthetic_corpus())
    rows = dataset[_LEAGUE]["X"]
    assert rows, "expected at least one emitted row (both sides have >=5 prior matches)"

    elo_diffs = [row[_ELO_DIFF_IDX] for row in rows]
    # The defect this closes: every row was elo_difference == 0.0 (the
    # registry default). A team that won 5 straight vs one that lost 5
    # straight must now show a real, non-zero rating gap.
    assert any(diff != 0.0 for diff in elo_diffs), (
        "elo_difference is still a constant registry default — the Elo "
        "replay is not wired into build_dataset()"
    )
    # Team A (5 straight wins) must be rated above Team B (5 straight losses).
    assert elo_diffs[-1] > 0.0

    # elo_league_adjusted stays at its permanent registry default (0.0) —
    # ATE-review policy, never computed live.
    assert all(row[_ELO_ADJ_IDX] == 0.0 for row in rows)


def test_incumbent_feature_copy_also_carries_real_elo() -> None:
    """X_incumbent (the legacy-schema copy used for comparison) merges from
    the same `features` dict after the Elo update, so it must agree."""
    dataset = train_on_real_matches.build_dataset(_synthetic_corpus())
    elo_idx = train_on_real_matches.CANONICAL_FEATURES_68.index("elo_difference")
    incumbent_rows = dataset[_LEAGUE]["X_incumbent"]
    assert incumbent_rows and incumbent_rows[-1][elo_idx] > 0.0
