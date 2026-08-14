"""Production contract tests for the unified match-analysis response."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder

from src.api.endpoints import full_analysis as endpoint
from src.data.elo_engine import EloContext
from src.models.causal_selector import CausalFeatureResult
from src.schemas.full_analysis import FullMatchAnalysisResponseSchema
from src.services.intelligence_synthesizer import (
    EnsemblePrediction,
    IntelligenceSynthesizer,
    OddsEdge,
)
from src.services.rl_betting_agent import RLRecommendationPayload
from src.services.uncertainty_service import UncertaintyBreakdown


def _ensemble(league: str = "EPL") -> EnsemblePrediction:
    return EnsemblePrediction(
        home_win_prob=0.50,
        draw_prob=0.28,
        away_win_prob=0.22,
        prediction="home_win",
        confidence=0.50,
        league=league,
        model_version="v5_phase7",
        calibration_method="isotonic",
        calibration_applied=True,
    )


def _uncertainty() -> UncertaintyBreakdown:
    return UncertaintyBreakdown(
        epistemic_unc=0.05,
        aleatoric_unc=0.10,
        concentration=0.8,
        credible_interval=(0.42, 0.58),
        confidence_tier="OK",
    )


def _elo() -> EloContext:
    return EloContext(
        home_elo=1550.0,
        away_elo=1500.0,
        elo_difference=50.0,
        home_elo_trend_5=2.0,
        away_elo_trend_5=-1.0,
        elo_momentum_cross=0.0,
    )


def _causal() -> list[CausalFeatureResult]:
    return [
        CausalFeatureResult(
            name="elo_difference",
            ate_win=0.2,
            ate_draw=0.0,
            ate_ci=(0.1, 0.3),
            p_value=0.01,
            classification="CAUSAL_DRIVER",
        )
    ]


def _rl(stake: float = 0.01, abstain: bool = False) -> RLRecommendationPayload:
    return RLRecommendationPayload(
        stake_fraction=stake,
        abstain=abstain,
        reward_components={},
        reason="test",
    )


@pytest.mark.parametrize(
    ("league", "expected"),
    [
        ("EPL", 0.04),
        ("LA_LIGA", 0.04),
        ("BUNDESLIGA", 0.04),
        ("SERIE_A", 0.04),
        ("LIGUE_1", 0.04),
        ("EREDIVISIE", 0.025),
        ("UCL", 0.02),
    ],
)
def test_effective_league_kelly_caps(league: str, expected: float) -> None:
    cap, gap, _ = endpoint._effective_kelly_cap(league)
    assert cap == pytest.approx(expected)
    assert cap <= 0.05
    assert gap is None


def test_unknown_league_does_not_fall_back_to_global_cap() -> None:
    cap, gap, freshness_limit = endpoint._effective_kelly_cap("UNKNOWN")
    assert cap == 0.0
    assert gap == "LEAGUE_POLICY_UNAVAILABLE"
    assert freshness_limit == 0


@pytest.mark.parametrize(
    ("uncertainty", "odds", "reason_fragment"),
    [
        (None, {"home_win": 2.2, "draw": 3.4, "away_win": 4.0}, "uncertainty unavailable"),
        (_uncertainty(), None, "market odds unavailable"),
    ],
)
def test_rl_advisory_abstains_and_zeroes_when_required_evidence_is_missing(
    uncertainty: UncertaintyBreakdown | None,
    odds: dict[str, float] | None,
    reason_fragment: str,
) -> None:
    recommendation = endpoint._rl_from_ensemble(
        _ensemble(),
        uncertainty,
        odds,
        effective_kelly_cap=0.04,
    )

    assert recommendation.abstain is True
    assert recommendation.stake_fraction == 0.0
    assert reason_fragment in recommendation.reason


def test_rl_advisory_public_stake_is_quarter_kelly_and_below_effective_cap() -> None:
    effective_cap = 0.02
    recommendation = endpoint._rl_from_ensemble(
        _ensemble(),
        _uncertainty(),
        {"home_win": 3.0, "draw": 4.0, "away_win": 5.0},
        effective_kelly_cap=effective_cap,
    )

    assert recommendation.abstain is False
    assert 0.0 < recommendation.stake_fraction <= effective_cap
    assert recommendation.stake_fraction == pytest.approx(0.005)


def test_quarter_kelly_edge_respects_effective_cap() -> None:
    edge = endpoint._odds_edge_from_features(
        _ensemble(),
        {"home_win": 3.0, "draw": 4.0, "away_win": 5.0},
        effective_kelly_cap=0.02,
    )
    assert edge is not None
    assert 0 < edge.kelly_stake <= 0.02


def test_baseline_is_partial_grounded_and_zero_stake() -> None:
    response = IntelligenceSynthesizer().synthesize(
        match_id="baseline",
        ensemble=_ensemble(),
        uncertainty=_uncertainty(),
        causal_results=_causal(),
        rl_rec=_rl(0.02),
        elo_ctx=_elo(),
        odds_edge=OddsEdge("home_win", 3.0, 0.5, 0.1, 0.02),
        critical_gaps=["MODEL_PREDICTION_REDUCED_EVIDENCE"],
        prediction_status="REDUCED_EVIDENCE_BASELINE",
        prediction_source="DIAGNOSTIC_BASELINE",
        effective_kelly_cap=0.04,
    )
    payload = response.to_dict()
    assert response.verdict == "PARTIAL"
    assert response.probabilities_available is False
    assert response.stake_permitted is False
    assert "No bet" in response.narrative
    assert "insufficient verified evidence" in response.narrative
    assert payload["ensemble"]["top_outcome_probability"] == 0.5
    assert payload["top_outcome_probability"] == 0.5
    assert payload["ensemble"]["confidence"] == 0.5


def test_ucl_high_conviction_is_capped_at_actionable() -> None:
    response = IntelligenceSynthesizer().synthesize(
        match_id="ucl",
        ensemble=_ensemble("UCL"),
        uncertainty=_uncertainty(),
        causal_results=_causal(),
        rl_rec=_rl(),
        elo_ctx=_elo(),
        prediction_status="AVAILABLE",
        effective_kelly_cap=0.02,
    )
    assert response.verdict == "ACTIONABLE"


@pytest.mark.asyncio
async def test_default_projection_fallback_is_non_actionable(monkeypatch) -> None:
    class FailingProjector:
        def __init__(self, **_kwargs):
            pass

        async def build_live_feature_vector(self, **_kwargs):
            raise ValueError("fixture unavailable")

    class FallbackPredictionEngine:
        called = False

        async def predict(self, **_kwargs):
            type(self).called = True
            return SimpleNamespace(
                to_dict=lambda: {
                    "home_win": 0.333,
                    "draw": 0.333,
                    "away_win": 0.334,
                    "model_version": "fallback",
                    "calibration_method": "raw",
                }
            )

    monkeypatch.setattr(endpoint, "UpcomingMatchFeatureProjector", FailingProjector)
    monkeypatch.setattr(endpoint, "PredictionEngine", FallbackPredictionEngine)
    monkeypatch.setattr(endpoint, "cache", None)

    payload = await endpoint.get_full_analysis("missing-fixture", league="EPL", db=object())
    parsed = FullMatchAnalysisResponseSchema.model_validate(payload)
    assert FallbackPredictionEngine.called is False
    assert parsed.prediction_status.value == "UNAVAILABLE"
    assert parsed.prediction_source.value == "NONE"
    assert parsed.probabilities_available is False
    assert parsed.partial_intelligence is True
    assert parsed.stake_permitted is False
    assert parsed.rl_recommendation.stake_fraction == 0.0
    assert parsed.actionability is not None
    assert parsed.actionability.suggested_stake_pct == 0.0
    assert parsed.odds_edge is None
    assert "No bet" in parsed.narrative


def _fake_live_vector(*, fixture_identity_verified: bool) -> dict:
    return {
        "features": [0.0] * 58,
        "features_dict": {},  # empty -> _elo_from_features defaults to exact parity
        "data_gaps": [],
        "critical_gaps": [],
        "advisory_gaps": [],
        "conflicts": [],
        "fixture_identity_verified": fixture_identity_verified,
        "elo_context": (
            endpoint.EloContext(
                home_elo=1500.0,
                away_elo=1500.0,
                elo_difference=0.0,
                home_elo_trend_5=0.0,
                away_elo_trend_5=0.0,
                elo_momentum_cross=0.0,
            )
            if fixture_identity_verified
            else None
        ),
        "identity_resolution": {
            "home_team_resolved": fixture_identity_verified,
            "away_team_resolved": fixture_identity_verified,
        },
        "data_quality": {"is_synthetic": False},
        "is_reduced_evidence_baseline": False,
        "staleness_seconds": 0,
        "league": "EPL",
        # Mirrors the canonical PostgreSQL payload that exposed the live bug:
        # the database value is UTC by convention but arrives without tzinfo.
        "kickoff_utc": datetime(2026, 8, 14, 18, 0, 0),
        "odds": None,
    }


class _ValidPredictionEngine:
    async def predict(self, **_kwargs):
        return SimpleNamespace(
            to_dict=lambda: {
                "home_win": 0.45,
                "draw": 0.28,
                "away_win": 0.27,
                "model_version": "v5_phase7",
                "calibration_method": "isotonic",
            }
        )


@pytest.mark.asyncio
async def test_elo_gap_not_flagged_at_exact_parity_when_identity_verified(monkeypatch) -> None:
    """A real, evenly-rated matchup can legitimately land at elo_difference==0.0 /
    home_elo==1500.0 — the old value-based heuristic would have false-positived on
    exactly this case. Gating on identity instead must not flag it."""

    class FakeProjector:
        def __init__(self, **_kwargs):
            pass

        async def build_live_feature_vector(self, **_kwargs):
            return _fake_live_vector(fixture_identity_verified=True)

    monkeypatch.setattr(endpoint, "UpcomingMatchFeatureProjector", FakeProjector)
    monkeypatch.setattr(endpoint, "PredictionEngine", _ValidPredictionEngine)
    monkeypatch.setattr(endpoint, "cache", None)

    payload = await endpoint.get_full_analysis("real-fixture-1", league="EPL", db=object())
    assert "elo_ratings" not in payload["data_gaps"]
    assert "FIXTURE_IDENTITY_UNVERIFIED" not in payload["evidence_quality"]["critical_gaps"]


@pytest.mark.asyncio
async def test_live_shape_serializes_kickoff_with_explicit_utc_offset(monkeypatch) -> None:
    class FakeProjector:
        def __init__(self, **_kwargs):
            pass

        async def build_live_feature_vector(self, **_kwargs):
            return _fake_live_vector(fixture_identity_verified=True)

    monkeypatch.setattr(endpoint, "UpcomingMatchFeatureProjector", FakeProjector)
    monkeypatch.setattr(endpoint, "PredictionEngine", _ValidPredictionEngine)
    monkeypatch.setattr(endpoint, "cache", None)

    payload = await endpoint.get_full_analysis("fd-558223", league="EPL", db=object())
    encoded = jsonable_encoder(payload)
    kickoff = encoded["kickoff_utc"]
    assert kickoff.endswith("Z") or kickoff.endswith("+00:00")
    assert datetime.fromisoformat(kickoff.replace("Z", "+00:00")).tzinfo == timezone.utc


def test_invalid_kickoff_fails_closed_instead_of_emitting_local_time() -> None:
    assert endpoint._utc_aware_datetime("not-a-timestamp") is None


@pytest.mark.asyncio
async def test_elo_gap_flagged_when_identity_unverified(monkeypatch) -> None:
    class FakeProjector:
        def __init__(self, **_kwargs):
            pass

        async def build_live_feature_vector(self, **_kwargs):
            return _fake_live_vector(fixture_identity_verified=False)

    monkeypatch.setattr(endpoint, "UpcomingMatchFeatureProjector", FakeProjector)
    monkeypatch.setattr(endpoint, "PredictionEngine", _ValidPredictionEngine)
    monkeypatch.setattr(endpoint, "cache", None)

    payload = await endpoint.get_full_analysis("real-fixture-2", league="EPL", db=object())
    assert "elo_ratings" in payload["data_gaps"]
    assert "FIXTURE_IDENTITY_UNVERIFIED" in payload["evidence_quality"]["critical_gaps"]


def test_openapi_exposes_typed_full_analysis_response() -> None:
    app = FastAPI()
    app.include_router(endpoint.router)
    schema = app.openapi()
    response = schema["paths"]["/matches/upcoming/{match_id}/full-analysis"]["get"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]
    assert response["$ref"].endswith("/FullMatchAnalysisResponseSchema")
    public_schema = schema["components"]["schemas"]["FullMatchAnalysisResponseSchema"]
    required = set(public_schema["required"])
    assert {
        "prediction_status",
        "prediction_source",
        "probabilities_available",
        "top_outcome_probability",
        "evidence_quality",
        "effective_kelly_cap",
        "stake_permitted",
    } <= required
