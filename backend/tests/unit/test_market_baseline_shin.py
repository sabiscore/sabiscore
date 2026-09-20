"""Shin (1992/1993) de-vigging contract for the G18 market baseline.

Every case the certification directive enumerates for a market-baseline
implementation is pinned here: symmetric, heavy favourite, extreme favourite,
malformed odds, zero/negative odds, excessive overround, missing outcome,
stale market, duplicated market, and timestamp leakage.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from src.models.evaluation.market_baseline import (
    MAX_OVERROUND,
    DevigResult,
    MarketBaselineError,
    assert_pre_evaluation,
    devig,
    implied_probabilities,
    overround,
    proportional_devig,
    shin_devig,
    solve_shin_z,
    validate_odds,
)

SYMMETRIC = (2.7027027027027026,) * 3  # q = 0.37 each, booksum 1.11
REALISTIC = (1.50, 4.20, 7.00)
HEAVY_FAVOURITE = (1.10, 9.00, 26.00)
NEAR_EVEN = (2.40, 3.30, 3.10)


# --------------------------------------------------------------------------
# Core arithmetic
# --------------------------------------------------------------------------


def test_symmetric_market_solves_to_the_analytic_root() -> None:
    """A symmetric book has a closed-form z; the solver must find exactly it.

    With q_i = 0.37 and booksum 1.11, requiring p_i = 1/3 reduces to
    0.888889 z^2 - 0.937778 z + 0.048889 = 0, whose admissible root is 0.055.
    This is the one case where the answer is known independently of the code,
    so it is the anchor for the whole solver.
    """
    result = shin_devig(SYMMETRIC)

    assert result.overround == pytest.approx(1.11, abs=1e-9)
    assert result.shin_z == pytest.approx(0.055, abs=1e-7)
    for p in result.probabilities:
        assert p == pytest.approx(1.0 / 3.0, abs=1e-9)


@pytest.mark.parametrize("odds", [SYMMETRIC, REALISTIC, HEAVY_FAVOURITE, NEAR_EVEN])
def test_probabilities_form_an_exact_simplex(odds: tuple[float, float, float]) -> None:
    result = shin_devig(odds)
    assert sum(result.probabilities) == pytest.approx(1.0, abs=1e-12)
    assert all(0.0 < p < 1.0 for p in result.probabilities)


@pytest.mark.parametrize("odds", [SYMMETRIC, REALISTIC, HEAVY_FAVOURITE, NEAR_EVEN])
def test_solver_residual_is_driven_to_tolerance(odds: tuple[float, float, float]) -> None:
    z, iterations, residual = solve_shin_z(odds)
    assert 0.0 <= z < 1.0
    assert iterations > 0
    assert abs(residual) < 1e-9


@pytest.mark.parametrize("odds", [REALISTIC, HEAVY_FAVOURITE, NEAR_EVEN])
def test_shin_moves_mass_toward_the_favourite(odds: tuple[float, float, float]) -> None:
    """The reason to use Shin at all.

    A bookmaker concentrates its margin on longshots, so proportional
    normalisation overstates longshot probability and understates the
    favourite's. Shin must correct in that direction -- if it ever moved mass
    the other way the baseline would be worse than the one it replaced.
    """
    shin = shin_devig(odds).probabilities
    proportional = proportional_devig(odds).probabilities
    favourite = min(range(3), key=lambda i: odds[i])

    assert shin[favourite] > proportional[favourite]
    for i in range(3):
        if i != favourite:
            assert shin[i] < proportional[i]


def test_correction_grows_with_market_lopsidedness() -> None:
    """The favourite-longshot gap should widen as the book gets more skewed."""

    def favourite_shift(odds: tuple[float, float, float]) -> float:
        i = min(range(3), key=lambda k: odds[k])
        return shin_devig(odds).probabilities[i] - proportional_devig(odds).probabilities[i]

    assert (
        favourite_shift(NEAR_EVEN)
        < favourite_shift(REALISTIC)
        < favourite_shift(HEAVY_FAVOURITE)
    )


def test_extreme_favourite_stays_on_the_simplex() -> None:
    """The bracket proof relies on every q_i < 1; check it holds at the edge."""
    odds = (1.01, 41.0, 95.0)
    result = shin_devig(odds)

    assert sum(result.probabilities) == pytest.approx(1.0, abs=1e-12)
    assert result.probabilities[0] > 0.95
    assert all(p > 0.0 for p in result.probabilities)
    assert 0.0 <= result.shin_z < 1.0


def test_a_book_with_no_margin_yields_zero_z() -> None:
    """Zero vig means no insider component to recover; Shin is the identity."""
    odds = (3.0, 3.0, 3.0)  # booksum exactly 1.0
    z, _, _ = solve_shin_z(odds)
    assert z == 0.0


def test_implied_probabilities_and_overround_are_the_raw_book() -> None:
    qs = implied_probabilities(REALISTIC)
    assert qs == pytest.approx((1 / 1.50, 1 / 4.20, 1 / 7.00))
    assert overround(REALISTIC) == pytest.approx(sum(qs))
    assert overround(REALISTIC) > 1.0


# --------------------------------------------------------------------------
# Validation / rejection
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("odds", "reason"),
    [
        ((1.50, 4.20), "incomplete_market"),
        ((1.50, 4.20, 7.00, 9.00), "incomplete_market"),
        ((1.50, 4.20, 0.0), "malformed_odds"),
        ((1.50, 4.20, -3.0), "malformed_odds"),
        ((1.50, 4.20, 1.0), "malformed_odds"),
        ((1.50, 4.20, 0.95), "malformed_odds"),
        ((1.50, 4.20, None), "malformed_odds"),
        ((1.50, 4.20, "abc"), "malformed_odds"),
        ((1.50, 4.20, float("nan")), "malformed_odds"),
        ((1.50, 4.20, float("inf")), "malformed_odds"),
    ],
)
def test_malformed_markets_are_rejected_with_a_stable_reason(odds, reason: str) -> None:
    with pytest.raises(MarketBaselineError) as excinfo:
        validate_odds(odds)
    assert excinfo.value.reason == reason


def test_excessive_overround_is_rejected() -> None:
    """A 40%-margin book is not a usable probability estimate."""
    odds = (1.40, 2.80, 3.20)
    assert overround(odds) > MAX_OVERROUND
    with pytest.raises(MarketBaselineError) as excinfo:
        shin_devig(odds)
    assert excinfo.value.reason == "overround_outside_integrity_limits"


def test_underround_arbitrage_book_is_rejected() -> None:
    """Booksum below the integrity floor is an arb or a data error, not a book."""
    odds = (3.20, 3.40, 3.60)
    assert overround(odds) < 1.005
    with pytest.raises(MarketBaselineError) as excinfo:
        shin_devig(odds)
    assert excinfo.value.reason == "overround_outside_integrity_limits"


def test_both_methods_apply_the_same_integrity_limits() -> None:
    """A book one method rejects must not be silently accepted by the other."""
    odds = (1.40, 2.80, 3.20)
    for method in ("shin", "proportional"):
        with pytest.raises(MarketBaselineError):
            devig(odds, method=method)


def test_unknown_method_is_rejected() -> None:
    with pytest.raises(MarketBaselineError) as excinfo:
        devig(REALISTIC, method="power")  # type: ignore[arg-type]
    assert excinfo.value.reason == "unknown_devig_method"


# --------------------------------------------------------------------------
# Temporal integrity
# --------------------------------------------------------------------------


def test_market_observed_after_evaluation_is_leakage() -> None:
    evaluation_at = datetime(2026, 8, 21, 14, 0, tzinfo=UTC)
    with pytest.raises(MarketBaselineError) as excinfo:
        assert_pre_evaluation(evaluation_at + timedelta(seconds=1), evaluation_at)
    assert excinfo.value.reason == "post_evaluation_market"


def test_market_observed_exactly_at_evaluation_is_leakage() -> None:
    """The boundary is closed: simultaneity cannot prove the forecast came first."""
    evaluation_at = datetime(2026, 8, 21, 14, 0, tzinfo=UTC)
    with pytest.raises(MarketBaselineError) as excinfo:
        assert_pre_evaluation(evaluation_at, evaluation_at)
    assert excinfo.value.reason == "post_evaluation_market"


def test_stale_market_is_rejected_against_a_budget() -> None:
    evaluation_at = datetime(2026, 8, 21, 14, 0, tzinfo=UTC)
    observed_at = evaluation_at - timedelta(days=9)
    with pytest.raises(MarketBaselineError) as excinfo:
        assert_pre_evaluation(observed_at, evaluation_at, max_staleness_seconds=86_400)
    assert excinfo.value.reason == "stale_market"


def test_fresh_pre_evaluation_market_is_accepted() -> None:
    evaluation_at = datetime(2026, 8, 21, 14, 0, tzinfo=UTC)
    assert_pre_evaluation(
        evaluation_at - timedelta(hours=2), evaluation_at, max_staleness_seconds=86_400
    ) is None


@pytest.mark.parametrize(
    ("observed_at", "evaluation_at", "reason"),
    [
        (None, datetime(2026, 8, 21, tzinfo=UTC), "observation_time_missing"),
        (datetime(2026, 8, 21, tzinfo=UTC), None, "evaluation_at_missing"),
        (datetime(2026, 8, 20), datetime(2026, 8, 21, tzinfo=UTC), "naive_timestamp"),
    ],
)
def test_unprovable_timing_fails_closed(observed_at, evaluation_at, reason: str) -> None:
    """Missing or naive timing cannot demonstrate the market predates the
    forecast, so it must be refused rather than assumed benign."""
    with pytest.raises(MarketBaselineError) as excinfo:
        assert_pre_evaluation(observed_at, evaluation_at)
    assert excinfo.value.reason == reason


# --------------------------------------------------------------------------
# Determinism and provenance
# --------------------------------------------------------------------------


def test_duplicate_observations_devig_identically() -> None:
    """The same book twice must give the same numbers bit for bit.

    A duplicated market row must not perturb a pooled baseline, and a
    version-sensitive solver would be exactly the kind of drift `docs/DEBT.md`
    item 113 records.
    """
    first = shin_devig(REALISTIC)
    second = shin_devig(tuple(REALISTIC))
    assert first.probabilities == second.probabilities
    assert first.shin_z == second.shin_z


def test_result_record_retains_every_reproduction_input() -> None:
    observed = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
    result = shin_devig(
        REALISTIC,
        provenance={"bookmaker": "pinnacle", "observed_at": observed.isoformat()},
    )
    record = result.as_record()

    assert record["method"] == "shin"
    assert record["raw_odds"] == {"home_win": 1.50, "draw": 4.20, "away_win": 7.00}
    assert record["overround"] == pytest.approx(overround(REALISTIC))
    assert record["shin_z"] is not None
    assert set(record["implied_probabilities"]) == {"home_win", "draw", "away_win"}
    assert set(record["probabilities"]) == {"home_win", "draw", "away_win"}
    assert record["provenance"]["bookmaker"] == "pinnacle"
    assert record["provenance"]["observed_at"] == observed.isoformat()
    assert math.isclose(sum(record["probabilities"].values()), 1.0, abs_tol=1e-12)


def test_proportional_result_declares_no_z() -> None:
    """A proportional baseline must never present itself as a Shin solution."""
    result: DevigResult = devig(REALISTIC, method="proportional")
    assert result.method == "proportional"
    assert result.shin_z is None
