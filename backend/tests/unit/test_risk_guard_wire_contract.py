"""The circuit breaker's disclosure must survive response-model validation.

⚠️ THE CLASS OF BUG THIS EXISTS FOR (docs/DEBT.md item 115)

`upcoming_match_service.py` sets `match["risk_guard"] = risk_decision.as_dict()`
whenever the ADR-0011 breaker suppresses a stake. `UpcomingMatchSchema` did not
declare that field, and Pydantic v2's default is `extra="ignore"` — so the
entire block was dropped at response validation. The breaker's *reason* (which
league threshold, what epistemic value, which policy version) never reached any
consumer, and a suppressed stake arrived at the UI indistinguishable from a
missing-lineup gap: one opaque `staking_suppressed_by_risk_guard` token in
`data_gaps` and nothing else.

Measured before the fix, on the payload the service actually builds:

    risk_guard survives schema?        -> False
    staking_authorization survives?    -> True

The sibling field carries a comment explaining it is "always present so a
consumer can distinguish 'no override in force' from 'the field went missing'".
That exact reasoning applies to this field and had not been applied to it.

⚠️ A field the service sets is not a field the client receives. The response
model is a filter, and a silent one.
"""

from __future__ import annotations

import pytest

from src.api.endpoints.upcoming_matches import UpcomingMatchSchema

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def _match_payload(**overrides: object) -> dict[str, object]:
    """A fixture row shaped exactly as `upcoming_match_service.py` emits it."""
    payload: dict[str, object] = {
        "match_id": "fd-564634",
        "home_team": "Levante",
        "away_team": "Real Betis",
        "league": "LA_LIGA",
        "match_date": "2026-09-21T14:00:00Z",
        "status": "scheduled",
        "data_gaps": ["staking_suppressed_by_risk_guard"],
        "staking_authorization": {
            "permitted": True,
            "basis": "OPERATOR_OVERRIDE",
            "certification_state": "OPERATOR_OVERRIDE_UNCERTIFIED",
            "is_override": True,
            "authorizing_identity": "Principal Architect - System-01",
            "rationale": "Staging/production integration for UX and load testing.",
            "authorized_at": "2026-09-19T22:12:18Z",
            "acknowledged_failures": ["0/6 market baseline beat"],
        },
        "risk_guard": {
            "tripped": True,
            "reason": "epistemic_in_measured_danger_zone",
            "league": "LA_LIGA",
            "epistemic": 0.0701,
            "threshold": 0.0776,
            "version": "v1",
        },
    }
    payload.update(overrides)
    return payload


def test_upcoming_match_schema_preserves_risk_guard() -> None:
    """The whole disclosure block, not just the opaque data_gaps token."""
    dumped = UpcomingMatchSchema(**_match_payload()).model_dump()

    assert "risk_guard" in dumped, (
        "risk_guard was dropped by the response model — the breaker's reason "
        "cannot reach any consumer, so a suppressed stake is indistinguishable "
        "from an ordinary data gap (docs/DEBT.md item 115)"
    )
    guard = dumped["risk_guard"]
    assert guard is not None
    # Every field the UI needs to explain the suppression, not merely announce it.
    assert guard["tripped"] is True
    assert guard["reason"] == "epistemic_in_measured_danger_zone"
    assert guard["league"] == "LA_LIGA"
    assert guard["epistemic"] == pytest.approx(0.0701)
    assert guard["threshold"] == pytest.approx(0.0776)


def test_absent_risk_guard_is_none_not_an_error() -> None:
    """The breaker only trips sometimes; not tripping must stay a clean 200.

    Absence is meaningful and safe here (unlike `staking_authorization`),
    because the breaker can only ever subtract permission, never add it.
    """
    payload = _match_payload()
    payload.pop("risk_guard")
    dumped = UpcomingMatchSchema(**payload).model_dump()
    assert dumped["risk_guard"] is None


def test_unmeasurable_epistemic_survives_as_null_not_zero() -> None:
    """`_epistemic_for_match` returns None when it cannot measure, and the
    breaker treats None as a trip. A substituted 0.0 would read as a real
    measurement sitting on the dangerous side of every threshold, so the
    schema must carry the null through rather than coerce it.
    """
    dumped = UpcomingMatchSchema(
        **_match_payload(
            risk_guard={
                "tripped": True,
                "reason": "epistemic_unavailable",
                "league": "EREDIVISIE",
                "epistemic": None,
                "threshold": 0.0776,
                "version": "v1",
            }
        )
    ).model_dump()

    assert dumped["risk_guard"]["epistemic"] is None, (
        "a null measurement must not be coerced to 0.0 — 0.0 is on the "
        "dangerous side of every measured threshold"
    )
