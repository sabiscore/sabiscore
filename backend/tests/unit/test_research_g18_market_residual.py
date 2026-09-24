"""The market-offset logit behind the G18 research track.

The only previous market-offset attempt silently scored a uniform forecast for
months (docs/DEBT.md, LogOddsResidualWrapper). These pin the three properties the
research result depends on: zero coefficients reproduce the market exactly, the
analytic gradient is right, and a planted bias is recovered.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.optimize import check_grad

from scripts import research_g18_market_residual as g18

RNG = np.random.default_rng(7)


def _market(n: int) -> np.ndarray:
    raw = RNG.dirichlet([4.0, 2.5, 3.0], size=n)
    return raw / raw.sum(axis=1, keepdims=True)


@pytest.mark.parametrize("kind", g18.CANDIDATES)
def test_zero_coefficients_reproduce_the_market_exactly(kind: str) -> None:
    p = _market(50)
    mh, md = g18.log_ratios(p)
    cov = RNG.normal(size=(50, 2))
    k = g18.design(kind, mh, cov)[0].shape[1]
    got = g18.predict(kind, np.zeros(k), np.zeros(k), mh, md, cov)
    np.testing.assert_allclose(got, p, atol=1e-12)


def test_analytic_gradient_matches_finite_differences() -> None:
    p = _market(200)
    mh, md = g18.log_ratios(p)
    cov = RNG.normal(size=(200, 2))
    y = np.array([RNG.choice(3, p=row) for row in p])
    xh, pen = g18.design("R3_residual", mh, cov)
    xd, _ = g18.design("R3_residual", md, cov)
    k, n, l2 = xh.shape[1], len(y), 1.0

    def f(theta):
        q = g18.softmax_offset(mh, md, xh, xd, theta[:k], theta[k:])
        nll = -np.mean(np.log(q[np.arange(n), y]))
        return nll + 0.5 * l2 * (np.sum(pen * theta[:k] ** 2) + np.sum(pen * theta[k:] ** 2)) / n

    def g(theta):
        q = g18.softmax_offset(mh, md, xh, xd, theta[:k], theta[k:])
        gh = xh.T @ (q[:, 0] - (y == 0)) / n + l2 * pen * theta[:k] / n
        gd = xd.T @ (q[:, 1] - (y == 1)) / n + l2 * pen * theta[k:] / n
        return np.concatenate([gh, gd])

    assert check_grad(f, g, RNG.normal(scale=0.3, size=2 * k)) < 1e-6


def test_a_planted_draw_bias_is_recovered() -> None:
    n = 20_000
    p = _market(n)
    mh, md = g18.log_ratios(p)
    truth = g18.softmax_offset(mh, md + 0.3, np.ones((n, 1)), np.ones((n, 1)), np.zeros(1), np.zeros(1))
    y = np.array([RNG.choice(3, p=row) for row in truth])
    bh, bd = g18.fit("R1_intercepts", mh, md, None, y, 1.0, {"gtol": 1e-9, "maxiter": 1000})
    assert bh[0] == pytest.approx(0.0, abs=0.06)
    assert bd[0] == pytest.approx(0.3, abs=0.06)
