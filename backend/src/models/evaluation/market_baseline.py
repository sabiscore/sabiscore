"""Canonical 1X2 market baseline: Shin (1992/1993) de-vigging.

Why this module exists
----------------------
Every de-vig in this repository before it divided each raw implied probability
by the booksum (``(1/o_i) / Sum(1/o_j)``). That *proportional* normalisation
assumes the bookmaker spreads its margin evenly across outcomes. It does not:
the margin is concentrated on longshots (the favourite-longshot bias), so
proportional normalisation systematically overstates the market's longshot
probabilities and understates its favourite probabilities. A model scored
against a proportionally de-vigged book is therefore scored against a baseline
that is itself mis-specified, in a direction that varies with how lopsided the
fixture is.

Shin's model instead treats the quoted prices as the equilibrium of a
bookmaker facing a proportion ``z`` of insider traders, and inverts that
relationship. It is the baseline the certification policy designates for G18.

The inversion
-------------
With raw (gross) implied probabilities ``q_i = 1 / o_i`` and booksum
``PI = Sum q_i``, Shin's estimate of the true probability is::

    p_i(z) = ( sqrt( z^2 + 4 (1 - z) q_i^2 / PI ) - z ) / ( 2 (1 - z) )

where ``z`` in ``[0, 1)`` is chosen so that ``Sum p_i(z) = 1``.

Bracketing is provable rather than assumed, which is why this solver needs no
heuristics and no external root finder:

* ``f(z) = Sum p_i(z) - 1`` is continuous on ``[0, 1)``.
* ``f(0) = sqrt(PI) - 1 > 0`` for any vigged book (``PI > 1``).
* ``p_i(z) -> q_i^2 / PI`` as ``z -> 1``, so
  ``f(1-) = Sum q_i^2 / PI - 1``. Since ``Sum q_i^2 < max(q_i) * Sum q_i =
  max(q_i) * PI``, we get ``f(1-) < max(q_i) - 1 < 0`` whenever every decimal
  odd exceeds 1.0 -- which validation already guarantees.

So a sign change always exists on ``[0, 1)`` for a validated vigged book, and
plain bisection converges. Bisection is deliberate: it is dependency-free and
bit-stable across library versions, which matters here because ``docs/DEBT.md``
item 113 is an open incident caused by exactly that kind of version drift.

Scope
-----
This is the *certification baseline*. Live serving paths
(``odds_service``, ``market_intel``, ``betting_intelligence``, ``core_engine``)
still use proportional normalisation and are deliberately untouched -- swapping
them would move published EV/edge numbers on production surfaces, which is a
separate authorisation. See ``docs/DEBT.md`` item 121.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Sequence

# Mirrors `providers/the_odds_api.py` (_MIN_OVERROUND / _MAX_OVERROUND) so a
# book this module accepts is one the provider gateway would also accept.
MIN_OVERROUND = 1.005
MAX_OVERROUND = 1.25

# A booksum within this distance of 1.0 carries no recoverable margin; Shin's
# z collapses to 0 and the inversion degenerates to the identity.
_ZERO_VIG_TOLERANCE = 1e-9

_BISECTION_MAX_ITERATIONS = 200
_BISECTION_TOLERANCE = 1e-12

DevigMethod = Literal["shin", "proportional"]

OUTCOMES: tuple[str, str, str] = ("home_win", "draw", "away_win")


class MarketBaselineError(ValueError):
    """Raised when a market observation cannot yield a usable baseline.

    Carries a stable ``reason`` code so callers can count rejections by cause
    instead of parsing a message.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class DevigResult:
    """A de-vigged 1X2 baseline plus every input needed to reproduce it.

    The directive requires the raw odds, implied probabilities, overround, the
    solved ``z`` and the de-vigged probabilities all to be retained; this record
    is the single object that carries them, so no call site has to remember to.
    """

    method: DevigMethod
    raw_odds: tuple[float, float, float]
    implied_probabilities: tuple[float, float, float]
    overround: float
    shin_z: float | None
    probabilities: tuple[float, float, float]
    solver_iterations: int | None = None
    solver_residual: float | None = None
    provenance: dict[str, Any] = field(default_factory=dict)

    def as_record(self) -> dict[str, Any]:
        """A JSON-safe row for the certification evidence bundle."""
        return {
            "method": self.method,
            "raw_odds": dict(zip(OUTCOMES, self.raw_odds)),
            "implied_probabilities": dict(zip(OUTCOMES, self.implied_probabilities)),
            "overround": self.overround,
            "shin_z": self.shin_z,
            "probabilities": dict(zip(OUTCOMES, self.probabilities)),
            "solver_iterations": self.solver_iterations,
            "solver_residual": self.solver_residual,
            "provenance": dict(self.provenance),
        }


def validate_odds(odds: Sequence[float]) -> tuple[float, float, float]:
    """Return the odds triple, or raise :class:`MarketBaselineError`.

    Rejects anything that is not three finite decimal odds strictly above 1.0.
    The ``> 1.0`` bound is not cosmetic: it is what guarantees ``q_i < 1``, and
    therefore the sign change the Shin solver relies on.
    """
    values = list(odds)
    if len(values) != 3:
        raise MarketBaselineError(
            "incomplete_market",
            f"1X2 baseline needs exactly 3 outcomes, got {len(values)}",
        )

    coerced: list[float] = []
    for name, value in zip(OUTCOMES, values):
        if value is None or isinstance(value, bool):
            raise MarketBaselineError("malformed_odds", f"{name} odds missing")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise MarketBaselineError(
                "malformed_odds", f"{name} odds not numeric: {value!r}"
            ) from exc
        if not math.isfinite(number):
            raise MarketBaselineError(
                "malformed_odds", f"{name} odds not finite: {number!r}"
            )
        if number <= 1.0:
            raise MarketBaselineError(
                "malformed_odds",
                f"{name} decimal odds must exceed 1.0, got {number!r}",
            )
        coerced.append(number)

    return coerced[0], coerced[1], coerced[2]


def implied_probabilities(odds: Sequence[float]) -> tuple[float, float, float]:
    """Raw (gross, un-normalised) implied probabilities ``1 / o_i``."""
    home, draw, away = validate_odds(odds)
    return 1.0 / home, 1.0 / draw, 1.0 / away


def overround(odds: Sequence[float]) -> float:
    """Booksum ``Sum 1 / o_i``. Above 1.0 by the bookmaker's margin."""
    return float(sum(implied_probabilities(odds)))


def _shin_probability(q: float, z: float, booksum: float) -> float:
    """One outcome's Shin probability at a given ``z``."""
    discriminant = z * z + 4.0 * (1.0 - z) * (q * q) / booksum
    # Non-negative for z in [0, 1) and q, booksum > 0; clamped so floating
    # point noise near the bracket ends can never produce a domain error.
    return (math.sqrt(max(discriminant, 0.0)) - z) / (2.0 * (1.0 - z))


def solve_shin_z(odds: Sequence[float]) -> tuple[float, int, float]:
    """Solve for Shin's insider proportion ``z``.

    Returns ``(z, iterations, residual)`` where ``residual`` is the final
    ``Sum p_i - 1``. Bisection on a provably bracketed root -- see the module
    docstring for why the bracket always exists on a validated vigged book.
    """
    booksum = overround(odds)
    qs = implied_probabilities(odds)

    if booksum <= 1.0 + _ZERO_VIG_TOLERANCE:
        # No recoverable margin: z = 0 and Shin degenerates to the identity.
        return 0.0, 0, float(booksum - 1.0)

    def residual(z: float) -> float:
        return sum(_shin_probability(q, z, booksum) for q in qs) - 1.0

    low, high = 0.0, 1.0 - 1e-12
    f_low = residual(low)
    if f_low <= 0.0:
        # f(0) = sqrt(PI) - 1, which is > 0 for PI > 1. Reaching here means the
        # booksum test above and this one disagree, so fail loudly rather than
        # returning a z that was never solved for.
        raise MarketBaselineError(
            "shin_bracket_invalid",
            f"expected f(0) > 0 for booksum {booksum!r}, got {f_low!r}",
        )

    iterations = 0
    mid = low
    f_mid = f_low
    for iterations in range(1, _BISECTION_MAX_ITERATIONS + 1):
        mid = 0.5 * (low + high)
        f_mid = residual(mid)
        if abs(f_mid) <= _BISECTION_TOLERANCE or (high - low) <= _BISECTION_TOLERANCE:
            break
        if f_mid > 0.0:
            low = mid
        else:
            high = mid

    return mid, iterations, f_mid


def shin_devig(
    odds: Sequence[float], *, provenance: dict[str, Any] | None = None
) -> DevigResult:
    """De-vig a 1X2 book with Shin's method."""
    triple = validate_odds(odds)
    qs = implied_probabilities(triple)
    booksum = float(sum(qs))

    if not (MIN_OVERROUND <= booksum <= MAX_OVERROUND):
        raise MarketBaselineError(
            "overround_outside_integrity_limits",
            f"booksum {booksum:.6f} outside [{MIN_OVERROUND}, {MAX_OVERROUND}]",
        )

    z, iterations, resid = solve_shin_z(triple)
    raw = tuple(_shin_probability(q, z, booksum) for q in qs)

    # Renormalise the residual. The solver drives Sum p_i to within 1e-12 of 1,
    # so this shifts nothing meaningful -- it just guarantees callers receive an
    # exact simplex rather than one that is off in the last few bits.
    total = float(sum(raw))
    if not math.isfinite(total) or total <= 0.0:
        raise MarketBaselineError(
            "shin_solution_invalid", f"non-positive probability mass {total!r}"
        )
    probabilities = (raw[0] / total, raw[1] / total, raw[2] / total)

    return DevigResult(
        method="shin",
        raw_odds=triple,
        implied_probabilities=qs,
        overround=booksum,
        shin_z=z,
        probabilities=probabilities,
        solver_iterations=iterations,
        solver_residual=resid,
        provenance=dict(provenance or {}),
    )


def proportional_devig(
    odds: Sequence[float], *, provenance: dict[str, Any] | None = None
) -> DevigResult:
    """Legacy proportional normalisation, retained for A/B comparison.

    Kept so a certification run can report both baselines side by side and show
    what changing the convention actually moved. It is not the designated G18
    baseline.
    """
    triple = validate_odds(odds)
    qs = implied_probabilities(triple)
    booksum = float(sum(qs))

    if not (MIN_OVERROUND <= booksum <= MAX_OVERROUND):
        raise MarketBaselineError(
            "overround_outside_integrity_limits",
            f"booksum {booksum:.6f} outside [{MIN_OVERROUND}, {MAX_OVERROUND}]",
        )

    return DevigResult(
        method="proportional",
        raw_odds=triple,
        implied_probabilities=qs,
        overround=booksum,
        shin_z=None,
        probabilities=(qs[0] / booksum, qs[1] / booksum, qs[2] / booksum),
        provenance=dict(provenance or {}),
    )


def devig(
    odds: Sequence[float],
    *,
    method: DevigMethod = "shin",
    provenance: dict[str, Any] | None = None,
) -> DevigResult:
    """De-vig a 1X2 book with the named method. Defaults to the G18 baseline."""
    if method == "shin":
        return shin_devig(odds, provenance=provenance)
    if method == "proportional":
        return proportional_devig(odds, provenance=provenance)
    raise MarketBaselineError("unknown_devig_method", f"unknown method {method!r}")


def assert_pre_evaluation(
    observed_at: datetime | None,
    evaluation_at: datetime | None,
    *,
    max_staleness_seconds: float | None = None,
) -> None:
    """Reject a market observation that leaks or is stale.

    An odds snapshot timestamped at or after ``evaluation_at`` carries
    information the forecast could not have had, so scoring against it
    manufactures an edge. That is the leakage this guard exists to stop; it
    fails closed when either timestamp is missing, because an unknown
    observation time cannot be shown to precede the forecast.
    """
    if evaluation_at is None:
        raise MarketBaselineError(
            "evaluation_at_missing",
            "evaluation_at is required to validate market observation timing",
        )
    if observed_at is None:
        raise MarketBaselineError(
            "observation_time_missing",
            "market observation carries no timestamp; cannot prove it predates evaluation_at",
        )
    if observed_at.tzinfo is None or evaluation_at.tzinfo is None:
        raise MarketBaselineError(
            "naive_timestamp",
            "market observation timing requires timezone-aware datetimes",
        )
    if observed_at >= evaluation_at:
        raise MarketBaselineError(
            "post_evaluation_market",
            f"market observed at {observed_at.isoformat()} does not predate "
            f"evaluation_at {evaluation_at.isoformat()}",
        )
    if max_staleness_seconds is not None:
        age = (evaluation_at - observed_at).total_seconds()
        if age > max_staleness_seconds:
            raise MarketBaselineError(
                "stale_market",
                f"market observation is {age:.0f}s old, exceeding "
                f"{max_staleness_seconds:.0f}s",
            )


__all__ = [
    "MAX_OVERROUND",
    "MIN_OVERROUND",
    "OUTCOMES",
    "DevigMethod",
    "DevigResult",
    "MarketBaselineError",
    "assert_pre_evaluation",
    "devig",
    "implied_probabilities",
    "overround",
    "proportional_devig",
    "shin_devig",
    "solve_shin_z",
    "validate_odds",
]
