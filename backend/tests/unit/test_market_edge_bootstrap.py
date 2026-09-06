"""The paired bootstrap must be able to detect a real effect, and only a real one.

A confidence interval that always spans zero would produce the same "no evidence"
answer whether or not an edge exists, and would look identical to a correct
negative result. These checks pin that the instrument has both directions of
sensitivity before any promotion argument is built on its output.

The pairing property is the one worth guarding. `block_bootstrap_ci` resamples
one probability matrix; running it separately on two heads draws different
blocks for each and destroys the pairing. The script stacks both heads into one
(n, 6) array so a single set of block indices applies to both. If that ever
regressed to two independent calls the interval would inflate to roughly the sum
of two variances, and a genuine small edge would silently become
"indistinguishable" — the exact failure this test exists to catch.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import numpy as np
import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "bootstrap_market_edge_ci.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("bootstrap_market_edge_ci", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod() -> Any:
    return _load_module()


@pytest.fixture(scope="module")
def fixture_data() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(7)
    n = 400
    y = rng.integers(0, 3, n)
    market = rng.dirichlet([4.0, 3.0, 3.0], size=n)
    truth = np.zeros((n, 3))
    truth[np.arange(n), y] = 1.0
    return y, market, truth


def _ci(mod: Any, y: np.ndarray, head: np.ndarray, market: np.ndarray) -> dict:
    return mod.block_bootstrap_ci(
        y,
        np.hstack([head, market]),
        mod._paired_difference,
        n_bootstrap=2000,
        block_size=10,
        rng_seed=1,
    )


def test_the_two_rps_implementations_agree(mod: Any) -> None:
    """Scoring with a different RPS than the one that produced the figures
    under test would make an implementation difference look like an effect."""
    mod._assert_scorers_agree()


def test_identical_heads_give_exactly_zero(mod: Any, fixture_data) -> None:
    y, market, _ = fixture_data
    result = _ci(mod, y, market.copy(), market)
    assert result["point_estimate"] == 0.0
    assert result["ci_lower"] == 0.0
    assert result["ci_upper"] == 0.0
    assert result["n_bootstrap"] == 2000, "replicates are being silently dropped"


def test_a_head_with_real_skill_produces_a_ci_below_zero(mod: Any, fixture_data) -> None:
    """RPS is lower-is-better, so a real edge is a negative difference."""
    y, market, truth = fixture_data
    result = _ci(mod, y, 0.7 * market + 0.3 * truth, market)
    assert result["ci_upper"] < 0, result


def test_a_degraded_head_produces_a_ci_above_zero(mod: Any, fixture_data) -> None:
    y, market, truth = fixture_data
    result = _ci(mod, y, 0.7 * market + 0.3 * (1.0 - truth) / 2.0, market)
    assert result["ci_lower"] > 0, result


def test_pairing_is_preserved_under_resampling(mod: Any, fixture_data) -> None:
    """The paired interval must be materially narrower than the unpaired one.

    Guards the stacking trick specifically: with correlated heads, pairing
    removes most of the shared variance. Measured at ~34x narrower on this
    fixture; asserted at a loose 5x so the test tracks the property, not the
    exact number.
    """
    y, market, truth = fixture_data
    head = 0.98 * market + 0.02 * truth

    paired = _ci(mod, y, head, market)
    paired_half = (paired["ci_upper"] - paired["ci_lower"]) / 2.0

    def mean_rps(y_true: np.ndarray, probs: np.ndarray) -> float:
        return mod._mean_rps(y_true, probs)

    a = mod.block_bootstrap_ci(y, head, mean_rps, n_bootstrap=2000, block_size=10, rng_seed=1)
    b = mod.block_bootstrap_ci(y, market, mean_rps, n_bootstrap=2000, block_size=10, rng_seed=2)
    unpaired_half = float(
        np.hypot((a["ci_upper"] - a["ci_lower"]) / 2.0, (b["ci_upper"] - b["ci_lower"]) / 2.0)
    )

    assert paired_half * 5 < unpaired_half, (
        f"paired half-width {paired_half:.5f} is not materially narrower than "
        f"unpaired {unpaired_half:.5f} — pairing has been lost"
    )
