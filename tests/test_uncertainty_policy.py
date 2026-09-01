"""
Unit tests for uncertainty decomposition, residualization, and uncertainty policy v1.2.0.
"""

import numpy as np
import pytest
from sabiscore.uncertainty.decomposition import (
    compute_shannon_uncertainty_components,
)
from sabiscore.uncertainty.residualizer import EpistemicResidualizer
from sabiscore.uncertainty.uncertainty_policy import UncertaintyPolicy


def test_shannon_uncertainty_bounds() -> None:
    # 5 trees, 10 samples, 3 classes
    np.random.seed(42)
    tree_probs = np.random.dirichlet((1, 1, 1), size=(5, 10))

    u_alea, u_epi, mean_probs = compute_shannon_uncertainty_components(tree_probs)

    assert u_alea.shape == (10,)
    assert u_epi.shape == (10,)
    assert mean_probs.shape == (10, 3)

    # Shannon entropy bounds for 3 classes: [0, log2(3)] ~ [0, 1.585]
    assert np.all(u_alea >= 0.0)
    assert np.all(u_alea <= 1.586)
    assert np.all(u_epi >= 0.0)


def test_epistemic_residualizer_orthogonality() -> None:
    np.random.seed(42)
    # Synthetic correlated uncertainties
    u_alea = np.linspace(0.1, 1.2, 100)
    # Strong synthetic inverse correlation
    u_epi_raw = 1.5 - 0.8 * u_alea + np.random.normal(0, 0.05, 100)

    residualizer = EpistemicResidualizer()
    u_epi_tilde = residualizer.fit_transform(u_alea, u_epi_raw)

    assert residualizer.is_fitted
    assert u_epi_tilde.shape == (100,)
    # Residualized metric should have near-zero trend relative to aleatoric baseline
    assert np.abs(np.corrcoef(u_alea, u_epi_tilde)[0, 1]) < 0.15


def test_uncertainty_policy_integration() -> None:
    np.random.seed(42)
    tree_probs = np.random.dirichlet((2, 2, 2), size=(10, 50))

    policy = UncertaintyPolicy()
    res = policy.extract_uncertainty(tree_probs)

    assert res.u_alea.shape == (50,)
    assert res.u_epi_raw.shape == (50,)
    assert res.u_epi_residualized.shape == (50,)

    # Fit residualizer via policy and re-extract
    policy.fit_residualizer(res.u_alea, res.u_epi_raw)
    res_fitted = policy.extract_uncertainty(tree_probs)

    assert policy.residualizer.is_fitted
    assert res_fitted.u_epi_residualized.shape == (50,)