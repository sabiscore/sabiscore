"""WP-A: tests for backend/scripts/train_on_real_matches.py's odds-column
reader. Not a package (pytest.ini excludes scripts/ from collection and
pythonpath only covers src/), so the module is loaded by inserting its
directory onto sys.path directly, same pattern the script itself already
uses for its own src/ imports."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from train_on_real_matches import _parse_odds_row  # noqa: E402


def test_prefers_single_bookmaker_over_market_average():
    row = {
        "avg_home": "2.10", "avg_draw": "3.40", "avg_away": "3.60",
        "bet365_home": "2.00", "bet365_draw": "3.30", "bet365_away": "3.80",
    }
    assert _parse_odds_row(row) == (2.00, 3.30, 3.80)


def test_market_average_alone_is_not_a_coherent_bookmaker_snapshot():
    row = {"AvgH": "1.90", "AvgD": "3.50", "AvgA": "4.20"}
    assert _parse_odds_row(row) is None


def test_falls_back_to_bet365_when_average_absent():
    row = {"bet365_home": "2.05", "bet365_draw": "3.25", "bet365_away": "3.75"}
    assert _parse_odds_row(row) == (2.05, 3.25, 3.75)


def test_returns_none_when_no_tier_resolves():
    row = {"home_team": "Arsenal", "away_team": "Brighton"}
    assert _parse_odds_row(row) is None


def test_partial_triple_does_not_resolve_a_tier():
    """A tier only counts when all three of home/draw/away are present —
    never mixes a real avg_home with a fallback draw/away from another tier."""
    row = {"avg_home": "2.10", "avg_draw": "", "avg_away": "3.60",
           "bet365_home": "2.00", "bet365_draw": "3.30", "bet365_away": "3.80"}
    assert _parse_odds_row(row) == (2.00, 3.30, 3.80)


def test_malformed_prices_are_rejected_instead_of_clamped():
    row = {"B365H": "0", "B365D": "3.30", "B365A": "3.80"}
    assert _parse_odds_row(row) is None
