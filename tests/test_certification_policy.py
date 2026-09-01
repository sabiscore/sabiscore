"""
Unit tests for certification policy v1.2.0 error_association gate.
"""

import numpy as np
import pytest
from sabiscore.policies.certification_policy import (
    compute_rps,
    verify_error_association_gate,
)


def test_compute_rps_perfect_predictions() -> None:
    y_true = np.array([0, 1, 2])
    y_prob = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ]
    )
    rps = compute_rps(y_true, y_prob)
    np.testing.assert_allclose(rps, [0.0, 0.0, 0.0], atol=1e-6)


def test_error_association_gate_pass() -> None:
    np.random.seed(42)
    n = 100
    u_alea = np.random.uniform(0.2, 1.0, n)
    # Create residualized epistemic metric that positively correlates with error
    rps_base = np.random.uniform(0.05, 0.4, n)
    u_epi_residualized = 0.5 * rps_base + np.random.normal(0, 0.01, n)
    y_true = np.random.choice([0, 1, 2], size=n)
    y_prob = np.full((n, 3), 1 / 3)

    passed, diag = verify_error_association_gate(
        u_alea, u_epi_residualized, y_true, y_prob, n_strata=3
    )

    assert passed is True
    assert diag["passed"] is True
    assert len(diag["strata_correlations"]) == 3
    assert all(c > 0.0 for c in diag["strata_correlations"])


def test_error_association_gate_fail_negative_correlation() -> None:
    np.random.seed(42)
    n = 100
    u_alea = np.random.uniform(0.2, 1.0, n)
    # Negative correlation with error
    u_epi_residualized = -0.5 * u_alea + np.random.normal(0, 0.01, n)
    y_true = np.random.choice([0, 1, 2], size=n)
    y_prob = np.full((n, 3), 1 / 3)

    passed, diag = verify_error_association_gate(
        u_alea, u_epi_residualized, y_true, y_prob, n_strata=3
    )

    assert passed is False
    assert diag["passed"] is False