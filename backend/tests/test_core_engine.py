from __future__ import annotations

import pytest

from src.schemas.core_engine import CoreEngineAnalyzeRequest, CoreMatchInput
from src.services.core_engine import analyze_core_matches


def _base_match(**overrides) -> dict:
    match = {
        "match_id": "match-1",
        "home_team": "Home",
        "away_team": "Away",
        "competition": "EPL",
        "kickoff_utc": "2026-08-15T15:00:00Z",
        "verified_evidence_providers": [
            "espn", "api_football", "football_data_org", "the_odds_api"
        ],
        "model": {
            "home_probability": 0.65,
            "draw_probability": 0.20,
            "away_probability": 0.15,
            "model_version": "core-v1",
            "calibration_method": "isotonic",
            "calibration_validated": True,
            "generation_certified": True,
            "epistemic_uncertainty": 0.03,
            "aleatoric_uncertainty": 0.10,
            "confidence_tier": "OK",
        },
        "market": {
            "bookmaker": "TestBook",
            "market_type": "1X2",
            "home_odds": 2.0,
            "draw_odds": 3.4,
            "away_odds": 4.8,
            "opening_home_odds": 2.05,
            "opening_draw_odds": 3.35,
            "opening_away_odds": 4.7,
            "captured_at": "2026-08-15T13:30:00Z",
        },
        "signals": {
            "xg_differential": 0.4,
            "xga_differential": -0.2,
            "opponent_adjusted_form": 0.3,
            "club_elo_difference": 75.0,
            "schedule_congestion": 0.1,
            "travel_load": 0.2,
            "confirmed_absences": [],
            "lineup_status": "CONFIRMED",
            "sharp_market_signal": "CONFIRMING",
        },
        "freshness": {
            "model_features_seconds": 300,
            "market_seconds": 120,
            "injury_news_seconds": 400,
            "lineup_seconds": 180,
        },
        "source_status": {
            "model": "VERIFIED",
            "market": "VERIFIED",
            "team_metrics": "VERIFIED",
            "availability": "VERIFIED",
        },
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(match.get(key), dict):
            match[key].update(value)
        else:
            match[key] = value
    return match


def _analyze(*matches: dict):
    payload = CoreEngineAnalyzeRequest(
        matches=[CoreMatchInput.model_validate(match) for match in matches]
    )
    return analyze_core_matches(payload.matches)


def test_partial_preserves_null_value_fields_for_missing_market_price():
    match = _base_match(market={"home_odds": None})

    result = _analyze(match).matches[0]

    assert result.verdict == "PARTIAL"
    assert result.best_market is None
    assert result.edge is None
    assert result.edge_percentage_points is None
    assert result.expected_value is None
    assert result.minimum_acceptable_odds is None
    assert result.stake == "pass"
    assert result.stake_fraction == 0.0
    assert "DATA_GAP: market.home_odds" in result.data_gaps


def test_invalid_market_overround_forces_partial():
    match = _base_match(
        market={"home_odds": 10.0, "draw_odds": 10.0, "away_odds": 10.0}
    )

    result = _analyze(match).matches[0]

    assert result.verdict == "PARTIAL"
    assert "DATA_GAP: INVALID_MARKET_OVERROUND" in result.data_gaps
    assert result.calculation_audit.market_overround == pytest.approx(0.3)


def test_high_conviction_is_allowed_for_clean_tier_one_fixture():
    result = _analyze(_base_match()).matches[0]

    assert result.verdict == "HIGH_CONVICTION"
    assert result.best_market == "HOME_ML"
    assert result.expected_value == pytest.approx(0.3)
    # EPL calibrated policy kelly_cap=0.04; global ceiling is 5% (directive §11/§12).
    assert result.stake_fraction == pytest.approx(0.04)
    assert result.stake == "2.5u"  # label is hardcoded "at-cap" signal regardless of cap value


def test_uncertified_generation_forces_partial_and_zero_stake():
    result = _analyze(
        _base_match(model={"generation_certified": False})
    ).matches[0]

    assert result.verdict == "PARTIAL"
    assert result.stake == "pass"
    assert result.stake_fraction == 0.0
    assert "DATA_GAP: MODEL_GENERATION_UNCERTIFIED" in result.data_gaps


def test_advisory_lineup_and_sharp_signal_do_not_force_partial():
    match = _base_match(
        signals={
            "lineup_status": "PROVISIONAL",
            "sharp_market_signal": "CONFLICTING",
            "confirmed_absences": ["Rotation risk"],
        }
    )

    result = _analyze(match).matches[0]

    assert result.verdict != "PARTIAL"
    assert result.data_gaps == []
    assert any("Lineup status" in risk for risk in result.risks)
    assert any("Sharp market signal" in risk for risk in result.risks)


def test_critical_source_data_gap_still_forces_partial():
    match = _base_match(source_status={"market": "DATA_GAP"})

    result = _analyze(match).matches[0]

    assert result.verdict == "PARTIAL"
    assert "DATA_GAP: market" in result.data_gaps


def test_conflicting_source_status_remains_fail_closed():
    match = _base_match(source_status={"market": "CONFLICTING"})

    result = _analyze(match).matches[0]

    assert result.verdict == "PARTIAL"
    assert result.data_freshness.status == "CONFLICTING"
    assert "CONFLICTING:market" in result.data_gaps


def test_ucl_soft_coverage_caps_high_conviction_to_actionable():
    match = _base_match(competition="UCL")

    result = _analyze(match).matches[0]

    assert result.verdict == "ACTIONABLE"
    assert result.best_market == "HOME_ML"
    assert any("UCL soft coverage" in risk for risk in result.risks)


def test_no_bet_when_clean_market_has_no_positive_edge_or_ev():
    match = _base_match()
    q_home = 1 / match["market"]["home_odds"]
    q_draw = 1 / match["market"]["draw_odds"]
    q_away = 1 / match["market"]["away_odds"]
    overround = q_home + q_draw + q_away
    match["model"].update(
        {
            "home_probability": q_home / overround,
            "draw_probability": q_draw / overround,
            "away_probability": q_away / overround,
            "epistemic_uncertainty": 0.12,
        }
    )

    result = _analyze(match).matches[0]

    assert result.verdict == "NO_BET"
    assert result.stake == "pass"
    assert result.stake_fraction == 0.0


def test_top_opportunities_excludes_pass_verdicts_and_limits_to_three():
    matches = []
    for index, probability in enumerate([0.64, 0.66, 0.68, 0.70], start=1):
        match = _base_match(match_id=f"action-{index}")
        match["model"]["home_probability"] = probability
        match["model"]["draw_probability"] = round((1.0 - probability) * 0.6, 6)
        match["model"]["away_probability"] = round(
            1.0 - match["model"]["home_probability"] - match["model"]["draw_probability"],
            6,
        )
        matches.append(match)

    partial = _base_match(match_id="partial", market={"home_odds": None})
    no_bet = _base_match(match_id="no-bet")
    q_home = 1 / no_bet["market"]["home_odds"]
    q_draw = 1 / no_bet["market"]["draw_odds"]
    q_away = 1 / no_bet["market"]["away_odds"]
    overround = q_home + q_draw + q_away
    no_bet["model"].update(
        {
            "home_probability": q_home / overround,
            "draw_probability": q_draw / overround,
            "away_probability": q_away / overround,
        }
    )

    response = _analyze(*matches, partial, no_bet)

    assert len(response.top_opportunities) == 3
    assert response.top_opportunities == ["action-4", "action-3", "action-2"]
    assert "partial" not in response.top_opportunities
    assert "no-bet" not in response.top_opportunities


def test_speculative_routed_to_batch_watchlist_not_top_opportunities():
    # Sub-threshold positive edge (~2pp, below the 4.2pp actionable floor) with a
    # confirming sharp signal -> SPECULATIVE, never top_opportunities.
    speculative = _base_match(
        match_id="speculative-1",
        model={
            "home_probability": 0.518778,
            "draw_probability": 0.283398,
            "away_probability": 0.197824,
        },
    )
    actionable = _base_match(match_id="action-1")

    response = _analyze(speculative, actionable)
    speculative_result = next(m for m in response.matches if m.match_id == "speculative-1")
    actionable_result = next(m for m in response.matches if m.match_id == "action-1")

    assert speculative_result.verdict == "SPECULATIVE"
    assert speculative_result.watchlist is True
    assert actionable_result.verdict in ("ACTIONABLE", "HIGH_CONVICTION")
    assert actionable_result.watchlist is False

    assert "speculative-1" in response.batch_watchlist
    assert "speculative-1" not in response.top_opportunities
    assert "action-1" in response.top_opportunities
    assert "action-1" not in response.batch_watchlist


# ---------------------------------------------------------------------------
# Provider ceiling gates (directive §9, C-07/08/09/10)
# ---------------------------------------------------------------------------


def test_zero_verified_providers_forces_partial():
    """Explicitly supplying an empty provider list forces PARTIAL (C-07/C-08)."""
    match = _base_match(verified_evidence_providers=[])
    result = _analyze(match).matches[0]
    assert result.verdict == "PARTIAL"
    assert any("NO_VERIFIED_EVIDENCE_PROVIDERS" in g for g in result.data_gaps)


def test_single_provider_caps_at_hold(monkeypatch):
    """One verified provider → max HOLD regardless of edge (C-09)."""
    match = _base_match(verified_evidence_providers=["api_football"])
    result = _analyze(match).matches[0]
    assert result.verdict == "HOLD"
    assert any("single" in r.lower() or "provider" in r.lower() for r in result.risks)


def test_two_providers_caps_below_high_conviction():
    """Two verified providers → max ACTIONABLE; HIGH_CONVICTION requires 4 (C-10)."""
    match = _base_match(verified_evidence_providers=["api_football", "the_odds_api"])
    result = _analyze(match).matches[0]
    assert result.verdict != "HIGH_CONVICTION"
    assert result.verdict in ("ACTIONABLE", "SPECULATIVE", "HOLD", "PARTIAL", "NO_BET")


def test_four_providers_allows_high_conviction():
    """Four verified providers → HIGH_CONVICTION eligible when other gates pass (C-10)."""
    match = _base_match(
        verified_evidence_providers=[
            "football_data_org", "api_football", "the_odds_api", "espn"
        ]
    )
    result = _analyze(match).matches[0]
    assert result.verdict == "HIGH_CONVICTION"


def test_none_providers_forces_partial():
    """verified_evidence_providers=None means caller omitted provenance → PARTIAL (P1-6)."""
    match = _base_match()
    del match["verified_evidence_providers"]  # remove so it defaults to None
    result = _analyze(match).matches[0]
    assert result.verdict == "PARTIAL"
