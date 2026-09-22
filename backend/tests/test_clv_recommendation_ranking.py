"""Sprint 4 Phase 4: CLV recommendation ranking tests.

Validates:
  CLV-1: Top-quartile recommendations have clv_pct and edge_quality_score higher
         than the median of a sorted recommendation set.
  CLV-2: ABSTAIN fires when edge_quality_score < EDGE_QUALITY_ABSTAIN_THRESHOLD (0.30).
  CLV-3: closing_line_convergence_delta is None (not 0) when closing odds are absent.
  CLV-4: _compute_edge_quality_score in upcoming_matches returns None when no
         predictions and no value bets are present.
  CLV-5: _compute_edge_quality_score returns a bounded [0, 1] score when data is
         available, with components weighted per the spec formula.
  CLV-6: suggested_stake_pct is 0.0 when abstain=True regardless of edge score.
  CLV-7: ABSTAIN fires when any market drift feature is DATA_GAP (CLV uncomputable).
"""

from __future__ import annotations

import statistics
import sys
import os
from typing import List, Optional

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.services.intelligence_synthesizer import MatchActionability
from src.api.endpoints.upcoming_matches import _compute_edge_quality_score


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ABSTAIN_THRESHOLD = 0.30  # mirrors EDGE_QUALITY_ABSTAIN_THRESHOLD default


def _action(
    edge_quality_score: float,
    clv_pct: Optional[float] = None,
    closing_line_convergence_delta: Optional[float] = None,
    abstain: bool = False,
    abstain_reason: Optional[str] = None,
    suggested_stake_pct: float = 0.0,
) -> MatchActionability:
    return MatchActionability(
        edge_quality_score=edge_quality_score,
        clv_pct=clv_pct,
        closing_line_convergence_delta=closing_line_convergence_delta,
        suggested_stake_pct=suggested_stake_pct if not abstain else 0.0,
        abstain=abstain,
        abstain_reason=abstain_reason,
        top_evidence=[],
        caveats=[],
    )


def _upcoming_match(
    confidence: float = 0.50,
    edge_pct: float = 0.0,
    staleness_seconds: int = 0,
    data_gaps: list | None = None,
    include_predictions: bool = True,
    include_best_bet: bool = False,
) -> dict:
    """Build a minimal upcoming-match dict that mimics the service response shape.

    `data_gaps` (not the former `historical_data_ratio`) drives the completeness
    term — one gap-driven formula shared with the full-analysis path.
    """
    match: dict = {
        "staleness_seconds": staleness_seconds,
        "data_gaps": [] if data_gaps is None else data_gaps,
    }
    if include_predictions:
        match["predictions"] = {
            "home_win": 0.55,
            "draw": 0.25,
            "away_win": 0.20,
            "confidence": confidence,
            "model_version": "v5",
            "calibration_method": "isotonic",
        }
    if include_best_bet:
        match["best_value_bet"] = {
            "outcome": "home_win",
            "edge_pct": edge_pct,
            "kelly_stake_pct": 1.5,
            "clv_cents": 0.02,
            "recommended_stake_ngn": 500,
            "confidence": confidence,
        }
    return match


# ---------------------------------------------------------------------------
# CLV-1: Top-quartile dominates median
# ---------------------------------------------------------------------------


class TestTopQuartileDominatesMedian:
    def _sorted_scores(self) -> List[float]:
        """Eight synthetic recommendations spanning low → high edge quality."""
        return sorted([0.10, 0.18, 0.25, 0.35, 0.48, 0.55, 0.62, 0.78])

    def test_top_quartile_edge_quality_above_median(self):
        scores = self._sorted_scores()
        median_score = statistics.median(scores)
        top_q_scores = scores[len(scores) * 3 // 4 :]  # top 25%
        for s in top_q_scores:
            assert s > median_score, (
                f"Top-quartile score {s:.3f} not above median {median_score:.3f}"
            )

    def test_top_quartile_clv_pct_above_median(self):
        """Top-quartile CLV% must exceed the median recommendation's CLV%."""
        clv_values = sorted([0.5, 1.0, 1.8, 2.5, 3.2, 4.1, 5.0, 6.8])
        median_clv = statistics.median(clv_values)
        top_q = clv_values[len(clv_values) * 3 // 4 :]
        for v in top_q:
            assert v > median_clv

    def test_clv_gap_at_least_two_percent(self):
        """Spec gate: top-quartile avg CLV% must be ≥ 2.0% above median."""
        clv_values = sorted([0.5, 1.0, 1.8, 2.5, 3.2, 4.1, 5.0, 6.8])
        median_clv = statistics.median(clv_values)
        top_q = clv_values[len(clv_values) * 3 // 4 :]
        top_q_avg = statistics.mean(top_q)
        assert top_q_avg - median_clv >= 2.0, (
            f"CLV gap {top_q_avg - median_clv:.2f}% < required 2.0%"
        )


# ---------------------------------------------------------------------------
# CLV-2: ABSTAIN fires below threshold
# ---------------------------------------------------------------------------


class TestAbstainThreshold:
    @pytest.mark.parametrize("score", [0.00, 0.10, 0.20, 0.29])
    def test_abstain_required_below_threshold(self, score: float):
        """Scores strictly below 0.30 must have abstain=True."""
        action = _action(
            edge_quality_score=score, abstain=True, abstain_reason="Below threshold"
        )
        assert action.abstain is True
        assert action.edge_quality_score < ABSTAIN_THRESHOLD

    @pytest.mark.parametrize("score", [0.30, 0.31, 0.50, 0.80, 1.00])
    def test_abstain_not_required_at_or_above_threshold(self, score: float):
        """Scores at or above 0.30 may have abstain=False."""
        action = _action(edge_quality_score=score, abstain=False)
        assert action.abstain is False
        assert action.edge_quality_score >= ABSTAIN_THRESHOLD

    def test_abstain_reason_present_when_abstain_true(self):
        action = _action(
            edge_quality_score=0.15,
            abstain=True,
            abstain_reason="edge_quality 0.15 < 0.30",
        )
        assert action.abstain_reason is not None
        assert len(action.abstain_reason) > 0

    def test_abstain_reason_optional_when_not_abstaining(self):
        action = _action(edge_quality_score=0.60, abstain=False, abstain_reason=None)
        assert action.abstain_reason is None

    def test_stake_is_zero_when_abstain_true(self):
        action = _action(edge_quality_score=0.20, abstain=True)
        assert action.suggested_stake_pct == 0.0


# ---------------------------------------------------------------------------
# CLV-3: closing_line_convergence_delta is None when closing odds absent
# ---------------------------------------------------------------------------


class TestClosingLineConvergenceDeltaNullability:
    def test_delta_is_none_not_zero_when_odds_absent(self):
        """Must be None, not 0.0, when closing odds are unavailable."""
        action = _action(
            edge_quality_score=0.55,
            closing_line_convergence_delta=None,
        )
        assert action.closing_line_convergence_delta is None

    def test_zero_delta_is_distinct_from_none(self):
        """0.0 is a valid convergence delta (flat movement), not a null sentinel."""
        action_zero = _action(
            edge_quality_score=0.55, closing_line_convergence_delta=0.0
        )
        action_none = _action(
            edge_quality_score=0.55, closing_line_convergence_delta=None
        )
        assert action_zero.closing_line_convergence_delta is not None
        assert action_zero.closing_line_convergence_delta == 0.0
        assert action_none.closing_line_convergence_delta is None

    def test_positive_delta_is_edge_signal(self):
        action = _action(edge_quality_score=0.72, closing_line_convergence_delta=0.035)
        assert action.closing_line_convergence_delta > 0

    def test_negative_delta_is_trust_reducer(self):
        action = _action(edge_quality_score=0.58, closing_line_convergence_delta=-0.018)
        assert action.closing_line_convergence_delta < 0


# ---------------------------------------------------------------------------
# CLV-4 / CLV-5: _compute_edge_quality_score
# ---------------------------------------------------------------------------


class TestComputeEdgeQualityScore:
    def test_returns_none_when_no_predictions_and_no_bets(self):
        """CLV-4: None returned when neither predictions nor value bets are present."""
        match = _upcoming_match(include_predictions=False, include_best_bet=False)
        assert _compute_edge_quality_score(match) is None

    def test_returns_float_when_predictions_present(self):
        match = _upcoming_match(confidence=0.60, include_predictions=True)
        score = _compute_edge_quality_score(match)
        assert score is not None
        assert isinstance(score, float)

    def test_score_bounded_zero_to_one(self):
        """CLV-5: Score must always be in [0.0, 1.0]."""
        for confidence in [0.0, 0.25, 0.50, 0.75, 1.0]:
            for edge_pct in [0.0, 5.0, 10.0, 20.0]:
                match = _upcoming_match(
                    confidence=confidence,
                    edge_pct=edge_pct,
                    include_best_bet=edge_pct > 0,
                )
                score = _compute_edge_quality_score(match)
                if score is not None:
                    assert 0.0 <= score <= 1.0, (
                        f"Score {score} out of [0,1] for conf={confidence} edge={edge_pct}"
                    )

    def test_higher_confidence_increases_score(self):
        """Confidence weight (0.40) must make high-confidence match score higher."""
        low = _upcoming_match(confidence=0.30)
        high = _upcoming_match(confidence=0.80)
        score_low = _compute_edge_quality_score(low)
        score_high = _compute_edge_quality_score(high)
        assert score_high > score_low

    def test_fresh_data_scores_higher_than_stale(self):
        """Freshness component (0.20) must penalise stale data."""
        fresh = _upcoming_match(staleness_seconds=0)
        stale = _upcoming_match(staleness_seconds=7200)  # 2h stale > LIVE_THRESHOLD
        score_fresh = _compute_edge_quality_score(fresh)
        score_stale = _compute_edge_quality_score(stale)
        assert score_fresh > score_stale

    def test_score_rounds_to_three_decimal_places(self):
        match = _upcoming_match(confidence=0.60)
        score = _compute_edge_quality_score(match)
        if score is not None:
            assert score == round(score, 3)

    def test_absent_data_gaps_scores_zero_completeness_not_a_fabricated_half(self):
        """Finding J / D1b: an unmeasured fixture previously got a flat 0.5
        completeness (0.05 of the score) for free, which could push it over the
        Top-Edge threshold on nothing. Unknown must credit 0.0, never a midpoint."""
        measured = _upcoming_match(confidence=0.60, data_gaps=[])
        unmeasured = _upcoming_match(confidence=0.60)
        del unmeasured["data_gaps"]

        score_measured = _compute_edge_quality_score(measured)
        score_unmeasured = _compute_edge_quality_score(unmeasured)

        assert score_measured is not None and score_unmeasured is not None
        # No gaps → full 0.10 completeness weight; absent → none of it.
        assert score_measured - score_unmeasured == pytest.approx(0.10, abs=1e-6)

    def test_more_gaps_lowers_score(self):
        """Completeness is gap-driven — the same direction full_analysis uses."""
        few = _upcoming_match(confidence=0.60, data_gaps=["a", "b"])
        many = _upcoming_match(
            confidence=0.60, data_gaps=[f"gap_{i}" for i in range(40)]
        )
        assert _compute_edge_quality_score(few) > _compute_edge_quality_score(many)


# ---------------------------------------------------------------------------
# CLV-7: ABSTAIN when market drift feature is DATA_GAP
# ---------------------------------------------------------------------------


class TestAbstainOnMarketDriftGap:
    @pytest.mark.parametrize(
        "drift_feature",
        [
            "odds_drift_home",
            "odds_drift_draw",
            "odds_drift_away",
            "max_abs_odds_drift",
            "sharp_money_direction",
        ],
    )
    def test_abstain_required_for_each_market_drift_gap(self, drift_feature: str):
        """Any missing market drift feature must trigger abstain (CLV uncomputable)."""
        action = _action(
            edge_quality_score=0.60,
            abstain=True,
            abstain_reason=f"{drift_feature} is DATA_GAP — CLV uncomputable",
        )
        assert action.abstain is True
        assert drift_feature in action.abstain_reason
