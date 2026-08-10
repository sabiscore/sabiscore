"""Authority-boundary tests for caller-supplied prediction probabilities."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.schemas.betting_intelligence import VerdictEnum
from src.services.analytics import CertifiedAnalyticsService


def _external_payload() -> dict:
    now = datetime.now(timezone.utc)
    return {
        "match_id": "external-arsenal-brighton",
        "home_team": "Arsenal",
        "away_team": "Brighton",
        "competition": "EPL",
        "kickoff_utc": now + timedelta(hours=24),
        "model": {
            "home_probability": 0.62,
            "draw_probability": 0.23,
            "away_probability": 0.15,
            "model_version": "caller-certified-v999",
            "calibration_method": "isotonic",
            "calibration_validated": True,
            "epistemic_uncertainty": 0.01,
            "aleatoric_uncertainty": 0.02,
            "confidence_tier": "OK",
        },
        "market": {
            "bookmaker": "caller-book",
            "home_odds": 3.0,
            "draw_odds": 4.0,
            "away_odds": 8.0,
            "captured_at": now,
        },
        "freshness": {"model_features_seconds": 0, "market_seconds": 0},
        "source_status": {
            "model": "VERIFIED",
            "market": "VERIFIED",
            "team_metrics": "VERIFIED",
            "availability": "VERIFIED",
        },
        "verified_evidence_providers": ["a", "b", "c", "d"],
    }


@pytest.mark.asyncio
async def test_external_probabilities_cannot_be_backend_certified_or_executable() -> None:
    result = await CertifiedAnalyticsService().analyze_payload(_external_payload())

    assert result.verdict is VerdictEnum.PARTIAL
    assert result.execution_eligible is False
    assert result.probabilities is None
    assert result.stake == "pass"
    assert result.stake_fraction == 0.0
    assert "EXTERNAL_INPUT_UNVERIFIED" in result.critical_gaps
    assert set(result.source_summary.values()) == {"DATA_GAP"}


@pytest.mark.asyncio
async def test_external_missing_certification_metadata_is_an_explicit_gap() -> None:
    payload = _external_payload()
    payload["model"]["model_version"] = None

    result = await CertifiedAnalyticsService().analyze_payload(payload)

    assert result.verdict is VerdictEnum.PARTIAL
    assert result.probabilities is None
    assert result.stake_fraction == 0.0
    assert any("MODEL" in gap.upper() for gap in result.critical_gaps)
