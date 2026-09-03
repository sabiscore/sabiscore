"""The xG candidate family: pure rolling math, its leak boundary, and the ORDER BY fix.

Three things pinned here, all opened by DEBT.md item 56 Finding 5:

1. ``rolling_xg_mean`` / ``derive_xg_rolling_features`` — the pure functions
   ``scripts/measure_xg_feature_ate.py`` and
   ``UpcomingMatchFeatureProjector.project_xg_rolling_features`` both call, so
   train/serve parity is mechanical rather than asserted.
2. ``_get_team_xg_series`` actually orders by recency. Its predecessor
   (``_get_team_xg``) issued ``SELECT ... WHERE match_id IN (...)`` with no
   ``ORDER BY`` while its caller took ``[:5]`` — latent only because
   ``match_stats`` has never held a row in production.
3. ``project_xg_rolling_features`` returns None (a DATA_GAP), never a
   fabricated 0.0, whenever either side lacks the minimum rolling history.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, Match, MatchStats, Team
from src.models.feature_registry import (
    XG_ROLLING_MIN_PERIODS,
    XG_ROLLING_WINDOW,
    derive_xg_rolling_features,
    rolling_xg_mean,
)
from src.services.upcoming_match_feature_service import UpcomingMatchFeatureProjector

# ---------------------------------------------------------------------------
# Pure math — no DB involved
# ---------------------------------------------------------------------------


def test_rolling_xg_mean_below_min_periods_is_none_not_zero() -> None:
    assert XG_ROLLING_MIN_PERIODS == 3
    assert rolling_xg_mean([1.4, 1.6]) is None  # only 2 observations
    assert rolling_xg_mean([]) is None
    assert rolling_xg_mean([None, None]) is None  # Nones don't count as observed


def test_rolling_xg_mean_uses_at_most_the_window() -> None:
    assert XG_ROLLING_WINDOW == 5
    # 6 observations supplied, most-recent-first; the 6th must be ignored.
    values = [2.0, 2.0, 2.0, 2.0, 2.0, 99.0]
    assert rolling_xg_mean(values) == pytest.approx(2.0)


def test_rolling_xg_mean_skips_none_but_keeps_position_semantics() -> None:
    # A None inside the window is dropped from the average, not treated as 0.
    assert rolling_xg_mean([1.0, None, 2.0, 3.0]) == pytest.approx(2.0)


def test_derive_xg_rolling_features_is_none_if_any_side_is_none() -> None:
    assert derive_xg_rolling_features(
        home_xg_for=1.5, home_xg_against=1.0, away_xg_for=None, away_xg_against=1.2
    ) is None


def test_derive_xg_rolling_features_arithmetic() -> None:
    result = derive_xg_rolling_features(
        home_xg_for=1.8, home_xg_against=1.0, away_xg_for=1.2, away_xg_against=1.4
    )
    assert result == {
        "xg_differential": pytest.approx((1.8 - 1.0) - (1.2 - 1.4)),
        "xg_attack_diff": pytest.approx(1.8 - 1.2),
        "xg_defense_diff": pytest.approx(1.4 - 1.0),
    }


# ---------------------------------------------------------------------------
# DB-backed: leak boundary + ordering
# ---------------------------------------------------------------------------


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def projector() -> UpcomingMatchFeatureProjector:
    return UpcomingMatchFeatureProjector()


KICKOFF = datetime(2026, 1, 1, 15, 0)


async def _seed_match_with_xg(
    session: AsyncSession,
    *,
    match_id: str,
    home_id: str,
    away_id: str,
    days_before_kickoff: int,
    home_xg: float,
    away_xg: float,
) -> None:
    session.add(
        Match(
            id=match_id,
            home_team_id=home_id,
            away_team_id=away_id,
            match_date=KICKOFF - timedelta(days=days_before_kickoff),
            status="finished",
            home_score=1,
            away_score=1,
        )
    )
    session.add_all(
        [
            MatchStats(match_id=match_id, team_id=home_id, expected_goals=home_xg),
            MatchStats(match_id=match_id, team_id=away_id, expected_goals=away_xg),
        ]
    )
    await session.commit()


async def test_get_team_xg_series_orders_most_recent_first_regardless_of_insert_order(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector
) -> None:
    """The ORDER BY fix: insert an OLD match after a RECENT one and confirm
    the series still comes back newest-first — the previous implementation's
    ``WHERE match_id IN (...)`` had no ordering guarantee at all.
    """
    session.add_all([Team(id="home", name="Home", active=True), Team(id="away", name="Away", active=True)])
    await session.commit()

    # Insert the OLDER match first, then the newer one — deliberately the
    # reverse of the order a correct ORDER BY match_date DESC must produce.
    await _seed_match_with_xg(
        session, match_id="old", home_id="home", away_id="away",
        days_before_kickoff=10, home_xg=1.0, away_xg=1.0,
    )
    await _seed_match_with_xg(
        session, match_id="new", home_id="home", away_id="away",
        days_before_kickoff=3, home_xg=2.0, away_xg=2.0,
    )

    matches = await projector._completed_matches_before("home", session, KICKOFF, 20)
    assert [m.id for m in matches] == ["new", "old"], (
        "_completed_matches_before must return most-recent-first"
    )

    series = await projector._get_team_xg_series("home", session, matches)
    assert series == [(2.0, 2.0), (1.0, 1.0)], (
        "xG series must follow the caller-supplied (already-ordered) match list, "
        "not database insertion or physical row order"
    )


async def test_completed_matches_before_excludes_matches_on_or_after_kickoff(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector
) -> None:
    session.add_all([Team(id="home", name="Home", active=True), Team(id="away", name="Away", active=True)])
    await session.commit()
    # A match at exactly kickoff time must not leak into pre-match features.
    session.add(Match(
        id="same-instant", home_team_id="home", away_team_id="away",
        match_date=KICKOFF, status="finished", home_score=1, away_score=0,
    ))
    await session.commit()

    matches = await projector._completed_matches_before("home", session, KICKOFF, 20)
    assert matches == []


async def test_completed_matches_before_excludes_unfinished_matches(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector
) -> None:
    session.add_all([Team(id="home", name="Home", active=True), Team(id="away", name="Away", active=True)])
    session.add(Match(
        id="scheduled", home_team_id="home", away_team_id="away",
        match_date=KICKOFF - timedelta(days=1), status="scheduled",
    ))
    await session.commit()

    matches = await projector._completed_matches_before("home", session, KICKOFF, 20)
    assert matches == []


async def test_project_xg_rolling_features_is_none_below_cold_start_floor(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector
) -> None:
    session.add_all([Team(id="home", name="Home", active=True), Team(id="away", name="Away", active=True)])
    await session.commit()
    # Only 2 prior matches for "home" — below XG_ROLLING_MIN_PERIODS (3).
    for i in range(2):
        await _seed_match_with_xg(
            session, match_id=f"h{i}", home_id="home", away_id="away",
            days_before_kickoff=10 - i, home_xg=1.5, away_xg=1.0,
        )

    result = await projector.project_xg_rolling_features(
        home_team_id="home", away_team_id="away", kickoff=KICKOFF, db=session,
    )
    assert result is None, "below the cold-start floor must be a DATA_GAP, not a fabricated value"


async def test_project_xg_rolling_features_computes_once_both_sides_have_history(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector
) -> None:
    session.add_all([
        Team(id="home", name="Home", active=True),
        Team(id="away", name="Away", active=True),
        Team(id="opp", name="Opp", active=True),
    ])
    await session.commit()

    # 3 matches each for home and away, against a shared third team so xG-for
    # and xG-against are both populated on both sides.
    for i in range(3):
        await _seed_match_with_xg(
            session, match_id=f"home-hist-{i}", home_id="home", away_id="opp",
            days_before_kickoff=15 - i, home_xg=1.8, away_xg=1.0,
        )
    for i in range(3):
        await _seed_match_with_xg(
            session, match_id=f"away-hist-{i}", home_id="opp", away_id="away",
            days_before_kickoff=12 - i, home_xg=1.3, away_xg=1.1,
        )

    result = await projector.project_xg_rolling_features(
        home_team_id="home", away_team_id="away", kickoff=KICKOFF, db=session,
    )
    assert result is not None
    # home: xg_for=1.8, xg_against=1.0 (rolling mean of 3 identical matches).
    # away: xg_for=1.1, xg_against=1.3.
    assert result["xg_differential"] == pytest.approx((1.8 - 1.0) - (1.1 - 1.3))
    assert result["xg_attack_diff"] == pytest.approx(1.8 - 1.1)
    assert result["xg_defense_diff"] == pytest.approx(1.3 - 1.0)
