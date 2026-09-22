"""Deterministic staking circuit breaker for the operator-override path (ADR-0011).

WHY THIS EXISTS
---------------
`OPERATOR_OVERRIDE_UNCERTIFIED` permits staking on a generation that did not
pass certification. One of the failures it overrides is `error_association`:
the model's epistemic-uncertainty signal is *inverted* — it is least accurate
precisely where its 300 bootstrap trees agree most (`docs/DEBT.md` item 50).

That inversion is not a diffuse quality problem; it is concentrated in an
identifiable region of the input space, and that region is computable at
serving time. This module suppresses staking inside it. The override accepts
the model's risk in general; this breaker declines the one slice of it we have
measured to be worst.

⚠️ DIRECTION. "High tree agreement" and "high epistemic uncertainty" are
INVERSE quantities, and getting them backwards would invert the breaker —
suppressing the safest fixtures and waving through the dangerous ones. The
danger zone is LOW epistemic uncertainty (trees agree). `trips()` therefore
tests ``epistemic <= threshold``, never ``>=``. `test_risk_guard.py` pins this
direction explicitly because a sign error here is a financial-loss bug, not a
cosmetic one.

THRESHOLDS ARE MEASURED, NOT CHOSEN
-----------------------------------
Each value below is the 25th-percentile epistemic uncertainty measured on that
league's own artifact against its own chronological holdout season — the same
rows `tests/unit/test_uncertainty_contract.py` scores. Reproduce with
`scripts/measure_epistemic_danger_zone.py`.

Measured 2026-09-19 on generation ``v5_phase7-20260808`` (hit-rate inside the
low-epistemic quartile vs outside):

    league       n     p25      lowQ_hit   rest_hit    delta
    EPL          375   0.0788   0.4362     0.5089     -7.3pp
    BUNDESLIGA   296   0.0879   0.3378     0.4910    -15.3pp
    LIGUE_1      306   0.0859   0.4416     0.5066     -6.5pp
    LA_LIGA      380   0.0776   0.4632     0.4702     -0.7pp   (flat)
    SERIE_A      375   0.0848   0.5106     0.4555     +5.5pp   (REVERSED)

⚠️ **The effect is not universal.** It is strong in EPL, BUNDESLIGA and
LIGUE_1, absent in LA_LIGA, and runs the OTHER WAY in SERIE_A. The breaker
still suppresses in all five, because a false positive costs a missed
opportunity while a false negative costs a user's money, and this generation
has no demonstrated edge to forgo in the first place (0/6 leagues beat the
market). That asymmetry is the whole justification — it is recorded here so
nobody later reads these thresholds as evidence of a uniform effect.

Thresholds are per-league rather than one global constant because the measured
p25 spans 0.0776–0.0879; a single value would over-suppress the low end and
under-protect the high end, and we have the real numbers for each.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Mapping, Optional

logger = logging.getLogger(__name__)

#: Structured log event name. Named as a constant so the monitoring dashboard
#: query and the emitting code cannot drift apart.
CIRCUIT_BREAKER_EVENT = "override_circuit_breaker_tripped"

#: 25th-percentile epistemic uncertainty per league — see module docstring.
#: Keys are canonical league ids (`core.league_policy.canonical_league_id`).
EPISTEMIC_DANGER_THRESHOLDS: Mapping[str, float] = {
    "EPL": 0.0788,
    "BUNDESLIGA": 0.0879,
    "LIGUE_1": 0.0859,
    "LA_LIGA": 0.0776,
    "SERIE_A": 0.0848,
}

#: Leagues with no measured holdout of their own (EREDIVISIE is pooled;
#: UCL has no dedicated model) get the most protective measured value rather
#: than a guess or a pass-through. Over-suppressing an unmeasured league is the
#: acceptable error; under-protecting it is not.
UNMEASURED_LEAGUE_THRESHOLD: float = max(EPISTEMIC_DANGER_THRESHOLDS.values())

#: Version the threshold set so a recorded decision can name which numbers
#: were in force. Bump whenever any value above changes.
DANGER_ZONE_VERSION = "v1-2026-09-19-v5_phase7"


@dataclass(frozen=True)
class RiskDecision:
    """Outcome of one circuit-breaker evaluation."""

    tripped: bool
    reason: Optional[str]
    league: str
    epistemic: Optional[float]
    threshold: float

    def as_dict(self) -> dict[str, object]:
        return {
            "tripped": self.tripped,
            "reason": self.reason,
            "league": self.league,
            "epistemic": self.epistemic,
            "threshold": self.threshold,
            "version": DANGER_ZONE_VERSION,
        }


def threshold_for(league: str) -> float:
    """The measured danger-zone boundary for a league, or the safe default."""
    return EPISTEMIC_DANGER_THRESHOLDS.get(
        (league or "").strip().upper(), UNMEASURED_LEAGUE_THRESHOLD
    )


def evaluate_staking_risk(
    *,
    league: str,
    epistemic: Optional[float],
    is_override: bool,
    match_id: str = "",
) -> RiskDecision:
    """Decide whether to suppress staking for one fixture.

    Scoped to the override path by design: a genuinely CERTIFIED generation has
    passed `error_association`, so the danger zone this breaker exists for has
    been shown not to apply to it. Running the breaker there would suppress
    stakes on evidence that no longer holds.

    ⚠️ Fails CLOSED. Under an override, an epistemic value that is missing,
    non-finite, or unparseable trips the breaker rather than passing the
    fixture through. "We could not measure the risk" and "there is no risk" are
    different states, and only one of them is safe to stake on.
    """
    threshold = threshold_for(league)

    if not is_override:
        return RiskDecision(False, None, league, epistemic, threshold)

    if epistemic is None:
        return _trip(
            "epistemic_uncertainty_unavailable", league, None, threshold, match_id
        )

    try:
        value = float(epistemic)
    except (TypeError, ValueError):
        return _trip(
            "epistemic_uncertainty_unparseable", league, None, threshold, match_id
        )

    if not math.isfinite(value):  # NaN, +inf or -inf
        return _trip(
            "epistemic_uncertainty_non_finite", league, None, threshold, match_id
        )

    # THE DIRECTION: low epistemic == high tree agreement == the measured
    # danger zone. Inverting this comparison inverts the breaker.
    if value <= threshold:
        return _trip(
            "epistemic_in_measured_danger_zone", league, value, threshold, match_id
        )

    return RiskDecision(False, None, league, value, threshold)


def _trip(
    reason: str,
    league: str,
    epistemic: Optional[float],
    threshold: float,
    match_id: str,
) -> RiskDecision:
    logger.warning(
        "staking suppressed by override circuit breaker",
        extra={
            "event": CIRCUIT_BREAKER_EVENT,
            "reason": reason,
            "league": league,
            "epistemic": epistemic,
            "threshold": threshold,
            "danger_zone_version": DANGER_ZONE_VERSION,
            "match_id": match_id,
        },
    )
    return RiskDecision(True, reason, league, epistemic, threshold)


__all__ = [
    "CIRCUIT_BREAKER_EVENT",
    "DANGER_ZONE_VERSION",
    "EPISTEMIC_DANGER_THRESHOLDS",
    "UNMEASURED_LEAGUE_THRESHOLD",
    "RiskDecision",
    "evaluate_staking_risk",
    "threshold_for",
]
