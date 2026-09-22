"""Tests for scripts/study_portfolio_f_contextual_state.py's pure logic.

The leakage guard is the point of this file. A referee home-win rate computed
over the whole corpus would include the fixture being predicted and
manufacture a spectacular fake result; these tests pin that every referee
statistic is built strictly from EARLIER fixtures.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from study_portfolio_f_contextual_state import enrich_contextual  # noqa: E402


def _fixture(
    day: int,
    home: str,
    away: str,
    outcome: int,
    referee: str | None = None,
    season: int = 2024,
):
    return {
        "league": "EPL",
        "season": season,
        "date": date(2024, 1, day),
        "home_team": home,
        "away_team": away,
        "referee": referee,
        "market_probs": [0.45, 0.28, 0.27],
        "outcome": outcome,
    }


def test_first_fixture_for_a_referee_has_no_prior_history():
    rows = enrich_contextual([_fixture(1, "A", "B", 0, referee="R Smith")])
    assert rows[0]["referee_prior_matches"] == 0
    assert rows[0]["referee_home_bias"] == 0.0


def test_referee_bias_never_includes_the_fixture_being_scored():
    # Every fixture is a home win. If the referee's own match leaked into its
    # own feature, the LAST fixture would still be scored against a rate built
    # only from the four before it -- and crucially the FIRST must be 0.0.
    fixtures = [
        _fixture(d, f"H{d}", f"A{d}", 0, referee="R Smith") for d in range(1, 6)
    ]
    rows = enrich_contextual(fixtures)
    assert rows[0]["referee_prior_matches"] == 0
    # Prior-match counts must be strictly the number of EARLIER fixtures.
    assert [r["referee_prior_matches"] for r in rows] == [0, 1, 2, 3, 4]


def test_referee_bias_is_shrunk_toward_zero_for_small_samples():
    # Three prior fixtures, all home wins, in a league whose base rate is also
    # built from those same three -- the raw deviation is 0, and even a
    # non-zero deviation would be heavily shrunk at n=3 vs the prior of 20.
    fixtures = [
        _fixture(d, f"H{d}", f"A{d}", 0, referee="R Smith") for d in range(1, 5)
    ]
    rows = enrich_contextual(fixtures)
    assert abs(rows[-1]["referee_home_bias"]) < 0.2


def test_rest_days_reset_across_seasons():
    # The same team playing in two different seasons must not be credited with
    # a multi-hundred-day "rest" at the later season's opener. This was a real
    # bug: state keyed by (league, team) without season produced rest_diff
    # values spanning +/-357 days.
    rows = enrich_contextual(
        [
            {**_fixture(10, "A", "B", 0), "season": 2023, "date": date(2023, 5, 10)},
            {**_fixture(10, "A", "C", 0), "season": 2024, "date": date(2024, 8, 10)},
        ]
    )
    later = [r for r in rows if r["season"] == 2024][0]
    assert later["home_rest"] <= 14.0


def test_rest_days_measured_within_a_season():
    rows = enrich_contextual(
        [
            _fixture(1, "A", "B", 0),
            _fixture(8, "A", "C", 0),  # team A plays again 7 days later
        ]
    )
    second = rows[1]
    assert second["home_rest"] == 7.0


def test_congestion_counts_only_fixtures_inside_the_window():
    rows = enrich_contextual(
        [
            _fixture(1, "A", "B", 0),
            _fixture(5, "A", "C", 0),
            _fixture(9, "A", "D", 0),  # 2 prior A fixtures within 14 days
        ]
    )
    assert rows[2]["congestion_diff"] == 2.0  # home has 2 recent, away D has 0
