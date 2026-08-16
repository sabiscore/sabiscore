"""Zero-fabrication regression tests for the upcoming-matches prediction path.

get_upcoming_matches_with_predictions() previously ran calculate_value_bets()
on PredictionEngine's uniform fallback result (returned whenever a model
artifact is missing or inference fails) whenever real market odds were
present — producing a fabricated edge/Kelly stake that reached the public
GET /upcoming/matches response. _is_fallback_prediction() is the gate that
prevents that; these tests pin its behavior and document the exact
fabrication it prevents.
"""

from __future__ import annotations

import sys
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.services.upcoming_match_service import (
    UpcomingMatchService,
    _is_fallback_prediction,
    _select_feature_vector,
)
from src.models.prediction import PredictionEngine


def test_is_fallback_prediction_true_for_fallback_model_version():
    assert _is_fallback_prediction({"model_version": "fallback"}) is True


def test_is_fallback_prediction_case_insensitive():
    assert _is_fallback_prediction({"model_version": "FALLBACK"}) is True
    assert _is_fallback_prediction({"model_version": "Fallback"}) is True


def test_is_fallback_prediction_false_for_real_model_version():
    assert _is_fallback_prediction({"model_version": "v6_phase8"}) is False


def test_is_fallback_prediction_false_when_model_version_missing():
    assert _is_fallback_prediction({}) is False


def test_select_feature_vector_handles_project_match_features_shape():
    """Regression: project_match_features() returns features_68/features_58 but
    no 'features' key. A `a or b or c` chain over those values calls bool() on a
    multi-element ndarray and raises ValueError, which the enrichment loop
    swallowed into data_gaps=["prediction_failed"] for every fixture in
    production. This must select the vector without raising."""
    features_result = {
        "features_68": np.zeros(68, dtype=np.float32),
        "features_58": np.zeros(58, dtype=np.float32),
    }

    vector = _select_feature_vector(features_result)

    assert vector.shape == (68,)


def test_select_feature_vector_prefers_widest_available():
    features_result = {
        "features": np.ones(86, dtype=np.float32),
        "features_68": np.zeros(68, dtype=np.float32),
        "features_58": np.zeros(58, dtype=np.float32),
    }

    assert _select_feature_vector(features_result).shape == (86,)


def test_select_feature_vector_falls_back_to_features_dict():
    features_result = {"features_dict": {"a": 1.0, "b": 2.0}}

    assert _select_feature_vector(features_result).shape == (2,)


def test_select_feature_vector_ignores_an_all_zero_vector_rather_than_skipping_it():
    """An all-zero vector is falsy-adjacent but still a real projection —
    presence must be decided by `is not None`, never by truthiness."""
    features_result = {"features_68": np.zeros(68, dtype=np.float32)}

    assert _select_feature_vector(features_result).shape == (68,)


def test_fallback_prediction_would_fabricate_a_positive_edge_if_ungated():
    """Documents why the gate in get_upcoming_matches_with_predictions exists:
    a uniform-fallback prediction, called directly against realistic odds,
    produces a real-looking value bet — the exact fabrication the caller
    must avoid reaching."""
    fallback_predictions = {"home_win": 0.333, "draw": 0.333, "away_win": 0.334}
    odds = {"home_win": 2.1, "draw": 3.4, "away_win": 4.0}

    bets = PredictionEngine.calculate_value_bets(fallback_predictions, odds)

    assert len(bets) > 0
    assert bets[0]["edge_pct"] > 0


def test_calculate_value_bets_caps_kelly_stake_at_league_policy_cap():
    """WP-17 prerequisite fix: calculate_value_bets previously applied no cap
    at all (a 4th, independent, uncapped Kelly implementation beyond
    insights/engine.py, betting_intelligence.py, core_engine.py). A
    pathological high-edge input must still respect EREDIVISIE's 0.025
    kelly_cap via get_league_policy, not an arbitrarily large raw stake."""
    predictions = {"home_win": 0.99, "draw": 0.005, "away_win": 0.005}
    odds = {"home_win": 1.5, "draw": 20.0, "away_win": 20.0}

    bets = PredictionEngine.calculate_value_bets(predictions, odds, league="EREDIVISIE")

    home_bet = next(b for b in bets if b["outcome"] == "home_win")
    assert home_bet["kelly_stake_pct"] <= 2.5


def test_calculate_value_bets_falls_back_to_max_kelly_cap_for_unknown_league():
    """Same pathological input, an unrecognized league string — falls back
    to the conservative global MAX_KELLY_CAP (5.0%), not uncapped, and NOT
    EREDIVISIE's tighter 2.5% cap (that would require a league that resolves)."""
    predictions = {"home_win": 0.99, "draw": 0.005, "away_win": 0.005}
    odds = {"home_win": 1.5, "draw": 20.0, "away_win": 20.0}

    bets = PredictionEngine.calculate_value_bets(predictions, odds, league="NOT_A_REAL_LEAGUE")

    home_bet = next(b for b in bets if b["outcome"] == "home_win")
    assert home_bet["kelly_stake_pct"] <= 5.0
    assert home_bet["kelly_stake_pct"] > 2.5


async def test_get_upcoming_matches_with_predictions_uses_build_live_feature_vector():
    """WP-B regression: the enrichment loop must call the enrichment wrapper
    (build_live_feature_vector — Elo/StatsBomb/Phase8 included), never the bare
    project_match_features() it wraps. Calling the bare projector silently
    dropped 27 of 68 canonical features (never counted as gaps either, since
    project_match_features()'s own _CALLER_RESOLVED_FEATURES assumes the caller
    tracks them) and left staleness_seconds permanently at 0 — a key the bare
    projector's return dict never carries at all — which is what produced
    near-identical edge_quality_score values across different fixtures on the
    live homepage (freshness = 1 - staleness/threshold, pinned at its max)."""
    future_date = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    fake_api_client = MagicMock()
    fake_api_client.get_upcoming_matches = AsyncMock(
        side_effect=AssertionError("request-time provider access is forbidden")
    )

    mocked_features_result = {
        "features": np.zeros(68, dtype=np.float32),
        "data_gaps": ["elo_difference", "home_pressing_intensity"],
        "data_quality": {"is_synthetic": False},
        "staleness_seconds": 54321,
    }
    mocked_prediction = MagicMock()
    mocked_prediction.to_dict.return_value = {
        "home_win": 0.4, "draw": 0.3, "away_win": 0.3,
        "model_version": "v6_test", "confidence": 0.5,
    }
    fake_db = MagicMock(name="db")

    with patch(
        "src.services.upcoming_match_service.UpcomingMatchFeatureProjector"
    ) as MockProjector, patch(
        "src.services.upcoming_match_service.PredictionEngine"
    ) as MockPredictionEngine, patch(
        "src.services.upcoming_match_service.OddsService"
    ) as MockOddsService, patch(
        "src.services.upcoming_match_service.cache_manager"
    ) as MockCache:
        # Force cache miss so prior tests cannot pollute this test via the
        # module-level cache_manager singleton (pre-existing flake pattern).
        MockCache.get.return_value = None
        MockProjector.return_value.build_live_feature_vector = AsyncMock(
            return_value=mocked_features_result
        )
        MockProjector.return_value.project_match_features = AsyncMock(
            side_effect=AssertionError("bare project_match_features must not be called")
        )
        MockPredictionEngine.return_value.predict = AsyncMock(return_value=mocked_prediction)
        MockOddsService.return_value.get_match_odds = AsyncMock(return_value={})

        service = UpcomingMatchService(api_client=fake_api_client)
        service.get_upcoming_matches = AsyncMock(return_value={
            "matches": [{
                "id": "test-match-1",
                "home_team": "Home FC",
                "away_team": "Away FC",
                "league": "EPL",
                "match_date": future_date,
                "status": "scheduled",
                "source": "database",
            }],
            "source": "database",
        })
        response = await service.get_upcoming_matches_with_predictions(
            db=fake_db, league="EPL", days_ahead=3, limit=5,
        )

    MockProjector.return_value.build_live_feature_vector.assert_awaited_once_with(
        match_id="test-match-1", league="EPL", db=fake_db
    )
    MockProjector.return_value.project_match_features.assert_not_awaited()
    fake_api_client.get_upcoming_matches.assert_not_awaited()

    enriched = response["upcoming_matches"][0]
    assert enriched["staleness_seconds"] == 54321  # not silently defaulted to 0
    assert enriched["staleness_available"] is True
    assert "elo_difference" in enriched["data_gaps"]
    assert "home_pressing_intensity" in enriched["data_gaps"]


async def test_uncertified_generation_exposes_forecast_but_never_value_or_stake():
    """Research probabilities may remain visible while public betting action is fail-closed."""
    future_date = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    fake_api_client = MagicMock()
    fake_db = MagicMock(name="db")
    mocked_prediction = MagicMock()
    mocked_prediction.to_dict.return_value = {
        "home_win": 0.60,
        "draw": 0.22,
        "away_win": 0.18,
        "model_version": "v5_phase7",
        "certification_state": "UNVERIFIED",
        "confidence": 0.60,
    }

    with patch(
        "src.services.upcoming_match_service.UpcomingMatchFeatureProjector"
    ) as MockProjector, patch(
        "src.services.upcoming_match_service.PredictionEngine"
    ) as MockPredictionEngine, patch(
        "src.services.upcoming_match_service.OddsService"
    ) as MockOddsService, patch(
        "src.services.upcoming_match_service.cache_manager"
    ) as MockCache:
        MockCache.get.return_value = None
        MockProjector.return_value.build_live_feature_vector = AsyncMock(
            return_value={
                "features": np.zeros(68, dtype=np.float32),
                "data_gaps": [],
                "data_quality": {"is_synthetic": False},
                "staleness_seconds": 120,
            }
        )
        MockPredictionEngine.return_value.predict = AsyncMock(return_value=mocked_prediction)
        MockOddsService.return_value.get_match_odds = AsyncMock(
            return_value={"home_win": 2.4, "draw": 4.0, "away_win": 6.0, "source": "test"}
        )

        service = UpcomingMatchService(api_client=fake_api_client)
        service.get_upcoming_matches = AsyncMock(return_value={
            "matches": [{
                "id": "uncertified-1",
                "home_team": "Home FC",
                "away_team": "Away FC",
                "league": "EPL",
                "match_date": future_date,
                "status": "scheduled",
                "source": "database",
            }],
            "source": "database",
        })
        response = await service.get_upcoming_matches_with_predictions(
            db=fake_db, league="EPL", days_ahead=3, limit=5, include_value_bets=True
        )

    enriched = response["upcoming_matches"][0]
    assert enriched["predictions"] is not None
    assert enriched["predictions"]["certification_state"] == "UNVERIFIED"
    assert enriched["value_bets"] == []
    assert enriched["best_value_bet"] is None
    assert enriched["has_value"] is False
    assert "model_generation_uncertified" in enriched["data_gaps"]


async def test_cached_or_db_fixture_discovery_never_calls_provider_or_model():
    fake_api_client = MagicMock()
    fake_api_client.get_upcoming_matches = AsyncMock(
        side_effect=AssertionError("interactive discovery must not call provider")
    )
    service = UpcomingMatchService(api_client=fake_api_client)
    service._get_upcoming_matches_from_db = AsyncMock(
        return_value={"matches": [], "total": 0, "source": "database"}
    )

    with patch(
        "src.services.upcoming_match_service.PredictionEngine",
        side_effect=AssertionError("interactive discovery must not load a model"),
    ):
        result = await service.get_upcoming_matches_cached_or_db(
            MagicMock(), league="EREDIVISIE", days_ahead=7, limit=10
        )

    fake_api_client.get_upcoming_matches.assert_not_awaited()
    assert result["source"] == "database"
    assert result["data_gap"] is False


# ---------------------------------------------------------------------------
# Contract: the DB row builder must satisfy UpcomingMatchesResponseSchema.
#
# _get_upcoming_matches_from_db() emitted "id" while UpcomingMatchSchema
# requires "match_id". Every include_predictions=false request therefore
# raised ValidationError inside the endpoint, whose broad `except Exception`
# converted it into source="error" + UPCOMING_SERVICE_UNAVAILABLE and an
# EMPTY fixture list. The public fixtures panel always sends
# include_predictions=false, so it showed "no upcoming fixtures" while the
# database held dozens of synced, in-window fixtures.
#
# The prediction path masked this in tests: it overwrites match["match_id"]
# on both its success and failure branches, so a prediction-path test can
# never catch a missing match_id in the shared row builder.
# ---------------------------------------------------------------------------


async def test_db_rows_satisfy_response_schema_without_predictions():
    """Run the real row builder against a real session, then validate with the
    real response schema — the exact sequence the endpoint performs."""
    import pytest_asyncio  # noqa: F401  (asyncio_mode=auto)
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from src.api.endpoints.upcoming_matches import UpcomingMatchesResponseSchema
    from src.core.database import Base, League, Match, Team

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        async with factory() as db:
            db.add(League(id="EPL", name="Premier League", country="England"))
            db.add_all([
                Team(id="t-home", name="Arsenal", league_id="EPL", active=True),
                Team(id="t-away", name="Chelsea", league_id="EPL", active=True),
            ])
            await db.commit()
            db.add(Match(
                id="fd-900001",
                home_team_id="t-home",
                away_team_id="t-away",
                league_id="EPL",
                match_date=now + timedelta(days=2),
                status="scheduled",
            ))
            await db.commit()

            service = UpcomingMatchService(api_client=MagicMock())
            with patch("src.services.upcoming_match_service.cache_manager") as MockCache:
                MockCache.get.return_value = None  # force a real DB read
                payload = await service.get_upcoming_matches(
                    db, league=None, days_ahead=14, limit=50
                )

            rows = payload["matches"]
            assert len(rows) == 1, "seeded in-window fixture must be returned"
            # The canonical identity key the schema and apps/web both read.
            assert rows[0]["match_id"] == "fd-900001"

            # Replicate the endpoint's normalisation, then validate for real.
            payload["upcoming_matches"] = payload.pop("matches")
            payload["matches_with_value"] = 0
            payload["avg_edge_pct"] = 0.0
            payload["offseason"] = False
            validated = UpcomingMatchesResponseSchema.model_validate(payload)

            assert validated.total == 1
            assert validated.source == "database"
            assert validated.upcoming_matches[0].match_id == "fd-900001"
            # A successful read must never look like an outage or an off-season.
            assert validated.data_gap is False
            assert validated.unavailable_reasons == []
            assert validated.offseason is False
    finally:
        await engine.dispose()


async def test_enrichment_failure_rolls_back_session_before_continuing() -> None:
    """A swallowed per-fixture DB error must not poison the next fixture query."""
    future_date = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    fake_db = AsyncMock(name="db")

    with patch(
        "src.services.upcoming_match_service.UpcomingMatchFeatureProjector"
    ) as MockProjector, patch(
        "src.services.upcoming_match_service.PredictionEngine"
    ), patch(
        "src.services.upcoming_match_service.cache_manager"
    ) as MockCache:
        MockCache.get.return_value = None
        MockProjector.return_value.build_live_feature_vector = AsyncMock(
            side_effect=RuntimeError("db transaction failed")
        )

        service = UpcomingMatchService()
        service.get_upcoming_matches = AsyncMock(
            return_value={
                "matches": [
                    {
                        "match_id": "fd-rollback-1",
                        "home_team": "Home FC",
                        "away_team": "Away FC",
                        "league": "EPL",
                        "match_date": future_date,
                        "status": "scheduled",
                        "source": "database",
                    }
                ],
                "source": "database",
            }
        )

        response = await service.get_upcoming_matches_with_predictions(
            db=fake_db,
            league="EPL",
            days_ahead=3,
            limit=5,
        )

    fake_db.rollback.assert_awaited_once()
    assert response["upcoming_matches"][0]["data_gaps"] == ["prediction_failed"]
