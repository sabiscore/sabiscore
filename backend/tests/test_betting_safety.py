"""P9 Betting Safety & UCL Hard-Cap Test Suite.

Formally verifies:
  1. Default-deny research posture:
     - `stake_permitted = False` when in research mode, uncertified model states,
       or whenever critical gaps / conflicts exist.
     - Stake fractions / Kelly values evaluate to 0.0 / "pass".
     - RL layer abstains (`abstain = True`).
     - Zero `EXECUTE_BET` functionality, zero automated wagering, and zero betting
       execution endpoints in the FastAPI application or backend source.
  2. UCL (Champions League) hard-cap:
     - Fixtures in UCL are hard-capped at ACTIONABLE and strictly forbidden from
       reaching HIGH_CONVICTION across both verdict engines (betting_intelligence
       and core_engine) and the synthesis layer (intelligence_synthesizer).
     - Boundary and fail-closed conditions for UCL fixtures.
"""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import pytest

from src.schemas.betting_intelligence import (
    CompetitionEnum,
    FreshnessInput,
    LineupStatusEnum,
    MarketInput,
    MatchAnalysisRequest,
    ModelInput,
    SharpSignalEnum,
    SourceStatusEnum,
    SourceStatusInput,
    VerdictEnum,
    EvidenceTierEnum,
)
from src.services.betting_intelligence import analyze_match
from src.services.core_engine import analyze_core_matches
from src.schemas.core_engine import CoreMatchInput
from src.services.market_intel import (
    build_market_intelligence,
    MarketDecisionState,
)
from src.services.intelligence_synthesizer import (
    EnsemblePrediction,
    IntelligenceSynthesizer,
    OddsEdge,
)
from src.models.causal_selector import CausalFeatureResult
from src.services.rl_betting_agent import RLRecommendationPayload
from src.services.uncertainty_service import UncertaintyBreakdown


MARKET_NOW = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
FUTURE_KICKOFF = datetime(2026, 8, 15, 15, 0, 0, tzinfo=timezone.utc)
FOUR_PROVIDERS = ["espn", "api_football", "football_data_org", "the_odds_api"]


def _make_model_input(
    home: float = 0.72,
    draw: float = 0.18,
    away: float = 0.10,
    epistemic: float = 0.03,
    certified: bool = True,
    tier: EvidenceTierEnum = EvidenceTierEnum.OK,
) -> ModelInput:
    return ModelInput(
        home_probability=home,
        draw_probability=draw,
        away_probability=away,
        model_version="v5_phase8",
        calibration_method="isotonic",
        calibration_validated=True,
        generation_certified=certified,
        epistemic_uncertainty=epistemic,
        aleatoric_uncertainty=0.10,
        confidence_tier=tier,
    )


def _make_market_input(
    home: float = 1.75,
    draw: float = 4.00,
    away: float = 6.00,
    captured_at: datetime = MARKET_NOW,
) -> MarketInput:
    return MarketInput(
        bookmaker="Pinnacle",
        market_type="1X2",
        home_odds=home,
        draw_odds=draw,
        away_odds=away,
        captured_at=captured_at,
    )


def _make_match_request(
    match_id: str = "test-ucl-001",
    competition: CompetitionEnum = CompetitionEnum.UCL,
    model: ModelInput | None = None,
    market: MarketInput | None = None,
    lineup_status: LineupStatusEnum = LineupStatusEnum.CONFIRMED,
    sharp_signal: SharpSignalEnum = SharpSignalEnum.CONFIRMING,
    market_seconds: int = 60,
    providers: list[str] | None = None,
    data_gaps: list[str] | None = None,
) -> MatchAnalysisRequest:
    return MatchAnalysisRequest(
        match_id=match_id,
        home_team="Real Madrid",
        away_team="Bayern Munich",
        competition=competition,
        kickoff_utc=FUTURE_KICKOFF,
        model=model or _make_model_input(),
        market=market or _make_market_input(),
        signals=dict(
            xg_differential=0.5,
            xga_differential=-0.3,
            lineup_status=lineup_status,
            sharp_market_signal=sharp_signal,
        ),
        freshness=FreshnessInput(
            market_seconds=market_seconds,
            model_features_seconds=market_seconds,
            lineup_seconds=market_seconds,
        ),
        source_status=SourceStatusInput(
            model=SourceStatusEnum.VERIFIED,
            market=SourceStatusEnum.VERIFIED,
            team_metrics=SourceStatusEnum.VERIFIED,
            availability=SourceStatusEnum.VERIFIED,
        ),
        data_gaps=data_gaps or [],
        verified_evidence_providers=FOUR_PROVIDERS if providers is None else providers,
    )


def _make_core_match(
    competition: str = "UCL", certified: bool = True, epistemic: float = 0.03
) -> dict:
    return {
        "match_id": "core-ucl-001",
        "home_team": "Real Madrid",
        "away_team": "Bayern Munich",
        "competition": competition,
        "kickoff_utc": "2026-08-15T15:00:00Z",
        "verified_evidence_providers": FOUR_PROVIDERS,
        "model": {
            "home_probability": 0.65,
            "draw_probability": 0.20,
            "away_probability": 0.15,
            "model_version": "core-v1",
            "calibration_method": "isotonic",
            "calibration_validated": True,
            "generation_certified": certified,
            "epistemic_uncertainty": epistemic,
            "aleatoric_uncertainty": 0.10,
            "confidence_tier": "OK",
        },
        "market": {
            "bookmaker": "Pinnacle",
            "market_type": "1X2",
            "home_odds": 2.0,
            "draw_odds": 3.4,
            "away_odds": 4.8,
            "opening_home_odds": 2.05,
            "opening_draw_odds": 3.35,
            "opening_away_odds": 4.7,
            "captured_at": "2026-08-15T14:30:00Z",
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
            "model_features_seconds": 60,
            "market_seconds": 60,
            "injury_news_seconds": 60,
            "lineup_seconds": 60,
        },
        "source_status": {
            "model": "VERIFIED",
            "market": "VERIFIED",
            "team_metrics": "VERIFIED",
            "availability": "VERIFIED",
        },
    }


# ===========================================================================
# R1: Backend Betting Safety & Default-Deny Research Posture
# ===========================================================================


class TestDefaultDenyResearchPosture:
    """Verifies that stake_permitted evaluates to False in Research Mode,
    unverified model states, or missing evidence, and that no executable
    stakes or automated betting capabilities are present."""

    def test_market_intel_uncertified_model_forces_stake_permitted_false(self):
        """In Research Mode (uncertified model), build_market_intelligence must evaluate
        stake_permitted = False and decision = RESEARCH_ONLY even with strong edge."""
        odds = {"home_win": 2.50, "draw": 3.40, "away_win": 3.10}
        model_probs = {
            "home_win": 0.60,
            "draw": 0.25,
            "away_win": 0.15,
        }  # Strong home edge: 60% vs ~40% implied

        with patch(
            "src.services.market_intel.active_generation_is_certified",
            return_value=False,
        ):
            intel = build_market_intelligence(
                odds=odds,
                model_probabilities=model_probs,
                captured_at=MARKET_NOW,
                pre_kickoff=True,
                bookmaker="Pinnacle",
            )

            assert intel.stake_permitted is False, (
                f"Expected stake_permitted=False in research mode, got {intel.stake_permitted}"
            )
            assert intel.decision == MarketDecisionState.RESEARCH_ONLY, (
                f"Expected decision=RESEARCH_ONLY, got {intel.decision}"
            )
            assert intel.provenance.certification_state == "UNVERIFIED"

    def test_market_intel_certified_model_can_permit_stake_when_gates_pass(self):
        """Contrast test: when certified, valid edge can permit stake, proving the gate is active."""
        odds = {"home_win": 2.50, "draw": 3.40, "away_win": 3.10}
        model_probs = {"home_win": 0.60, "draw": 0.25, "away_win": 0.15}

        with patch(
            "src.services.market_intel.active_generation_is_certified",
            return_value=True,
        ):
            intel = build_market_intelligence(
                odds=odds,
                model_probabilities=model_probs,
                captured_at=MARKET_NOW,
                pre_kickoff=True,
                bookmaker="Pinnacle",
            )

            assert intel.stake_permitted is True
            assert intel.decision == MarketDecisionState.ACTIONABLE
            assert intel.provenance.certification_state == "CERTIFIED"

    def test_betting_intelligence_uncertified_model_forces_partial_and_zero_stake(self):
        """In betting_intelligence engine, uncertified model forces PARTIAL and zero stake."""
        req = _make_match_request(
            model=_make_model_input(certified=False),
        )
        result = analyze_match(req, evaluation_at=MARKET_NOW)

        assert result.verdict == VerdictEnum.PARTIAL
        assert result.stake == "pass"
        assert result.stake_fraction == 0.0
        assert result.execution_eligible is False
        assert "DATA_GAP: MODEL_GENERATION_UNCERTIFIED" in result.critical_gaps

    def test_core_engine_uncertified_model_forces_hold_and_zero_stake(self):
        """In core_engine, uncertified model generation forces HOLD and stake pass."""
        match_dict = _make_core_match(certified=False)
        response = analyze_core_matches([CoreMatchInput.model_validate(match_dict)])
        match_result = response.matches[0]

        assert match_result.verdict in ("HOLD", "PARTIAL"), (
            f"Expected fail-closed verdict when uncertified, got {match_result.verdict}"
        )
        assert match_result.stake == "pass"
        assert match_result.stake_fraction == 0.0

    def test_intelligence_synthesizer_evaluates_stake_permitted_false_when_unverified(
        self,
    ):
        """In intelligence_synthesizer, unverified fixture or critical gaps evaluate
        stake_permitted = False and zero out RL and Kelly stakes."""
        synth = IntelligenceSynthesizer()
        ensemble = EnsemblePrediction(
            home_win_prob=0.60,
            draw_prob=0.25,
            away_win_prob=0.15,
            prediction="home_win",
            confidence=0.60,
            league="EPL",
            model_version="v5_phase7",
        )
        uncertainty = UncertaintyBreakdown(
            epistemic_unc=0.03,
            aleatoric_unc=0.10,
            concentration=0.75,
            credible_interval=(0.50, 0.70),
            confidence_tier="OK",
        )
        rl_rec = RLRecommendationPayload(
            stake_fraction=0.03,
            abstain=False,
            reward_components={},
            reason="Sample",
        )
        odds_edge = OddsEdge(
            market="home_win",
            market_odds=2.20,
            model_prob=0.60,
            edge=0.10,
            kelly_stake=0.03,
        )

        # 1. Unverified fixture path: fixture_verified is False / omitted
        res_unverified = synth.synthesize(
            match_id="m1",
            ensemble=ensemble,
            uncertainty=uncertainty,
            causal_results=[
                CausalFeatureResult(
                    name="elo_difference",
                    ate_win=0.1,
                    ate_draw=-0.02,
                    ate_ci=(0.05, 0.15),
                    p_value=0.01,
                    classification="POSITIVE",
                )
            ],
            rl_rec=rl_rec,
            elo_ctx=None,
            odds_edge=odds_edge,
            fixture_verified=False,
        )
        assert res_unverified.stake_permitted is False
        assert res_unverified.rl_recommendation.abstain is True
        assert res_unverified.rl_recommendation.stake_fraction == 0.0
        assert res_unverified.odds_edge.kelly_stake == 0.0

        # 2. Critical gaps present (e.g. MODEL_UNCERTAINTY_UNAVAILABLE)
        res_gapped = synth.synthesize(
            match_id="m2",
            ensemble=ensemble,
            uncertainty=uncertainty,
            causal_results=[
                CausalFeatureResult(
                    name="elo_difference",
                    ate_win=0.1,
                    ate_draw=-0.02,
                    ate_ci=(0.05, 0.15),
                    p_value=0.01,
                    classification="POSITIVE",
                )
            ],
            rl_rec=rl_rec,
            elo_ctx=None,
            odds_edge=odds_edge,
            fixture_verified=True,
            critical_gaps=["MODEL_UNCERTAINTY_UNAVAILABLE"],
        )
        assert res_gapped.stake_permitted is False
        assert res_gapped.rl_recommendation.abstain is True
        assert res_gapped.rl_recommendation.stake_fraction == 0.0


# ===========================================================================
# R1: AST & Route Introspection — Absence of EXECUTE_BET and Automated Betting
# ===========================================================================


class TestNoAutomatedBettingOrExecuteBet:
    """Formally inspects the backend codebase to verify that no EXECUTE_BET
    functionality, automated betting handlers, or broker execution APIs exist."""

    def test_no_execute_bet_or_automated_wagering_symbols_in_backend_src(self):
        """Scans the backend/src directory AST for any function, class, or variable
        definition that implements bet execution or automated betting."""
        backend_src = Path(__file__).resolve().parent.parent / "src"
        assert backend_src.is_dir(), f"Expected directory at {backend_src}"

        prohibited_terms = {
            "execute_bet",
            "execute_bets",
            "place_bet",
            "place_bets",
            "submit_wager",
            "submit_bet",
            "auto_bet",
            "auto_wager",
            "place_order",
        }

        violations: list[str] = []

        for py_file in backend_src.rglob("*.py"):
            try:
                tree = ast.parse(
                    py_file.read_text(encoding="utf-8"), filename=str(py_file)
                )
            except Exception as e:
                pytest.fail(f"Failed to parse {py_file}: {e}")

            for node in ast.walk(tree):
                if isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    name_lower = node.name.lower()
                    if name_lower in prohibited_terms:
                        violations.append(
                            f"{py_file.name}:{node.lineno} -> {node.name}"
                        )
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            if (
                                target.id.lower() in prohibited_terms
                                or target.id == "EXECUTE_BET"
                            ):
                                violations.append(
                                    f"{py_file.name}:{node.lineno} -> {target.id}"
                                )

        assert not violations, (
            f"Found prohibited bet execution symbols in backend/src: {violations}"
        )

    def test_fastapi_app_has_no_bet_execution_routes(self):
        """Verifies that the mounted FastAPI application exposes no endpoints
        for placing bets, executing wagers, or broker integration."""
        from src.api.main import app

        prohibited_path_fragments = [
            "/execute-bet",
            "/place-bet",
            "/wager",
            "/bet-placement",
            "/broker",
        ]
        matched_routes: list[str] = []

        for route in app.routes:
            path = getattr(route, "path", "").lower()
            methods = getattr(route, "methods", set())
            for fragment in prohibited_path_fragments:
                if fragment in path:
                    matched_routes.append(f"{methods} {path}")

        assert not matched_routes, (
            f"FastAPI app must not expose bet execution routes; found: {matched_routes}"
        )

    def test_verdict_enums_do_not_contain_execute_bet_states(self):
        """Verifies that VerdictEnum and MarketDecisionState contain only analytical
        decision states and never an EXECUTE_BET state."""
        allowed_verdicts = {
            "HIGH_CONVICTION",
            "ACTIONABLE",
            "SPECULATIVE",
            "HOLD",
            "PARTIAL",
            "NO_BET",
        }
        for item in VerdictEnum:
            assert item.value in allowed_verdicts, (
                f"Unexpected verdict enum: {item.value}"
            )
            assert "EXECUTE" not in item.value
            assert item.value != "EXECUTE_BET"

        allowed_decisions = {
            "ACTIONABLE",
            "HOLD",
            "NO_BET",
            "PARTIAL",
            "RESEARCH_ONLY",
        }
        for item in MarketDecisionState:
            assert item.value in allowed_decisions, (
                f"Unexpected market decision enum: {item.value}"
            )
            assert "EXECUTE" not in item.value


# ===========================================================================
# R2: Backend UCL Hard-Cap Coverage
# ===========================================================================


class TestUCLHardCapCoverage:
    """Verifies that fixtures in the Champions League (UCL) are strictly hard-capped
    at ACTIONABLE and can NEVER reach HIGH_CONVICTION across both engines and synthesis."""

    def test_ucl_cannot_reach_high_conviction_in_betting_intelligence_engine(self):
        """Explicitly mocks a UCL fixture with optimal parameters that would grant
        HIGH_CONVICTION in domestic leagues, and asserts it is capped at ACTIONABLE."""
        # Baseline non-UCL (EPL) fixture with ideal parameters
        epl_req = _make_match_request(
            competition=CompetitionEnum.EPL,
            model=_make_model_input(home=0.75, draw=0.15, away=0.10, epistemic=0.02),
            market=_make_market_input(
                home=1.70, draw=4.00, away=6.00, captured_at=MARKET_NOW
            ),
            lineup_status=LineupStatusEnum.CONFIRMED,
            sharp_signal=SharpSignalEnum.CONFIRMING,
            market_seconds=60,
        )
        epl_result = analyze_match(
            epl_req,
            causal_drivers=["elo_difference", "xg_differential"],
            evaluation_at=MARKET_NOW,
        )
        assert epl_result.verdict == VerdictEnum.HIGH_CONVICTION, (
            f"Expected EPL baseline to achieve HIGH_CONVICTION, got {epl_result.verdict}"
        )

        # Exactly identical fixture in UCL
        ucl_req = _make_match_request(
            competition=CompetitionEnum.UCL,
            model=_make_model_input(home=0.75, draw=0.15, away=0.10, epistemic=0.02),
            market=_make_market_input(
                home=1.70, draw=4.00, away=6.00, captured_at=MARKET_NOW
            ),
            lineup_status=LineupStatusEnum.CONFIRMED,
            sharp_signal=SharpSignalEnum.CONFIRMING,
            market_seconds=60,
        )
        ucl_result = analyze_match(
            ucl_req,
            causal_drivers=["elo_difference", "xg_differential"],
            evaluation_at=MARKET_NOW,
        )

        # Assert UCL is capped at ACTIONABLE
        assert ucl_result.verdict == VerdictEnum.ACTIONABLE, (
            f"UCL fixture must be hard-capped at ACTIONABLE, got {ucl_result.verdict}"
        )
        assert ucl_result.verdict != VerdictEnum.HIGH_CONVICTION, (
            "UCL fixture MUST NEVER reach HIGH_CONVICTION"
        )
        assert "UCL soft-coverage cap applied" in ucl_result.explanation

    def test_ucl_cannot_reach_high_conviction_in_core_engine(self):
        """Verifies core_engine.py hard-caps UCL fixtures at ACTIONABLE and adds risk note."""
        # Non-UCL (EPL) baseline
        epl_match = _make_core_match(competition="EPL", epistemic=0.02)
        epl_response = analyze_core_matches([CoreMatchInput.model_validate(epl_match)])
        assert epl_response.matches[0].verdict == "HIGH_CONVICTION", (
            f"Expected EPL to reach HIGH_CONVICTION, got {epl_response.matches[0].verdict}"
        )

        # UCL match with identical parameters
        ucl_match = _make_core_match(competition="UCL", epistemic=0.02)
        ucl_response = analyze_core_matches([CoreMatchInput.model_validate(ucl_match)])
        ucl_result = ucl_response.matches[0]

        assert ucl_result.verdict == "ACTIONABLE", (
            f"Core engine UCL must be capped at ACTIONABLE, got {ucl_result.verdict}"
        )
        assert ucl_result.verdict != "HIGH_CONVICTION"
        assert any(
            "UCL soft coverage caps the verdict at ACTIONABLE" in r
            for r in ucl_result.risks
        ), f"Expected UCL soft coverage risk explanation in {ucl_result.risks}"

    @pytest.mark.parametrize("league_code", ["UCL", "UEFA_CHAMPIONS_LEAGUE"])
    def test_ucl_hard_capped_in_intelligence_synthesizer(self, league_code: str):
        """Verifies intelligence_synthesizer CEILING-caps UCL at ACTIONABLE.

        The UCL cap is a CEILING (verdict cannot EXCEED ACTIONABLE), not a floor.
        A UCL fixture that only warrants SPECULATIVE based on evidence will remain
        SPECULATIVE — the cap does not artificially inflate the verdict. This test
        verifies HIGH_CONVICTION is never returned, which is the P9 invariant.
        """
        synth = IntelligenceSynthesizer()
        ensemble = EnsemblePrediction(
            home_win_prob=0.70,
            draw_prob=0.20,
            away_win_prob=0.10,
            prediction="home_win",
            confidence=0.70,
            league=league_code,
            model_version="v5_phase7",
        )
        uncertainty = UncertaintyBreakdown(
            epistemic_unc=0.02,
            aleatoric_unc=0.08,
            concentration=0.85,
            credible_interval=(0.60, 0.80),
            confidence_tier="OK",
        )
        rl_rec = RLRecommendationPayload(
            stake_fraction=0.02,
            abstain=False,
            reward_components={},
            reason="High edge home win",
        )
        odds_edge = OddsEdge(
            market="home_win",
            market_odds=1.80,
            model_prob=0.70,
            edge=0.15,
            kelly_stake=0.02,
        )

        res = synth.synthesize(
            match_id=f"test-{league_code}",
            ensemble=ensemble,
            uncertainty=uncertainty,
            causal_results=[
                CausalFeatureResult(
                    name="elo_difference",
                    ate_win=0.15,
                    ate_draw=-0.03,
                    ate_ci=(0.08, 0.22),
                    p_value=0.001,
                    classification="POSITIVE",
                ),
                CausalFeatureResult(
                    name="xg_differential",
                    ate_win=0.10,
                    ate_draw=-0.02,
                    ate_ci=(0.04, 0.16),
                    p_value=0.002,
                    classification="POSITIVE",
                ),
            ],
            rl_rec=rl_rec,
            elo_ctx=None,
            odds_edge=odds_edge,
            fixture_verified=True,
            effective_kelly_cap=0.03,
        )

        # The P9 invariant: UCL must NEVER reach HIGH_CONVICTION.
        # The cap is a ceiling — SPECULATIVE/HOLD are valid when evidence is weak.
        assert res.verdict != "HIGH_CONVICTION", (
            f"UCL fixture from synthesizer must never reach HIGH_CONVICTION; got {res.verdict}"
        )
        assert res.verdict in ("ACTIONABLE", "SPECULATIVE", "HOLD", "PARTIAL", "NO_BET")

    def test_ucl_boundary_low_edge_falls_to_hold_or_speculative(self):
        """Verifies UCL capping does not artificially elevate low-edge or unviable fixtures."""
        # Thin edge below min_actionable_edge (e.g. edge ~0.015 < 0.02)
        req = _make_match_request(
            competition=CompetitionEnum.UCL,
            model=_make_model_input(home=0.51, draw=0.25, away=0.24, epistemic=0.03),
            market=_make_market_input(
                home=2.00, draw=3.40, away=4.00
            ),  # fair ~0.485, edge ~0.025
        )
        # Give no causal drivers, dropping it from actionable to speculative
        result = analyze_match(req, causal_drivers=[], evaluation_at=MARKET_NOW)

        # Should be SPECULATIVE or HOLD, never elevated to ACTIONABLE
        assert result.verdict in (
            VerdictEnum.SPECULATIVE,
            VerdictEnum.HOLD,
            VerdictEnum.NO_BET,
        )
        assert result.verdict != VerdictEnum.HIGH_CONVICTION
        assert result.verdict != VerdictEnum.ACTIONABLE

    def test_ucl_boundary_critical_gap_falls_to_partial_with_zero_stake(self):
        """Verifies UCL fixture with critical gap fails closed to PARTIAL and stake pass."""
        req = _make_match_request(
            competition=CompetitionEnum.UCL,
            data_gaps=["DATA_GAP: LINEUP_DATA_GAP"],
        )
        result = analyze_match(req, evaluation_at=MARKET_NOW)

        assert result.verdict == VerdictEnum.PARTIAL
        assert result.stake == "pass"
        assert result.stake_fraction == 0.0
        assert result.execution_eligible is False
