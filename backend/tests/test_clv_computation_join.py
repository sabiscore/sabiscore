"""Regression tests for repositories.fixtures.get_clv_records():

1. Joins the latest logged prediction per match to its latest captured
   closing line, on match_id — not canonical_fixture_id, which is hardcoded
   None on every write site today (see docs/adr/0004-clv-capture.md
   Addendum 2).
2. Does NOT require the match to be finished, unlike get_settled_predictions —
   a closing line exists as soon as clv_capture_service captures it near
   kickoff, independent of the eventual result.
3. Picks the latest row on both sides when duplicates exist.
4. Excludes non-closing-line snapshots and fixtures with no closing line at all.
5. league= filters via the Match join.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, Match
from src.db.models import MarketSnapshot, MatchPredictionLog
from src.repositories.fixtures import get_clv_records


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _seed_match(
    session: AsyncSession,
    match_id: str,
    *,
    match_date: datetime,
    league_id: str = "EPL",
    status: str = "scheduled",
) -> None:
    session.add(
        Match(
            id=match_id,
            home_team_id="team-home",
            away_team_id="team-away",
            league_id=league_id,
            match_date=match_date,
            status=status,
        )
    )
    await session.commit()


def _prediction(
    match_id: str, created_at: datetime, *, home: float = 0.5, draw: float = 0.3, away: float = 0.2
) -> MatchPredictionLog:
    return MatchPredictionLog(
        match_id=match_id,
        canonical_fixture_id=None,
        model_version="v5_phase7",
        calibration_method=None,
        home_probability=home,
        draw_probability=draw,
        away_probability=away,
        confidence=home,
        created_at=created_at,
    )


def _closing_snapshot(
    match_id: str,
    captured_at: datetime,
    *,
    home: float = 0.45,
    draw: float = 0.28,
    away: float = 0.27,
    is_closing_line: bool = True,
) -> MarketSnapshot:
    return MarketSnapshot(
        match_id=match_id,
        canonical_fixture_id=None,
        provider="the_odds_api",
        bookmaker="consensus",
        market_type="1X2",
        home_odds=round(1 / home, 4),
        draw_odds=round(1 / draw, 4),
        away_odds=round(1 / away, 4),
        home_implied_prob_devigged=home,
        draw_implied_prob_devigged=draw,
        away_implied_prob_devigged=away,
        is_closing_line=is_closing_line,
        captured_at=captured_at,
        coherent=True,
        executable=False,
    )


async def test_joins_latest_prediction_to_latest_closing_line(session: AsyncSession) -> None:
    match_date = datetime(2026, 8, 8, 15, 0)
    await _seed_match(session, "match-1", match_date=match_date)
    session.add(_prediction("match-1", match_date - timedelta(hours=2), home=0.55, draw=0.25, away=0.20))
    session.add(_closing_snapshot("match-1", match_date - timedelta(minutes=5), home=0.48, draw=0.27, away=0.25))
    await session.commit()

    records = await get_clv_records(session, model_version="v5_phase7")

    assert len(records) == 1
    assert records[0]["model_probs"] == pytest.approx([0.55, 0.25, 0.20])
    assert records[0]["closing_probs"] == pytest.approx([0.48, 0.27, 0.25])


async def test_does_not_require_match_to_be_finished(session: AsyncSession) -> None:
    """Unlike get_settled_predictions, a scheduled (not yet played) match with a
    captured closing line is included — CLV compares belief to market close,
    independent of the eventual result."""
    match_date = datetime(2026, 8, 10, 15, 0)
    await _seed_match(session, "match-scheduled", match_date=match_date, status="scheduled")
    session.add(_prediction("match-scheduled", match_date - timedelta(hours=1)))
    session.add(_closing_snapshot("match-scheduled", match_date - timedelta(minutes=5)))
    await session.commit()

    records = await get_clv_records(session, model_version="v5_phase7")
    assert len(records) == 1


async def test_picks_latest_prediction_when_match_has_two(session: AsyncSession) -> None:
    match_date = datetime(2026, 8, 8, 15, 0)
    await _seed_match(session, "match-1", match_date=match_date)
    session.add(_prediction("match-1", match_date - timedelta(days=2), home=0.10, draw=0.10, away=0.80))
    session.add(_prediction("match-1", match_date - timedelta(hours=1), home=0.60, draw=0.25, away=0.15))
    session.add(_closing_snapshot("match-1", match_date - timedelta(minutes=5)))
    await session.commit()

    records = await get_clv_records(session, model_version="v5_phase7")

    assert len(records) == 1
    assert records[0]["model_probs"] == pytest.approx([0.60, 0.25, 0.15])


async def test_excludes_prediction_captured_at_or_after_closing_line(
    session: AsyncSession,
) -> None:
    match_date = datetime(2026, 8, 8, 15, 0)
    await _seed_match(session, "match-temporal", match_date=match_date)
    closing_at = match_date - timedelta(minutes=5)
    session.add(
        _prediction(
            "match-temporal",
            closing_at - timedelta(minutes=1),
            home=0.55,
            draw=0.25,
            away=0.20,
        )
    )
    session.add(
        _prediction(
            "match-temporal",
            closing_at,
            home=0.98,
            draw=0.01,
            away=0.01,
        )
    )
    session.add(
        _prediction(
            "match-temporal",
            closing_at + timedelta(minutes=1),
            home=0.99,
            draw=0.005,
            away=0.005,
        )
    )
    session.add(_closing_snapshot("match-temporal", closing_at))
    await session.commit()

    records = await get_clv_records(session, model_version="v5_phase7")

    assert len(records) == 1
    assert records[0]["model_probs"] == pytest.approx([0.55, 0.25, 0.20])


async def test_picks_latest_closing_snapshot_when_two_exist(session: AsyncSession) -> None:
    """Defends the dedup subquery against the capture job ever writing two
    closing-line rows for one fixture (not prevented by the schema)."""
    match_date = datetime(2026, 8, 8, 15, 0)
    await _seed_match(session, "match-1", match_date=match_date)
    session.add(_prediction("match-1", match_date - timedelta(hours=1)))
    session.add(_closing_snapshot("match-1", match_date - timedelta(hours=1), home=0.40, draw=0.30, away=0.30))
    session.add(_closing_snapshot("match-1", match_date - timedelta(minutes=1), home=0.50, draw=0.25, away=0.25))
    await session.commit()

    records = await get_clv_records(session, model_version="v5_phase7")

    assert len(records) == 1
    assert records[0]["closing_probs"] == pytest.approx([0.50, 0.25, 0.25])


async def test_equal_timestamps_use_latest_ids_without_multiplying_join(
    session: AsyncSession,
) -> None:
    match_date = datetime(2026, 8, 8, 15, 0)
    prediction_at = match_date - timedelta(hours=1)
    closing_at = match_date - timedelta(minutes=5)
    await _seed_match(session, "match-tied", match_date=match_date)
    session.add(
        _prediction(
            "match-tied", prediction_at, home=0.40, draw=0.30, away=0.30
        )
    )
    session.add(
        _prediction(
            "match-tied", prediction_at, home=0.60, draw=0.25, away=0.15
        )
    )
    session.add(
        _closing_snapshot(
            "match-tied", closing_at, home=0.45, draw=0.30, away=0.25
        )
    )
    session.add(
        _closing_snapshot(
            "match-tied", closing_at, home=0.50, draw=0.25, away=0.25
        )
    )
    await session.commit()

    records = await get_clv_records(session, model_version="v5_phase7")

    assert len(records) == 1
    assert records[0]["model_probs"] == pytest.approx([0.60, 0.25, 0.15])
    assert records[0]["closing_probs"] == pytest.approx([0.50, 0.25, 0.25])


async def test_excludes_non_closing_line_snapshot(session: AsyncSession) -> None:
    match_date = datetime(2026, 8, 8, 15, 0)
    await _seed_match(session, "match-1", match_date=match_date)
    session.add(_prediction("match-1", match_date - timedelta(hours=1)))
    session.add(_closing_snapshot("match-1", match_date - timedelta(minutes=5), is_closing_line=False))
    await session.commit()

    records = await get_clv_records(session, model_version="v5_phase7")
    assert records == []


async def test_excludes_fixture_with_no_closing_line_at_all(session: AsyncSession) -> None:
    match_date = datetime(2026, 8, 8, 15, 0)
    await _seed_match(session, "match-1", match_date=match_date)
    session.add(_prediction("match-1", match_date - timedelta(hours=1)))
    await session.commit()

    records = await get_clv_records(session, model_version="v5_phase7")
    assert records == []


async def test_league_filter_narrows_via_match_join(session: AsyncSession) -> None:
    match_date = datetime(2026, 8, 8, 15, 0)
    await _seed_match(session, "match-epl", match_date=match_date, league_id="EPL")
    session.add(_prediction("match-epl", match_date - timedelta(hours=1)))
    session.add(_closing_snapshot("match-epl", match_date - timedelta(minutes=5)))

    await _seed_match(session, "match-ded", match_date=match_date, league_id="DED")
    session.add(_prediction("match-ded", match_date - timedelta(hours=1)))
    session.add(_closing_snapshot("match-ded", match_date - timedelta(minutes=5)))
    await session.commit()

    records = await get_clv_records(
        session, model_version="v5_phase7", league="EPL"
    )
    assert len(records) == 1
