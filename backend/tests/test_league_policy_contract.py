"""League policy and fail-closed contract tests."""

from __future__ import annotations

import pytest

from src.core.league_policy import (
    LeaguePolicy,
    LeaguePolicyUnavailableError,
    get_league_policy,
)
from src.schemas.betting_intelligence import CompetitionEnum, VerdictEnum
from src.services.betting_intelligence import analyze_match
from tests.test_betting_intelligence_engine import _request
from tests.test_core_engine import _analyze, _base_match


def test_all_supported_league_policies_are_registered() -> None:
    for league_id in (
        "premier_league",
        "la_liga",
        "bundesliga",
        "serie_a",
        "ligue_1",
        "eredivisie",
        "ucl",
    ):
        policy = get_league_policy(league_id)
        assert policy.version
        assert policy.draw_prior > 0
        assert policy.home_advantage_coefficient > 0
        assert 0 < policy.kelly_cap <= 0.05
        assert policy.market_freshness_ttl_seconds > 0
        assert policy.model_feature_freshness_ttl_seconds > 0
        assert policy.lineup_freshness_ttl_seconds > 0
        assert policy.high_conviction_edge_threshold > 0
        assert policy.ece_recalibration_threshold > 0
        assert policy.minimum_calibration_samples > 0


def test_league_policy_aliases_preserve_existing_ids() -> None:
    assert get_league_policy("EPL").league_id == "EPL"
    assert get_league_policy("premier_league").league_id == "EPL"
    assert get_league_policy("LA-LIGA").league_id == "LA_LIGA"
    assert get_league_policy("ucl").league_id == "UCL"


def test_unknown_league_policy_raises() -> None:
    with pytest.raises(LeaguePolicyUnavailableError):
        get_league_policy("unknown_league")


def test_missing_betting_intelligence_policy_fails_closed() -> None:
    # analyze_match imports get_league_policy locally, so remove the registry entry instead.
    original = LeaguePolicy._registry.pop(CompetitionEnum.EPL.value)
    try:
        result = analyze_match(_request(competition=CompetitionEnum.EPL))
    finally:
        LeaguePolicy._registry[CompetitionEnum.EPL.value] = original

    assert result.verdict == VerdictEnum.PARTIAL
    assert result.execution_eligible is False
    assert "DATA_GAP: LEAGUE_POLICY_UNAVAILABLE" in result.data_gaps


def test_missing_core_engine_policy_fails_closed() -> None:
    original = LeaguePolicy._registry.pop("EPL")
    try:
        result = _analyze(_base_match()).matches[0]
    finally:
        LeaguePolicy._registry["EPL"] = original

    assert result.verdict == "PARTIAL"
    assert "DATA_GAP: LEAGUE_POLICY_UNAVAILABLE" in result.data_gaps
