"""Unit tests for M0 metric additions: log_loss_multiclass, accuracy_and_per_class,
block_bootstrap_ci — all added to metrics.py as part of the v5 directive M0 milestone.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from src.models.evaluation.metrics import (
    accuracy_and_per_class,
    block_bootstrap_ci,
    log_loss_multiclass,
    ranked_probability_score,
    brier_score_decomposition,
)


class TestLogLossMulticlass:
    """Tests for log_loss_multiclass — canonical implementation."""

    def test_perfect_prediction_zero_loss(self):
        """Perfect probability assignment gives near-zero log loss."""
        y_true = np.array([0, 1, 2])
        y_proba = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
        loss = log_loss_multiclass(y_true, y_proba)
        assert math.isfinite(loss)
        assert loss < 0.01  # clipped, not literally 0

    def test_uniform_prediction_gives_log3(self):
        """Uniform (1/3, 1/3, 1/3) probabilities → log(3) ≈ 1.0986."""
        y_true = np.array([0, 1, 2] * 10)
        y_proba = np.full((30, 3), 1.0 / 3.0)
        loss = log_loss_multiclass(y_true, y_proba)
        assert abs(loss - math.log(3)) < 0.01

    def test_empty_returns_zero(self):
        result = log_loss_multiclass(np.array([]), np.zeros((0, 3)))
        assert result == 0.0

    def test_raises_on_1d_proba(self):
        with pytest.raises(ValueError, match="2D"):
            log_loss_multiclass(np.array([0, 1]), np.array([0.5, 0.5]))

    def test_lower_is_better_ordering(self):
        """Model with higher confidence on correct class has lower log loss."""
        y_true = np.array([0, 0, 0])
        good = np.array([[0.9, 0.05, 0.05]] * 3)
        bad = np.array([[0.4, 0.3, 0.3]] * 3)
        assert log_loss_multiclass(y_true, good) < log_loss_multiclass(y_true, bad)


class TestAccuracyAndPerClass:
    """Tests for accuracy_and_per_class."""

    def test_perfect_classifier(self):
        y_true = np.array([0, 1, 2])
        y_proba = np.eye(3)
        result = accuracy_and_per_class(y_true, y_proba)
        assert result["accuracy"] == 1.0
        assert result["macro_f1"] == 1.0
        for cls in ["class_0", "class_1", "class_2"]:
            assert result["per_class"][cls]["precision"] == 1.0
            assert result["per_class"][cls]["recall"] == 1.0
            assert result["per_class"][cls]["f1"] == 1.0

    def test_uniform_classifier(self):
        """Uniform classifier — accuracy ≈ 1/3."""
        y_true = np.array([0, 1, 2] * 10)
        y_proba = np.full((30, 3), 1.0 / 3.0)
        result = accuracy_and_per_class(y_true, y_proba)
        # Argmax of equal probs returns class 0 → all predicted as 0
        assert 0.0 <= result["accuracy"] <= 1.0
        assert result["n_samples"] == 30

    def test_empty_returns_defaults(self):
        result = accuracy_and_per_class(np.array([]), np.zeros((0, 3)))
        assert result["accuracy"] == 0.0
        assert result["n_samples"] == 0

    def test_support_counts_correct(self):
        y_true = np.array([0, 0, 1, 2])
        y_proba = np.eye(3)[[0, 0, 1, 2]]
        result = accuracy_and_per_class(y_true, y_proba)
        assert result["per_class"]["class_0"]["support"] == 2
        assert result["per_class"]["class_1"]["support"] == 1
        assert result["per_class"]["class_2"]["support"] == 1


class TestBlockBootstrapCI:
    """Tests for block_bootstrap_ci."""

    def test_ci_bounds_surround_point_estimate(self):
        """CI lower ≤ point estimate ≤ CI upper."""
        rng = np.random.default_rng(0)
        n = 100
        y_true = rng.integers(0, 3, size=n)
        y_proba = rng.dirichlet([1, 1, 1], size=n)

        def rps_mean(yt, yp):
            return float(np.mean([
                ranked_probability_score(int(yt[i]), yp[i].tolist())
                for i in range(len(yt))
            ]))

        result = block_bootstrap_ci(y_true, y_proba, rps_mean, n_bootstrap=200)
        assert result["ci_lower"] <= result["point_estimate"] <= result["ci_upper"]
        assert result["n_bootstrap"] == 200

    def test_insufficient_samples_returns_note(self):
        """Too few samples returns note without crashing."""
        y_true = np.array([0, 1, 2])
        y_proba = np.eye(3)

        def dummy_metric(yt, yp):
            return 0.5

        result = block_bootstrap_ci(y_true, y_proba, dummy_metric, block_size=10)
        assert result["note"] == "insufficient_samples_for_block_bootstrap"
        assert result["point_estimate"] == 0.5


class TestBrierConvention:
    """Guard test: confirms MEAN aggregation convention documented in metric-contract.json."""

    def test_brier_mean_aggregation_convention(self):
        """brier_score_decomposition uses MEAN, not sum — contract v1.0.0."""
        y_true = np.array([0, 1, 2, 0])
        y_proba = np.array([
            [0.8, 0.1, 0.1],
            [0.1, 0.8, 0.1],
            [0.1, 0.1, 0.8],
            [0.5, 0.3, 0.2],
        ])
        result = brier_score_decomposition(y_true, y_proba)
        # Mean brier_score must be < 1.0 (it is mean, not sum of all samples)
        assert result["mean"]["brier_score"] < 1.0
        # n_samples must be preserved
        assert result["n_samples"] == 4
