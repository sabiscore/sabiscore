"""Tests for scripts/_incremental_value_harness.py's pure logic.

Covers the de-vig math and the RPS/block-bootstrap wrapper only -- not the
live network fetch, CSV loading, or sklearn model fit, matching the
precedent set for the sibling Phase 3/Stage 1-2 scripts in this same
directory (test only the pure functions; the acquisition/analysis pipeline
is exercised by actually running it, not by a mocked test).
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from _incremental_value_harness import (  # noqa: E402
    devig,
    mean_rps,
    paired_rps_diff_bootstrap,
)


def test_devig_sums_to_one():
    probs = devig(2.0, 3.5, 4.0)
    assert abs(sum(probs) - 1.0) < 1e-9


def test_devig_preserves_relative_ordering():
    # Shorter odds (more likely per the bookmaker) must devig to a higher
    # probability -- a normalization bug that e.g. inverted odds would flip
    # this ordering silently.
    probs = devig(1.5, 4.0, 6.0)
    assert probs[0] > probs[1] > probs[2]


def test_devig_removes_the_overround():
    # 1/2.0 + 1/3.5 + 1/4.0 = 0.5 + 0.2857 + 0.25 = 1.0357 (3.57% overround).
    # Raw implied probabilities must not already sum to 1.
    raw_sum = 1 / 2.0 + 1 / 3.5 + 1 / 4.0
    assert raw_sum > 1.0
    probs = devig(2.0, 3.5, 4.0)
    assert abs(sum(probs) - 1.0) < 1e-9
    assert abs(probs[0] - (1 / 2.0) / raw_sum) < 1e-9


def test_mean_rps_zero_for_perfect_certain_predictions():
    y_true = np.array([0, 1, 2])
    y_proba = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    assert mean_rps(y_true, y_proba) == 0.0


def test_mean_rps_penalizes_confident_wrong_predictions_more_than_uncertain_ones():
    y_true = np.array([0, 0])
    confident_wrong = np.array([[0.0, 0.0, 1.0], [0.0, 0.0, 1.0]])
    uncertain = np.array([[0.34, 0.33, 0.33], [0.34, 0.33, 0.33]])
    assert mean_rps(y_true, confident_wrong) > mean_rps(y_true, uncertain)


def test_paired_bootstrap_ci_excludes_zero_for_a_consistent_improvement():
    # Candidate is uniformly better (lower RPS) than baseline on every
    # fixture -- the CI on the paired difference must exclude zero and be
    # negative throughout, not merely have a negative point estimate.
    rng = np.random.default_rng(0)
    n = 200
    y_true = rng.integers(0, 3, size=n)
    baseline = np.full((n, 3), 1 / 3)
    candidate = baseline.copy()
    # Nudge every prediction toward the true class -- strictly better RPS.
    candidate[np.arange(n), y_true] += 0.2
    candidate = candidate / candidate.sum(axis=1, keepdims=True)

    result = paired_rps_diff_bootstrap(y_true, candidate, baseline)
    assert result["point_estimate"] < 0
    assert result["ci_upper"] < 0


def test_paired_bootstrap_ci_includes_zero_for_no_real_difference():
    rng = np.random.default_rng(1)
    n = 200
    y_true = rng.integers(0, 3, size=n)
    baseline = np.full((n, 3), 1 / 3)
    candidate = baseline.copy()  # identical -> zero difference everywhere

    result = paired_rps_diff_bootstrap(y_true, candidate, baseline)
    assert result["point_estimate"] == 0.0
    assert result["ci_lower"] <= 0.0 <= result["ci_upper"]
