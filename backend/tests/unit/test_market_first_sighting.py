"""Directive v10 U6: the first price SabiScore saw, for the counter-case.

Same fixture and same bookmaker only: a "move" measured across two books is not
a price move. It is the first sighting, never the opening line: nothing here
observes when a market opened.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.api.endpoints.full_analysis import _first_sighting
from src.db.models import Base, MarketSnapshot
from src.schemas.full_analysis import FullMatchMarketResponse

KICKOFF = datetime(2026, 10, 9, 18, 0)


@pytest.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


def _snapshot(*, bookmaker: str, captured_at: datetime, home: float) -> MarketSnapshot:
    return MarketSnapshot(
        match_id="fd-558881",
        provider="the_odds_api",
        bookmaker=bookmaker,
        market_type="1X2",
        home_odds=home,
        draw_odds=7.36,
        away_odds=8.65,
        is_closing_line=False,
        captured_at=captured_at,
        coherent=True,
        executable=True,
    )


async def _seed(factory, *rows: MarketSnapshot) -> None:
    async with factory() as session:
        session.add_all(rows)
        await session.commit()


async def test_returns_the_earliest_pre_kickoff_price_from_the_same_bookmaker(factory):
    await _seed(
        factory,
        _snapshot(bookmaker="pinnacle", captured_at=KICKOFF - timedelta(hours=2), home=1.30),
        _snapshot(bookmaker="pinnacle", captured_at=KICKOFF - timedelta(hours=5), home=1.28),
        # Earlier still, but another book: never compared across books.
        _snapshot(bookmaker="betclic", captured_at=KICKOFF - timedelta(hours=9), home=1.20),
        # After kickoff: not a pre-match price.
        _snapshot(bookmaker="pinnacle", captured_at=KICKOFF + timedelta(minutes=1), home=1.10),
    )
    async with factory() as session:
        seen = await _first_sighting(
            session,
            match_id="fd-558881",
            bookmaker="pinnacle",
            kickoff=KICKOFF.replace(tzinfo=timezone.utc),
        )

    assert seen == {
        "bookmaker": "pinnacle",
        "captured_at": (KICKOFF - timedelta(hours=5)).replace(tzinfo=timezone.utc).isoformat(),
        "home_win": 1.28,
        "draw": 7.36,
        "away_win": 8.65,
    }


@pytest.mark.parametrize(
    ("bookmaker", "kickoff"),
    [(None, KICKOFF), ("pinnacle", None), ("williamhill", KICKOFF)],
)
async def test_nothing_is_published_when_the_comparison_cannot_be_made(factory, bookmaker, kickoff):
    await _seed(
        factory,
        _snapshot(bookmaker="pinnacle", captured_at=KICKOFF - timedelta(hours=5), home=1.28),
    )
    async with factory() as session:
        seen = await _first_sighting(
            session, match_id="fd-558881", bookmaker=bookmaker, kickoff=kickoff
        )

    assert seen is None


def test_the_market_schema_carries_the_first_sighting():
    outcome = {"implied": 0.5, "fair": 0.48, "model_prob": None, "edge": None, "expected_value": None}
    market = FullMatchMarketResponse(
        devig_method="proportional",
        overround=1.05,
        evaluable=False,
        outcomes=[
            {"outcome": name, "odds": 2.0, **outcome} for name in ("home_win", "draw", "away_win")
        ],
        first_seen={
            "bookmaker": "pinnacle",
            "captured_at": "2026-10-09T13:00:00+00:00",
            "home_win": 1.28,
            "draw": 7.36,
            "away_win": 8.65,
        },
    )

    assert market.model_dump()["first_seen"]["home_win"] == 1.28
