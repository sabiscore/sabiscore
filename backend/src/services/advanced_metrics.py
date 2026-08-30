"""Pure deterministic advanced football metrics engine.

CONTRACT:
- Pure functions only: zero side-effects, zero network/database I/O, zero global state.
- Zero-fabrication: Missing, non-positive, or unavailable data returns None or a typed
  unavailable status enum. Missing data is NEVER converted to 0.0 or synthetic estimates.
- Strict sign conventions and input validations.
"""

from __future__ import annotations

from enum import Enum
from typing import NamedTuple, Optional


class MetricStatus(str, Enum):
    """Lifecycle and availability status for advanced analytical metrics."""

    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    ADVISORY_REQUIRES_CORPUS = "ADVISORY_REQUIRES_CORPUS"


class MetricResult(NamedTuple):
    """Typed result envelope for advanced metrics requiring corpus verification."""

    value: Optional[float]
    status: MetricStatus
    reason: Optional[str] = None


def calculate_ppda(
    opponent_passes: float | int,
    defensive_actions: float | int,
) -> Optional[float]:
    """Calculate Passes Allowed Per Defensive Action (PPDA).

    Formula:
        PPDA = opponent_passes / defensive_actions

    Interpretation:
        Lower PPDA indicates higher pressing intensity (fewer passes allowed
        before a defensive action occurs).

    Args:
        opponent_passes: Total passes made by opponent in defensive 3/5 of pitch.
        defensive_actions: Sum of tackles, interceptions, challenges, and fouls in defensive 3/5.

    Returns:
        float ratio if valid, None if defensive_actions == 0 (fail-closed, avoiding division by zero).

    Raises:
        ValueError: If opponent_passes < 0 or defensive_actions < 0.
    """
    if opponent_passes < 0 or defensive_actions < 0:
        raise ValueError("PPDA inputs must be non-negative numbers")

    if defensive_actions == 0:
        return None

    return round(float(opponent_passes) / float(defensive_actions), 4)


def evaluate_shot_stopping(
    psxg_total: float | int,
    actual_goals_conceded: float | int,
) -> Optional[float]:
    """Calculate Post-Shot Expected Goals (PSxG) Shot-Stopping Delta.

    Formula:
        Delta_PSxG = psxg_total - actual_goals_conceded

    Sign Convention:
        - Positive (> 0): Goalkeeper saved MORE goals than expected based on post-shot trajectory.
        - Negative (< 0): Goalkeeper conceded MORE goals than expected based on post-shot trajectory.
        - Zero (== 0): Goalkeeper performed exactly on par with post-shot expectation.

    Args:
        psxg_total: Cumulative post-shot expected goals faced on target.
        actual_goals_conceded: Total goals conceded excluding own goals.

    Returns:
        float delta value if valid.

    Raises:
        ValueError: If psxg_total < 0 or actual_goals_conceded < 0.
    """
    if psxg_total < 0 or actual_goals_conceded < 0:
        raise ValueError("PSxG and actual goals conceded must be non-negative numbers")

    return round(float(psxg_total) - float(actual_goals_conceded), 4)


def evaluate_xt(
    event_corpus_available: bool = False,
    event_count: int = 0,
) -> MetricResult:
    """Evaluate Expected Threat (xT) calculation availability.

    xT computation strictly requires a dense, spatiotemporally aligned 2D event coordinate
    stream (pitch-grid action transitions) for both training and serving parity.

    When dense event telemetry is not present for live serving, this returns
    MetricStatus.ADVISORY_REQUIRES_CORPUS without synthesizing or fabricating grid values.

    Args:
        event_corpus_available: Whether verified 2D event coordinate data is available.
        event_count: Count of granular pitch events recorded for the match.

    Returns:
        MetricResult with typed MetricStatus and explanatory reason.
    """
    if not event_corpus_available or event_count <= 0:
        return MetricResult(
            value=None,
            status=MetricStatus.ADVISORY_REQUIRES_CORPUS,
            reason="Dense 2D pitch event corpus not available for live serving",
        )

    return MetricResult(
        value=None,
        status=MetricStatus.UNAVAILABLE,
        reason="xT event grid model serving pipeline uncertified",
    )


__all__ = [
    "MetricResult",
    "MetricStatus",
    "calculate_ppda",
    "evaluate_shot_stopping",
    "evaluate_xt",
]
