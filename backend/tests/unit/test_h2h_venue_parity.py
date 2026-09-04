"""The h2h/venue/market-interaction family: pure math, TeamHistory's window
discipline, and train/serve parity against live serving (docs/DEBT.md item 56,
PRODUCTION_EXECUTIVE_DIRECTIVE.md §2/§5 Phase 2).

Four things pinned here, mirroring test_xg_rolling_parity.py's structure for
the same reason that file exists:

1. ``derive_h2h_features``/``derive_home_venue_features``/
   ``derive_market_interaction_features`` — the pure functions BOTH
   ``scripts/train_on_real_matches.py``'s ``TeamHistory`` and
   ``UpcomingMatchFeatureProjector`` call, so train/serve parity is
   mechanical rather than asserted.
2. ``TeamHistory``'s own window discipline (H2H_WINDOW=10,
   HOME_VENUE_WINDOW=20) — new accumulator state this session added, not
   covered by any existing test.
3. The live serving queries (``_get_h2h_stats``/``_get_home_venue_stats``)
   exclude a meeting at or after kickoff and order most-recent-first
   regardless of insert order — same guarantees test_xg_rolling_parity.py
   already pins for the sibling xG family, on a genuinely different query.
4. The parity assertion itself: TeamHistory's accumulator and the live
   projector, fed the IDENTICAL match history, must agree EXACTLY (equality,
   not "both non-null") — and both sides must agree that a pair with no
   shared history is a gap, never a fabricated default.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, Match, Team
from src.models.feature_registry import (
    H2H_WINDOW,
    HOME_VENUE_WINDOW,
    derive_h2h_features,
    derive_home_venue_features,
    derive_market_interaction_features,
)
from src.services.upcoming_match_feature_service import UpcomingMatchFeatureProjector

# Not a package (pytest.ini excludes scripts/ from collection and pythonpath
# only covers src/) — same pattern as test_train_on_real_matches_elo.py.
_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import train_on_real_matches  # noqa: E402

# ---------------------------------------------------------------------------
# Part A — pure math, no DB
# ---------------------------------------------------------------------------


def test_derive_h2h_features_empty_is_none_not_zero() -> None:
    assert derive_h2h_features([]) is None


def test_derive_home_venue_features_empty_is_none_not_neutral() -> None:
    assert derive_home_venue_features([]) is None


def test_window_constants_pinned() -> None:
    assert H2H_WINDOW == 10
    assert HOME_VENUE_WINDOW == 20


def test_derive_h2h_features_perspective_flip_is_symmetric_and_opposite_sign() -> None:
    # Arsenal beat Chelsea twice, from Arsenal's home perspective.
    arsenal_home = derive_h2h_features([(2, 1), (3, 0)])
    # The IDENTICAL two meetings, scored from Chelsea's home perspective —
    # each entry's (gf, ga) flips.
    chelsea_home = derive_h2h_features([(1, 2), (0, 3)])
    assert arsenal_home == {
        "h2h_home_wins": 2.0, "h2h_away_wins": 0.0, "h2h_draws": 0.0,
        "h2h_matches": 2.0, "h2h_dominance": pytest.approx(1.0),
    }
    assert chelsea_home == {
        "h2h_home_wins": 0.0, "h2h_away_wins": 2.0, "h2h_draws": 0.0,
        "h2h_matches": 2.0, "h2h_dominance": pytest.approx(-1.0),
    }


def test_derive_home_venue_features_all_draws_gives_zero_loss_rate_and_advantage() -> None:
    # Losses computed by subtraction (total - wins - draws), matching
    # _get_home_venue_stats() exactly — an all-draw input is the case a
    # naive third counter could get wrong.
    result = derive_home_venue_features([(1, 1), (0, 0), (2, 2)])
    assert result == {
        "home_venue_win_rate": 0.0, "home_venue_draw_rate": 1.0,
        "home_venue_loss_rate": 0.0, "home_advantage_strength": 0.0,
    }


def test_derive_market_interaction_features_arithmetic() -> None:
    result = derive_market_interaction_features(
        market_prob_home=0.5,
        home_form_last5_home=1.5,
        home_venue_win_rate=0.6,
        h2h_dominance=0.2,
    )
    assert result == {
        "h2h_market_agreement": pytest.approx(0.2 * 0.5),
        "venue_market_combo": pytest.approx(0.6 * 0.5),
        "form_market_agreement_home": pytest.approx((1.5 / 3.0) * 0.5),
        "form_market_disagreement": pytest.approx(abs((1.5 / 3.0) - 0.5)),
    }


def test_derive_market_interaction_features_gates_each_key_independently() -> None:
    # Only h2h_dominance resolved -> only h2h_market_agreement is returned.
    assert derive_market_interaction_features(
        market_prob_home=0.5, h2h_dominance=0.4,
    ) == {"h2h_market_agreement": pytest.approx(0.2)}
    # Nothing resolved -> no interaction keys at all, never a value computed
    # from a mix of a real signal and a registry default.
    assert derive_market_interaction_features(market_prob_home=0.5) == {}


# ---------------------------------------------------------------------------
# Part B — TeamHistory's window discipline (new accumulator state, no DB)
# ---------------------------------------------------------------------------


def test_team_history_h2h_window_keeps_only_the_newest_10_meetings() -> None:
    hist = train_on_real_matches.TeamHistory()
    # 11 meetings, alternating host, strictly increasing margin so the
    # dropped (oldest) meeting is identifiable by its arithmetic effect.
    for i in range(11):
        home, away = ("home", "away") if i % 2 == 0 else ("away", "home")
        hist.record_match(home, away, i + 1, 0)  # home side of THIS meeting always wins
    result = hist.h2h("home", "away")
    assert result is not None
    assert result["h2h_matches"] == 10.0, "an 11th meeting must not widen the window past H2H_WINDOW"


def test_team_history_venue_window_keeps_only_the_newest_20_hosted_matches() -> None:
    hist = train_on_real_matches.TeamHistory()
    for i in range(21):
        hist.record_match("home", "away", 1, 0)  # "home" hosts every one of these
    result = hist.venue("home")
    assert result is not None
    assert result["home_venue_win_rate"] == 1.0
    # If the window were unbounded this would still read 1.0 (every match is
    # a win) — assert the COUNT the window actually kept, not just the rate.
    assert sum(len(v) for v in hist._home_venue.values()) == HOME_VENUE_WINDOW


# ---------------------------------------------------------------------------
# Part C — live serving guarantees (mirrors test_xg_rolling_parity.py's
# structure for _completed_matches_before, on the genuinely separate
# _get_h2h_stats/_get_home_venue_stats queries)
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


async def _seed_match(
    session: AsyncSession, *, match_id: str, home_id: str, away_id: str,
    days_before_kickoff: int, home_score: int, away_score: int, status: str = "finished",
) -> None:
    session.add(Match(
        id=match_id, home_team_id=home_id, away_team_id=away_id,
        match_date=KICKOFF - timedelta(days=days_before_kickoff),
        status=status, home_score=home_score, away_score=away_score,
    ))
    await session.commit()


async def test_get_h2h_stats_excludes_a_meeting_at_or_after_kickoff(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector,
) -> None:
    session.add_all([Team(id="home", name="Home", active=True), Team(id="away", name="Away", active=True)])
    await session.commit()
    session.add(Match(
        id="same-instant", home_team_id="home", away_team_id="away",
        match_date=KICKOFF, status="finished", home_score=2, away_score=0,
    ))
    await session.commit()

    result = await projector._get_h2h_stats("home", "away", session, KICKOFF)
    assert result is None


async def test_get_home_venue_stats_excludes_a_match_at_or_after_kickoff(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector,
) -> None:
    session.add_all([Team(id="home", name="Home", active=True), Team(id="away", name="Away", active=True)])
    await session.commit()
    session.add(Match(
        id="same-instant", home_team_id="home", away_team_id="away",
        match_date=KICKOFF, status="finished", home_score=2, away_score=0,
    ))
    await session.commit()

    result = await projector._get_home_venue_stats("home", session, KICKOFF)
    assert result is None


async def test_get_h2h_stats_orders_most_recent_first_regardless_of_insert_order(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector,
) -> None:
    session.add_all([Team(id="home", name="Home", active=True), Team(id="away", name="Away", active=True)])
    await session.commit()
    # Insert the OLDER meeting first, then the newer one — the previous xG
    # ORDER BY incident (DEBT.md item 56 Finding 5) was exactly this kind of
    # bug going undetected because nothing tested insert-order independence.
    await _seed_match(
        session, match_id="old", home_id="home", away_id="away",
        days_before_kickoff=20, home_score=0, away_score=3,
    )
    await _seed_match(
        session, match_id="new", home_id="home", away_id="away",
        days_before_kickoff=5, home_score=4, away_score=0,
    )

    result = await projector._get_h2h_stats("home", "away", session, KICKOFF, n=1)
    # LIMIT 1 ORDER BY match_date DESC must return only "new" (4-0), not
    # "old" (0-3) — if ordering were wrong or absent, this would flip sign.
    assert result == {
        "h2h_home_wins": 1.0, "h2h_away_wins": 0.0, "h2h_draws": 0.0,
        "h2h_matches": 1.0, "h2h_dominance": pytest.approx(1.0),
    }


# ---------------------------------------------------------------------------
# Part D — the parity assertion: TeamHistory vs live serving, identical input
# ---------------------------------------------------------------------------


async def test_h2h_parity_between_training_accumulator_and_live_serving(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector,
) -> None:
    session.add_all([Team(id="home", name="Home", active=True), Team(id="away", name="Away", active=True)])
    await session.commit()

    hist = train_on_real_matches.TeamHistory()
    # Meetings alternate which side hosted, so the perspective flip is
    # actually exercised, not just the trivial single-orientation case.
    meetings = [
        (40, "home", "away", 2, 1),
        (30, "away", "home", 0, 0),
        (20, "home", "away", 3, 1),
        (10, "away", "home", 1, 2),
    ]
    for i, (days_before, m_home, m_away, hg, ag) in enumerate(meetings):
        await _seed_match(
            session, match_id=f"h2h-{i}", home_id=m_home, away_id=m_away,
            days_before_kickoff=days_before, home_score=hg, away_score=ag,
        )
        hist.record_match(m_home, m_away, hg, ag)

    training = hist.h2h("home", "away")
    serving = await projector._get_h2h_stats("home", "away", session, KICKOFF)
    assert training is not None and serving is not None
    assert training == pytest.approx(serving)


async def test_venue_parity_between_training_accumulator_and_live_serving(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector,
) -> None:
    session.add_all([
        Team(id="home", name="Home", active=True),
        Team(id="opp1", name="Opp1", active=True),
        Team(id="opp2", name="Opp2", active=True),
    ])
    await session.commit()

    hist = train_on_real_matches.TeamHistory()
    # "home" hosts every one of these, against different opponents — venue
    # record is opponent-agnostic by definition.
    hosted = [(30, "opp1", 2, 0), (20, "opp2", 1, 1), (10, "opp1", 0, 2)]
    for i, (days_before, opponent, hg, ag) in enumerate(hosted):
        await _seed_match(
            session, match_id=f"venue-{i}", home_id="home", away_id=opponent,
            days_before_kickoff=days_before, home_score=hg, away_score=ag,
        )
        hist.record_match("home", opponent, hg, ag)

    training = hist.venue("home")
    serving = await projector._get_home_venue_stats("home", session, KICKOFF)
    assert training is not None and serving is not None
    assert training == pytest.approx(serving)


async def test_both_sides_agree_a_never_met_pair_is_a_gap_not_a_default(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector,
) -> None:
    session.add_all([Team(id="x", name="X", active=True), Team(id="y", name="Y", active=True)])
    await session.commit()

    hist = train_on_real_matches.TeamHistory()
    assert hist.h2h("x", "y") is None
    assert hist.venue("x") is None
    assert await projector._get_h2h_stats("x", "y", session, KICKOFF) is None
    assert await projector._get_home_venue_stats("x", session, KICKOFF) is None
