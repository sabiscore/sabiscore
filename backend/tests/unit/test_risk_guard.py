"""Circuit breaker for the operator-override staking path (ADR-0011).

The load-bearing property is DIRECTION. High tree agreement means LOW
epistemic uncertainty, and that is the measured danger zone (43.0% hit-rate in
EPL vs 50.9% outside it). A breaker that tested `epistemic >= threshold` would
suppress the safest fixtures and stake the worst ones while looking entirely
plausible in review — so the direction is asserted explicitly here rather than
left implied by a single happy-path case.
"""
from __future__ import annotations

import logging

import pytest

from src.services.risk_guard import (
    CIRCUIT_BREAKER_EVENT,
    EPISTEMIC_DANGER_THRESHOLDS,
    UNMEASURED_LEAGUE_THRESHOLD,
    evaluate_staking_risk,
    threshold_for,
)

EPL_THRESHOLD = EPISTEMIC_DANGER_THRESHOLDS["EPL"]


# ── direction: the whole point ───────────────────────────────────────────────


def test_high_tree_agreement_trips_the_breaker() -> None:
    """LOW epistemic == trees agree == measured danger zone == suppress."""
    decision = evaluate_staking_risk(
        league="EPL", epistemic=EPL_THRESHOLD - 0.01, is_override=True
    )

    assert decision.tripped is True
    assert decision.reason == "epistemic_in_measured_danger_zone"


def test_low_tree_agreement_does_not_trip() -> None:
    """HIGH epistemic == trees disagree == outside the danger zone == allow."""
    decision = evaluate_staking_risk(
        league="EPL", epistemic=EPL_THRESHOLD + 0.01, is_override=True
    )

    assert decision.tripped is False
    assert decision.reason is None


def test_breaker_is_not_inverted() -> None:
    """Pins the sign directly: the dangerous input must trip and the safe one
    must not. If someone flips `<=` to `>=`, both halves fail at once."""
    dangerous = evaluate_staking_risk(league="EPL", epistemic=0.02, is_override=True)
    safe = evaluate_staking_risk(league="EPL", epistemic=0.18, is_override=True)

    assert dangerous.tripped is True, "near-total tree agreement must be suppressed"
    assert safe.tripped is False, "high ensemble disagreement must not be suppressed"


def test_threshold_boundary_is_inclusive() -> None:
    """Exactly at the measured p25 is inside the danger zone."""
    assert evaluate_staking_risk(
        league="EPL", epistemic=EPL_THRESHOLD, is_override=True
    ).tripped is True


# ── fail-closed behaviour ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad, reason",
    [
        (None, "epistemic_uncertainty_unavailable"),
        (float("nan"), "epistemic_uncertainty_non_finite"),
        (float("inf"), "epistemic_uncertainty_non_finite"),
        (float("-inf"), "epistemic_uncertainty_non_finite"),
        ("not-a-number", "epistemic_uncertainty_unparseable"),
    ],
)
def test_unmeasurable_epistemic_fails_closed(bad: object, reason: str) -> None:
    """"We could not measure the risk" is not "there is no risk"."""
    decision = evaluate_staking_risk(league="EPL", epistemic=bad, is_override=True)  # type: ignore[arg-type]

    assert decision.tripped is True
    assert decision.reason == reason


# ── scope ────────────────────────────────────────────────────────────────────


def test_breaker_is_inert_without_an_override() -> None:
    """A CERTIFIED generation passed error_association, so the danger zone this
    breaker exists for was not demonstrated for it."""
    decision = evaluate_staking_risk(
        league="EPL", epistemic=0.001, is_override=False
    )

    assert decision.tripped is False


def test_breaker_can_only_subtract_permission() -> None:
    """It never grants staking — `is_override=False` with a wildly safe value
    still reports untripped rather than 'permitted'."""
    decision = evaluate_staking_risk(league="EPL", epistemic=0.9, is_override=False)
    assert decision.tripped is False
    # The decision object carries no notion of granting; permission lives in
    # staking_authorization(). Guard against that changing.
    assert not hasattr(decision, "permitted")


# ── thresholds ───────────────────────────────────────────────────────────────


def test_every_measured_league_has_its_own_threshold() -> None:
    for league in ("EPL", "BUNDESLIGA", "LIGUE_1", "LA_LIGA", "SERIE_A"):
        assert threshold_for(league) == EPISTEMIC_DANGER_THRESHOLDS[league]


def test_unmeasured_league_gets_the_most_protective_threshold() -> None:
    """EREDIVISIE is a pooled model and UCL has none; neither has a measured
    p25. They must not fall through to 'no suppression'."""
    assert threshold_for("EREDIVISIE") == UNMEASURED_LEAGUE_THRESHOLD
    assert threshold_for("UCL") == UNMEASURED_LEAGUE_THRESHOLD
    assert UNMEASURED_LEAGUE_THRESHOLD == max(EPISTEMIC_DANGER_THRESHOLDS.values())


def test_unknown_league_is_protected_not_ignored() -> None:
    assert evaluate_staking_risk(
        league="NOT_A_LEAGUE", epistemic=0.01, is_override=True
    ).tripped is True


def test_league_lookup_is_case_insensitive() -> None:
    assert threshold_for("epl") == EPISTEMIC_DANGER_THRESHOLDS["EPL"]


# ── telemetry ────────────────────────────────────────────────────────────────


def test_trip_emits_the_structured_warning_event(caplog: pytest.LogCaptureFixture) -> None:
    """The dashboard queries on this event name; the emitting code and the
    query must not drift."""
    with caplog.at_level(logging.WARNING, logger="src.services.risk_guard"):
        evaluate_staking_risk(
            league="EPL", epistemic=0.01, is_override=True, match_id="fd-1"
        )

    records = [r for r in caplog.records if getattr(r, "event", None) == CIRCUIT_BREAKER_EVENT]
    assert len(records) == 1
    record = records[0]
    assert record.levelno == logging.WARNING
    assert record.league == "EPL"  # type: ignore[attr-defined]
    assert record.match_id == "fd-1"  # type: ignore[attr-defined]
    assert record.reason == "epistemic_in_measured_danger_zone"  # type: ignore[attr-defined]


def test_no_event_when_the_breaker_does_not_trip(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="src.services.risk_guard"):
        evaluate_staking_risk(league="EPL", epistemic=0.5, is_override=True)

    assert not [
        r for r in caplog.records if getattr(r, "event", None) == CIRCUIT_BREAKER_EVENT
    ]
