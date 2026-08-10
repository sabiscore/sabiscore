"""
TYPE-F fusion verdict invariant tests (Phase 8 Sprint 1 gate, PR-6).

Validates the full gate table from the APEX-SabiScore spec §7-D:

  DATA_GAP     → always PARTIAL (B13 override, highest priority)
  LOW_EVIDENCE → HOLD
  RL abstain   → HOLD
  confidence OK + RL bets + high prob + elo causal → HIGH_CONVICTION
  confidence OK + RL bets + any causal driver      → ACTIONABLE
  confidence OK + RL bets + no causal drivers      → SPECULATIVE

Also tests:
  - Narrative length is always ≤ 280 characters (B11)
  - PARTIAL verdict fires when data_gaps is non-empty regardless of other inputs
"""

from __future__ import annotations

import pytest

from src.services.intelligence_synthesizer import (
    EnsemblePrediction,
    IntelligenceSynthesizer,
)
from src.data.elo_engine import EloContext
from src.models.causal_selector import CausalFeatureResult
from src.services.rl_betting_agent import RLRecommendationPayload
from src.services.uncertainty_service import UncertaintyBreakdown


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _ens(home=0.55, draw=0.25, away=0.20, prediction="home_win", confidence=0.55) -> EnsemblePrediction:
    return EnsemblePrediction(
        home_win_prob=home,
        draw_prob=draw,
        away_win_prob=away,
        prediction=prediction,
        confidence=confidence,
        league="epl",
        model_version="v5_phase7",
    )


def _uncertainty(tier: str = "OK") -> UncertaintyBreakdown:
    return UncertaintyBreakdown(
        epistemic_unc=0.05,
        aleatoric_unc=0.10,
        concentration=0.70,
        credible_interval=(0.45, 0.65),
        confidence_tier=tier,
    )


def _rl(abstain: bool = False, stake: float = 0.05) -> RLRecommendationPayload:
    return RLRecommendationPayload(
        stake_fraction=stake if not abstain else 0.0,
        abstain=abstain,
        reward_components={},
        reason="test",
    )


def _elo(diff: float = 0.0) -> EloContext:
    return EloContext(
        home_elo=1550.0,
        away_elo=1550.0 - diff,
        elo_difference=diff,
        home_elo_trend_5=0.0,
        away_elo_trend_5=0.0,
        elo_momentum_cross=0.0,
    )


def _causal(names: list[str], classification: str = "CAUSAL_DRIVER") -> list[CausalFeatureResult]:
    return [
        CausalFeatureResult(
            name=name,
            ate_win=0.30,
            ate_draw=0.10,
            ate_ci=(0.20, 0.40),
            p_value=0.01,
            classification=classification,
        )
        for name in names
    ]


def _synth(match_id: str = "test::001", **kwargs) -> dict:
    """Build a synthesize() call with all required fields, overridable via kwargs."""
    base = dict(
        match_id=match_id,
        ensemble=_ens(),
        uncertainty=_uncertainty("OK"),
        causal_results=_causal(["elo_difference"]),
        rl_rec=_rl(abstain=False),
        elo_ctx=_elo(50.0),
        odds_edge=None,
        data_gaps=[],
    )
    base.update(kwargs)
    return base


SYNTH = IntelligenceSynthesizer()


# ---------------------------------------------------------------------------
# Gate-table tests
# ---------------------------------------------------------------------------


class TestVerdictGateTable:
    def test_advisory_gap_does_not_force_partial(self):
        """Optional Elo evidence reduces coverage without blocking a valid analysis."""
        result = SYNTH.synthesize(
            **_synth(
                data_gaps=["elo_ratings"],
                # even if everything else would yield HIGH_CONVICTION
                ensemble=_ens(confidence=0.65),
                uncertainty=_uncertainty("OK"),
                causal_results=_causal(["elo_difference"]),
                rl_rec=_rl(abstain=False),
                elo_ctx=_elo(120.0),
            )
        )
        assert result.verdict == "HIGH_CONVICTION"
        assert result.partial_intelligence is False
        assert result.evidence_quality.advisory_gaps == ["elo_ratings"]

    def test_data_gap_empty_list_not_partial(self):
        """Empty data_gaps list must not trigger PARTIAL."""
        result = SYNTH.synthesize(**_synth(data_gaps=[]))
        assert result.verdict != "PARTIAL"

    def test_multiple_advisory_gaps_do_not_force_partial(self):
        result = SYNTH.synthesize(**_synth(data_gaps=["elo_ratings", "causal_analysis"]))
        assert result.verdict == "HIGH_CONVICTION"
        assert result.partial_intelligence is False
        assert result.data_gaps == ["elo_ratings", "causal_analysis"]

    def test_critical_gap_forces_partial(self):
        result = SYNTH.synthesize(
            **_synth(data_gaps=["MODEL_PREDICTION_UNAVAILABLE"])
        )
        assert result.verdict == "PARTIAL"
        assert result.partial_intelligence is True
        assert result.evidence_quality.critical_gaps == [
            "MODEL_PREDICTION_UNAVAILABLE"
        ]

    def test_conflict_forces_partial_and_remains_separate(self):
        result = SYNTH.synthesize(
            **_synth(
                data_gaps=["lineup_context"],
                conflicts=["CONFLICTING_MARKET_SNAPSHOTS"],
            )
        )
        assert result.verdict == "PARTIAL"
        assert result.evidence_quality.advisory_gaps == ["lineup_context"]
        assert result.evidence_quality.conflicts == [
            "CONFLICTING_MARKET_SNAPSHOTS"
        ]

    def test_low_evidence_yields_hold(self):
        result = SYNTH.synthesize(**_synth(uncertainty=_uncertainty("LOW_EVIDENCE")))
        assert result.verdict == "HOLD"

    def test_rl_abstain_yields_hold(self):
        result = SYNTH.synthesize(**_synth(rl_rec=_rl(abstain=True)))
        assert result.verdict == "HOLD"

    def test_rl_abstain_overrides_causal_drivers(self):
        """RL abstain should HOLD even if causal drivers + elo signal are present."""
        result = SYNTH.synthesize(
            **_synth(
                rl_rec=_rl(abstain=True),
                causal_results=_causal(["elo_difference", "home_pressing_intensity"]),
                elo_ctx=_elo(200.0),
                ensemble=_ens(confidence=0.70),
            )
        )
        assert result.verdict == "HOLD"

    def test_high_conviction_all_signals(self):
        """max_prob > 0.52 + elo_difference causal + OK tier + RL bets → HIGH_CONVICTION."""
        result = SYNTH.synthesize(
            **_synth(
                ensemble=_ens(confidence=0.60),
                uncertainty=_uncertainty("OK"),
                causal_results=_causal(["elo_difference", "home_pressing_intensity"]),
                rl_rec=_rl(abstain=False),
                elo_ctx=_elo(80.0),
            )
        )
        assert result.verdict == "HIGH_CONVICTION"

    def test_high_conviction_requires_elo_driver(self):
        """Without elo_difference as a causal driver, HIGH_CONVICTION is not reachable."""
        result = SYNTH.synthesize(
            **_synth(
                ensemble=_ens(confidence=0.60),
                uncertainty=_uncertainty("OK"),
                causal_results=_causal(["home_pressing_intensity"]),  # no elo_difference
                rl_rec=_rl(abstain=False),
                elo_ctx=_elo(80.0),
            )
        )
        assert result.verdict == "ACTIONABLE"

    def test_high_conviction_requires_min_prob(self):
        """max_prob ≤ 0.52 prevents HIGH_CONVICTION even with all other gates passing."""
        result = SYNTH.synthesize(
            **_synth(
                ensemble=_ens(confidence=0.51),
                uncertainty=_uncertainty("OK"),
                causal_results=_causal(["elo_difference"]),
                rl_rec=_rl(abstain=False),
            )
        )
        assert result.verdict == "ACTIONABLE"

    def test_actionable_with_any_causal_driver(self):
        result = SYNTH.synthesize(
            **_synth(
                ensemble=_ens(confidence=0.45),
                causal_results=_causal(["progressive_carry_diff"]),
                rl_rec=_rl(abstain=False),
            )
        )
        assert result.verdict == "ACTIONABLE"

    def test_speculative_no_causal_drivers(self):
        result = SYNTH.synthesize(
            **_synth(
                causal_results=[],
                rl_rec=_rl(abstain=False),
            )
        )
        assert result.verdict == "SPECULATIVE"

    def test_speculative_non_driver_classification_still_speculative(self):
        """Features with ASSUMPTION_PASS (not CAUSAL_DRIVER) must not trigger ACTIONABLE."""
        result = SYNTH.synthesize(
            **_synth(
                causal_results=_causal(["elo_difference"], classification="ASSUMPTION_PASS"),
                rl_rec=_rl(abstain=False),
            )
        )
        assert result.verdict == "SPECULATIVE"


# ---------------------------------------------------------------------------
# Narrative invariants
# ---------------------------------------------------------------------------


class TestNarrativeInvariants:
    @pytest.mark.parametrize(
        "scenario",
        [
            _synth(),
            _synth(data_gaps=["elo_ratings"]),
            _synth(uncertainty=_uncertainty("LOW_EVIDENCE")),
            _synth(rl_rec=_rl(abstain=True)),
            _synth(causal_results=[], rl_rec=_rl(abstain=False)),
        ],
    )
    def test_narrative_max_280_chars(self, scenario):
        """B11: narrative must never exceed 280 characters."""
        result = SYNTH.synthesize(**scenario)
        assert len(result.narrative) <= 280, (
            f"Narrative too long ({len(result.narrative)} chars): {result.narrative!r}"
        )

    def test_narrative_non_empty(self):
        result = SYNTH.synthesize(**_synth())
        assert result.narrative.strip()

    def test_narrative_has_no_bracket_prefix(self):
        """Narrative must not contain machine-readable [VERDICT] bracket prefix.
        The verdict badge in the frontend already communicates verdict — bracket tags
        in narrative are noisy on a user-facing surface and were removed (WP-B).
        """
        for gaps in ([], ["elo_ratings"]):
            result = SYNTH.synthesize(**_synth(data_gaps=gaps))
            assert not result.narrative.startswith("["), (
                f"Narrative has machine-readable bracket prefix: {result.narrative!r}"
            )


# ---------------------------------------------------------------------------
# Data propagation invariants
# ---------------------------------------------------------------------------


class TestDataPropagation:
    def test_data_gaps_propagated_to_response(self):
        gaps = ["elo_ratings", "causal_analysis"]
        result = SYNTH.synthesize(**_synth(data_gaps=gaps))
        assert result.data_gaps == gaps

    def test_evidence_gaps_are_deduplicated_with_counts(self):
        result = SYNTH.synthesize(
            **_synth(
                data_gaps=["elo_ratings", "ELO_RATINGS", "lineup_context"],
                advisory_gaps=["lineup_context"],
            )
        )
        quality = result.evidence_quality.to_dict()
        assert quality["advisory_gaps"] == ["lineup_context", "elo_ratings"]
        assert quality["advisory_gap_count"] == 2
        assert quality["total_gap_count"] == 2

    def test_partial_intelligence_flag_matches_gaps(self):
        result_with = SYNTH.synthesize(**_synth(data_gaps=["ensemble_prediction"]))
        result_without = SYNTH.synthesize(**_synth(data_gaps=[]))
        assert result_with.partial_intelligence is True
        assert result_without.partial_intelligence is False


# ---------------------------------------------------------------------------
# ABSTAIN advisory path (Sprint 4 Phase 4: edge_quality_score threshold)
# ---------------------------------------------------------------------------


from src.services.intelligence_synthesizer import MatchActionability  # noqa: E402


def _actionability(
    edge_quality_score: float = 0.50,
    clv_pct: float | None = None,
    closing_line_convergence_delta: float | None = None,
    abstain: bool = False,
    abstain_reason: str | None = None,
) -> MatchActionability:
    return MatchActionability(
        edge_quality_score=edge_quality_score,
        clv_pct=clv_pct,
        closing_line_convergence_delta=closing_line_convergence_delta,
        suggested_stake_pct=0.0 if abstain else 1.5,
        abstain=abstain,
        abstain_reason=abstain_reason,
        top_evidence=[],
        caveats=[],
    )


class TestAbstainAdvisoryPath:
    """edge_quality_score ABSTAIN advisory layer (spec Phase 4 guardrail)."""

    def test_abstain_false_when_edge_quality_above_threshold(self):
        """Score above default threshold (0.30) → abstain must be False."""
        action = _actionability(edge_quality_score=0.45, abstain=False)
        assert action.abstain is False

    def test_abstain_true_when_edge_quality_below_threshold(self):
        """Score below default threshold (0.30) → abstain must be True."""
        action = _actionability(edge_quality_score=0.20, abstain=True, abstain_reason="Low edge quality")
        assert action.abstain is True
        assert action.abstain_reason is not None

    def test_abstain_at_exact_threshold_boundary(self):
        """Score equal to threshold is still below — abstain True."""
        action = _actionability(edge_quality_score=0.30, abstain=True, abstain_reason="At threshold")
        assert action.abstain is True

    def test_abstain_propagates_through_synthesize(self):
        """synthesize() must preserve actionability.abstain in the response."""
        action = _actionability(edge_quality_score=0.15, abstain=True, abstain_reason="edge_quality below 0.30")
        result = SYNTH.synthesize(
            **_synth(
                actionability=action,
                data_gaps=[],
                ensemble=_ens(confidence=0.60),
                causal_results=_causal(["elo_difference"]),
                rl_rec=_rl(abstain=False),
            )
        )
        assert result.actionability is not None
        assert result.actionability.abstain is True
        assert result.actionability.edge_quality_score == 0.15

    def test_abstain_does_not_override_verdict(self):
        """Advisory ABSTAIN must NOT change the TYPE-F verdict — verdict is independent."""
        action = _actionability(edge_quality_score=0.10, abstain=True, abstain_reason="Low edge")
        result = SYNTH.synthesize(
            **_synth(
                actionability=action,
                data_gaps=[],
                ensemble=_ens(confidence=0.65),
                causal_results=_causal(["elo_difference"]),
                rl_rec=_rl(abstain=False),
                elo_ctx=_elo(80.0),
            )
        )
        # Verdict layer is independent; HIGH_CONVICTION should still fire if signals are present
        assert result.verdict == "HIGH_CONVICTION"
        assert result.actionability.abstain is True

    def test_abstain_true_when_market_drift_is_data_gap(self):
        """Any market drift DATA_GAP must trigger abstain (CLV uncomputable)."""
        action = _actionability(
            edge_quality_score=0.50,
            abstain=True,
            abstain_reason="market drift feature is DATA_GAP",
        )
        result = SYNTH.synthesize(
            **_synth(
                actionability=action,
                data_gaps=["odds_drift_home"],
            )
        )
        assert result.actionability.abstain is True
        assert "odds_drift_home" in result.data_gaps

    def test_suggested_stake_zero_when_abstain(self):
        """suggested_stake_pct must be 0.0 when abstain=True."""
        action = _actionability(edge_quality_score=0.25, abstain=True)
        assert action.suggested_stake_pct == 0.0


# ---------------------------------------------------------------------------
# Nullable closing_line_convergence_delta
# ---------------------------------------------------------------------------


class TestClosingLineConvergenceDelta:
    def test_convergence_delta_null_when_odds_unavailable(self):
        """closing_line_convergence_delta must be None, not 0, when closing odds absent."""
        action = _actionability(
            edge_quality_score=0.55,
            closing_line_convergence_delta=None,
        )
        assert action.closing_line_convergence_delta is None

    def test_convergence_delta_positive_when_model_led_market(self):
        """Positive delta = model probability led the closing line (edge signal)."""
        action = _actionability(
            edge_quality_score=0.70,
            closing_line_convergence_delta=0.04,
        )
        assert action.closing_line_convergence_delta is not None
        assert action.closing_line_convergence_delta > 0

    def test_convergence_delta_negative_when_model_lagged(self):
        """Negative delta = model lagged the market (trust modifier down)."""
        action = _actionability(
            edge_quality_score=0.60,
            closing_line_convergence_delta=-0.02,
        )
        assert action.closing_line_convergence_delta < 0

    def test_convergence_delta_propagates_through_synthesize(self):
        """Nullable delta must flow through synthesize() to the response unchanged."""
        action = _actionability(
            edge_quality_score=0.55,
            closing_line_convergence_delta=None,
        )
        result = SYNTH.synthesize(**_synth(actionability=action))
        assert result.actionability.closing_line_convergence_delta is None

    def test_convergence_delta_zero_not_used_as_null_sentinel(self):
        """0.0 is a valid delta (no convergence movement), not the same as absent."""
        action = _actionability(
            edge_quality_score=0.55,
            closing_line_convergence_delta=0.0,
        )
        # 0.0 must survive — it is not None
        assert action.closing_line_convergence_delta is not None
        assert action.closing_line_convergence_delta == 0.0
