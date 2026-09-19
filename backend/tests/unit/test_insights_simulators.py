"""`src/insights/simulators.py` — first executable coverage this module has had.

The module shipped with `np.math.factorial(...)`, a private alias NumPy REMOVED
in 2.0, so `_calculate_poisson_probs` raised `AttributeError` on every call
under the installed NumPy (2.5.0). Nothing in the repository imports this
module, so neither a caller nor a test ever surfaced it (docs/DEBT.md item 73).

Before the fix these tests fail at the first call with:
    AttributeError: module 'numpy' has no attribute 'math'

They assert correctness, not merely absence of a crash: the Poisson pmf is
checked against `scipy.stats`, so a plausible-looking-but-wrong replacement
would not pass either.
"""
from __future__ import annotations

import ast
import inspect
import math
import textwrap

import numpy as np
import pytest

from src.insights.simulators import MatchSimulator


def test_poisson_probabilities_match_the_analytic_pmf() -> None:
    scipy_stats = pytest.importorskip("scipy.stats")
    simulator = MatchSimulator(random_seed=42)
    max_goals, lam = 8, 1.6

    probs = simulator._calculate_poisson_probs(lam, max_goals)

    # The implementation renormalises over the truncated support, so compare
    # against an identically-truncated analytic pmf rather than the untruncated
    # one — otherwise the tail mass beyond max_goals shows up as a false failure.
    analytic = scipy_stats.poisson.pmf(np.arange(max_goals + 1), lam)
    analytic = analytic / analytic.sum()

    assert probs.shape == (max_goals + 1,)
    np.testing.assert_allclose(probs, analytic, rtol=1e-9, atol=1e-12)


def test_poisson_probabilities_form_a_valid_distribution() -> None:
    probs = MatchSimulator(random_seed=7)._calculate_poisson_probs(2.3, 10)
    assert np.all(probs >= 0.0)
    assert probs.sum() == pytest.approx(1.0)
    assert np.all(np.isfinite(probs))


def test_factorial_source_is_the_stdlib_not_the_removed_numpy_alias() -> None:
    """Pins the actual defect: `_calculate_poisson_probs` must call
    `math.factorial`, never `np.math.factorial`.

    CORRECTED: the original assertion (`not hasattr(np, "math")`) tested a
    fact about the installed NumPy library, not about this module's code.
    The module docstring above was written against NumPy 2.5.0 in the
    Python 3.14 research environment, where `np.math` genuinely no longer
    exists -- but `requirements.txt` pins `numpy==1.26.2` for
    `python_version < "3.14"`, which is what actually serves in production
    (`render.yaml` `PYTHON_VERSION: 3.11.9`), and 1.26.2 still exposes
    `np.math` (with a DeprecationWarning, not a removal). Under that pinned
    version the original assertion was false regardless of whether this
    module's fix was correct -- backwards for a regression guard.

    A plain source-text check doesn't work either: the fix itself left an
    explanatory comment containing the literal string "np.math", so
    `"np.math" not in source` flags its own fix's comment as the violation
    (watched failing on exactly that before this version was written).
    `monkeypatch.delattr(np, "math")` doesn't work either -- NumPy exposes
    `math` via the module's `__getattr__` deprecation shim, not a real
    attribute, so there is nothing for `delattr` to remove.

    An AST walk is precise where both of those aren't: comments are not
    parsed into nodes at all, so this only sees real code, and it doesn't
    depend on whatever the installed NumPy happens to still support.
    """
    source = textwrap.dedent(inspect.getsource(MatchSimulator._calculate_poisson_probs))
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "math"
            and isinstance(node.value, ast.Name)
            and node.value.id == "np"
        ):
            pytest.fail(
                "_calculate_poisson_probs references np.math again -- use "
                "the stdlib math module instead (docs/DEBT.md item 73)"
            )
    assert math.factorial(5) == 120


def test_full_simulation_produces_a_coherent_outcome_simplex() -> None:
    simulator = MatchSimulator(random_seed=42)
    result = simulator.run_match_simulation(home_xg=1.6, away_xg=1.1, n_sims=500, max_goals=8)

    # Keys are `*_prob`-suffixed here even though MatchSimulationResult.result
    # uses the bare 'home_win'/'draw'/'away_win' labels — read, not assumed.
    outcomes = result["outcome_probabilities"]
    total = sum(float(outcomes[k]) for k in ("home_win_prob", "draw_prob", "away_win_prob"))
    assert total == pytest.approx(1.0, abs=1e-6)
    assert result["simulations_run"] == 500
    assert 0.0 <= float(result["btts_probability"]) <= 1.0


def test_simulation_is_reproducible_for_a_fixed_seed() -> None:
    first = MatchSimulator(random_seed=11).run_match_simulation(1.4, 1.2, n_sims=300, max_goals=6)
    second = MatchSimulator(random_seed=11).run_match_simulation(1.4, 1.2, n_sims=300, max_goals=6)
    assert first["outcome_probabilities"] == second["outcome_probabilities"]
