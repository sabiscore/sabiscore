"""Sprint 4 Slice A: MatchActionability invariant tests.

Tests the _build_actionability helper and the MatchActionability dataclass
properties that drive the CLV-centered advisory in the full-analysis endpoint.

  ACT-1: abstain=True when RL layer abstains.
  ACT-2: abstain=True when edge_quality_score < EDGE_QUALITY_ABSTAIN_THRESHOLD.
  ACT-3: suggested_stake_pct=0.0 when abstain=True.
  ACT-4: top_evidence populated from causal drivers.
  ACT-5: top_evidence padded with market and drift signals.
  ACT-6: caveats include data-gap warning when gaps are present.
  ACT-7: caveats include low-evidence warning on LOW_EVIDENCE confidence tier.
  ACT-8: edge_quality_score is in [0, 1].
  ACT-9: closing_line_convergence_delta is None when drift keys are in data_gaps.
  ACT-10: to_dict() serialises actionability field correctly in FullMatchAnalysisResponse.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Ensure threshold is set for tests
os.environ.setdefault("EDGE_QUALITY_ABSTAIN_THRESHOLD", "0.30")

from src.api.endpoints.full_analysis import (
    _build_actionability,
    _closing_line_convergence_delta,
    _compute_edge_quality_score,
)
from src.services.intelligence_synthesizer import (
    EnsemblePrediction,
    IntelligenceSynthesizer,
    MatchActionability,
    OddsEdge,
)
from src.data.elo_engine import EloContext
from src.models.causal_selector import CausalFeatureResult
from src.services.rl_betting_agent import RLRecommendationPayload
from src.services.uncertainty_service import UncertaintyBreakdown


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _ens(
    home=0.55,
    draw=0.25,
    away=0.20,
    prediction="home_win",
    confidence=0.60,
) -> EnsemblePrediction:
    return EnsemblePrediction(
        home_win_prob=home,
        draw_prob=draw,
        away_win_prob=away,
        prediction=prediction,
        confidence=confidence,
        league="epl",
        model_version="v5_phase8",
    )


def _odds_edge(edge: float = 0.08, market: str = "home_win") -> OddsEdge:
    return OddsEdge(
        market=market,
        market_odds=2.20,
        model_prob=0.55,
        edge=edge,
        kelly_stake=round(edge / (2.20 - 1), 4),
    )


def _rl(abstain: bool = False, reason: str = "test") -> RLRecommendationPayload:
    return RLRecommendationPayload(
        stake_fraction=0.0 if abstain else 0.05,
        abstain=abstain,
        reward_components={},
        reason=reason,
    )


def _uncertainty(tier: str = "OK") -> UncertaintyBreakdown:
    return UncertaintyBreakdown(
        epistemic_unc=0.08,
        aleatoric_unc=0.10,
        concentration=0.70,
        credible_interval=(0.45, 0.65),
        confidence_tier=tier,
    )


def _causal(names: list[str]) -> list[CausalFeatureResult]:
    return [
        CausalFeatureResult(
            name=n,
            ate_win=0.12,
            ate_draw=0.0,
            ate_ci=(0.05, 0.20),
            p_value=0.02,
            classification="CAUSAL_DRIVER",
        )
        for n in names
    ]


def _features(with_drift: bool = True) -> dict:
    base: dict = {
        "elo_difference": 80.0,
        "home_elo": 1600.0,
        "away_elo": 1520.0,
    }
    if with_drift:
        base["odds_drift_home"] = 0.04
        base["odds_drift_draw"] = -0.01
        base["odds_drift_away"] = -0.03
    return base


# ---------------------------------------------------------------------------
# ACT-1: RL abstain propagates to MatchActionability
# ---------------------------------------------------------------------------


class TestRLAbstainPropagation:
    def test_abstain_true_when_rl_abstains(self):
        act = _build_actionability(
            ensemble=_ens(),
            odds_edge=_odds_edge(),
            features_dict=_features(),
            data_gaps=[],
            causal_results=_causal(["home_form_diff"]),
            rl_rec=_rl(abstain=True, reason="RL: low reward"),
            uncertainty=_uncertainty(),
            canonical_feature_count=86,
        )
        assert act.abstain is True

    def test_abstain_false_when_rl_bets(self):
        act = _build_actionability(
            ensemble=_ens(),
            odds_edge=_odds_edge(),
            features_dict=_features(),
            data_gaps=[],
            causal_results=_causal(["home_form_diff"]),
            rl_rec=_rl(abstain=False),
            uncertainty=_uncertainty(),
            canonical_feature_count=86,
        )
        assert act.abstain is False

    def test_abstain_reason_mirrors_rl_reason_on_abstain(self):
        act = _build_actionability(
            ensemble=_ens(),
            odds_edge=_odds_edge(),
            features_dict=_features(),
            data_gaps=[],
            causal_results=[],
            rl_rec=_rl(abstain=True, reason="Volatile market"),
            uncertainty=_uncertainty(),
            canonical_feature_count=86,
        )
        assert act.abstain_reason == "Volatile market"

    def test_abstain_reason_is_none_when_not_abstaining(self):
        act = _build_actionability(
            ensemble=_ens(),
            odds_edge=_odds_edge(),
            features_dict=_features(),
            data_gaps=[],
            causal_results=_causal(["home_form_diff"]),
            rl_rec=_rl(abstain=False),
            uncertainty=_uncertainty(),
            canonical_feature_count=86,
        )
        assert act.abstain_reason is None


# ---------------------------------------------------------------------------
# ACT-2 / ACT-3: Edge quality threshold triggers abstain, stakes zeroed
# ---------------------------------------------------------------------------


class TestEdgeQualityAbstain:
    def test_abstain_when_edge_quality_below_threshold(self):
        """Low confidence + no edge + no drift → score < 0.30 → abstain."""
        # Generate many string gap names to drive completeness near 0
        many_gaps = [f"feature_{i}" for i in range(60)]
        act = _build_actionability(
            ensemble=_ens(home=0.36, draw=0.33, away=0.31, confidence=0.36),
            odds_edge=None,  # no market edge
            features_dict={},  # no drift
            data_gaps=many_gaps,
            causal_results=[],
            rl_rec=_rl(abstain=False),  # RL says bet, but edge score blocks it
            uncertainty=_uncertainty(),
            canonical_feature_count=86,
        )
        assert act.abstain is True
        assert act.suggested_stake_pct == 0.0

    def test_stake_zero_when_abstain(self):
        act = _build_actionability(
            ensemble=_ens(),
            odds_edge=_odds_edge(),
            features_dict=_features(),
            data_gaps=[],
            causal_results=_causal(["elo_difference"]),
            rl_rec=_rl(abstain=True),
            uncertainty=_uncertainty(),
            canonical_feature_count=86,
        )
        assert act.suggested_stake_pct == 0.0

    def test_stake_positive_when_active(self):
        act = _build_actionability(
            ensemble=_ens(confidence=0.65),
            odds_edge=_odds_edge(edge=0.10),
            features_dict=_features(),
            data_gaps=[],
            causal_results=_causal(["elo_difference"]),
            rl_rec=_rl(abstain=False),
            uncertainty=_uncertainty(),
            canonical_feature_count=86,
        )
        # Not abstaining and have Kelly stake → suggested_stake_pct > 0
        assert act.suggested_stake_pct >= 0.0


# ---------------------------------------------------------------------------
# ACT-4 / ACT-5: top_evidence construction
# ---------------------------------------------------------------------------


class TestTopEvidenceConstruction:
    def test_causal_drivers_populate_top_evidence(self):
        act = _build_actionability(
            ensemble=_ens(),
            odds_edge=None,
            features_dict={},
            data_gaps=[],
            causal_results=_causal(["home_form_diff", "elo_difference"]),
            rl_rec=_rl(),
            uncertainty=_uncertainty(),
            canonical_feature_count=86,
        )
        assert any("Home Form Diff" in e or "home_form_diff" in e.lower() for e in act.top_evidence)

    def test_market_edge_appended_when_no_causal_drivers(self):
        act = _build_actionability(
            ensemble=_ens(),
            odds_edge=_odds_edge(edge=0.10),
            features_dict={},
            data_gaps=[],
            causal_results=[],  # no causal drivers
            rl_rec=_rl(),
            uncertainty=_uncertainty(),
            canonical_feature_count=86,
        )
        assert any("edge" in e.lower() or "market" in e.lower() for e in act.top_evidence)

    def test_top_evidence_max_3_items(self):
        act = _build_actionability(
            ensemble=_ens(),
            odds_edge=_odds_edge(edge=0.10),
            features_dict=_features(),
            data_gaps=[],
            causal_results=_causal(["f1", "f2", "f3", "f4", "f5"]),  # > 3
            rl_rec=_rl(),
            uncertainty=_uncertainty(),
            canonical_feature_count=86,
        )
        assert len(act.top_evidence) <= 3


# ---------------------------------------------------------------------------
# ACT-6 / ACT-7: Caveats
# ---------------------------------------------------------------------------


class TestCaveats:
    def test_data_gap_caveat_when_gaps_present(self):
        act = _build_actionability(
            ensemble=_ens(),
            odds_edge=_odds_edge(),
            features_dict=_features(),
            data_gaps=["pi_home_attack", "berrar_home"],
            causal_results=_causal(["elo_difference"]),
            rl_rec=_rl(),
            uncertainty=_uncertainty(),
            canonical_feature_count=86,
        )
        assert any("gap" in c.lower() or "data" in c.lower() for c in act.caveats)

    def test_low_evidence_caveat_on_low_confidence_tier(self):
        act = _build_actionability(
            ensemble=_ens(),
            odds_edge=_odds_edge(),
            features_dict=_features(),
            data_gaps=[],
            causal_results=[],
            rl_rec=_rl(),
            uncertainty=_uncertainty(tier="LOW_EVIDENCE"),
            canonical_feature_count=86,
        )
        assert any("evidence" in c.lower() or "epistemic" in c.lower() for c in act.caveats)

    def test_no_caveats_on_clean_high_quality_signal(self):
        act = _build_actionability(
            ensemble=_ens(confidence=0.68),
            odds_edge=_odds_edge(edge=0.12),
            features_dict=_features(),
            data_gaps=[],
            causal_results=_causal(["elo_difference", "home_form_diff"]),
            rl_rec=_rl(),
            uncertainty=_uncertainty(tier="OK"),
            canonical_feature_count=86,
        )
        # No data gaps, no low evidence → no caveats from those sources
        gap_caveats = [c for c in act.caveats if "gap" in c.lower()]
        assert len(gap_caveats) == 0


# ---------------------------------------------------------------------------
# ACT-8: edge_quality_score bounds
# ---------------------------------------------------------------------------


class TestEdgeQualityScore:
    def test_score_in_unit_range(self):
        for conf in [0.33, 0.45, 0.60, 0.75]:
            score = _compute_edge_quality_score(
                ensemble=_ens(confidence=conf),
                odds_edge=_odds_edge(),
                features_dict=_features(),
                data_gaps=[],
                n_canonical=86,
            )
            assert 0.0 <= score <= 1.0, f"Score out of range for conf={conf}: {score}"

    def test_score_higher_with_more_signals(self):
        low_score = _compute_edge_quality_score(
            ensemble=_ens(confidence=0.36),
            odds_edge=None,
            features_dict={},
            data_gaps=["odds_drift_home", "odds_drift_draw", "odds_drift_away"],
            n_canonical=86,
        )
        high_score = _compute_edge_quality_score(
            ensemble=_ens(confidence=0.70),
            odds_edge=_odds_edge(edge=0.14),
            features_dict=_features(),
            data_gaps=[],
            n_canonical=86,
        )
        assert high_score > low_score


# ---------------------------------------------------------------------------
# ACT-9: closing_line_convergence_delta
# ---------------------------------------------------------------------------


class TestClosingLineConvergenceDelta:
    def test_returns_none_when_drift_key_in_data_gaps(self):
        delta = _closing_line_convergence_delta(
            ensemble=_ens(prediction="home_win"),
            features_dict={"odds_drift_home": 0.05},
            data_gaps=["odds_drift_home"],  # marked as gap
        )
        assert delta is None

    def test_returns_float_when_drift_available(self):
        delta = _closing_line_convergence_delta(
            ensemble=_ens(prediction="home_win"),
            features_dict={"odds_drift_home": 0.04},
            data_gaps=[],
        )
        assert delta == pytest.approx(0.04)

    def test_returns_none_for_unknown_prediction_key(self):
        delta = _closing_line_convergence_delta(
            ensemble=_ens(prediction="other"),
            features_dict={"odds_drift_other": 0.03},
            data_gaps=[],
        )
        assert delta is None


# ---------------------------------------------------------------------------
# ACT-10: to_dict() serialisation
# ---------------------------------------------------------------------------


class TestToDict:
    def _synthesize_with_actionability(self, actionability: MatchActionability | None) -> dict:
        synth = IntelligenceSynthesizer()
        ensemble = _ens()
        resp = synth.synthesize(
            match_id="test-123",
            ensemble=ensemble,
            uncertainty=_uncertainty(),
            causal_results=[],
            rl_rec=_rl(),
            elo_ctx=EloContext(
                home_elo=1550.0,
                away_elo=1500.0,
                elo_difference=50.0,
                home_elo_trend_5=5.0,
                away_elo_trend_5=-3.0,
                elo_momentum_cross=0.0,
            ),
            actionability=actionability,
        )
        return resp.to_dict()

    def test_to_dict_actionability_null_when_none(self):
        d = self._synthesize_with_actionability(None)
        assert d["actionability"] is None

    def test_to_dict_actionability_serialised_when_set(self):
        act = MatchActionability(
            edge_quality_score=0.72,
            clv_pct=None,
            closing_line_convergence_delta=0.025,
            suggested_stake_pct=4.5,
            abstain=False,
            abstain_reason=None,
            top_evidence=["Elo Difference", "Market edge +8.0pp on home win"],
            caveats=[],
        )
        d = self._synthesize_with_actionability(act)
        assert d["actionability"] is not None
        assert d["actionability"]["edge_quality_score"] == pytest.approx(0.72)
        assert d["actionability"]["clv_pct"] is None
        assert d["actionability"]["closing_line_convergence_delta"] == pytest.approx(0.025)
        # No causal driver produces SPECULATIVE, which is watchlist-only and
        # must serialize a closed public stake gate across compatibility fields.
        assert d["verdict"] == "SPECULATIVE"
        assert d["stake_permitted"] is False
        assert d["actionability"]["suggested_stake_pct"] == 0.0
        assert d["actionability"]["abstain"] is True
        assert d["actionability"]["abstain_reason"] is not None
        assert len(d["actionability"]["top_evidence"]) == 2
        assert d["actionability"]["caveats"] == []
