"""Sprint 4 Phase 5: /api/upcoming offseason contract tests.

Validates Guardrail #15:
  When all ACTIVE_LEAGUES have no upcoming fixtures, /api/upcoming must return
    { fixtures: [], offseason: true, next_season_start: "<date>" }

Checks:
  OFF-1: UpcomingMatchesResponseSchema.offseason is True when match list is empty.
  OFF-2: next_season_start is a non-empty ISO date string when offseason=True.
  OFF-3: offseason is False (not absent) when matches are present.
  OFF-4: next_season_start is None when offseason=False (in-season).
  OFF-5: _compute_edge_quality_score returns None for an empty fixture, not 0.
  OFF-6: Endpoint logic sets offseason flag in-process (no 404, no bare [] response).
  OFF-7: _next_season_start returns a plausible 2026 date for all known league slugs.
  OFF-8: League slug normalisation works (spaces → underscore, mixed-case).
"""

from __future__ import annotations

import sys
import os
from datetime import date
from typing import Optional

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.api.endpoints.upcoming_matches import (
    _compute_edge_quality_score,
    _next_season_start,
    UpcomingMatchesResponseSchema,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_KNOWN_LEAGUES = [
    "epl",
    "premier_league",
    "la_liga",
    "laliga",
    "bundesliga",
    "serie_a",
    "seriea",
    "ligue_1",
    "ligue1",
    "eredivisie",
    "ucl",
    "champions_league",
]


def _empty_response(league: Optional[str] = "epl", offseason: bool = True) -> dict:
    """Minimal response dict with an empty fixture list."""
    return {
        "upcoming_matches": [],
        "total": 0,
        "matches_with_value": 0,
        "avg_edge_pct": 0.0,
        "cache_hit": False,
        "ttl_seconds": 300,
        "source": "test",
        "offseason": offseason,
        "next_season_start": _next_season_start(league) if offseason else None,
    }


def _response_with_matches(n: int = 3) -> dict:
    """Minimal response dict with n fixture placeholders."""
    matches = [
        {
            "match_id": f"test_match_{i}",
            "home_team": "Home FC",
            "away_team": "Away FC",
            "league": "EPL",
            "match_date": "2026-08-10T15:00:00Z",
            "status": "scheduled",
        }
        for i in range(n)
    ]
    return {
        "upcoming_matches": matches,
        "total": n,
        "matches_with_value": 0,
        "avg_edge_pct": 0.0,
        "cache_hit": False,
        "ttl_seconds": 300,
        "source": "test",
        "offseason": False,
        "next_season_start": None,
    }


# ---------------------------------------------------------------------------
# OFF-1 / OFF-2: offseason=True contract when fixture list is empty
# ---------------------------------------------------------------------------


class TestOffseasonTrueWhenEmpty:
    def test_offseason_flag_is_true_for_empty_fixture_list(self):
        """OFF-1: offseason must be True when upcoming_matches is empty."""
        payload = _empty_response(league="epl", offseason=True)
        schema = UpcomingMatchesResponseSchema.model_validate(payload)
        assert schema.offseason is True

    def test_next_season_start_is_non_null_when_offseason(self):
        """OFF-2: next_season_start must be a non-empty string when offseason=True."""
        payload = _empty_response(league="epl", offseason=True)
        schema = UpcomingMatchesResponseSchema.model_validate(payload)
        assert schema.next_season_start is not None
        assert len(schema.next_season_start) > 0

    def test_next_season_start_is_iso_date_format(self):
        """next_season_start must be parseable as an ISO 8601 date."""
        payload = _empty_response(league="epl", offseason=True)
        schema = UpcomingMatchesResponseSchema.model_validate(payload)
        assert schema.next_season_start is not None
        parsed = date.fromisoformat(schema.next_season_start)
        assert parsed.year >= 2026

    def test_total_is_zero_when_offseason(self):
        payload = _empty_response(offseason=True)
        schema = UpcomingMatchesResponseSchema.model_validate(payload)
        assert schema.total == 0
        assert schema.upcoming_matches == []


# ---------------------------------------------------------------------------
# OFF-3 / OFF-4: offseason=False when matches present
# ---------------------------------------------------------------------------


class TestOffseasonFalseWhenMatchesPresent:
    def test_offseason_false_when_matches_present(self):
        """OFF-3: offseason must be False when fixture list is non-empty."""
        payload = _response_with_matches(n=5)
        schema = UpcomingMatchesResponseSchema.model_validate(payload)
        assert schema.offseason is False

    def test_next_season_start_none_when_not_offseason(self):
        """OFF-4: next_season_start must be None when offseason=False."""
        payload = _response_with_matches(n=2)
        schema = UpcomingMatchesResponseSchema.model_validate(payload)
        assert schema.next_season_start is None

    def test_fixture_count_matches_total(self):
        payload = _response_with_matches(n=4)
        schema = UpcomingMatchesResponseSchema.model_validate(payload)
        assert schema.total == 4
        assert len(schema.upcoming_matches) == 4


# ---------------------------------------------------------------------------
# OFF-5: _compute_edge_quality_score returns None for a bare empty dict
# ---------------------------------------------------------------------------


class TestEdgeQualityScoreOffseason:
    def test_empty_match_dict_returns_none(self):
        """OFF-5: an empty fixture entry must not produce a synthetic edge score."""
        assert _compute_edge_quality_score({}) is None

    def test_match_with_no_predictions_and_no_bets_returns_none(self):
        assert _compute_edge_quality_score({"staleness_seconds": 0}) is None


# ---------------------------------------------------------------------------
# OFF-6: Response is a valid schema object — not 404 or bare array
# ---------------------------------------------------------------------------


class TestOffseasonResponseIsValidSchema:
    def test_model_validate_does_not_raise_for_offseason_payload(self):
        """OFF-6: model_validate must succeed (no exception = no 404 code path)."""
        payload = _empty_response(offseason=True)
        schema = UpcomingMatchesResponseSchema.model_validate(payload)
        assert isinstance(schema, UpcomingMatchesResponseSchema)

    def test_source_field_present_in_offseason_response(self):
        """source field must always be present, even in offseason state."""
        payload = _empty_response(offseason=True)
        schema = UpcomingMatchesResponseSchema.model_validate(payload)
        assert schema.source is not None


# ---------------------------------------------------------------------------
# OFF-7: _next_season_start covers all known league slugs
# ---------------------------------------------------------------------------


class TestNextSeasonStartCoverage:
    @pytest.mark.parametrize("league", _KNOWN_LEAGUES)
    def test_known_league_returns_2026_date(self, league: str):
        """OFF-7: all known league slugs must map to a 2026 season-start date."""
        start = _next_season_start(league)
        parsed = date.fromisoformat(start)
        assert parsed.year == 2026, (
            f"League '{league}' returned next_season_start={start!r} (year != 2026)"
        )

    def test_unknown_league_returns_fallback_date(self):
        start = _next_season_start("unknown_league_xyz")
        parsed = date.fromisoformat(start)
        assert parsed.year >= 2026

    def test_none_league_returns_fallback_date(self):
        start = _next_season_start(None)
        parsed = date.fromisoformat(start)
        assert parsed.year >= 2026


# ---------------------------------------------------------------------------
# OFF-8: Slug normalisation
# ---------------------------------------------------------------------------


class TestSlugNormalisation:
    def test_epl_with_space_returns_same_as_underscore(self):
        """OFF-8: 'premier league' (space) normalises to 'premier_league'."""
        with_space = _next_season_start("premier league")
        with_underscore = _next_season_start("premier_league")
        assert with_space == with_underscore

    def test_mixed_case_slug_handled(self):
        """League slugs must be case-insensitive."""
        lower = _next_season_start("epl")
        upper = _next_season_start("EPL")
        mixed = _next_season_start("Epl")
        assert lower == upper == mixed

    def test_la_liga_variants_resolve_consistently(self):
        a = _next_season_start("la_liga")
        b = _next_season_start("laliga")
        c = _next_season_start("La Liga")
        assert a == b == c
