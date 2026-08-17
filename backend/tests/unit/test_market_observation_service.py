"""Regression coverage for deterministic market observation lifecycle writes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, League, Match, OddsHistory, Team
from src.db.models import MarketSnapshot
from src.services.market_observation_service import (
    POST_KICKOFF_REJECTED,
    PRE_MATCH_CLOSING,
    PRE_MATCH_INTERMEDIATE,
    PRE_MATCH_OPENING,
    persist_market_board,
    utc_naive,
)


@pytest.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield session_factory
    await engine.dispose()


async def _seed_fixture(
    factory,
    *,
    match_id: str = "fd-100",
    kickoff: datetime,
    league_id: str = "EPL",
    home_id: str = "team-home",
    home_name: str = "Arsenal FC",
    away_id: str = "team-away",
    away_name: str = "Liverpool FC",
) -> None:
    async with factory() as session:
        if await session.get(League, league_id) is None:
            session.add(League(id=league_id, name=league_id, country="test"))
        if await session.get(Team, home_id) is None:
            session.add(Team(id=home_id, name=home_name, league_id=league_id))
        if await session.get(Team, away_id) is None:
            session.add(Team(id=away_id, name=away_name, league_id=league_id))
        session.add(
            Match(
                id=match_id,
                league_id=league_id,
                home_team_id=home_id,
                away_team_id=away_id,
                match_date=kickoff,
                season="2026",
                status="scheduled",
            )
        )
        await session.commit()


def _record(
    *,
    event_id: str = "odds-event-1",
    kickoff: datetime,
    home_team: str = "Arsenal",
    away_team: str = "Liverpool",
    home: float = 2.0,
    draw: float = 3.5,
    away: float = 4.0,
    bookmaker: str = "pinnacle",
) -> dict:
    return {
        "provider": "the_odds_api",
        "provider_event_id": event_id,
        "provider_event_timestamp": kickoff.replace(tzinfo=timezone.utc).isoformat(),
        "home_team": home_team,
        "away_team": away_team,
        "bookmaker": bookmaker,
        "bookmaker_last_update": None,
        "home_odds": home,
        "draw_odds": draw,
        "away_odds": away,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "coherent": True,
        "executable": True,
    }


async def _rows(factory):
    async with factory() as session:
        history = (
            (await session.execute(select(OddsHistory).order_by(OddsHistory.id)))
            .scalars()
            .all()
        )
        snapshots = (
            (await session.execute(select(MarketSnapshot).order_by(MarketSnapshot.id)))
            .scalars()
            .all()
        )
    return history, snapshots


async def test_first_real_pre_match_observation_is_opening(factory) -> None:
    kickoff = datetime(2026, 8, 20, 18, 0)
    observed = kickoff - timedelta(minutes=30)
    await _seed_fixture(factory, kickoff=kickoff)

    async with factory() as session:
        result = await persist_market_board(
            session, league="EPL", records=[_record(kickoff=kickoff)], observed_at=observed
        )
        await session.commit()

    assert result.opening == 1
    assert result.closing == 0
    history, snapshots = await _rows(factory)
    assert len(history) == 1
    assert history[0].market_type == "match_odds"
    assert len(snapshots) == 1
    assert snapshots[0].is_closing_line is False
    assert snapshots[0].provenance["evidence_class"] == PRE_MATCH_OPENING
    assert snapshots[0].provenance["opening_semantics"] == "first_observed_by_sabiscore"


async def test_changed_observation_is_intermediate_and_identical_repeat_dedupes(factory) -> None:
    kickoff = datetime(2026, 8, 20, 18, 0)
    await _seed_fixture(factory, kickoff=kickoff)

    async with factory() as session:
        await persist_market_board(
            session,
            league="EPL",
            records=[_record(kickoff=kickoff)],
            observed_at=kickoff - timedelta(minutes=30),
        )
        changed = await persist_market_board(
            session,
            league="EPL",
            records=[_record(kickoff=kickoff, home=1.95, draw=3.6, away=4.1)],
            observed_at=kickoff - timedelta(minutes=10),
        )
        duplicate = await persist_market_board(
            session,
            league="EPL",
            records=[_record(kickoff=kickoff, home=1.95, draw=3.6, away=4.1)],
            observed_at=kickoff - timedelta(minutes=8),
        )
        await session.commit()

    assert changed.intermediate == 1
    assert duplicate.deduped == 1
    history, snapshots = await _rows(factory)
    assert len(history) == 2
    assert len(snapshots) == 2
    assert snapshots[-1].provenance["evidence_class"] == PRE_MATCH_INTERMEDIATE


async def test_unchanged_price_inside_closing_window_still_writes_fresh_close(factory) -> None:
    kickoff = datetime(2026, 8, 20, 18, 0)
    await _seed_fixture(factory, kickoff=kickoff)

    async with factory() as session:
        await persist_market_board(
            session,
            league="EPL",
            records=[_record(kickoff=kickoff)],
            observed_at=kickoff - timedelta(minutes=30),
        )
        closing = await persist_market_board(
            session,
            league="EPL",
            records=[_record(kickoff=kickoff)],
            observed_at=kickoff - timedelta(minutes=4),
        )
        await session.commit()

    assert closing.closing == 1
    history, snapshots = await _rows(factory)
    assert len(history) == 2
    assert len(snapshots) == 2
    assert snapshots[-1].is_closing_line is True
    assert snapshots[-1].captured_at == kickoff - timedelta(minutes=4)
    assert snapshots[-1].provenance["evidence_class"] == PRE_MATCH_CLOSING


async def test_later_closing_supersedes_all_earlier_current_closings(factory) -> None:
    kickoff = datetime(2026, 8, 20, 18, 0)
    await _seed_fixture(factory, kickoff=kickoff)

    async with factory() as session:
        await persist_market_board(
            session,
            league="EPL",
            records=[_record(kickoff=kickoff)],
            observed_at=kickoff - timedelta(minutes=4),
        )
        await persist_market_board(
            session,
            league="EPL",
            records=[_record(kickoff=kickoff, home=1.9, draw=3.7, away=4.2)],
            observed_at=kickoff - timedelta(minutes=1),
        )
        await session.commit()

    _history, snapshots = await _rows(factory)
    current = [row for row in snapshots if row.is_closing_line]
    superseded = [
        row
        for row in snapshots
        if (row.provenance or {}).get("evidence_class") == "PRE_MATCH_CLOSING_SUPERSEDED"
    ]
    assert len(current) == 1
    assert current[0].captured_at == kickoff - timedelta(minutes=1)
    assert current[0].provenance["evidence_class"] == PRE_MATCH_CLOSING
    assert len(superseded) == 1


async def test_first_observation_inside_closing_window_does_not_fabricate_opening(factory) -> None:
    kickoff = datetime(2026, 8, 20, 18, 0)
    await _seed_fixture(factory, kickoff=kickoff)

    async with factory() as session:
        result = await persist_market_board(
            session,
            league="EPL",
            records=[_record(kickoff=kickoff)],
            observed_at=kickoff - timedelta(minutes=4),
        )
        await session.commit()

    assert result.opening == 0
    assert result.closing == 1
    _history, snapshots = await _rows(factory)
    assert not any(
        (snapshot.provenance or {}).get("evidence_class") == PRE_MATCH_OPENING
        for snapshot in snapshots
    )


@pytest.mark.parametrize("offset", [timedelta(0), timedelta(seconds=1)])
async def test_kickoff_equality_and_post_kickoff_are_rejected(factory, offset) -> None:
    kickoff = datetime(2026, 8, 20, 18, 0)
    await _seed_fixture(factory, kickoff=kickoff)

    async with factory() as session:
        result = await persist_market_board(
            session,
            league="EPL",
            records=[_record(kickoff=kickoff)],
            observed_at=kickoff + offset,
        )
        await session.commit()

    assert result.rejected_post_kickoff == 1
    history, snapshots = await _rows(factory)
    assert history == []
    assert snapshots == []


def test_utc_naive_preserves_instant_for_aware_provider_timestamp() -> None:
    plus_one = timezone(timedelta(hours=1))
    source = datetime(2026, 8, 20, 19, 0, tzinfo=plus_one)
    assert utc_naive(source) == datetime(2026, 8, 20, 18, 0)


async def test_swapped_team_orientation_fails_closed(factory) -> None:
    kickoff = datetime(2026, 8, 20, 18, 0)
    await _seed_fixture(factory, kickoff=kickoff)

    async with factory() as session:
        result = await persist_market_board(
            session,
            league="EPL",
            records=[_record(kickoff=kickoff, home_team="Liverpool", away_team="Arsenal")],
            observed_at=kickoff - timedelta(minutes=30),
        )
        await session.commit()

    assert result.unmatched == 1
    history, snapshots = await _rows(factory)
    assert history == []
    assert snapshots == []


async def test_same_team_candidates_within_tolerance_are_ambiguous(factory) -> None:
    kickoff = datetime(2026, 8, 20, 18, 0)
    await _seed_fixture(factory, match_id="fd-100", kickoff=kickoff)
    await _seed_fixture(
        factory,
        match_id="fd-101",
        kickoff=kickoff + timedelta(minutes=2),
        home_id="team-home-2",
        away_id="team-away-2",
    )

    async with factory() as session:
        result = await persist_market_board(
            session,
            league="EPL",
            records=[_record(kickoff=kickoff)],
            observed_at=kickoff - timedelta(minutes=30),
        )
        await session.commit()

    assert result.ambiguous == 1
    history, snapshots = await _rows(factory)
    assert history == []
    assert snapshots == []


async def test_one_observation_failure_is_savepoint_isolated(factory) -> None:
    kickoff = datetime(2026, 8, 20, 18, 0)
    await _seed_fixture(factory, match_id="fd-100", kickoff=kickoff)
    await _seed_fixture(
        factory,
        match_id="fd-200",
        kickoff=kickoff + timedelta(minutes=20),
        home_id="team-home-200",
        home_name="Chelsea FC",
        away_id="team-away-200",
        away_name="Everton FC",
    )
    records = [
        _record(event_id="event-a", kickoff=kickoff),
        _record(
            event_id="event-b",
            kickoff=kickoff + timedelta(minutes=20),
            home_team="Chelsea",
            away_team="Everton",
        ),
    ]

    from src.services import market_observation_service

    original = market_observation_service._persist_record
    calls = 0

    async def flaky(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("isolated write failure")
        return await original(*args, **kwargs)

    async with factory() as session:
        with patch.object(market_observation_service, "_persist_record", new=flaky):
            result = await persist_market_board(
                session,
                league="EPL",
                records=records,
                observed_at=kickoff - timedelta(minutes=30),
            )
        await session.commit()

    assert result.write_errors == 1
    assert result.opening == 1
    history, snapshots = await _rows(factory)
    assert len(history) == 1
    assert len(snapshots) == 1


def test_post_kickoff_constant_is_explicit() -> None:
    assert POST_KICKOFF_REJECTED == "POST_KICKOFF_REJECTED"
    assert PRE_MATCH_INTERMEDIATE == "PRE_MATCH_INTERMEDIATE"
