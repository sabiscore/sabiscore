"""WP-3.3 regression tests:

1. predictions.py::_save_prediction_to_db persists a MatchPredictionLog row
   alongside the legacy Prediction row (previously only the latter was written;
   match_prediction_logs had a working insert path but no live caller).
2. repositories.fixtures.get_settled_predictions() joins the latest eligible
   pre-kickoff prediction per match to its settled result, in the shape
   model_registry.walk_forward_validate() expects.
3. The production full-analysis path captures and deduplicates that log.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.api.endpoints.predictions import _save_prediction_to_db
from src.api.endpoints import full_analysis as full_analysis_endpoint
from src.core.database import Base, Match
from src.db.models import MatchPredictionLog
from src.repositories.fixtures import get_settled_predictions
from src.schemas.prediction import PredictionResponse


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def _prediction_response(match_id: str, created_at: datetime, **overrides) -> PredictionResponse:
    payload = dict(
        match_id=match_id,
        home_team="Home FC",
        away_team="Away FC",
        league="epl",
        predictions={"home_win": 0.55, "draw": 0.25, "away_win": 0.20},
        confidence=0.55,
        brier_score=0.18,
        metadata={"model_version": "v5_phase7", "calibration_method": "isotonic"},
        created_at=created_at,
    )
    payload.update(overrides)
    return PredictionResponse(**payload)


# ---------------------------------------------------------------------------
# WP-3.3a: _save_prediction_to_db writes MatchPredictionLog
# ---------------------------------------------------------------------------


async def test_save_prediction_writes_match_prediction_log(session: AsyncSession) -> None:
    created_at = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    result = _prediction_response("match-1", created_at)

    await _save_prediction_to_db(db=session, prediction_data=result, match_id="match-1")

    rows = (await session.execute(MatchPredictionLog.__table__.select())).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.match_id == "match-1"
    assert row.canonical_fixture_id is None
    assert row.model_version == "v5_phase7"
    assert row.calibration_method == "isotonic"
    assert row.home_probability == pytest.approx(0.55)
    assert row.draw_probability == pytest.approx(0.25)
    assert row.away_probability == pytest.approx(0.20)


# ---------------------------------------------------------------------------
# WP-3.3b: get_settled_predictions() join
# ---------------------------------------------------------------------------


async def _seed_settled_match(
    session: AsyncSession,
    match_id: str,
    *,
    home_score: int,
    away_score: int,
    match_date: datetime,
    league_id: str = "EPL",
) -> None:
    session.add(
        Match(
            id=match_id,
            home_team_id="team-home",
            away_team_id="team-away",
            league_id=league_id,
            match_date=match_date,
            status="finished",
            home_score=home_score,
            away_score=away_score,
        )
    )
    await session.commit()


async def test_get_settled_predictions_joins_latest_log_to_result(session: AsyncSession) -> None:
    match_date = datetime(2026, 8, 1, 15, 0)
    await _seed_settled_match(session, "match-1", home_score=2, away_score=1, match_date=match_date)

    # Two prediction logs for the same match — the join must pick the latest.
    session.add(
        MatchPredictionLog(
            match_id="match-1",
            canonical_fixture_id=None,
            model_version="stale",
            calibration_method=None,
            home_probability=0.10,
            draw_probability=0.10,
            away_probability=0.80,
            confidence=0.80,
            created_at=match_date - timedelta(days=2),
        )
    )
    session.add(
        MatchPredictionLog(
            match_id="match-1",
            canonical_fixture_id=None,
            model_version="latest",
            calibration_method="isotonic",
            home_probability=0.60,
            draw_probability=0.25,
            away_probability=0.15,
            confidence=0.60,
            created_at=match_date - timedelta(hours=1),
        )
    )
    await session.commit()

    records = await get_settled_predictions(session, model_version="latest")

    assert len(records) == 1
    record = records[0]
    assert record["outcome"] == 0  # home_score(2) > away_score(1)
    assert record["probs"] == pytest.approx([0.60, 0.25, 0.15])


async def test_get_settled_predictions_excludes_post_kickoff_log(
    session: AsyncSession,
) -> None:
    match_date = datetime(2026, 8, 1, 15, 0)
    await _seed_settled_match(
        session,
        "match-temporal",
        home_score=2,
        away_score=1,
        match_date=match_date,
    )
    session.add(
        MatchPredictionLog(
            match_id="match-temporal",
            canonical_fixture_id=None,
            model_version="eligible",
            home_probability=0.55,
            draw_probability=0.25,
            away_probability=0.20,
            confidence=0.55,
            created_at=match_date - timedelta(minutes=1),
        )
    )
    session.add(
        MatchPredictionLog(
            match_id="match-temporal",
            canonical_fixture_id=None,
            model_version="leaked",
            home_probability=0.99,
            draw_probability=0.005,
            away_probability=0.005,
            confidence=0.99,
            created_at=match_date + timedelta(minutes=1),
        )
    )
    await session.commit()

    records = await get_settled_predictions(session, model_version="eligible")

    assert len(records) == 1
    assert records[0]["probs"] == pytest.approx([0.55, 0.25, 0.20])


async def test_get_settled_predictions_breaks_equal_timestamps_by_latest_id(
    session: AsyncSession,
) -> None:
    match_date = datetime(2026, 8, 1, 15, 0)
    created_at = match_date - timedelta(hours=1)
    await _seed_settled_match(
        session,
        "match-tied",
        home_score=2,
        away_score=1,
        match_date=match_date,
    )
    session.add(
        MatchPredictionLog(
            match_id="match-tied",
            model_version="v5_phase7",
            home_probability=0.20,
            draw_probability=0.20,
            away_probability=0.60,
            created_at=created_at,
        )
    )
    session.add(
        MatchPredictionLog(
            match_id="match-tied",
            model_version="v5_phase7",
            home_probability=0.60,
            draw_probability=0.25,
            away_probability=0.15,
            created_at=created_at,
        )
    )
    await session.commit()

    records = await get_settled_predictions(
        session, model_version="v5_phase7"
    )

    assert len(records) == 1
    assert records[0]["probs"] == pytest.approx([0.60, 0.25, 0.15])


async def test_get_settled_predictions_excludes_unsettled_matches(session: AsyncSession) -> None:
    match_date = datetime(2026, 8, 10, 15, 0)
    session.add(
        Match(
            id="match-scheduled",
            home_team_id="team-home",
            away_team_id="team-away",
            league_id="EPL",
            match_date=match_date,
            status="scheduled",
            home_score=None,
            away_score=None,
        )
    )
    await session.commit()
    session.add(
        MatchPredictionLog(
            match_id="match-scheduled",
            canonical_fixture_id=None,
            model_version="v5_phase7",
            calibration_method=None,
            home_probability=0.5,
            draw_probability=0.3,
            away_probability=0.2,
            confidence=0.5,
            created_at=match_date - timedelta(days=1),
        )
    )
    await session.commit()

    records = await get_settled_predictions(session, model_version="v5_phase7")
    assert records == []


async def test_get_settled_predictions_outcome_encoding(session: AsyncSession) -> None:
    """outcome: 0=home_win, 1=draw, 2=away_win — the encoding
    walk_forward_validate() / ranked_probability_score() expect."""
    match_date = datetime(2026, 8, 1, 15, 0)
    cases = [
        ("match-draw", 1, 1, 1),
        ("match-away", 0, 3, 2),
    ]
    for match_id, home_score, away_score, _expected in cases:
        await _seed_settled_match(
            session, match_id, home_score=home_score, away_score=away_score, match_date=match_date
        )
        session.add(
            MatchPredictionLog(
                match_id=match_id,
                canonical_fixture_id=None,
                model_version="v5_phase7",
                calibration_method=None,
                home_probability=0.33,
                draw_probability=0.34,
                away_probability=0.33,
                confidence=0.34,
                created_at=match_date - timedelta(hours=1),
            )
        )
        await session.commit()

    records = await get_settled_predictions(session, model_version="v5_phase7")
    outcomes = {r["outcome"] for r in records}
    assert outcomes == {1, 2}


async def test_full_analysis_capture_flows_into_settlement_join(
    session: AsyncSession,
    monkeypatch,
) -> None:
    """scheduled fixture -> full analysis -> log -> result -> settled join."""

    kickoff = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=1)
    session.add(
        Match(
            id="match-full-analysis",
            home_team_id="team-home",
            away_team_id="team-away",
            league_id="EPL",
            match_date=kickoff,
            status="scheduled",
        )
    )
    await session.commit()

    class FakeProjector:
        def __init__(self, **_kwargs):
            pass

        async def build_live_feature_vector(self, **_kwargs):
            return {
                "features": [0.0] * 58,
                "features_dict": {"home_form": 0.4},
                "data_gaps": [],
                "critical_gaps": [],
                "advisory_gaps": [],
                "conflicts": [],
                "fixture_identity_verified": True,
                "identity_resolution": {
                    "home_team_resolved": True,
                    "away_team_resolved": True,
                },
                "data_quality": {"is_synthetic": False},
                "is_reduced_evidence_baseline": False,
                "staleness_seconds": 0,
                "league": "EPL",
                "home_team": "Home FC",
                "away_team": "Away FC",
                "kickoff_utc": kickoff.isoformat(),
                "odds": None,
                "market_snapshot_acquired": True,
                "feature_source": {"home_form": "settled_history"},
            }

    class FakePredictionEngine:
        async def predict(self, **_kwargs):
            return SimpleNamespace(
                to_dict=lambda: {
                    "home_win": 0.55,
                    "draw": 0.25,
                    "away_win": 0.20,
                    "model_version": "v5_phase7",
                    "calibration_method": "isotonic",
                }
            )

    monkeypatch.setattr(
        full_analysis_endpoint,
        "UpcomingMatchFeatureProjector",
        FakeProjector,
    )
    monkeypatch.setattr(
        full_analysis_endpoint,
        "PredictionEngine",
        FakePredictionEngine,
    )
    monkeypatch.setattr(full_analysis_endpoint, "cache", None)

    await full_analysis_endpoint.get_full_analysis(
        "match-full-analysis",
        league="EPL",
        db=session,
    )
    await full_analysis_endpoint.get_full_analysis(
        "match-full-analysis",
        league="EPL",
        db=session,
    )

    logs = (
        await session.execute(
            select(MatchPredictionLog).where(
                MatchPredictionLog.match_id == "match-full-analysis"
            )
        )
    ).scalars().all()
    assert len(logs) == 1
    assert logs[0].input_hash
    assert logs[0].payload["capture_trigger"] == "interactive_full_analysis"

    fixture = (
        await session.execute(
            select(Match).where(Match.id == "match-full-analysis")
        )
    ).scalar_one()
    fixture.status = "finished"
    fixture.home_score = 2
    fixture.away_score = 1
    await session.commit()

    records = await get_settled_predictions(session, model_version="v5_phase7")
    assert len(records) == 1
    assert records[0]["outcome"] == 0
    assert records[0]["probs"] == pytest.approx([0.55, 0.25, 0.20])
