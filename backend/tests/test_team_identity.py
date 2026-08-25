"""WP-1 regression tests: resolve_team_id() must handle short-name vs
legal-name variants (D2a) via affix-stripping and reconcile_team() fallback,
while still failing closed on true nicknames and ambiguous names.
"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, League, Match, Team
from src.db.models import EloRatingSnapshot
from src.services.team_identity import resolve_team_id
from src.utils.season import canonical_season
from datetime import datetime


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _seed(session: AsyncSession, *names: str) -> None:
    session.add_all([Team(id=f"team-{i}", name=n, active=True) for i, n in enumerate(names)])
    await session.commit()


async def test_exact_match(session: AsyncSession) -> None:
    await _seed(session, "Arsenal", "Chelsea")
    assert await resolve_team_id("Arsenal", session) == "team-0"


async def test_case_insensitive_exact_match(session: AsyncSession) -> None:
    await _seed(session, "Arsenal", "Chelsea")
    assert await resolve_team_id("arsenal", session) == "team-0"


async def test_short_name_resolves_against_legal_name_suffix(session: AsyncSession) -> None:
    await _seed(session, "Arsenal FC", "Chelsea FC")
    assert await resolve_team_id("Arsenal", session) == "team-0"


async def test_legal_name_resolves_against_short_name(session: AsyncSession) -> None:
    await _seed(session, "Arsenal", "Chelsea")
    assert await resolve_team_id("Arsenal FC", session) == "team-0"


async def test_afc_prefix_resolves(session: AsyncSession) -> None:
    await _seed(session, "AFC Bournemouth", "Chelsea")
    assert await resolve_team_id("Bournemouth", session) == "team-0"


async def test_true_nickname_fails_closed(session: AsyncSession) -> None:
    await _seed(session, "Tottenham Hotspur", "Chelsea")
    # documented limitation (reconciliation.py docstring): nicknames need alias
    # resolution, not threshold tuning — this must stay unresolved, not guessed.
    assert await resolve_team_id("Spurs", session) is None


async def test_unrelated_name_fails_closed(session: AsyncSession) -> None:
    await _seed(session, "Arsenal", "Chelsea")
    assert await resolve_team_id("Some Nonexistent FC", session) is None


async def test_empty_name_fails_closed(session: AsyncSession) -> None:
    await _seed(session, "Arsenal")
    assert await resolve_team_id("", session) is None
    assert await resolve_team_id("   ", session) is None


async def test_no_teams_in_db_fails_closed(session: AsyncSession) -> None:
    assert await resolve_team_id("Arsenal", session) is None


def test_canonical_season_format_parity() -> None:
    # August match -> current/next year season
    assert canonical_season(datetime(2026, 8, 10)) == "2026/2027"
    # February match -> previous/current year season
    assert canonical_season(datetime(2027, 2, 15)) == "2026/2027"
    # boundary: July 1 flips to the new season
    assert canonical_season(datetime(2026, 7, 1)) == "2026/2027"
    assert canonical_season(datetime(2026, 6, 30)) == "2025/2026"


async def _seed_league(
    session: AsyncSession, league_id: str, *names: str
) -> None:
    """League-scoped seed with real Elo history, mirroring how fixture sync
    calls resolve_team_id(league_id=..., require_elo_history=True)."""
    session.add(League(id=league_id, name=league_id, country="test"))
    session.add_all(
        [
            Team(id=f"fdco-{league_id.lower()}-{i}", name=n, league_id=league_id, active=True)
            for i, n in enumerate(names)
        ]
    )
    await session.flush()
    for i, _ in enumerate(names):
        match_id = f"hist-{league_id.lower()}-{i}"
        match_date = datetime(2025, 9, 20, 15, 0)
        session.add(
            Match(
                id=match_id,
                league_id=league_id,
                home_team_id=f"fdco-{league_id.lower()}-{i}",
                away_team_id=f"fdco-{league_id.lower()}-{(i + 1) % len(names)}",
                match_date=match_date,
                season="2025/2026",
                status="finished",
                home_score=1,
                away_score=0,
            )
        )
        await session.flush()
        session.add(
            EloRatingSnapshot(
                match_id=match_id,
                team_id=f"fdco-{league_id.lower()}-{i}",
                pre_match_elo=1500.0,
                post_match_elo=1510.0,
                league=league_id,
                season="2025/2026",
                match_date=match_date,
                created_at=match_date,
            )
        )
    await session.commit()


# docs/DEBT.md item 39: the orphan-team repair manifest reported three
# BUNDESLIGA sides stuck on ORPHAN_NO_RESOLVER_MATCH. Two were audited alias
# gaps -- the historical corpus abbreviates the club, the live provider sends
# the full legal name, and reconcile_team() lands in REQUIRES_REVIEW (0.81 /
# 0.74) rather than auto-accepting. The third had no corpus entry at all.


async def test_eintracht_frankfurt_resolves_to_the_corpus_abbreviation(
    session: AsyncSession,
) -> None:
    await _seed_league(session, "BUNDESLIGA", "Ein Frankfurt", "Bayern Munich")
    assert (
        await resolve_team_id(
            "Eintracht Frankfurt",
            session,
            league_id="BUNDESLIGA",
            require_elo_history=True,
        )
        == "fdco-bundesliga-0"
    )


async def test_hamburger_sv_resolves_to_the_corpus_abbreviation(
    session: AsyncSession,
) -> None:
    await _seed_league(session, "BUNDESLIGA", "Hamburg", "Bayern Munich")
    assert (
        await resolve_team_id(
            "Hamburger SV",
            session,
            league_id="BUNDESLIGA",
            require_elo_history=True,
        )
        == "fdco-bundesliga-0"
    )


async def test_newly_promoted_club_absent_from_the_corpus_still_fails_closed(
    session: AsyncSession,
) -> None:
    """SV 07 Elversberg is the third stuck side and is NOT a bug: it appears in
    none of the seven committed Bundesliga seasons, so no Elo-bearing target
    exists. Adding aliases must not make an absent club resolve to a neighbour.
    """
    await _seed_league(session, "BUNDESLIGA", "Ein Frankfurt", "Hamburg", "Bayern Munich")
    assert (
        await resolve_team_id(
            "SV 07 Elversberg",
            session,
            league_id="BUNDESLIGA",
            require_elo_history=True,
        )
        is None
    )


async def test_alias_does_not_leak_across_leagues(session: AsyncSession) -> None:
    """_AUDITED_ALIASES is keyed on (league, identity_key). A Bundesliga alias
    must not fire for an identically-named club in another competition."""
    await _seed_league(session, "EPL", "Ein Frankfurt", "Arsenal")
    assert (
        await resolve_team_id(
            "Eintracht Frankfurt",
            session,
            league_id="EPL",
            require_elo_history=True,
        )
        is None
    )
