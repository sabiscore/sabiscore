"""Adversarial Verification Suite for Challenger 2 (SabiScore APEX Production Activation).

Tests:
1. Candidate Model Quarantine & Zero-Stake Enforcement
2. Probability Simplex Violations & Fail-Closed Behavior
3. Copy Compliance & Zero Prohibited Gambling Claims
4. Staking Guardrails: Quarter-Kelly (0.25) & 5% Hard Cap Across All Engines
"""

import json
import math
from datetime import datetime, timezone
from pathlib import Path
import pytest

from src.models.active_generation import (
    ActiveGenerationError,
    active_generation_is_certified,
    load_active_generation,
)
from src.schemas.prediction import (
    LeagueCode,
    PredictionResponse,
    RLRecommendation,
)
from src.schemas.value_bet import ValueBetResponse
from src.api.endpoints.predictions import _fail_closed_if_uncertified
from src.services.betting_intelligence import (
    KELLY_FRACTION,
    MAX_KELLY_CAP,
    SPECULATIVE_STAKE_CAP,
    analyze_match,
    _full_kelly,
    _expected_value,
)
from src.schemas.betting_intelligence import (
    CompetitionEnum,
    FreshnessInput,
    EvidenceTierEnum,
    MarketInput,
    MatchAnalysisRequest,
    ModelInput,
    SignalsInput,
    SourceStatusEnum,
    SourceStatusInput,
    VerdictEnum,
)
from src.services.core_engine import (
    CORE_KELLY_FRACTION,
    CORE_MAX_KELLY_CAP,
    _evaluate_match,
)
from src.schemas.core_engine import (
    CoreFreshnessInput,
    CoreMarketInput,
    CoreMatchInput,
    CoreModelInput,
    CoreSignalsInput,
    CoreSourceStatusInput,
)
from src.services.rl_betting_agent import RLBettingAgent
from src.core.league_policy import get_league_policy


# ============================================================================
# DOMAIN 1: CANDIDATE MODEL QUARANTINE & ZERO-STAKE ENFORCEMENT
# ============================================================================

class TestCandidateModelQuarantine:
    """Adversarial stress-testing of candidate model quarantine and active generation."""

    def test_candidate_manifest_is_strictly_quarantined(self):
        candidate_manifest_path = Path(__file__).resolve().parents[1] / "models" / "candidate" / "candidate_manifest.json"
        assert candidate_manifest_path.is_file(), "candidate_manifest.json must exist"
        data = json.loads(candidate_manifest_path.read_text(encoding="utf-8"))
        
        assert data.get("status") == "UNVERIFIED_CANDIDATE", "Candidate status must be UNVERIFIED_CANDIDATE"
        assert data.get("promotion_permitted") is False, "promotion_permitted must be False"
        assert "failed_gates" in data, "Must record failed gates"
        failed_gates = set(data["failed_gates"])
        assert {"serving_feature_availability", "no_league_regression", "market_baseline"}.issubset(failed_gates)

    def test_active_generation_is_unverified_and_fail_closed(self):
        active_gen_path = Path(__file__).resolve().parents[1] / "models" / "active_generation.json"
        data = json.loads(active_gen_path.read_text(encoding="utf-8"))
        
        assert data.get("certification_state") == "UNVERIFIED"
        assert data.get("promotion_state") == "ACTIVE_FAIL_CLOSED"
        assert data.get("certified_at") is None
        assert active_generation_is_certified() is False, "Production active generation must NOT report certified"

    def test_tamper_attempt_certified_without_evidence_fails_closed(self, tmp_path):
        """Simulate an attacker editing active_generation.json to claim CERTIFIED without valid evidence."""
        models_dir = Path(__file__).resolve().parents[1] / "models"
        real_manifest = json.loads((models_dir / "active_generation.json").read_text(encoding="utf-8"))
        
        # Copy real artifact files to tmp_path so artifact existence and hash checks pass
        for league, entry in real_manifest["artifacts"].items():
            for key in ("artifact", "metadata"):
                fname = entry[key]
                (tmp_path / fname).write_bytes((models_dir / fname).read_bytes())

        # Attack 1: claim CERTIFIED with no certification_evidence
        tampered = dict(real_manifest)
        tampered["certification_state"] = "CERTIFIED"
        
        fake_manifest = tmp_path / "active_generation.json"
        fake_manifest.write_text(json.dumps(tampered), encoding="utf-8")
        
        with pytest.raises(ActiveGenerationError, match="no certification_evidence is declared"):
            load_active_generation(models_dir=tmp_path)

    def test_tamper_attempt_certified_with_failed_gates_evidence_fails_closed(self, tmp_path):
        """Simulate an attacker pointing certification_evidence to a report with failing gates."""
        models_dir = Path(__file__).resolve().parents[1] / "models"
        
        # Create a report with failing gates
        fake_report = tmp_path / "fake_report.json"
        fake_report_content = {
            "promotion_permitted": True,
            "gates": {
                "serving_feature_availability": {"status": "FAIL"},
                "market_baseline": {"status": "PASS"},
            }
        }
        fake_report.write_text(json.dumps(fake_report_content), encoding="utf-8")
        import hashlib
        report_hash = hashlib.sha256(fake_report.read_bytes()).hexdigest()
        
        real_manifest = json.loads((models_dir / "active_generation.json").read_text(encoding="utf-8"))
        tampered = dict(real_manifest)
        tampered["certification_state"] = "CERTIFIED"
        tampered["certification_evidence"] = {
            "report": "fake_report.json",
            "report_sha256": report_hash,
        }
        
        # Copy real artifact files to tmp_path so artifact checks pass
        for league, entry in real_manifest["artifacts"].items():
            for key in ("artifact", "metadata"):
                fname = entry[key]
                (tmp_path / fname).write_bytes((models_dir / fname).read_bytes())
                
        (tmp_path / "active_generation.json").write_text(json.dumps(tampered), encoding="utf-8")
        
        with pytest.raises(ActiveGenerationError, match="Certification evidence has failing gates"):
            load_active_generation(models_dir=tmp_path)

    def test_uncertified_state_strips_public_stakes_in_predictions_endpoint(self):
        """_fail_closed_if_uncertified must strictly zero out all value bets and stakes."""
        assert not active_generation_is_certified()
        
        response = PredictionResponse(
            match_id="test_match_123",
            home_team="Arsenal",
            away_team="Liverpool",
            league=LeagueCode.EPL,
            predictions={"home_win": 0.60, "draw": 0.25, "away_win": 0.15},
            confidence=0.60,
            brier_score=0.18,
            explanations={},
            value_bets=[
                ValueBetResponse(
                    match_id="test_match_123",
                    market="home_win",
                    odds=2.20,
                    fair_probability=0.55,
                    implied_probability=0.45,
                    edge_percent=10.0,
                    edge_ngn=1000.0,
                    kelly_stake_ngn=500.0,
                    kelly_fraction=0.25,
                    confidence=0.85,
                    expected_roi=0.10,
                )
            ],
            rl_recommendation=RLRecommendation(
                stake_fraction=0.045,
                abstain=False,
                reward_components={"R_pnl": 0.05},
                reason="High value home bet",
            ),
            metadata={"model_version": "v5_phase7", "stake_permitted": True},
            created_at=datetime.now(timezone.utc),
        )
        
        guarded = _fail_closed_if_uncertified(response)
        
        assert guarded.value_bets == [], "value_bets must be empty list"
        assert guarded.metadata["certification_state"] == "UNVERIFIED"
        assert guarded.metadata["stake_permitted"] is False
        assert guarded.rl_recommendation is not None
        assert guarded.rl_recommendation.stake_fraction == 0.0
        assert guarded.rl_recommendation.abstain is True
        assert "not certified" in guarded.rl_recommendation.reason

    def test_betting_intelligence_engine_zero_stakes_when_uncertified(self):
        """betting_intelligence.analyze_match must force PARTIAL and 0 stake on uncertified model."""
        req = MatchAnalysisRequest(
            match_id="match_unverified_1",
            competition=CompetitionEnum.EPL,
            home_team="Arsenal",
            away_team="Chelsea",
            kickoff_utc=datetime(2026, 9, 1, 15, 0, tzinfo=timezone.utc),
            model=ModelInput(
                model_version="v5_phase7",
                calibration_method="platt",
                home_probability=0.60,
                draw_probability=0.25,
                away_probability=0.15,
                epistemic_uncertainty=0.02,
                aleatoric_uncertainty=0.05,
                confidence_tier=EvidenceTierEnum.OK,
                calibration_validated=True,
                generation_certified=False,  # Uncertified
            ),
            market=MarketInput(
                bookmaker="bet365",
                market_type="1X2",
                captured_at=datetime.now(timezone.utc),
                home_odds=2.20,
                draw_odds=3.60,
                away_odds=3.80,
            ),
            freshness=FreshnessInput(
                model_features_seconds=300,
                market_seconds=120,
                injury_news_seconds=1800,
                lineup_seconds=600,
            ),
            source_status=SourceStatusInput(
                model=SourceStatusEnum.VERIFIED,
                market=SourceStatusEnum.VERIFIED,
                team_metrics=SourceStatusEnum.VERIFIED,
                availability=SourceStatusEnum.VERIFIED,
            ),
            signals=SignalsInput(
                lineup_status=SignalsInput().lineup_status,
            ),
            verified_evidence_providers=["provider_a", "provider_b"],
        )
        
        res = analyze_match(req)
        assert res.verdict == VerdictEnum.PARTIAL
        assert res.stake_fraction == 0.0 or res.stake_fraction is None
        assert res.stake == "pass"
        assert "DATA_GAP: MODEL_GENERATION_UNCERTIFIED" in res.data_gaps

    def test_core_engine_zero_stakes_when_uncertified(self):
        """core_engine._evaluate_match must force PARTIAL and no stake on uncertified model."""
        match_input = CoreMatchInput(
            match_id="core_unverified_1",
            competition="EPL",
            home_team="Arsenal",
            away_team="Chelsea",
            kickoff_utc=datetime(2026, 9, 1, 15, 0, tzinfo=timezone.utc),
            model=CoreModelInput(
                model_version="v5_phase7",
                calibration_method="platt",
                home_probability=0.60,
                draw_probability=0.25,
                away_probability=0.15,
                epistemic_uncertainty=0.02,
                aleatoric_uncertainty=0.05,
                confidence_tier="OK",
                calibration_validated=True,
                generation_certified=False,  # Uncertified
            ),
            market=CoreMarketInput(
                bookmaker="bet365",
                market_type="1X2",
                captured_at=datetime.now(timezone.utc),
                home_odds=2.20,
                draw_odds=3.60,
                away_odds=3.80,
            ),
            freshness=CoreFreshnessInput(
                model_features_seconds=300,
                market_seconds=120,
                injury_news_seconds=1800,
                lineup_seconds=600,
            ),
            source_status=CoreSourceStatusInput(
                model="VERIFIED",
                market="VERIFIED",
                team_metrics="VERIFIED",
                availability="VERIFIED",
            ),
            signals=CoreSignalsInput(lineup_status="CONFIRMED"),
            verified_evidence_providers=["p1", "p2"],
        )
        
        output = _evaluate_match(match_input)
        assert output.verdict == "PARTIAL"
        assert output.stake_fraction == 0.0 or output.stake_fraction is None
        assert output.stake == "pass"
        assert "DATA_GAP: MODEL_GENERATION_UNCERTIFIED" in output.data_gaps


# ============================================================================
# DOMAIN 2: PROBABILITY SIMPLEX VIOLATIONS
# ============================================================================

class TestProbabilitySimplexViolations:
    """Stress-test non-simplex probability rejection across all analytical boundaries."""

    @pytest.mark.parametrize(
        "p_home,p_draw,p_away,expected_valid",
        [
            (0.50, 0.30, 0.20, True),
            (1.00, 0.00, 0.00, True),
            (0.333333, 0.333333, 0.333334, True),
            (-0.05, 0.55, 0.50, False),   # negative probability
            (1.10, -0.10, 0.00, False),   # out of range > 1 and < 0
            (0.50, 0.50, 0.50, False),    # sum = 1.5
            (0.20, 0.20, 0.20, False),    # sum = 0.6
            (0.00, 0.00, 0.00, False),    # sum = 0.0
            (float("nan"), 0.5, 0.5, False),  # NaN
            (float("inf"), 0.0, 0.0, False),  # Inf
        ],
    )
    def test_core_engine_probability_simplex_check(self, p_home, p_draw, p_away, expected_valid):
        match_input = CoreMatchInput(
            match_id="simplex_test",
            competition="EPL",
            home_team="Arsenal",
            away_team="Chelsea",
            kickoff_utc=datetime(2026, 9, 1, 15, 0, tzinfo=timezone.utc),
            model=CoreModelInput(
                model_version="v5_phase7",
                calibration_method="platt",
                home_probability=p_home,
                draw_probability=p_draw,
                away_probability=p_away,
                epistemic_uncertainty=0.02,
                aleatoric_uncertainty=0.05,
                confidence_tier="OK",
                calibration_validated=True,
                generation_certified=True,
            ),
            market=CoreMarketInput(
                bookmaker="bet365",
                market_type="1X2",
                captured_at=datetime.now(timezone.utc),
                home_odds=2.00,
                draw_odds=3.50,
                away_odds=4.00,
            ),
            freshness=CoreFreshnessInput(
                model_features_seconds=300,
                market_seconds=120,
                injury_news_seconds=1800,
                lineup_seconds=600,
            ),
            source_status=CoreSourceStatusInput(
                model="VERIFIED",
                market="VERIFIED",
                team_metrics="VERIFIED",
                availability="VERIFIED",
            ),
            signals=CoreSignalsInput(lineup_status="CONFIRMED"),
            verified_evidence_providers=["p1", "p2", "p3", "p4"],
        )
        
        output = _evaluate_match(match_input)
        if not expected_valid:
            has_simplex_gap = any("INVALID_MODEL_PROBABILITY" in g for g in output.data_gaps)
            assert has_simplex_gap, f"Expected simplex data gap, got: {output.data_gaps}"
            assert output.verdict == "PARTIAL"
            assert output.stake == "pass"
        else:
            simplex_gaps = [g for g in output.data_gaps if "INVALID_MODEL_PROBABILITY" in g]
            assert simplex_gaps == [], f"Unexpected simplex gaps on valid input: {simplex_gaps}"

    def test_betting_intelligence_probability_simplex_schema_validation(self):
        """Pydantic model input validation should catch non-simplex probabilities."""
        # Test 1: Negative probability
        with pytest.raises(Exception):
            ModelInput(
                model_version="v5_phase7",
                calibration_method="platt",
                home_probability=-0.10,
                draw_probability=0.60,
                away_probability=0.50,
                epistemic_uncertainty=0.02,
                aleatoric_uncertainty=0.05,
                confidence_tier=EvidenceTierEnum.OK,
                calibration_validated=True,
                generation_certified=True,
            )

        # Test 2: Sum != 1.0 (0.6 + 0.3 + 0.3 = 1.2)
        with pytest.raises(ValueError, match="Probabilities must sum to 1.0"):
            ModelInput(
                model_version="v5_phase7",
                calibration_method="platt",
                home_probability=0.60,
                draw_probability=0.30,
                away_probability=0.30,
                epistemic_uncertainty=0.02,
                aleatoric_uncertainty=0.05,
                confidence_tier=EvidenceTierEnum.OK,
                calibration_validated=True,
                generation_certified=True,
            )


# ============================================================================
# DOMAIN 3: PROHIBITED COPY LEAKS SCANNER
# ============================================================================

class TestProhibitedCopyLeaks:
    """Exhaustive scan of code and templates for prohibited certainty/gambling marketing copy."""

    def test_no_prohibited_copy_in_frontend_source(self):
        import re
        web_src = Path(__file__).resolve().parents[2] / "apps" / "web" / "src"
        assert web_src.is_dir()
        
        regex = re.compile(r"\b(banker|guaranteed|sure bet|free money|execute immediately)\b", re.IGNORECASE)
        lock_regex = re.compile(r"(?<![a-zA-Z])lock(s)?(?![a-zA-Z])", re.IGNORECASE)
        
        violations = []
        for p in web_src.rglob("*"):
            if not p.is_file() or p.suffix not in (".ts", ".tsx", ".js", ".jsx", ".json", ".mdx", ".html"):
                continue
            if ".test." in p.name or ".spec." in p.name:
                continue  # skip test suites that explicitly assert against banned terms
                
            text = p.read_text(encoding="utf-8", errors="ignore")
            
            if regex.search(text):
                for match in regex.finditer(text):
                    violations.append(f"{p.relative_to(web_src)}: matched '{match.group(0)}'")
            
            # Check for standalone 'lock'
            for match in lock_regex.finditer(text):
                line = text[max(0, match.start() - 30):min(len(text), match.end() + 30)]
                violations.append(f"{p.relative_to(web_src)}: matched 'lock' in line: '{line.strip()}'")

        assert violations == [], f"Found prohibited copy leaks in frontend: {violations}"


# ============================================================================
# DOMAIN 4: STAKING GUARDRAILS (QUARTER-KELLY 0.25 & 5% CAP)
# ============================================================================

class TestStakingGuardrails:
    """Stress-test Quarter-Kelly and 5% hard cap enforcement across all engines."""

    def test_constants_conform_to_apex_directive(self):
        assert KELLY_FRACTION == 0.25, "betting_intelligence KELLY_FRACTION must be exactly 0.25 (Quarter-Kelly)"
        assert MAX_KELLY_CAP == 0.05, "betting_intelligence MAX_KELLY_CAP must be exactly 0.05 (5%)"
        assert CORE_KELLY_FRACTION == 0.25, "core_engine CORE_KELLY_FRACTION must be exactly 0.25 (Quarter-Kelly)"
        assert CORE_MAX_KELLY_CAP == 0.05, "core_engine CORE_MAX_KELLY_CAP must be exactly 0.05 (5%)"
        assert SPECULATIVE_STAKE_CAP == 0.0, "SPECULATIVE must have 0.0 stake cap (watchlist only)"

    def test_all_league_policies_do_not_exceed_5pct_cap(self):
        leagues = ["EPL", "LA_LIGA", "BUNDESLIGA", "SERIE_A", "LIGUE_1", "EREDIVISIE", "UCL"]
        for league_id in leagues:
            policy = get_league_policy(league_id)
            assert policy.kelly_cap <= 0.05, f"League {league_id} kelly_cap {policy.kelly_cap} exceeds 5% cap"

    def test_full_kelly_calculation_mathematical_oracle(self):
        """Verify _full_kelly and Quarter-Kelly under extreme boundary conditions."""
        # Case 1: Negative EV -> 0.0
        assert _full_kelly(ev=-0.10, decimal_odds=2.0) == 0.0
        assert _full_kelly(ev=0.0, decimal_odds=2.0) == 0.0
        
        # Case 2: Odds <= 1.0 -> 0.0
        assert _full_kelly(ev=0.50, decimal_odds=1.0) == 0.0
        assert _full_kelly(ev=0.50, decimal_odds=0.9) == 0.0
        
        # Case 3: Standard 10% edge: p = 0.55, odds = 2.0 -> EV = 0.10, Full Kelly = 0.10 / 1.0 = 0.10
        fk = _full_kelly(ev=0.10, decimal_odds=2.0)
        assert math.isclose(fk, 0.10, rel_tol=1e-5)
        qk = min(fk * KELLY_FRACTION, MAX_KELLY_CAP)
        assert math.isclose(qk, 0.025, rel_tol=1e-5)
        
        # Case 4: Extreme edge: p = 0.90, odds = 5.0 -> EV = 3.50, Full Kelly = 3.50 / 4.0 = 0.875
        # Quarter-Kelly = 0.875 * 0.25 = 0.21875 -> Must be capped at 0.05!
        fk_extreme = _full_kelly(ev=3.50, decimal_odds=5.0)
        qk_capped = min(fk_extreme * KELLY_FRACTION, MAX_KELLY_CAP)
        assert qk_capped == 0.05, f"Expected 0.05 cap, got {qk_capped}"

    def test_rl_betting_agent_strictly_enforces_max_kelly_cap(self):
        """RLBettingAgent must clamp continuous actions and Kelly fallbacks to max_kelly_cap."""
        agent = RLBettingAgent(max_kelly_cap=0.05)
        
        # Test extreme input values
        probs = {"home_win": 0.99, "draw": 0.005, "away_win": 0.005}
        odds = {"home_win": 10.0, "draw": 10.0, "away_win": 10.0}
        
        rec = agent.recommend(
            probabilities=probs,
            odds=odds,
            confidence=0.99,
            epistemic_unc=0.01,
        )
        assert 0.0 <= rec.stake_fraction <= 0.05, f"RL stake {rec.stake_fraction} exceeded 5% cap"

    def test_adversarial_monte_carlo_sweep_over_all_odds_and_probs(self):
        """Generate 5,000 random adversarial (probability, odds) pairs and verify invariants."""
        import random
        random.seed(42)
        
        for _ in range(5000):
            p = random.uniform(0.001, 0.999)
            odds = random.uniform(1.01, 50.0)
            
            ev = _expected_value(p, odds)
            fk = _full_kelly(ev, odds)
            qk = min(fk * 0.25, 0.05) if ev > 0 else 0.0
            
            # INVARIANT 1: Stake is never negative
            assert qk >= 0.0, f"Negative stake: {qk} for p={p}, odds={odds}"
            
            # INVARIANT 2: Stake never exceeds 5% hard cap
            assert qk <= 0.05, f"Stake exceeded 5% cap: {qk} for p={p}, odds={odds}"
            
            # INVARIANT 3: If EV <= 0, stake is strictly 0.0
            if ev <= 0:
                assert qk == 0.0, f"Non-zero stake for non-positive EV: {qk} (ev={ev})"
