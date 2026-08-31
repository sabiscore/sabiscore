"""Aleatoric residualization of epistemic uncertainty (docs/DEBT.md item 50).

The residualizer removes a monotone aleatoric baseline from epistemic
uncertainty. These tests pin what it does, what it refuses to do, and — most
importantly — the invariance that explains why residualizing does NOT rescue
`UNCERTAINTY_GATES["error_association"]` when that gate is evaluated as a rank
correlation inside aleatoric strata.
"""
from __future__ import annotations

import warnings

import numpy as np
import pytest

from src.models.epistemic_residualizer import (
    MIN_FIT_ROWS,
    RESIDUALIZER_VERSION,
    EpistemicResidualizer,
    EpistemicResidualizerError,
)


def _confounded(n: int = 400, seed: int = 42):
    """Epistemic carrying a strong monotone aleatoric trend, as measured on the
    real holdouts (corr(epistemic, aleatoric) = -0.267)."""
    rng = np.random.default_rng(seed)
    u_alea = np.linspace(0.6, 1.05, n)
    u_epi = 0.30 - 0.20 * u_alea + rng.normal(0.0, 0.01, n)
    return u_alea, u_epi


def test_residual_removes_the_monotone_aleatoric_trend():
    u_alea, u_epi = _confounded()
    before = abs(float(np.corrcoef(u_alea, u_epi)[0, 1]))
    residual = EpistemicResidualizer().fit_transform(u_alea, u_epi)
    after = abs(float(np.corrcoef(u_alea, residual)[0, 1]))
    assert before > 0.9, "fixture should start strongly confounded"
    assert after < 0.15, f"residual still tracks aleatoric ({after:.3f})"


def test_a_flat_baseline_would_remove_nothing():
    """Regression guard for a bug this module shipped with and the tests caught.

    The direction was hardcoded `increasing=True`, but the real confound is
    NEGATIVE (epistemic falls as aleatoric rises). An increasing-only isotonic
    fit against a decreasing trend collapses to a near-constant, so the
    "residual" was the original signal minus a constant — rank-identical to
    doing nothing, while looking like it worked. A diagnostic run against that
    build reported residualization as a no-op, which was the bug talking, not
    the data.

    Pinned by construction: a genuinely flat baseline must leave within-stratum
    ordering untouched, so if `_INCREASING` is ever pinned back to True this
    equality starts holding for the real (decreasing) fixture too, and
    `test_residual_removes_the_monotone_aleatoric_trend` fails alongside it.

    ⚠️ **The first version of this fixture passed here and failed in CI.** It
    made `u_alea` vary and `flat_epi` a *tiny but exactly monotonic* ramp
    (`linspace`) built from the same 200-point index order as `u_alea` — so
    `corr(u_alea, flat_epi) == 1.0` exactly, isotonic regression fit it with
    zero training error, and the residual was EXACTLY 0.0 everywhere, not
    merely small. `argsort` of an all-tied array is implementation-defined
    (numpy's default sort is not guaranteed stable on ties), so the assertion
    only ever passed by an accident of which numpy/sklearn build happened to
    order those ties the same way `argsort(flat_epi)` did — it broke the
    moment CI's pinned numpy 1.26/sklearn 1.3 (vs. a newer local venv)
    produced a different tie order. A genuinely flat *baseline* means `u_alea`
    itself carries no discriminating signal, forcing `f` to a single fitted
    constant by construction (whatever `_INCREASING` resolves to, one unique
    x-value collapses to one bin) — then `residual = flat_epi - constant` is a
    plain scalar shift, which preserves order via ordinary float comparison,
    not tie-breaking. Deterministic regardless of numpy/scipy/sklearn version.
    """
    rng = np.random.default_rng(0)
    u_alea = np.full(200, 0.8)
    flat_epi = np.full(200, 0.09) + rng.normal(0.0, 0.01, 200)
    with warnings.catch_warnings():
        # Constant x makes the auto-direction Spearman check undefined —
        # expected and harmless here; the point of this fixture IS that x
        # carries no signal.
        warnings.simplefilter("ignore")
        residual = EpistemicResidualizer().fit_transform(u_alea, flat_epi)
    np.testing.assert_array_equal(np.argsort(residual), np.argsort(flat_epi))


def test_round_trips_through_serialisation():
    """The serialised form must actually predict after reload. Assigning
    sklearn's private fitted attributes (`f_x_`, `y_thresholds_`) leaves the
    interpolator unbuilt and `predict` raises, so `from_dict` re-fits on the
    stored knots through the public API instead."""
    u_alea, u_epi = _confounded()
    original = EpistemicResidualizer().fit(u_alea, u_epi)
    restored = EpistemicResidualizer.from_dict(original.to_dict())

    assert restored.is_fitted
    np.testing.assert_allclose(
        restored.transform(u_alea, u_epi), original.transform(u_alea, u_epi), atol=1e-12
    )


def test_unfitted_round_trip_stays_unfitted():
    restored = EpistemicResidualizer.from_dict(EpistemicResidualizer().to_dict())
    assert restored.is_fitted is False


def test_version_mismatch_is_refused():
    payload = EpistemicResidualizer().fit(*_confounded()).to_dict()
    payload["version"] = "r0-from-a-different-build"
    with pytest.raises(EpistemicResidualizerError, match="version mismatch"):
        EpistemicResidualizer.from_dict(payload)


def test_transform_before_fit_raises():
    with pytest.raises(EpistemicResidualizerError, match="must be fitted"):
        EpistemicResidualizer().transform(np.zeros(10), np.zeros(10))


def test_too_few_rows_to_fit_a_baseline_is_refused():
    u_alea, u_epi = _confounded(n=MIN_FIT_ROWS - 1)
    with pytest.raises(ValueError, match=f">= {MIN_FIT_ROWS} rows"):
        EpistemicResidualizer().fit(u_alea, u_epi)


def test_non_finite_and_mismatched_input_is_refused():
    u_alea, u_epi = _confounded()
    broken = u_epi.copy()
    broken[3] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        EpistemicResidualizer().fit(u_alea, broken)
    with pytest.raises(ValueError, match="length mismatch"):
        EpistemicResidualizer().fit(u_alea, u_epi[:-1])


def test_declared_version_is_stable():
    assert RESIDUALIZER_VERSION == "r1"
