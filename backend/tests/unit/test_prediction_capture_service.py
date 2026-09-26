"""Directive v9 L4: every scheduled fixture gets one pre-kickoff forecast.

Before this pass, prediction logs were written only when a person opened a
fixture, so the served generation reached 0 settled predictions (2026-09-25)
and v8's 200-settled milestone had no guaranteed input.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.api import main as api_main
from src.core.database import Base, Match
from src.db.models import MatchPredictionLog
from src.models.active_generation import served_identity
from src.services import (
    clv_capture_service,
    prediction_capture_service,
    prediction_log_service,
)
from src.services.prediction_capture_service import capture_due_predictions
from src.services.prediction_log_service import (
    PredictionLogCapture,
    persist_prediction_log,
)

NOW = datetime(2026, 10, 9, 12, 0, 0)

_ARTIFACT = {
    "artifact": "x.pkl",
    "artifact_sha256": "a" * 64,
    "metadata": "x.json",
    "metadata_sha256": "b" * 64,
    "required": True,
}
MANIFEST = {
    "schema_version": 1,
    "generation": "v5_phase7-20260922",
    "active_version": "v5_phase7",
    "feature_schema_version": "apex_v1_68",
    "served_head": "stacked_meta_model",
    "certification_state": "UNVERIFIED",
    "artifacts": {
        "epl": copy.deepcopy(_ARTIFACT),
        "eredivisie": copy.deepcopy(_ARTIFACT),
    },
}
IDENTITY = served_identity(MANIFEST)


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture(autouse=True)
def manifest(monkeypatch):
    for module in (prediction_capture_service, prediction_log_service):
        monkeypatch.setattr(module, "read_active_manifest", lambda: MANIFEST)
    return MANIFEST


async def _fixture(
    session: AsyncSession, match_id: str, kickoff: datetime, league: str = "EPL"
) -> None:
    session.add(
        Match(
            id=match_id,
            league_id=league,
            home_team_id=f"{match_id}-h",
            away_team_id=f"{match_id}-a",
            match_date=kickoff,
            status="scheduled",
        )
    )
    await session.commit()


class _Analyze:
    """Stands in for get_full_analysis: logs through the real persistence path."""

    def __init__(self, *, decline: set[str] = frozenset(), fail: set[str] = frozenset()):
        self.calls: list[tuple[str, str]] = []
        self.decline = set(decline)
        self.fail = set(fail)

    async def __call__(self, *, match_id, league, db, odds_service):
        self.calls.append((match_id, league))
        if match_id in self.fail:
            raise RuntimeError("provider exploded")
        if match_id in self.decline:
            return {"prediction_status": "REDUCED_EVIDENCE_BASELINE"}
        await persist_prediction_log(
            db,
            PredictionLogCapture(
                match_id=match_id,
                model_version="v5_phase7",
                home_probability=0.5,
                draw_probability=0.3,
                away_probability=0.2,
                input_hash=f"inputs-{match_id}",
                evaluated_at=NOW,
            ),
            require_scheduled_pre_kickoff=True,
        )
        await db.commit()
        return {"prediction_status": "AVAILABLE"}


async def _logs(session: AsyncSession) -> list[tuple[str, str]]:
    rows = await session.execute(
        select(MatchPredictionLog.match_id, MatchPredictionLog.model_version)
    )
    return sorted(tuple(r) for r in rows.all())


@pytest.mark.asyncio
async def test_one_row_per_fixture_per_served_identity(session):
    await _fixture(session, "m1", NOW + timedelta(hours=1))
    analyze = _Analyze()

    first = await capture_due_predictions(session, analyze=analyze, now=NOW)
    second = await capture_due_predictions(session, analyze=analyze, now=NOW)

    assert first["captured"] == 1
    assert second["already_captured"] == 1 and second["captured"] == 0
    assert analyze.calls == [("m1", "EPL")]  # never re-analysed once captured
    assert await _logs(session) == [("m1", IDENTITY)]


@pytest.mark.asyncio
async def test_only_fixtures_inside_the_pre_kickoff_window(session):
    await _fixture(session, "kicked-off", NOW - timedelta(minutes=5))
    await _fixture(session, "too-close", NOW + timedelta(minutes=10))
    await _fixture(session, "window-start", NOW + timedelta(minutes=15))
    await _fixture(session, "window-end", NOW + timedelta(hours=3))
    await _fixture(session, "too-far", NOW + timedelta(hours=4))
    analyze = _Analyze()

    counts = await capture_due_predictions(session, analyze=analyze, now=NOW)

    assert sorted(m for m, _ in analyze.calls) == ["window-end", "window-start"]
    assert counts["due"] == 2
    # Never a row at or after kickoff.
    assert "kicked-off" not in {m for m, _ in await _logs(session)}


@pytest.mark.asyncio
async def test_no_capture_outside_the_served_leagues(session):
    await _fixture(session, "ucl", NOW + timedelta(hours=1), league="UCL")
    await _fixture(session, "ned", NOW + timedelta(hours=1), league="EREDIVISIE")
    analyze = _Analyze()

    counts = await capture_due_predictions(session, analyze=analyze, now=NOW)

    assert analyze.calls == [("ned", "EREDIVISIE")]
    assert counts["unsupported_league"] == 1


@pytest.mark.asyncio
async def test_a_previous_generation_row_is_not_a_capture(session):
    await _fixture(session, "m1", NOW + timedelta(hours=1))
    session.add(
        MatchPredictionLog(
            match_id="m1",
            model_version="v5_phase7-20260808@0000000000000000",
            home_probability=0.4,
            draw_probability=0.3,
            away_probability=0.3,
            created_at=NOW - timedelta(days=1),
        )
    )
    await session.commit()

    counts = await capture_due_predictions(session, analyze=_Analyze(), now=NOW)

    assert counts["captured"] == 1


@pytest.mark.asyncio
async def test_one_failing_fixture_does_not_cost_the_round(session):
    await _fixture(session, "a", NOW + timedelta(hours=1))
    await _fixture(session, "b", NOW + timedelta(hours=1, minutes=5))
    await _fixture(session, "c", NOW + timedelta(hours=1, minutes=10))
    analyze = _Analyze(fail={"a"}, decline={"b"})

    counts = await capture_due_predictions(session, analyze=analyze, now=NOW)

    assert [m for m, _ in analyze.calls] == ["a", "b", "c"]
    assert counts == {
        "due": 3,
        "captured": 1,
        "already_captured": 0,
        "not_captured": 1,
        "unsupported_league": 0,
        "errors": 1,
    }
    assert await _logs(session) == [("c", IDENTITY)]


@pytest.mark.asyncio
async def test_a_capture_failure_never_costs_the_clv_capture(monkeypatch):
    order: list[str] = []

    async def clv(provider=None):
        order.append("clv")
        return {"outcome": "ok"}

    async def capture(odds_service=None):
        order.append("capture")
        raise RuntimeError("capture broke")

    monkeypatch.setattr(clv_capture_service, "run_clv_capture_pass", clv)
    monkeypatch.setattr(
        prediction_capture_service, "run_prediction_capture_pass", capture
    )

    await api_main._clv_capture_tick(provider=None, odds_service=None)  # no raise
    await api_main._clv_capture_tick(provider=None, odds_service=None)

    assert order == ["clv", "capture", "clv", "capture"]


@pytest.mark.asyncio
async def test_pass_reports_an_unreadable_manifest_instead_of_writing(monkeypatch):
    from src.models.active_generation import ActiveGenerationError

    def unreadable():
        raise ActiveGenerationError("manifest unreadable")

    monkeypatch.setattr(prediction_capture_service, "read_active_manifest", unreadable)

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    import src.db.session as db_session

    monkeypatch.setattr(db_session, "AsyncSessionLocal", _Session)

    async def never(**_kwargs):
        raise AssertionError("must not analyse without a served identity")

    result = await prediction_capture_service.run_prediction_capture_pass(
        analyze=never
    )
    assert result["outcome"] == "manifest_unreadable"
    assert result["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_the_matchday_burst_can_be_read_after_the_fact(monkeypatch):
    """Directive v11 §1: D1 reads each capture tick's duration and memory. A
    person polling /health every five minutes from 15:00 to 18:45 UTC is not a
    measurement plan, so passes that had work to do are kept, bounded."""
    from collections import deque

    import src.db.session as db_session

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    counts = iter([{"due": 2, "captured": 2, "errors": 0}, {"due": 0, "captured": 0, "errors": 0}] * 30)

    async def fake_capture(_session, **_kwargs):
        return next(counts)

    monkeypatch.setattr(db_session, "AsyncSessionLocal", _Session)
    monkeypatch.setattr(prediction_capture_service, "capture_due_predictions", fake_capture)
    monkeypatch.setattr(prediction_capture_service, "_RECENT_PASSES", deque(maxlen=4))

    for _ in range(2):
        await prediction_capture_service.run_prediction_capture_pass(analyze=object())

    recent = prediction_capture_service.last_prediction_capture_result()["recent"]
    assert len(recent) == 1  # the idle pass (nothing due) is not history
    assert recent[0]["due"] == 2 and recent[0]["captured"] == 2
    assert recent[0]["duration_ms"] >= 0
    assert isinstance(recent[0]["rss_mb"], int)

    for _ in range(58):
        await prediction_capture_service.run_prediction_capture_pass(analyze=object())
    # 30 passes had work; the history keeps only the newest, bounded.
    assert len(prediction_capture_service.last_prediction_capture_result()["recent"]) == 4
