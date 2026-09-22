"""Regression tests for the shared next-season calendar.

Three endpoint modules each carried their own copy of these dates and drifted
up to 14 days early against football-data.org's ``currentSeason.startDate``
(EPL read 2026-08-08 against a real 2026-08-21). These pin the corrected
values and the single-source-of-truth wiring so the three surfaces cannot
disagree again.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.api.endpoints.leagues import _to_item
from src.api.endpoints.offseason import _SEASON_TABLE
from src.api.endpoints.upcoming_matches import _next_season_start
from src.core.league_config import ACTIVE_LEAGUES
from src.core.season_calendar import canonical_key, next_season_start

# Verified 2026-08-04 against GET /v4/competitions/{code} currentSeason.startDate.
PROVIDER_VERIFIED = {
    "EPL": "2026-08-21",
    "LA_LIGA": "2026-08-16",
    "BUNDESLIGA": "2026-08-28",
    "SERIE_A": "2026-08-23",
    "LIGUE_1": "2026-08-22",
    "EREDIVISIE": "2026-08-07",
}


@pytest.mark.parametrize("league,expected", sorted(PROVIDER_VERIFIED.items()))
def test_matches_provider_current_season_start(league: str, expected: str) -> None:
    assert next_season_start(league) == expected


@pytest.mark.parametrize(
    "spelling,canonical",
    [
        ("EPL", "EPL"),
        ("epl", "EPL"),
        ("premier_league", "EPL"),
        ("Premier League", "EPL"),
        ("LA_LIGA", "LA_LIGA"),
        ("La Liga", "LA_LIGA"),
        ("la_liga", "LA_LIGA"),
        ("laliga", "LA_LIGA"),
        ("Serie A", "SERIE_A"),
        ("seriea", "SERIE_A"),
        ("Ligue 1", "LIGUE_1"),
        ("ligue1", "LIGUE_1"),
        ("champions_league", "UCL"),
    ],
)
def test_every_league_vocabulary_folds_to_one_key(
    spelling: str, canonical: str
) -> None:
    """Canonical, display, and slug spellings must all resolve identically."""
    assert canonical_key(spelling) == canonical
    assert next_season_start(spelling) == next_season_start(canonical)


def test_unknown_and_absent_leagues_fall_back_to_a_real_date() -> None:
    for value in (None, "", "   ", "unknown_league_xyz"):
        start = next_season_start(value)
        assert start is not None
        assert date.fromisoformat(start).year >= 2026


def test_leagues_endpoint_serves_the_shared_calendar() -> None:
    """Every ACTIVE_LEAGUES profile resolves — no silent None from a key mismatch."""
    for profile in ACTIVE_LEAGUES:
        item = _to_item(profile)
        assert item.next_season_start is not None, f"{profile.id} resolved to None"
        expected = PROVIDER_VERIFIED.get(canonical_key(profile.id) or "")
        if expected:
            assert item.next_season_start == expected


def test_offseason_and_upcoming_endpoints_agree_with_the_calendar() -> None:
    """The three surfaces must never disagree about the same league again."""
    for league, expected in PROVIDER_VERIFIED.items():
        assert _next_season_start(league) == expected
        slug = league.lower()
        if slug in _SEASON_TABLE:
            assert _SEASON_TABLE[slug]["next_season_start"] == expected


def test_no_supported_league_still_claims_the_old_august_8_opener() -> None:
    """EPL and Ligue 1 both read 2026-08-08 before this fix."""
    for league in ("EPL", "LIGUE_1"):
        assert next_season_start(league) != "2026-08-08"
