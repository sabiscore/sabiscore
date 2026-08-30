"""Unit tests for GET /model-performance and /model-performance/summary.

Contracts verified:
  1. Below walk_forward_validate's data floor (n_splits*2=10 records) -> 503
     with reason="insufficient_settled_predictions" (the honest, corrected
     reason — not the old, now-false "not_yet_integrated" string).
  2. Once enough settled+logged predictions exist -> 200 with a real payload.
  3. league= accepts the canonical vocabulary (e.g. "EREDIVISIE") even though
     Match.league_id stores football-data.org codes ("DED") — the two-league-
     vocabulary trap this codebase has hit before (CLAUDE.md vΩ.26).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, Match
from src.db.models import MarketSnapshot, MatchPredictionLog


@pytest.fixture(autouse=True)
def _reset_settlement_module_state():
    from src.services import settlement_service

    settlement_service._registry_instance = None
    yield


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _seed(session: AsyncSession, n: int, *, league_id: str = "DED", base_date: datetime | None = None) -> None:
    base_date = base_date or datetime(2026, 8, 1, 15, 0)
    for i in range(n):
        match_id = f"fd-{league_id}-{i}"
        session.add(
            Match(
                id=match_id,
                home_team_id="team-home",
                away_team_id="team-away",
                league_id=league_id,
                match_date=base_date + timedelta(days=i),
                status="finished",
                home_score=i % 3,
                away_score=(i + 1) % 3,
            )
        )
        session.add(
            MatchPredictionLog(
                match_id=match_id,
                canonical_fixture_id=None,
                model_version="v5_phase7",
                calibration_method=None,
                home_probability=0.4,
                draw_probability=0.3,
                away_probability=0.3,
                confidence=0.4,
                created_at=base_date + timedelta(days=i, hours=-1),
            )
        )
    await session.commit()


async def _seed_with_closing_lines(
    session: AsyncSession,
    n: int,
    *,
    league_id: str = "DED",
    base_date: datetime | None = None,
    finished: bool = True,
) -> None:
    """Match + MatchPredictionLog + a captured closing-line MarketSnapshot for
    each of n fixtures. finished=False leaves matches unsettled (no scores) —
    used to prove clv isn't gated by the walk-forward floor (they're
    independent data sources in the same response, see performance.py)."""
    base_date = base_date or datetime(2026, 8, 1, 15, 0)
    for i in range(n):
        match_id = f"clv-{league_id}-{i}"
        match_date = base_date + timedelta(days=i)
        session.add(
            Match(
                id=match_id,
                home_team_id="team-home",
                away_team_id="team-away",
                league_id=league_id,
                match_date=match_date,
                status="finished" if finished else "scheduled",
                home_score=(i % 3) if finished else None,
                away_score=((i + 1) % 3) if finished else None,
            )
        )
        session.add(
            MatchPredictionLog(
                match_id=match_id,
                canonical_fixture_id=None,
                model_version="v5_phase7",
                calibration_method=None,
                home_probability=0.5,
                draw_probability=0.3,
                away_probability=0.2,
                confidence=0.5,
                created_at=match_date - timedelta(hours=1),
            )
        )
        session.add(
            MarketSnapshot(
                match_id=match_id,
                canonical_fixture_id=None,
                provider="the_odds_api",
                bookmaker="consensus",
                market_type="1X2",
                home_odds=2.0,
                draw_odds=3.4,
                away_odds=3.8,
                home_implied_prob_devigged=0.45,
                draw_implied_prob_devigged=0.28,
                away_implied_prob_devigged=0.27,
                is_closing_line=True,
                captured_at=match_date - timedelta(minutes=5),
                coherent=True,
                executable=False,
            )
        )
    await session.commit()


def _status_and_body(response) -> tuple[int, dict]:
    if hasattr(response, "status_code"):
        return response.status_code, json.loads(response.body)
    return 200, response


async def test_model_performance_503_below_floor(session: AsyncSession) -> None:
    from src.api.endpoints.performance import model_performance

    await _seed(session, n=3)
    response = await model_performance(league=None, window=180, db=session)
    status, body = _status_and_body(response)

    assert status == 503
    assert body["reason"] == "insufficient_settled_predictions"


async def test_model_performance_200_once_seeded(session: AsyncSession) -> None:
    from src.api.endpoints.performance import model_performance

    await _seed(session, n=10)
    response = await model_performance(league=None, window=180, db=session)
    status, body = _status_and_body(response)

    assert status == 200
    assert body["status"] == "OK"
    assert body["settled_predictions"] == 10
    assert body["walk_forward"]["skipped"] is False


async def test_model_performance_series_matches_the_chart_contract(session: AsyncSession) -> None:
    """The chart reads series[].{date,accuracy,rps,n_matches} plus current_accuracy
    and baseline_accuracy. Pin every one — an earlier revision returned a payload
    with none of them and the chart silently rendered an empty state forever."""
    from src.api.endpoints.performance import model_performance

    await _seed(session, n=12)
    response = await model_performance(league=None, window=180, db=session)
    status, body = _status_and_body(response)

    assert status == 200
    assert body["series"], "series must be non-empty when folds validated"
    for point in body["series"]:
        assert set(point) == {"date", "accuracy", "rps", "n_matches"}
        assert 0.0 <= point["accuracy"] <= 1.0
        assert 0.0 <= point["rps"] <= 1.0
        assert point["n_matches"] >= 1
    # One owner for the reference line — the client must not hardcode its own.
    assert body["baseline_accuracy"] == pytest.approx(1 / 3)
    assert 0.0 <= body["current_accuracy"] <= 1.0
    assert len(body["series"]) == body["walk_forward"]["n_splits"]


async def test_model_performance_league_filter_accepts_canonical_form(session: AsyncSession) -> None:
    from src.api.endpoints.performance import model_performance

    await _seed(session, n=10, league_id="EREDIVISIE")
    await _seed(session, n=10, league_id="EPL", base_date=datetime(2026, 9, 1, 15, 0))

    response = await model_performance(league="EREDIVISIE", window=180, db=session)
    status, body = _status_and_body(response)

    assert status == 200
    assert body["settled_predictions"] == 10  # only the EREDIVISIE rows counted


async def test_model_performance_league_filter_accepts_legacy_code_alias(session: AsyncSession) -> None:
    from src.api.endpoints.performance import model_performance

    await _seed(session, n=10, league_id="EREDIVISIE")
    await _seed(session, n=10, league_id="EPL", base_date=datetime(2026, 9, 1, 15, 0))

    response = await model_performance(league="DED", window=180, db=session)
    status, body = _status_and_body(response)

    assert status == 200
    assert body["settled_predictions"] == 10


async def test_model_performance_clv_skipped_when_no_closing_lines(session: AsyncSession) -> None:
    from src.api.endpoints.performance import model_performance

    await _seed(session, n=10)  # predictions + finished matches, zero closing lines
    response = await model_performance(league=None, window=180, db=session)
    status, body = _status_and_body(response)

    assert status == 200  # walk-forward has enough settled predictions
    assert body["clv"]["skipped"] is True
    assert body["clv"]["n"] == 0


async def test_model_performance_clv_computed_once_enough_closing_lines(session: AsyncSession) -> None:
    from src.api.endpoints.performance import model_performance

    await _seed_with_closing_lines(session, n=10, finished=True)
    response = await model_performance(league=None, window=180, db=session)
    status, body = _status_and_body(response)

    assert status == 200
    assert body["clv"]["skipped"] is False
    assert body["clv"]["n"] == 10


async def test_model_performance_clv_not_gated_by_walk_forward_floor(session: AsyncSession) -> None:
    """clv and walk_forward are independent data floors in the same response:
    enough captured closing lines but zero finished matches must still 503
    on walk-forward while clv itself reports a real, non-skipped result."""
    from src.api.endpoints.performance import model_performance

    await _seed_with_closing_lines(session, n=10, finished=False)
    response = await model_performance(league=None, window=180, db=session)
    status, body = _status_and_body(response)

    assert status == 503
    assert body["clv"]["skipped"] is False
    assert body["clv"]["n"] == 10


async def test_model_performance_summary_503_below_floor(session: AsyncSession) -> None:
    from src.api.endpoints.performance import model_performance_summary

    await _seed(session, n=2)
    response = await model_performance_summary(db=session)
    status, body = _status_and_body(response)

    assert status == 503
    assert body["reason"] == "insufficient_settled_predictions"
    # CLV has its own floor, independent of walk-forward's. The /performance page
    # reads it from this endpoint, so it must be present on the 503 body too —
    # otherwise the tile can only ever say "0 of 10" while the join is working.
    assert "clv" in body


async def test_model_performance_summary_200_once_seeded(session: AsyncSession) -> None:
    from src.api.endpoints.performance import model_performance_summary

    await _seed(session, n=10)
    response = await model_performance_summary(db=session)
    status, body = _status_and_body(response)

    assert status == 200
    assert body["status"] == "OK"
    assert body["total_settled"] == 10
    assert "rps_overall" in body
    # accuracy_overall is what the summary cards read; rps_overall alone left every
    # card showing an em-dash even with real settled data behind it.
    assert 0.0 <= body["accuracy_overall"] <= 1.0
    assert body["n_splits"] >= 1
    # _seed writes no closing lines, so CLV correctly skips — but the key must
    # still be there. The /performance tile reads `n` to show progress toward the
    # floor, and an absent key is indistinguishable from a zero join.
    assert body["clv"]["skipped"] is True
    assert body["clv"]["n"] == 0


async def test_model_performance_summary_reports_clv_once_closing_lines_exist(
    session: AsyncSession,
) -> None:
    """The summary endpoint feeds the /performance stat tiles, which had no CLV
    at all until this shipped — the value was computed on the sibling windowed
    route and never reached the page."""
    from src.api.endpoints.performance import model_performance_summary

    await _seed_with_closing_lines(session, n=10, finished=True)
    response = await model_performance_summary(db=session)
    status, body = _status_and_body(response)

    assert status == 200
    assert body["clv"]["skipped"] is False
    assert body["clv"]["n"] == 10


async def test_value_bet_scan_reads_only_fresh_persisted_actionable_rows(
    session: AsyncSession,
    monkeypatch,
) -> None:
    from src.api.endpoints.performance import value_bet_scan

    monkeypatch.setattr(
        "src.api.endpoints.performance._certified_value_generation",
        lambda: (True, "v5_phase7", "certified"),
    )
    now = datetime.now().replace(microsecond=0)
    session.add_all(
        [
            Match(
                id="fd-actionable",
                home_team_id="home",
                away_team_id="away",
                league_id="DED",
                match_date=now + timedelta(days=1),
                status="scheduled",
            ),
            MatchPredictionLog(
                match_id="fd-actionable",
                canonical_fixture_id=None,
                model_version="v5_phase7",
                calibration_method="isotonic",
                home_probability=0.5,
                draw_probability=0.3,
                away_probability=0.2,
                confidence=0.5,
                created_at=now - timedelta(minutes=2),
                payload={
                    "verdict": "ACTIONABLE",
                    "stake_permitted": True,
                    "partial_intelligence": False,
                    "staleness_available": True,
                    "staleness_seconds": 120,
                    "evidence_quality": {"critical_gaps": [], "conflicts": []},
                    "ensemble": {"confidence": 0.5},
                    "odds_edge": {
                        "market": "home",
                        "market_odds": 2.2,
                        "model_prob": 0.5,
                        "edge": 0.0455,
                    },
                },
            ),
            Match(
                id="fd-partial",
                home_team_id="home",
                away_team_id="away",
                league_id="DED",
                match_date=now + timedelta(days=1),
                status="scheduled",
            ),
            MatchPredictionLog(
                match_id="fd-partial",
                canonical_fixture_id=None,
                model_version="v5_phase7",
                home_probability=0.4,
                draw_probability=0.3,
                away_probability=0.3,
                created_at=now - timedelta(minutes=2),
                payload={
                    "verdict": "PARTIAL",
                    "stake_permitted": False,
                    "partial_intelligence": True,
                },
            ),
        ]
    )
    await session.commit()

    response = await value_bet_scan(days=7, limit=50, db=session)
    payload = response.model_dump()

    assert payload["total"] == 1
    assert payload["fixtures"][0]["match_id"] == "fd-actionable"
    assert payload["fixtures"][0]["edge_pct"] == pytest.approx(4.55)
    assert payload["source"] == "persisted_prediction_logs"


async def test_value_bet_scan_is_fail_closed_while_generation_unverified(
    monkeypatch,
) -> None:
    from unittest.mock import AsyncMock
    from src.api.endpoints import performance

    monkeypatch.setattr(
        performance,
        "_certified_value_generation",
        lambda: (False, None, "model_not_certified"),
    )
    db = AsyncMock()

    response = await performance.value_bet_scan(days=7, limit=50, db=db)
    payload = response.model_dump()

    assert payload["fixtures"] == []
    assert payload["total"] == 0
    assert payload["status"] == "RESEARCH_ONLY"
    assert payload["reason"] == "model_not_certified"
    assert payload["source"] == "certification_gate"
    db.execute.assert_not_awaited()
