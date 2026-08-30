"""Adversarial stress-testing suite for Market Intelligence and Provenance Layer.

Empirical verification harness covering:
1. Extreme prices (ultra-heavy favourites, massive longshots, boundary odds).
2. Numerical stability of power-method de-vigging and proportional fallback.
3. Strict fail-closed staking gates on uncertified model generations across randomized edge scenarios.
4. Fail-closed behavior on incomplete markets, missing outcomes, None inputs, malformed types, NaN/Inf.
5. Strict fail-closed behavior on suspended and in-play markets even under certified models with huge edge.
6. Edge case where edge is positive but EV is negative (huge bookmaker margin).
7. Full Pydantic v2 serialization and deserialization integrity.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from unittest.mock import patch

from src.connectors.odds_market import (
    implied_probabilities,
    power_method_probs,
)
from src.services.market_intel import (
    EdgeClassification,
    MarketDecisionState,
    MarketIntelligenceSummary,
    build_market_intelligence,
)


class TestExtremeMarketPricesAndNumericalStability:
    """Stress testing mathematical operators under extreme and pathological odds distributions."""

    def test_heavy_favourite_vs_extreme_underdog(self):
        """Heavy favourite (1.01) vs massive longshots (25.0, 100.0)."""
        odds = {"home_win": 1.01, "draw": 25.0, "away_win": 100.0}
        model_probs = {"home_win": 0.98, "draw": 0.015, "away_win": 0.005}

        summary = build_market_intelligence(odds=odds, model_probabilities=model_probs)

        assert summary.market_overround > 1.0
        assert summary.provenance.is_complete is True
        assert summary.provenance.devig_method in ("POWER_METHOD", "PROPORTIONAL")

        # Verify all outcomes are present and probabilities sum to 1.0
        fair_sum = sum(o.fair_market_probability for o in summary.outcomes.values())
        assert abs(fair_sum - 1.0) < 1e-4

        # In power method, favourite-longshot bias correction increases the favourite's fair prob relative to raw implied
        home = summary.outcomes["home_win"]
        assert home.decimal_odds == 1.01
        assert home.raw_implied_probability == round(1.0 / 1.01, 4)
        assert home.fair_market_probability > 0.90

    def test_ultra_extreme_favourite_boundary(self):
        """Odds right at the valid boundary (1.0002) with extreme underdogs."""
        odds = {"home_win": 1.0002, "draw": 2000.0, "away_win": 5000.0}
        summary = build_market_intelligence(odds=odds)

        assert summary.provenance.is_complete is True
        fair_sum = sum(o.fair_market_probability for o in summary.outcomes.values())
        assert abs(fair_sum - 1.0) < 1e-3
        assert summary.outcomes["home_win"].fair_market_probability > 0.99

    def test_massive_overround_crush(self):
        """Massive bookmaker margin (110% on each outcome -> overround ~ 2.72)."""
        odds = {"home_win": 1.10, "draw": 1.10, "away_win": 1.10}
        summary = build_market_intelligence(odds=odds)

        assert summary.market_overround > 2.70
        assert summary.margin_percentage > 170.0
        fair_sum = sum(o.fair_market_probability for o in summary.outcomes.values())
        assert abs(fair_sum - 1.0) < 1e-4
        for o in summary.outcomes.values():
            assert abs(o.fair_market_probability - 0.3333) < 1e-3

    def test_zero_margin_fair_book(self):
        """Zero-margin fair market (odds 3.0, 3.0, 3.0)."""
        odds = {"home_win": 3.0, "draw": 3.0, "away_win": 3.0}
        summary = build_market_intelligence(odds=odds)

        assert abs(summary.market_overround - 1.0) < 1e-4
        assert abs(summary.margin_percentage - 0.0) < 1e-4
        for o in summary.outcomes.values():
            assert abs(o.fair_market_probability - 0.3333) < 1e-3

    def test_sub_unity_overround_arbitrage_book(self):
        """Sub-unity overround (arbitrage market: 3.5, 3.5, 3.5 -> sum(1/p) = 0.857)."""
        odds = {"home_win": 3.5, "draw": 3.5, "away_win": 3.5}
        summary = build_market_intelligence(odds=odds)

        assert summary.market_overround < 1.0
        assert summary.margin_percentage < 0.0
        fair_sum = sum(o.fair_market_probability for o in summary.outcomes.values())
        assert abs(fair_sum - 1.0) < 1e-4

    def test_power_method_vs_proportional_consistency(self):
        """Compare power method and proportional de-vigging on symmetric and asymmetric odds."""
        # Case A: Symmetric odds
        sym_odds = {"home_win": 2.80, "draw": 3.20, "away_win": 2.80}
        p_power = power_method_probs(sym_odds)
        p_prop = implied_probabilities(sym_odds, remove_vig=True)
        assert abs(sum(p_power.values()) - 1.0) < 1e-6
        assert abs(sum(p_prop.values()) - 1.0) < 1e-6
        # On symmetric flanks, home and away must be equal
        assert abs(p_power["home_win"] - p_power["away_win"]) < 1e-6

        # Case B: Asymmetric odds (power method should penalize longshot more than proportional)
        asym_odds = {"home_win": 1.25, "draw": 6.00, "away_win": 12.00}
        p_power_asym = power_method_probs(asym_odds)
        p_prop_asym = implied_probabilities(asym_odds, remove_vig=True)
        assert p_power_asym["away_win"] < p_prop_asym["away_win"]
        assert p_power_asym["home_win"] > p_prop_asym["home_win"]


class TestAdversarialInputsAndMalformedData:
    """Stress testing resilience to invalid types, non-numeric values, and partial mappings."""

    def test_none_odds_mapping(self):
        """Passing None for odds must fail-closed cleanly."""
        summary = build_market_intelligence(odds=None)  # type: ignore[arg-type]
        assert summary.outcomes == {}
        assert summary.market_overround == 0.0
        assert summary.decision == MarketDecisionState.PARTIAL
        assert summary.stake_permitted is False
        assert "market_odds_unavailable" in summary.data_gaps

    def test_nan_infinity_and_negative_odds(self):
        """Odds containing NaN, Inf, negative, or <= 1.0001 are safely dropped."""
        dirty_odds = {
            "home_win": float("nan"),
            "draw": float("inf"),
            "away_win": -2.50,
        }
        summary = build_market_intelligence(odds=dirty_odds)
        assert summary.outcomes == {}
        assert summary.provenance.is_complete is False
        assert summary.decision == MarketDecisionState.PARTIAL
        assert summary.stake_permitted is False
        assert "market_odds_unavailable" in summary.data_gaps

    def test_boundary_odds_below_and_at_threshold(self):
        """Odds <= 1.0001 are filtered as invalid."""
        boundary_odds = {"home_win": 1.0, "draw": 1.0001, "away_win": 1.0002}
        summary = build_market_intelligence(odds=boundary_odds)
        # Only away_win is > 1.0001
        assert len(summary.outcomes) == 1
        assert "away_win" in summary.outcomes
        assert summary.provenance.is_complete is False
        assert summary.decision == MarketDecisionState.PARTIAL

    def test_malformed_model_probabilities(self):
        """Model probabilities with NaN, string, or negative values are handled gracefully."""
        odds = {"home_win": 2.0, "draw": 3.4, "away_win": 3.8}
        bad_model_probs = {
            "home_win": float("nan"),
            "draw": -0.25,
            "away_win": "invalid",  # type: ignore[dict-item]
        }
        summary = build_market_intelligence(odds=odds, model_probabilities=bad_model_probs)
        assert summary.provenance.is_complete is True
        for o in summary.outcomes.values():
            assert o.model_probability is None
            assert o.probability_edge is None
            assert o.expected_value is None
            assert o.classification == EdgeClassification.INSUFFICIENT_DATA


class TestUncertifiedStakingLockInvariant:
    """Rigorous invariant testing: uncertified models MUST NEVER permit staking."""

    def test_live_uncertified_state_from_disk(self):
        """Verify directly against disk state that active generation returns UNVERIFIED and forbids staking."""
        summary = build_market_intelligence(
            odds={"home_win": 3.0, "draw": 3.5, "away_win": 2.5},
            model_probabilities={"home_win": 0.85, "draw": 0.10, "away_win": 0.05},
        )
        assert summary.provenance.certification_state == "UNVERIFIED"
        assert summary.stake_permitted is False
        assert summary.decision == MarketDecisionState.RESEARCH_ONLY

    @patch("src.services.market_intel.active_generation_is_certified", return_value=False)
    @patch("src.services.market_intel.active_model_version", return_value="v5_unverified")
    @patch("src.services.market_intel.active_feature_schema_version", return_value="canonical_58")
    def test_randomized_edges_on_uncertified_model(self, mock_schema, mock_ver, mock_cert):
        """Assert stake_permitted is False across 200 randomized edge scenarios when uncertified."""
        rng = random.Random(42)

        for _ in range(200):
            # Generate random realistic to extreme odds
            h_odds = rng.uniform(1.05, 20.0)
            d_odds = rng.uniform(2.0, 20.0)
            a_odds = rng.uniform(1.05, 20.0)
            odds = {"home_win": h_odds, "draw": d_odds, "away_win": a_odds}

            # Generate random model probabilities (even absurdly high ones)
            p1 = rng.uniform(0.0, 1.0)
            p2 = rng.uniform(0.0, 1.0 - p1)
            p3 = max(0.0, 1.0 - p1 - p2)
            model_probs = {"home_win": p1, "draw": p2, "away_win": p3}

            summary = build_market_intelligence(odds=odds, model_probabilities=model_probs)

            # Invariant assertions:
            assert summary.stake_permitted is False, (
                f"Invariant violated! stake_permitted was True for uncertified model! "
                f"odds={odds}, model_probs={model_probs}"
            )
            assert summary.decision == MarketDecisionState.RESEARCH_ONLY
            assert summary.provenance.certification_state == "UNVERIFIED"

    def test_active_generation_error_falls_back_to_unverified(self):
        """When active_generation module raises ActiveGenerationError, fail closed."""
        with patch("src.services.market_intel.active_generation_is_certified", side_effect=RuntimeError("Corrupt manifest")):
            with patch("src.services.market_intel.active_model_version", side_effect=RuntimeError("Corrupt manifest")):
                with patch("src.services.market_intel.active_feature_schema_version", side_effect=RuntimeError("Corrupt manifest")):
                    summary = build_market_intelligence(
                        odds={"home_win": 2.0, "draw": 3.4, "away_win": 3.8},
                        model_probabilities={"home_win": 0.8, "draw": 0.1, "away_win": 0.1},
                    )
                    assert summary.provenance.certification_state == "UNVERIFIED"
                    assert summary.provenance.model_version == "v5_unverified"
                    assert summary.provenance.feature_schema_version == "canonical_58"
                    assert summary.stake_permitted is False
                    assert summary.decision == MarketDecisionState.RESEARCH_ONLY


class TestSuspensionsAndInPlayFailClosedGates:
    """Verify that suspended and in-play markets block staking even when certified."""

    @patch("src.services.market_intel.active_generation_is_certified", return_value=True)
    def test_certified_model_suspended_market_blocks_staking(self, mock_cert):
        """Suspended market with certified model and massive edge must HOLD and forbid staking."""
        odds = {"home_win": 3.0, "draw": 3.5, "away_win": 2.5}
        model_probs = {"home_win": 0.70, "draw": 0.15, "away_win": 0.15}

        summary = build_market_intelligence(
            odds=odds,
            model_probabilities=model_probs,
            is_suspended=True,
            pre_kickoff=True,
        )

        assert summary.provenance.is_suspended is True
        assert summary.provenance.certification_state == "CERTIFIED"
        assert summary.stake_permitted is False
        assert summary.decision == MarketDecisionState.HOLD
        assert "market_suspended" in summary.data_gaps

    @patch("src.services.market_intel.active_generation_is_certified", return_value=True)
    def test_certified_model_in_play_market_blocks_staking(self, mock_cert):
        """In-play match (pre_kickoff=False) with certified model and huge edge must HOLD and forbid staking."""
        odds = {"home_win": 3.0, "draw": 3.5, "away_win": 2.5}
        model_probs = {"home_win": 0.70, "draw": 0.15, "away_win": 0.15}

        summary = build_market_intelligence(
            odds=odds,
            model_probabilities=model_probs,
            is_suspended=False,
            pre_kickoff=False,
        )

        assert summary.provenance.pre_kickoff is False
        assert summary.provenance.certification_state == "CERTIFIED"
        assert summary.stake_permitted is False
        assert summary.decision == MarketDecisionState.HOLD
        assert "in_play_or_post_match" in summary.data_gaps

    @patch("src.services.market_intel.active_generation_is_certified", return_value=True)
    def test_positive_edge_but_negative_ev_blocks_staking(self, mock_cert):
        """Under high overround, positive edge with negative EV must NOT permit staking."""
        # Construct synthetic scenario with high bookmaker vig
        # home fair prob ~ 0.449, raw implied = 0.6502 -> price = 1 / 0.6502 = 1.538
        # Model gives 0.55 -> edge = 0.55 - 0.449 = +0.101 (>= 0.042)
        # EV = 0.55 * 1.538 - 1.0 = 0.8459 - 1.0 = -0.1541 (< 0)
        # Draw and away model probs = 0.225, below fair ~ 0.2755 -> negative edge
        odds = {"home_win": 1.538, "draw": 2.00, "away_win": 2.00}
        model_probs = {"home_win": 0.55, "draw": 0.225, "away_win": 0.225}

        summary = build_market_intelligence(odds=odds, model_probabilities=model_probs)
        assert summary.best_edge_outcome == "home_win"
        assert summary.best_edge_value is not None and summary.best_edge_value >= 0.042
        # EV is negative
        assert summary.outcomes["home_win"].expected_value is not None
        assert summary.outcomes["home_win"].expected_value < 0
        # Staking MUST be forbidden because EV <= 0
        assert summary.stake_permitted is False
        assert summary.decision == MarketDecisionState.HOLD


class TestSerializationAndSchemaParity:
    """Verify Pydantic v2 JSON dumping, loading, and field compatibility."""

    def test_full_json_roundtrip(self):
        """Full market intelligence summary dumps to JSON and validates back identically."""
        captured_time = datetime(2026, 8, 30, 6, 0, 0, tzinfo=timezone.utc)
        odds = {"home_win": 2.10, "draw": 3.40, "away_win": 3.60}
        model_probs = {"home_win": 0.50, "draw": 0.28, "away_win": 0.22}

        summary = build_market_intelligence(
            odds=odds,
            model_probabilities=model_probs,
            provider="the_odds_api",
            bookmaker="betfair",
            captured_at=captured_time,
            staleness_seconds=45,
            is_suspended=False,
            pre_kickoff=True,
            uncertainty_available=True,
        )

        json_str = summary.model_dump_json()
        assert isinstance(json_str, str)

        reloaded = MarketIntelligenceSummary.model_validate_json(json_str)
        assert reloaded.market_overround == summary.market_overround
        assert reloaded.stake_permitted == summary.stake_permitted
        assert reloaded.decision == summary.decision
        assert reloaded.provenance.provider == "the_odds_api"
        assert reloaded.provenance.bookmaker == "betfair"
        assert reloaded.provenance.model_version == summary.provenance.model_version
        assert reloaded.provenance.captured_at == captured_time
        assert len(reloaded.outcomes) == 3
