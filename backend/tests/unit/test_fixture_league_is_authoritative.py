"""A fixture-id request must take its competition from the fixture, not the caller.

`GET /matches/upcoming/{id}/full-analysis` declares `league: str = Query(default="EPL")`,
and `apps/web`'s proxy independently defaults the same parameter to `"EPL"`. Neither
fails closed, so a request that omits it analysed every fixture as English Premier
League: the wrong odds board (confirmed in production logs — an Eredivisie fixture
logged `Cache hit for live odds: EPL`), the wrong Elo and model artifact, and the
wrong league policy — EPL's kelly_cap 0.04 in place of Eredivisie's 0.025 and UCL's
0.02. The fixture row already records the answer.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, League, Match, Team
from src.services.upcoming_match_feature_service import UpcomingMatchFeatureProjector


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
    p = UpcomingMatchFeatureProjector()
    p._use_phase8 = False
    return p


async def _seed(session: AsyncSession, league_id: str | None) -> None:
    if league_id:
        session.add(League(id=league_id, name=league_id, country="NL"))
    session.add_all(
        [
            Team(id="team-home", name="SC Heerenveen", active=True),
            Team(id="team-away", name="AZ", active=True),
            Match(
                id="fd-558256",
                home_team_id="team-home",
                away_team_id="team-away",
                league_id=league_id,
                match_date=datetime(2026, 9, 6, 12, 30),
                status="scheduled",
            ),
        ]
    )
    await session.commit()


@pytest.mark.parametrize("caller_league", ["EPL", "epl", "La Liga"])
async def test_fixture_league_overrides_the_caller(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector, caller_league: str
) -> None:
    await _seed(session, "EREDIVISIE")
    result = await projector.build_live_feature_vector(
        match_id="fd-558256", league=caller_league, db=session
    )
    assert result["league"] == "EREDIVISIE", (
        f"caller passed {caller_league!r}; the fixture says EREDIVISIE and the fixture wins. "
        "A wrong league here selects the wrong odds board, Elo, artifact and kelly_cap."
    )


async def test_non_canonical_stored_league_is_normalized(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector
) -> None:
    """Guard the two-vocabulary trap: a display-form row must fold to the canonical id."""
    await _seed(session, "La Liga")
    result = await projector.build_live_feature_vector(
        match_id="fd-558256", league="EPL", db=session
    )
    assert result["league"] == "LA_LIGA"


async def test_missing_fixture_league_fails_closed(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector
) -> None:
    """A fixture-id request must not silently fall back to a caller-supplied league."""
    await _seed(session, None)

    with pytest.raises(ValueError, match="missing league_id"):
        await projector.build_live_feature_vector(
            match_id="fd-558256", league="SERIE_A", db=session
        )
