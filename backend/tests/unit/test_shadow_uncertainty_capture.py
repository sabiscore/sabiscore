"""Shadow production records the ensemble-dispersion measurement (ADR 0009).

Accepting research-only is only a *stage* rather than a dead end if the
evidence that could end it keeps accumulating. Every `error_association`
measurement to date comes from the 2024-25 backtest corpus; docs/DEBT.md item
50's remaining hypothesis — that a better-generalizing generation simply
passes the gate — cannot be tested against live settled outcomes unless the
number is stored per fixture as it is predicted.

These tests pin BOTH halves of that: the measurement is captured, and
capturing it did not quietly reopen the staking gate.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from src.api.endpoints.full_analysis import (
    _shadow_log_payload,
    _uncertainty_from_features,
)
from src.models.ensemble_uncertainty import UNAVAILABLE, UNCERTAINTY_CONTRACT_VERSION
from src.schemas.full_analysis import PredictionSource, PredictionStatus


def _payload(research_uncertainty: dict) -> dict:
    return _shadow_log_payload(
        evaluated_at=datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc),
        prediction_status=PredictionStatus.AVAILABLE,
        prediction_source=PredictionSource.UNCERTIFIED_MODEL,
        fixture_verified=True,
        critical_gaps=["MODEL_UNCERTAINTY_UNAVAILABLE", "MODEL_GENERATION_UNCERTIFIED"],
        advisory_gaps=["STALE_ENRICHMENT_EVIDENCE"],
        conflicts=[],
        research_uncertainty=research_uncertainty,
    )


def test_the_gate_stays_closed_no_matter_what_the_features_say():
    """The load-bearing guard. `_uncertainty_from_features` feeds the
    MODEL_UNCERTAINTY_UNAVAILABLE critical gap, and it must keep returning None
    while `error_association` fails — regardless of the fact that a real
    measurement is now computed and logged a few lines away in the same request.

    If this ever returns a breakdown, the gap stops firing and `stake_permitted`
    can become true, so this failing means staking was re-enabled."""
    for features in ({}, {"home_form_last5_home": 0.5}, {f"f{i}": 0.1 for i in range(68)}):
        assert asyncio.run(_uncertainty_from_features("EPL", features)) is None


def test_payload_carries_the_research_measurement():
    measurement = {
        "epistemic": 0.0928,
        "aleatoric": 0.9312,
        "total": 1.0240,
        "credible_interval": [0.21, 0.78],
        "method": "ensemble_dispersion",
        "model_count": 300,
        "version": UNCERTAINTY_CONTRACT_VERSION,
        "available": True,
    }
    payload = _payload(measurement)

    assert payload["research_uncertainty"] == measurement
    # Stage 15's required shadow uncertainty fields must all be present.
    for field in ("epistemic", "aleatoric", "total", "method", "model_count", "available"):
        assert field in payload["research_uncertainty"]


def test_an_unavailable_measurement_is_recorded_honestly_not_dropped():
    """A fixture whose measurement could not be taken must still say so. A
    missing key and `available: false` are different facts, and only the
    second one is a measurement."""
    payload = _payload(UNAVAILABLE.as_dict())
    assert payload["research_uncertainty"]["available"] is False
    assert payload["research_uncertainty"]["model_count"] == 0


def test_research_block_does_not_displace_the_evidence_record():
    """Settlement and CLV read this payload. The research block is additive —
    if it ever shadowed the evidence keys, the shadow record would lose the
    gap accounting those consumers depend on."""
    payload = _payload(UNAVAILABLE.as_dict())
    assert payload["prediction_status"] == PredictionStatus.AVAILABLE.value
    assert payload["fixture_verified"] is True
    assert payload["evidence"]["critical_gaps"] == [
        "MODEL_GENERATION_UNCERTIFIED",
        "MODEL_UNCERTAINTY_UNAVAILABLE",
    ]
    assert payload["evidence"]["advisory_gaps"] == ["STALE_ENRICHMENT_EVIDENCE"]
    assert payload["capture_trigger"] == "interactive_full_analysis"


def test_critical_gap_still_names_uncertainty_as_unavailable():
    """Belt-and-braces on the honesty of the record: the same payload that
    carries a real epistemic number must still declare the gate closed, or the
    stored evidence would contradict the served verdict."""
    payload = _payload({"epistemic": 0.09, "available": True, "method": "ensemble_dispersion"})
    assert "MODEL_UNCERTAINTY_UNAVAILABLE" in payload["evidence"]["critical_gaps"]
