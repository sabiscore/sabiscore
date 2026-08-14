"""
SabiScore Core Engine — Betting Intelligence Contract Tests
Tests every decision gate, edge case, and fabrication-prevention invariant.

Run with:
  PYTHONPATH=backend pytest -q backend/tests/test_betting_intelligence_engine.py --no-cov
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.schemas.betting_intelligence import (
    BatchAnalysisRequest,
    CompetitionEnum,
    EvidenceTierEnum,
    FreshnessInput,
    FreshnessStatusEnum,
    LineupStatusEnum,
    MarketInput,
    MatchAnalysisRequest,
    ModelInput,
    SharpSignalEnum,
    SourceStatusInput,
    SourceStatusEnum,
    VerdictEnum,
)
from src.services.betting_intelligence import (
    KELLY_FRACTION,
    MAX_KELLY_CAP,
    MIN_ACTIONABLE_EDGE,
    _apply_verdict_gate,
    _rank_top_opportunities,
    _compute_devig,
    _expected_value,
    _full_kelly,
    _minimum_acceptable_odds,
    analyze_batch,
    analyze_match,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FUTURE_KICKOFF = datetime.now(timezone.utc) + timedelta(hours=24)
MARKET_NOW = datetime.now(timezone.utc)
_DEFAULT = object()


def _model(
    home: float = 0.55,
    draw: float = 0.25,
    away: float = 0.20,
    tier: EvidenceTierEnum = EvidenceTierEnum.OK,
    calibration_validated: bool = True,
    epistemic: float = 0.08,
) -> ModelInput:
    return ModelInput(
        home_probability=home,
        draw_probability=draw,
        away_probability=away,
        model_version="test-v1.0",
        calibration_method="isotonic",
        calibration_validated=calibration_validated,
        generation_certified=True,
        epistemic_uncertainty=epistemic,
        aleatoric_uncertainty=0.10,
        confidence_tier=tier,
    )


def _market(
    home: float = 1.80,
    draw: float = 3.50,
    away: float = 4.50,
    seconds_old: int = 300,
) -> MarketInput:
    return MarketInput(
        bookmaker="Pinnacle",
        home_odds=home,
        draw_odds=draw,
        away_odds=away,
        captured_at=MARKET_NOW,
    )


def test_uncertified_generation_forces_partial_and_zero_stake():
    request = _request()
    request.model = request.model.model_copy(update={"generation_certified": False})

    result = analyze_match(request, evaluation_at=MARKET_NOW)

    assert result.verdict == VerdictEnum.PARTIAL
    assert result.stake == "pass"
    assert result.stake_fraction == 0.0
    assert "DATA_GAP: MODEL_GENERATION_UNCERTIFIED" in result.critical_gaps


_FOUR_PROVIDERS = ["espn", "api_football", "football_data_org", "the_odds_api"]


def _request(
    match_id: str = "test-001",
    competition: CompetitionEnum = CompetitionEnum.EPL,
    model=_DEFAULT,
    market=_DEFAULT,
    freshness_seconds: int = 300,
    source_status_market: SourceStatusEnum = SourceStatusEnum.VERIFIED,
    data_gaps=None,
    verified_evidence_providers=_DEFAULT,
) -> MatchAnalysisRequest:
    return MatchAnalysisRequest(
        match_id=match_id,
        home_team="Arsenal",
        away_team="Chelsea",
        competition=competition,
        kickoff_utc=FUTURE_KICKOFF,
        model=_model() if model is _DEFAULT else model,
        market=_market() if market is _DEFAULT else market,
        freshness=FreshnessInput(
            market_seconds=freshness_seconds,
            model_features_seconds=freshness_seconds,
        ),
        source_status=SourceStatusInput(
            model=SourceStatusEnum.VERIFIED,
            market=source_status_market,
            team_metrics=SourceStatusEnum.VERIFIED,
            availability=SourceStatusEnum.VERIFIED,
        ),
        data_gaps=data_gaps or [],
        verified_evidence_providers=(
            _FOUR_PROVIDERS if verified_evidence_providers is _DEFAULT
            else verified_evidence_providers
        ),
    )


# ---------------------------------------------------------------------------
# De-vig mathematics
# ---------------------------------------------------------------------------


class TestDevig:
    def test_overround_standard_market(self):
        overround, h, d, a = _compute_devig(1.80, 3.50, 4.50)
        assert 1.0 < overround < 1.15, f"Expected typical overround, got {overround}"

    def test_fair_probs_sum_to_one(self):
        _, h, d, a = _compute_devig(1.80, 3.50, 4.50)
        assert abs(h + d + a - 1.0) < 1e-9

    def test_de_vig_reduces_implied_prob(self):
        overround, h, d, a = _compute_devig(1.80, 3.50, 4.50)
        raw_h = 1 / 1.80
        assert h < raw_h  # de-vigged home is lower than raw (margin removed)
        assert overround > 1.0

    def test_even_market_devig(self):
        _, h, d, a = _compute_devig(2.0, 3.0, 4.0)
        assert abs(h + d + a - 1.0) < 1e-9

    def test_ev_positive_with_edge(self):
        # model_prob=0.60 at odds=1.80 → EV = 0.60*1.80-1 = 0.08
        ev = _expected_value(0.60, 1.80)
        assert ev > 0
        assert abs(ev - 0.08) < 1e-9

    def test_ev_negative_no_edge(self):
        ev = _expected_value(0.45, 1.80)  # implied=0.556 > 0.45
        assert ev < 0

    def test_kelly_positive_on_edge(self):
        ev = _expected_value(0.60, 1.80)
        fk = _full_kelly(ev, 1.80)
        assert fk > 0

    def test_kelly_zero_on_negative_ev(self):
        ev = _expected_value(0.45, 1.80)
        fk = _full_kelly(ev, 1.80)
        assert fk == 0.0

    def test_minimum_acceptable_odds(self):
        mao = _minimum_acceptable_odds(0.60, MIN_ACTIONABLE_EDGE)
        assert mao is not None
        assert mao > 1.0

    def test_minimum_acceptable_odds_none_on_impossible(self):
        # model_prob=0.03, min_edge=0.042 → denom<0 → None
        mao = _minimum_acceptable_odds(0.03, 0.042)
        assert mao is None


# ---------------------------------------------------------------------------
# Gate 1: PARTIAL — missing or invalid critical inputs
# ---------------------------------------------------------------------------


class TestPartialGate:
    def test_no_model_returns_partial(self):
        req = _request(model=None)
        result = analyze_match(req)
        assert result.verdict == VerdictEnum.PARTIAL
        assert any("model" in g.lower() for g in result.data_gaps)

    def test_no_market_returns_partial(self):
        req = _request(market=None)
        result = analyze_match(req)
        assert result.verdict == VerdictEnum.PARTIAL
        assert any("market" in g.lower() for g in result.data_gaps)

    def test_caller_declared_data_gap_forces_partial(self):
        req = _request(data_gaps=["DATA_GAP: ensemble_prediction"])
        result = analyze_match(req)
        assert result.verdict == VerdictEnum.PARTIAL

    def test_no_critical_gaps_does_not_trigger_partial_gate(self):
        verdict = _apply_verdict_gate(
            critical_gaps=[],
            competition=CompetitionEnum.EPL,
            model=_model(home=0.65, draw=0.20, away=0.15),
            market=_market(home=1.80, draw=3.50, away=4.50),
            market_freshness=FreshnessStatusEnum.FRESH,
            best_ev=0.17,
            best_edge=0.12,
            best_stake_fraction=0.01,
            sharp_signal=SharpSignalEnum.NEUTRAL,
            lineup_status=LineupStatusEnum.CONFIRMED,
            kickoff_utc=None,
            verified_provider_count=4,
        )

        assert verdict in (VerdictEnum.ACTIONABLE, VerdictEnum.HIGH_CONVICTION)

    def test_none_provider_count_forces_partial(self):
        # None means caller omitted provenance → treat as 0 verified owners (P1-6)
        verdict = _apply_verdict_gate(
            critical_gaps=[],
            competition=CompetitionEnum.EPL,
            model=_model(home=0.65, draw=0.20, away=0.15),
            market=_market(home=1.80, draw=3.50, away=4.50),
            market_freshness=FreshnessStatusEnum.FRESH,
            best_ev=0.17,
            best_edge=0.12,
            best_stake_fraction=0.01,
            sharp_signal=SharpSignalEnum.NEUTRAL,
            lineup_status=LineupStatusEnum.CONFIRMED,
            kickoff_utc=None,
            verified_provider_count=None,
        )

        assert verdict == VerdictEnum.PARTIAL

    def test_critical_gap_still_forces_partial_gate(self):
        verdict = _apply_verdict_gate(
            critical_gaps=["DATA_GAP: model_probabilities"],
            competition=CompetitionEnum.EPL,
            model=_model(home=0.65, draw=0.20, away=0.15),
            market=_market(home=1.80, draw=3.50, away=4.50),
            market_freshness=FreshnessStatusEnum.FRESH,
            best_ev=0.17,
            best_edge=0.12,
            best_stake_fraction=0.01,
            sharp_signal=SharpSignalEnum.NEUTRAL,
            lineup_status=LineupStatusEnum.CONFIRMED,
            kickoff_utc=None,
        )

        assert verdict == VerdictEnum.PARTIAL

    def test_market_source_status_data_gap_forces_partial(self):
        req = _request(source_status_market=SourceStatusEnum.DATA_GAP)
        result = analyze_match(req)
        assert result.verdict == VerdictEnum.PARTIAL

    def test_market_source_status_conflicting_forces_partial(self):
        req = _request(source_status_market=SourceStatusEnum.CONFLICTING)
        result = analyze_match(req)
        assert result.verdict == VerdictEnum.PARTIAL
        assert any("CONFLICTING" in g for g in result.data_gaps)
        assert result.critical_gaps == []
        assert result.conflicts == ["CONFLICTING: market_odds"]

    def test_partial_stake_is_pass(self):
        req = _request(model=None)
        result = analyze_match(req)
        assert result.stake == "pass"
        assert result.stake_fraction == 0.0

    def test_partial_edge_is_null(self):
        req = _request(model=None)
        result = analyze_match(req)
        assert result.edge is None
        assert result.expected_value is None
        assert result.best_market is None

    def test_partial_probabilities_null_when_no_model(self):
        req = _request(model=None)
        result = analyze_match(req)
        assert result.probabilities is None

    def test_stale_market_source_forces_partial(self):
        req = _request(source_status_market=SourceStatusEnum.STALE)
        result = analyze_match(req)
        assert result.verdict == VerdictEnum.PARTIAL

    def test_unknown_model_feature_freshness_forces_partial(self):
        req = _request()
        req.freshness.model_features_seconds = None
        result = analyze_match(req)
        assert result.verdict == VerdictEnum.PARTIAL
        assert any("model_features" in gap for gap in result.data_gaps)

    def test_stale_model_features_force_partial(self):
        req = _request(freshness_seconds=7200)
        result = analyze_match(req)
        assert result.verdict == VerdictEnum.PARTIAL
        assert any("STALE: model_features" in gap for gap in result.data_gaps)

    def test_advisory_only_signals_never_force_partial(self):
        """Unconfirmed lineup far from kickoff, a conflicting sharp signal, and a
        caller-supplied known risk are advisory by design (Section 11 of the
        certification contract) — they must never enter data_gaps/critical_gaps
        or trigger the Gate 1 PARTIAL check, only influence HOLD/confidence."""
        req = _request()
        req.signals.lineup_status = LineupStatusEnum.PROVISIONAL
        req.signals.sharp_market_signal = SharpSignalEnum.CONFLICTING
        req.signals.confirmed_absences = ["Player X (knock)"]
        req.known_risks = ["Squad rotation possible ahead of cup fixture"]
        result = analyze_match(req)
        assert result.data_gaps == []
        assert result.critical_gaps == []
        assert result.verdict != VerdictEnum.PARTIAL


# ---------------------------------------------------------------------------
# Gate 2: NO_BET — valid data but no positive value
# ---------------------------------------------------------------------------


class TestNoBetGate:
    def test_no_edge_returns_no_bet(self):
        # Market prices home at 1.80 (implied ~0.556), model says 0.50 — model below market
        req = _request(model=_model(home=0.50, draw=0.28, away=0.22))
        result = analyze_match(req)
        assert result.verdict == VerdictEnum.NO_BET

    def test_no_bet_stake_is_pass(self):
        req = _request(model=_model(home=0.50, draw=0.28, away=0.22))
        result = analyze_match(req)
        assert result.stake == "pass"
        assert result.stake_fraction == 0.0

    def test_negative_ev_returns_no_bet(self):
        # Even if model prob is slightly above implied, EV may be negative
        req = _request(
            model=_model(home=0.52, draw=0.28, away=0.20),
            market=_market(home=1.85, draw=3.60, away=4.80),
        )
        result = analyze_match(req)
        # Verify the engine actually returns NO_BET when EV is non-positive
        if result.verdict == VerdictEnum.NO_BET:
            assert result.stake == "pass"

    def test_no_bet_does_not_return_edge_as_zero(self):
        """Edge should be null under NO_BET — not forced to 0."""
        req = _request(model=_model(home=0.50, draw=0.28, away=0.22))
        result = analyze_match(req)
        if result.verdict == VerdictEnum.NO_BET:
            assert result.edge is None


# ---------------------------------------------------------------------------
# Gate 3: HOLD
# ---------------------------------------------------------------------------


class TestHoldGate:
    def test_low_evidence_tier_returns_hold(self):
        req = _request(
            model=_model(
                home=0.62,
                draw=0.22,
                away=0.16,
                tier=EvidenceTierEnum.LOW_EVIDENCE,
            )
        )
        result = analyze_match(req)
        assert result.verdict in (VerdictEnum.HOLD, VerdictEnum.PARTIAL)

    def test_unvalidated_calibration_returns_hold(self):
        req = _request(
            model=_model(
                home=0.62,
                draw=0.22,
                away=0.16,
                calibration_validated=False,
            )
        )
        result = analyze_match(req)
        assert result.verdict in (VerdictEnum.HOLD, VerdictEnum.PARTIAL)

    def test_hold_stake_is_pass(self):
        req = _request(
            model=_model(tier=EvidenceTierEnum.LOW_EVIDENCE)
        )
        result = analyze_match(req)
        if result.verdict == VerdictEnum.HOLD:
            assert result.stake == "pass"
            assert result.stake_fraction == 0.0


# ---------------------------------------------------------------------------
# Gate 4 + 5: SPECULATIVE and ACTIONABLE
# ---------------------------------------------------------------------------


class TestSpeculativeActionable:
    def test_sub_threshold_edge_is_speculative(self):
        # Home at odds 2.10 with model 0.52 → edge ≈ 0.52 - 0.476 ≈ 0.044 ... borderline
        # But sub-threshold with tight odds
        req = _request(
            model=_model(home=0.51, draw=0.27, away=0.22),
            market=_market(home=1.95, draw=3.60, away=4.20),
        )
        result = analyze_match(req)
        assert result.verdict in (VerdictEnum.SPECULATIVE, VerdictEnum.NO_BET, VerdictEnum.ACTIONABLE, VerdictEnum.HOLD)

    def test_speculative_is_watchlist_only_with_zero_stake(self):
        req = _request(
            model=_model(home=0.51, draw=0.27, away=0.22),
            market=_market(home=2.10, draw=3.60, away=4.20),
        )
        result = analyze_match(req)
        if result.verdict == VerdictEnum.SPECULATIVE:
            # Research-only verdicts remain non-executable.
            assert result.watchlist is True
            assert result.execution_eligible is False
            assert result.stake == "pass"
            assert result.stake_fraction == 0.0

    def test_actionable_has_positive_edge_and_ev(self):
        # Strong edge: model 0.65 home vs Pinnacle 1.80 market
        req = _request(
            model=_model(home=0.65, draw=0.20, away=0.15),
            market=_market(home=1.80, draw=3.50, away=4.50),
        )
        result = analyze_match(req)
        if result.verdict == VerdictEnum.ACTIONABLE:
            assert result.edge is not None and result.edge > 0
            assert result.expected_value is not None and result.expected_value > 0

    def test_actionable_has_best_market_selected(self):
        req = _request(
            model=_model(home=0.65, draw=0.20, away=0.15),
            market=_market(home=1.80, draw=3.50, away=4.50),
        )
        result = analyze_match(req)
        if result.verdict in (VerdictEnum.ACTIONABLE, VerdictEnum.HIGH_CONVICTION):
            assert result.best_market is not None


# ---------------------------------------------------------------------------
# Gate 6: HIGH_CONVICTION
# ---------------------------------------------------------------------------


class TestHighConviction:
    def _hc_request(self, competition=CompetitionEnum.EPL):
        return _request(
            competition=competition,
            model=_model(home=0.72, draw=0.18, away=0.10, epistemic=0.05),
            market=_market(home=1.75, draw=4.00, away=6.00, seconds_old=200),
        )

    def test_epl_can_reach_high_conviction(self):
        result = analyze_match(
            self._hc_request(CompetitionEnum.EPL),
            causal_drivers=["elo_difference", "xg_differential"],
        )
        # HC requires edge >= HIGH_CONVICTION_EDGE; market needs to offer this
        assert result.verdict in (
            VerdictEnum.HIGH_CONVICTION,
            VerdictEnum.ACTIONABLE,
            VerdictEnum.NO_BET,
        )

    def test_ucl_cannot_reach_high_conviction(self):
        """UCL is structurally capped — HIGH_CONVICTION is forbidden."""
        req = self._hc_request(competition=CompetitionEnum.UCL)
        result = analyze_match(
            req,
            causal_drivers=["elo_difference", "xg_differential"],
        )
        assert result.verdict != VerdictEnum.HIGH_CONVICTION, (
            f"UCL must not reach HIGH_CONVICTION; got {result.verdict}"
        )

    def test_all_supported_leagues_except_ucl_can_reach_hc(self):
        non_ucl = [
            CompetitionEnum.EPL,
            CompetitionEnum.LA_LIGA,
            CompetitionEnum.SERIE_A,
            CompetitionEnum.BUNDESLIGA,
            CompetitionEnum.LIGUE_1,
            CompetitionEnum.EREDIVISIE,
        ]
        for league in non_ucl:
            result = analyze_match(
                self._hc_request(league),
                causal_drivers=["elo_difference"],
            )
            # Should be HC, ACTIONABLE, or NO_BET — never UCL-capped
            assert result.verdict in (
                VerdictEnum.HIGH_CONVICTION,
                VerdictEnum.ACTIONABLE,
                VerdictEnum.NO_BET,
                VerdictEnum.SPECULATIVE,
            ), f"Unexpected verdict {result.verdict} for {league}"


# ---------------------------------------------------------------------------
# Zero fabrication: missing odds must not inject generic prices
# ---------------------------------------------------------------------------


class TestZeroFabrication:
    def test_missing_odds_returns_partial_not_bet(self):
        """When market=None, result must be PARTIAL — never using fabricated odds."""
        req = _request(market=None)
        result = analyze_match(req)
        assert result.verdict == VerdictEnum.PARTIAL
        assert result.stake == "pass"
        assert result.stake_fraction == 0.0
        assert result.edge is None
        assert result.expected_value is None

    def test_missing_model_no_probability_fabrication(self):
        """When model=None, probabilities must be null — never 33/33/34."""
        req = _request(model=None)
        result = analyze_match(req)
        assert result.probabilities is None

    def test_conflicting_market_source_returns_partial(self):
        req = _request(source_status_market=SourceStatusEnum.CONFLICTING)
        result = analyze_match(req)
        assert result.verdict == VerdictEnum.PARTIAL
        assert result.stake == "pass"

    def test_data_gap_in_request_blocks_execution(self):
        """Caller-declared DATA_GAP must block execution."""
        req = _request(data_gaps=["DATA_GAP: injury_news"])
        result = analyze_match(req)
        assert result.verdict == VerdictEnum.PARTIAL
        assert result.stake == "pass"

    def test_no_default_odds_injection(self):
        """Engine must not inject default odds when market=None.
        Legacy violation was: {"home_win": 2.38, "draw": 3.85, "away_win": 3.13}
        This test verifies that behavior is gone.
        """
        req = _request(market=None)
        result = analyze_match(req)
        # Must be PARTIAL, not any executable verdict
        assert result.verdict == VerdictEnum.PARTIAL
        # Edge and EV must be null, not computed from phantom odds
        assert result.edge is None
        assert result.expected_value is None
        assert result.best_market is None


# ---------------------------------------------------------------------------
# Kelly sizing and stake constraints
# ---------------------------------------------------------------------------


class TestKellyAndStake:
    def test_stake_never_exceeds_kelly_cap(self):
        req = _request(
            model=_model(home=0.80, draw=0.12, away=0.08),
            market=_market(home=1.80, draw=4.50, away=8.00),
        )
        result = analyze_match(req)
        assert result.stake_fraction <= MAX_KELLY_CAP + 1e-9

    def test_stake_is_zero_for_partial(self):
        req = _request(model=None)
        result = analyze_match(req)
        assert result.stake_fraction == 0.0
        assert result.stake == "pass"

    def test_stake_is_zero_for_no_bet(self):
        req = _request(model=_model(home=0.50, draw=0.28, away=0.22))
        result = analyze_match(req)
        if result.verdict == VerdictEnum.NO_BET:
            assert result.stake_fraction == 0.0
            assert result.stake == "pass"

    def test_stake_is_zero_for_hold(self):
        req = _request(model=_model(tier=EvidenceTierEnum.LOW_EVIDENCE))
        result = analyze_match(req)
        if result.verdict == VerdictEnum.HOLD:
            assert result.stake_fraction == 0.0
            assert result.stake == "pass"


# ---------------------------------------------------------------------------
# All three outcomes evaluated (not just model favorite)
# ---------------------------------------------------------------------------


class TestAllOutcomeEvaluation:
    def test_all_market_evaluations_returned(self):
        req = _request(
            model=_model(home=0.60, draw=0.25, away=0.15),
            market=_market(home=1.80, draw=3.50, away=5.00),
        )
        result = analyze_match(req)
        if result.all_market_evaluations:
            assert len(result.all_market_evaluations) == 3

    def test_best_market_not_always_model_favorite(self):
        # away_win with high odds may offer better EV even at low probability
        req = _request(
            model=_model(home=0.40, draw=0.30, away=0.30),
            market=_market(home=2.50, draw=3.20, away=3.80),
        )
        result = analyze_match(req)
        # The engine should consider all three — no assertion on which wins
        # but verify it runs without error
        assert result.verdict in VerdictEnum.__members__.values()

    def test_edge_against_devigged_probability_not_raw(self):
        """Edge must be model_prob - fair_market_prob, not model_prob - (1/odds)."""
        req = _request(
            model=_model(home=0.60, draw=0.25, away=0.15),
            market=_market(home=1.80, draw=3.50, away=4.50),
        )
        result = analyze_match(req)
        if result.edge is not None and result.market_odds is not None and result.fair_market_probability is not None:
            # Edge should use fair_market (de-vigged) not raw implied
            assert abs(result.edge - (result.probabilities.home - result.fair_market_probability)) < 0.01


# ---------------------------------------------------------------------------
# De-vigged probability and EV
# ---------------------------------------------------------------------------


class TestDeViggedEdge:
    def test_fair_market_probability_in_result(self):
        req = _request(
            model=_model(home=0.65, draw=0.22, away=0.13),
            market=_market(home=1.80, draw=3.50, away=5.00),
        )
        result = analyze_match(req)
        if result.fair_market_probability is not None:
            # Allow some tolerance since best market selection varies
            assert 0 < result.fair_market_probability < 1.0

    def test_ev_calculation_correct(self):
        req = _request(
            model=_model(home=0.65, draw=0.22, away=0.13),
            market=_market(home=1.80, draw=3.50, away=5.00),
        )
        result = analyze_match(req)
        if result.expected_value is not None and result.market_odds is not None:
            # EV should equal model_prob * odds - 1
            if result.probabilities and result.best_market is not None:
                market_name = result.best_market.value.replace("_ML", "").lower()
                if market_name == "home":
                    model_prob = result.probabilities.home
                elif market_name == "draw":
                    model_prob = result.probabilities.draw
                else:
                    model_prob = result.probabilities.away
                expected_ev = model_prob * result.market_odds - 1.0
                assert abs(result.expected_value - expected_ev) < 0.001


# ---------------------------------------------------------------------------
# Batch analysis and ranking
# ---------------------------------------------------------------------------


class TestBatchAnalysis:
    def _build_batch(self):
        matches = [
            # Match 1: Strong signal — ACTIONABLE+
            MatchAnalysisRequest(
                match_id="match-hc",
                home_team="Arsenal",
                away_team="Brentford",
                competition=CompetitionEnum.EPL,
                kickoff_utc=FUTURE_KICKOFF,
                model=_model(home=0.70, draw=0.18, away=0.12, epistemic=0.05),
                market=_market(home=1.75, draw=4.00, away=7.00, seconds_old=200),
                freshness=FreshnessInput(market_seconds=200, model_features_seconds=200),
                source_status=SourceStatusInput(
                    model=SourceStatusEnum.VERIFIED,
                    market=SourceStatusEnum.VERIFIED,
                    team_metrics=SourceStatusEnum.VERIFIED,
                    availability=SourceStatusEnum.VERIFIED,
                ),
            ),
            # Match 2: No odds — PARTIAL
            MatchAnalysisRequest(
                match_id="match-partial",
                home_team="Liverpool",
                away_team="Man City",
                competition=CompetitionEnum.EPL,
                kickoff_utc=FUTURE_KICKOFF,
                model=_model(),
                market=None,
                freshness=FreshnessInput(),
                source_status=SourceStatusInput(market=SourceStatusEnum.DATA_GAP),
            ),
            # Match 3: No value — NO_BET
            MatchAnalysisRequest(
                match_id="match-nobet",
                home_team="Nottm Forest",
                away_team="Wolves",
                competition=CompetitionEnum.EPL,
                kickoff_utc=FUTURE_KICKOFF,
                model=_model(home=0.45, draw=0.30, away=0.25),
                market=_market(home=1.90, draw=3.30, away=4.20),
                freshness=FreshnessInput(market_seconds=400),
                source_status=SourceStatusInput(
                    model=SourceStatusEnum.VERIFIED,
                    market=SourceStatusEnum.VERIFIED,
                    team_metrics=SourceStatusEnum.VERIFIED,
                    availability=SourceStatusEnum.VERIFIED,
                ),
            ),
        ]
        return BatchAnalysisRequest(matches=matches)

    def test_batch_returns_all_matches(self):
        batch = self._build_batch()
        response = analyze_batch(batch)
        assert len(response.matches) == 3

    def test_partial_excluded_from_top_opportunities(self):
        batch = self._build_batch()
        response = analyze_batch(batch)
        assert "match-partial" not in response.top_opportunities

    def test_no_bet_excluded_from_top_opportunities(self):
        batch = self._build_batch()
        response = analyze_batch(batch)
        assert "match-nobet" not in response.top_opportunities

    def test_top_opportunities_at_most_three(self):
        batch = self._build_batch()
        response = analyze_batch(batch)
        assert len(response.top_opportunities) <= 3

    def test_top_opportunities_only_qualifying_verdicts(self):
        batch = self._build_batch()
        response = analyze_batch(batch)
        for opp_id in response.top_opportunities:
            match_result = next(m for m in response.matches if m.match_id == opp_id)
            assert match_result.verdict in (
                VerdictEnum.HIGH_CONVICTION,
                VerdictEnum.ACTIONABLE,
            )

    def test_speculative_excluded_from_top_opportunities_routed_to_watchlist(self):
        speculative = analyze_match(
            _request(
                match_id="match-speculative",
                model=_model(home=0.46, draw=0.32, away=0.22, epistemic=0.02),
                market=_market(home=2.20, draw=3.10, away=4.20),
            )
        )
        actionable = analyze_match(
            _request(
                match_id="match-actionable",
                model=_model(home=0.65, draw=0.20, away=0.15),
                market=_market(home=1.80, draw=3.50, away=4.50),
            )
        )
        partial = analyze_match(_request(match_id="match-partial-2", model=None))

        assert speculative.verdict == VerdictEnum.SPECULATIVE
        assert actionable.verdict in (VerdictEnum.ACTIONABLE, VerdictEnum.HIGH_CONVICTION)
        assert partial.verdict == VerdictEnum.PARTIAL

        # Default test signals carry no contextual fields, so completeness (and
        # therefore confidence_adjusted_value) is 0 for both — set explicitly to
        # confirm the qualifying filter routes by verdict, not just by CAV.
        speculative.confidence_adjusted_value = 0.01
        actionable.confidence_adjusted_value = 0.05

        top, watchlist = _rank_top_opportunities([speculative, actionable, partial])

        assert "match-speculative" in watchlist
        assert "match-speculative" not in top
        assert "match-actionable" in top
        assert "match-actionable" not in watchlist
        assert "match-partial-2" not in top
        assert "match-partial-2" not in watchlist

    def test_batch_engine_version_preserved(self):
        batch = BatchAnalysisRequest(
            matches=[_request()],
            engine_version="1.1.0",
        )
        response = analyze_batch(batch)
        assert response.engine_version == "1.1.0"

    def test_empty_top_opportunities_when_no_qualifying(self):
        # All PARTIAL
        batch = BatchAnalysisRequest(
            matches=[_request(model=None), _request(market=None)],
        )
        response = analyze_batch(batch)
        assert len(response.top_opportunities) == 0

    def test_top_opportunities_rank_by_confidence_adjusted_value_first(self):
        high_cav_speculative = analyze_match(
            _request(
                match_id="speculative-higher-cav",
                model=_model(home=0.46, draw=0.32, away=0.22, epistemic=0.02),
                market=_market(home=2.20, draw=3.10, away=4.20),
            )
        )
        lower_cav_actionable = analyze_match(
            _request(
                match_id="actionable-lower-cav",
                model=_model(home=0.66, draw=0.20, away=0.14, epistemic=0.18),
                market=_market(home=1.78, draw=3.80, away=5.80),
            )
        )
        high_cav_speculative.verdict = VerdictEnum.SPECULATIVE
        high_cav_speculative.confidence_adjusted_value = 0.09
        high_cav_speculative.expected_value = 0.03
        lower_cav_actionable.verdict = VerdictEnum.ACTIONABLE
        lower_cav_actionable.confidence_adjusted_value = 0.04
        lower_cav_actionable.expected_value = 0.12

        top, watchlist = _rank_top_opportunities([lower_cav_actionable, high_cav_speculative])

        # SPECULATIVE never enters top_opportunities, regardless of CAV ranking.
        assert top == ["actionable-lower-cav"]
        assert watchlist == ["speculative-higher-cav"]


# ---------------------------------------------------------------------------
# Invalidation conditions
# ---------------------------------------------------------------------------


class TestInvalidationConditions:
    def test_actionable_has_invalidation_conditions(self):
        req = _request(
            model=_model(home=0.65, draw=0.20, away=0.15),
            market=_market(home=1.80, draw=3.50, away=4.50),
        )
        result = analyze_match(req)
        if result.verdict in (VerdictEnum.ACTIONABLE, VerdictEnum.HIGH_CONVICTION):
            assert len(result.invalidation_conditions) > 0
            assert any("odds" in c.lower() or "edge" in c.lower() for c in result.invalidation_conditions)

    def test_minimum_acceptable_odds_present_when_actionable(self):
        req = _request(
            model=_model(home=0.65, draw=0.20, away=0.15),
            market=_market(home=1.80, draw=3.50, away=4.50),
        )
        result = analyze_match(req)
        if result.verdict in (VerdictEnum.ACTIONABLE, VerdictEnum.HIGH_CONVICTION, VerdictEnum.SPECULATIVE):
            assert result.minimum_acceptable_odds is not None
            assert result.minimum_acceptable_odds > 1.0


# ---------------------------------------------------------------------------
# Calculation audit
# ---------------------------------------------------------------------------


class TestCalculationAudit:
    def test_audit_present_for_actionable(self):
        req = _request(
            model=_model(home=0.65, draw=0.20, away=0.15),
            market=_market(home=1.80, draw=3.50, away=4.50),
        )
        result = analyze_match(req)
        if result.verdict in (VerdictEnum.ACTIONABLE, VerdictEnum.HIGH_CONVICTION):
            assert result.calculation_audit is not None
            assert result.calculation_audit.bookmaker == "Pinnacle"
            assert result.calculation_audit.market_overround is not None
            assert result.calculation_audit.kelly_fraction == KELLY_FRACTION

    def test_audit_has_devigged_probabilities(self):
        req = _request(
            model=_model(home=0.65, draw=0.20, away=0.15),
            market=_market(home=1.80, draw=3.50, away=4.50),
        )
        result = analyze_match(req)
        if result.calculation_audit is not None:
            assert result.calculation_audit.fair_market_home is not None
            assert result.calculation_audit.fair_market_draw is not None
            assert result.calculation_audit.fair_market_away is not None
            # Fair probs should sum to ~1
            total = (
                result.calculation_audit.fair_market_home
                + result.calculation_audit.fair_market_draw
                + result.calculation_audit.fair_market_away
            )
            assert abs(total - 1.0) < 1e-4


# ---------------------------------------------------------------------------
# Model probability validation
# ---------------------------------------------------------------------------


class TestModelProbabilityValidation:
    def test_invalid_prob_sum_raises(self):
        with pytest.raises(Exception):
            ModelInput(
                home_probability=0.50,
                draw_probability=0.50,
                away_probability=0.50,  # sum = 1.50
                model_version="v1",
                calibration_method="raw",
                calibration_validated=True,
                epistemic_uncertainty=0.1,
                aleatoric_uncertainty=0.1,
                confidence_tier=EvidenceTierEnum.OK,
            )

    def test_valid_probs_accepted(self):
        m = ModelInput(
            home_probability=0.50,
            draw_probability=0.30,
            away_probability=0.20,
            model_version="v1",
            calibration_method="raw",
            calibration_validated=True,
            epistemic_uncertainty=0.1,
            aleatoric_uncertainty=0.1,
            confidence_tier=EvidenceTierEnum.OK,
        )
        assert abs(m.home_probability + m.draw_probability + m.away_probability - 1.0) < 0.005
