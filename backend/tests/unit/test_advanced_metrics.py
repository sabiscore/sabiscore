"""Unit tests for Advanced Metrics Engine (PPDA, PSxG, xT).

Tests cover all mathematical invariants, edge cases, sign conventions, zero divisions,
negative input rejections, and fail-closed corpus verification.
"""

from __future__ import annotations

import pytest

from src.services.advanced_metrics import (
    MetricResult,
    MetricStatus,
    calculate_ppda,
    evaluate_shot_stopping,
    evaluate_xt,
)


class TestPPDA:
    """Tests for Passes Allowed Per Defensive Action (PPDA)."""

    def test_ppda_standard_calculation(self):
        """Standard PPDA formula: opponent_passes / defensive_actions."""
        # 450 passes / 45 actions = 10.0
        result = calculate_ppda(450, 45)
        assert result == 10.0

        # High pressing team allows fewer passes
        high_press = calculate_ppda(200, 40)
        assert high_press == 5.0

        # Low block team allows more passes
        low_block = calculate_ppda(600, 30)
        assert low_block == 20.0

    def test_ppda_zero_defensive_actions_returns_none(self):
        """Zero defensive actions must fail-closed and return None (not Infinity or error)."""
        result = calculate_ppda(100, 0)
        assert result is None

    def test_ppda_zero_opponent_passes_returns_zero(self):
        """Zero opponent passes with positive defensive actions returns 0.0."""
        result = calculate_ppda(0, 50)
        assert result == 0.0

    def test_ppda_negative_inputs_raise_value_error(self):
        """Negative passes or defensive actions must raise ValueError."""
        with pytest.raises(ValueError, match="non-negative"):
            calculate_ppda(-10, 5)

        with pytest.raises(ValueError, match="non-negative"):
            calculate_ppda(10, -5)

        with pytest.raises(ValueError, match="non-negative"):
            calculate_ppda(-100, -20)

    def test_ppda_float_inputs_and_rounding(self):
        """PPDA supports float inputs and rounds to 4 decimal places."""
        result = calculate_ppda(450.5, 45.0)
        assert result == round(450.5 / 45.0, 4)
        assert isinstance(result, float)


class TestShotStopping:
    """Tests for Post-Shot Expected Goals (PSxG) Shot-Stopping Delta."""

    def test_shot_stopping_positive_delta(self):
        """Positive delta: Goalkeeper saved MORE goals than expected (superior shot-stopping)."""
        # PSxG 2.5 - 1 goal conceded = +1.5 saved
        result = evaluate_shot_stopping(2.5, 1)
        assert result == 1.5

    def test_shot_stopping_negative_delta(self):
        """Negative delta: Goalkeeper conceded MORE goals than expected (sub-par shot-stopping)."""
        # PSxG 1.0 - 2 goals conceded = -1.0
        result = evaluate_shot_stopping(1.0, 2)
        assert result == -1.0

    def test_shot_stopping_on_par(self):
        """Zero delta: Goalkeeper performed exactly on par with expectation."""
        result = evaluate_shot_stopping(2.0, 2)
        assert result == 0.0

    def test_shot_stopping_negative_inputs_raise_value_error(self):
        """Negative PSxG or goals conceded must raise ValueError."""
        with pytest.raises(ValueError, match="non-negative"):
            evaluate_shot_stopping(-1.0, 2)

        with pytest.raises(ValueError, match="non-negative"):
            evaluate_shot_stopping(2.5, -1)

        with pytest.raises(ValueError, match="non-negative"):
            evaluate_shot_stopping(-0.5, -2)

    def test_shot_stopping_precision(self):
        """Validates numerical precision and floating point rounding."""
        result = evaluate_shot_stopping(1.33333, 1)
        assert result == 0.3333


class TestExpectedThreatXT:
    """Tests for Expected Threat (xT) calculation gating."""

    def test_xt_no_event_corpus_returns_advisory_requires_corpus(self):
        """When dense 2D event corpus is unavailable, returns ADVISORY_REQUIRES_CORPUS."""
        res = evaluate_xt(event_corpus_available=False, event_count=0)
        assert isinstance(res, MetricResult)
        assert res.value is None
        assert res.status == MetricStatus.ADVISORY_REQUIRES_CORPUS
        assert "corpus not available" in (res.reason or "").lower()

    def test_xt_corpus_flag_with_zero_count_requires_corpus(self):
        """Claimed corpus with 0 events is still classified as ADVISORY_REQUIRES_CORPUS."""
        res = evaluate_xt(event_corpus_available=True, event_count=0)
        assert res.value is None
        assert res.status == MetricStatus.ADVISORY_REQUIRES_CORPUS

    def test_xt_with_events_classified_as_uncertified_pipeline(self):
        """When events exist but serving pipeline is uncertified, returns UNAVAILABLE without synthetic numbers."""
        res = evaluate_xt(event_corpus_available=True, event_count=1200)
        assert res.value is None
        assert res.status == MetricStatus.UNAVAILABLE
        assert "uncertified" in (res.reason or "").lower()


class TestMetricStatusEnum:
    """Tests for MetricStatus enum integrity."""

    def test_metric_status_members(self):
        """Verify all required enum variants exist."""
        assert MetricStatus.AVAILABLE == "AVAILABLE"
        assert MetricStatus.PARTIAL == "PARTIAL"
        assert MetricStatus.UNAVAILABLE == "UNAVAILABLE"
        assert MetricStatus.ADVISORY_REQUIRES_CORPUS == "ADVISORY_REQUIRES_CORPUS"
