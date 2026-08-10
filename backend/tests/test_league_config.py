"""Unit tests for league_config.py — ACTIVE_LEAGUES, LEAGUE_BY_ID, helpers."""

from __future__ import annotations

import pytest

from src.core.league_config import (
    ACTIVE_LEAGUES,
    LEAGUE_BY_ID,
    allows_low_evidence,
    get_league_profile,
    is_active_league,
)

_EXPECTED_LEAGUE_IDS = {"EPL", "La Liga", "Bundesliga", "Serie A", "Ligue 1", "Eredivisie", "UCL"}


def test_active_leagues_has_correct_count():
    assert len(ACTIVE_LEAGUES) == 7


def test_active_leagues_contains_all_expected_ids():
    ids = {p.id for p in ACTIVE_LEAGUES}
    assert ids == _EXPECTED_LEAGUE_IDS


def test_league_by_id_matches_active_leagues():
    ids_from_frozenset = {p.id for p in ACTIVE_LEAGUES}
    ids_from_dict = set(LEAGUE_BY_ID.keys())
    assert ids_from_frozenset == ids_from_dict


def test_get_league_profile_known():
    profile = get_league_profile("EPL")
    assert profile is not None
    assert profile.id == "EPL"
    assert profile.name == "Premier League"


def test_get_league_profile_unknown_returns_none():
    profile = get_league_profile("UNKNOWN")
    assert profile is None


def test_get_league_profile_ucl():
    profile = get_league_profile("UCL")
    assert profile is not None
    assert profile.coverage == "SOFT"
    assert profile.low_evidence_allowed is True
    assert profile.caveat_text is not None


def test_is_active_league_true_for_known():
    for lid in _EXPECTED_LEAGUE_IDS:
        assert is_active_league(lid), f"{lid} should be active"


def test_is_active_league_false_for_unknown():
    assert not is_active_league("MLS")
    assert not is_active_league("")
    assert not is_active_league("NONEXISTENT")


def test_allows_low_evidence_ucl():
    assert allows_low_evidence("UCL") is True


def test_allows_low_evidence_full_leagues():
    # Eredivisie is SOFT (pending calibration) so low_evidence IS allowed there
    for lid in ("EPL", "La Liga", "Bundesliga", "Serie A", "Ligue 1"):
        assert allows_low_evidence(lid) is False, f"{lid} should not allow low_evidence"


def test_allows_low_evidence_unknown():
    assert allows_low_evidence("NONEXISTENT") is False


def test_league_profile_dataclass_frozen():
    profile = get_league_profile("EPL")
    with pytest.raises((AttributeError, TypeError)):
        profile.id = "CHANGED"  # type: ignore[misc]


def test_full_coverage_leagues_have_no_caveat():
    for profile in ACTIVE_LEAGUES:
        if profile.coverage == "FULL":
            assert profile.caveat_text is None


def test_all_league_profiles_have_required_fields():
    for profile in ACTIVE_LEAGUES:
        assert profile.id
        assert profile.name
        assert profile.coverage in ("FULL", "SOFT", "EXPERIMENTAL")
        assert profile.model_min_seasons >= 1
        assert isinstance(profile.low_evidence_allowed, bool)
