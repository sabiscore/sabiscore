"""Accuracy evidence must never pool model generations.

`walk_forward_validate` scores whatever records it is handed. If those records
mix two model generations, the resulting accuracy/RPS describes a system that
never existed, and the pooled count inflates the sample size that gates
certification. Production held 7 `v5_phase7` + 6 `v6_phase8` predictions when
this was found, reported to `/health` as a single `settled_predictions_total`.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, Match
from src.db.models import MatchPredictionLog
from src.repositories.fixtures import get_settled_predictions

KICKOFF = datetime(2026, 8, 16, 15, 0, 0)


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _settled_match(session: AsyncSession, match_id: str, *, home: int, away: int) -> None:
    session.add(
        Match(
            id=match_id,
            league_id="EPL",
            home_team_id="t-home",
            away_team_id="t-away",
            match_date=KICKOFF,
            status="finished",
            home_score=home,
            away_score=away,
        )
    )
    await session.flush()


async def _log(
    session: AsyncSession,
    match_id: str,
    *,
    model_version: str,
    created_at: datetime,
    probs: tuple[float, float, float],
) -> None:
    session.add(
        MatchPredictionLog(
            match_id=match_id,
            model_version=model_version,
            created_at=created_at,
            home_probability=probs[0],
            draw_probability=probs[1],
            away_probability=probs[2],
        )
    )
    await session.flush()


@pytest.mark.asyncio
async def test_unscoped_query_still_pools_every_generation(session: AsyncSession) -> None:
    """The permissive default is preserved for ad-hoc research queries."""

    await _settled_match(session, "m-1", home=2, away=0)
    await _settled_match(session, "m-2", home=1, away=1)
    await _log(session, "m-1", model_version="v5_phase7", created_at=KICKOFF - timedelta(days=1), probs=(0.6, 0.2, 0.2))
    await _log(session, "m-2", model_version="v6_phase8", created_at=KICKOFF - timedelta(days=1), probs=(0.3, 0.4, 0.3))

    assert len(await get_settled_predictions(session)) == 2


@pytest.mark.asyncio
async def test_scoped_query_returns_only_the_requested_generation(session: AsyncSession) -> None:
    await _settled_match(session, "m-1", home=2, away=0)
    await _settled_match(session, "m-2", home=1, away=1)
    await _log(session, "m-1", model_version="v5_phase7", created_at=KICKOFF - timedelta(days=1), probs=(0.6, 0.2, 0.2))
    await _log(session, "m-2", model_version="v6_phase8", created_at=KICKOFF - timedelta(days=1), probs=(0.3, 0.4, 0.3))

    records = await get_settled_predictions(session, model_version="v5_phase7")
    assert len(records) == 1
    assert records[0]["probs"] == [0.6, 0.2, 0.2]


@pytest.mark.asyncio
async def test_newer_foreign_generation_does_not_hide_the_requested_one(
    session: AsyncSession,
) -> None:
    """The subquery subtlety, and the reason the filter cannot live only on the
    outer select.

    `latest_per_match` picks max(created_at) per match. Filtering only the outer
    select would first select the newer v6_phase8 row and then discard it,
    returning nothing for a match that holds a perfectly valid v5_phase7
    prediction. Production match `fd-564632` carries exactly this shape.
    """

    await _settled_match(session, "m-both", home=2, away=0)
    await _log(
        session,
        "m-both",
        model_version="v5_phase7",
        created_at=KICKOFF - timedelta(days=2),
        probs=(0.7, 0.2, 0.1),
    )
    await _log(
        session,
        "m-both",
        model_version="v6_phase8",
        created_at=KICKOFF - timedelta(days=1),  # newer, different generation
        probs=(0.1, 0.2, 0.7),
    )

    records = await get_settled_predictions(session, model_version="v5_phase7")
    assert len(records) == 1, "the newer foreign-generation row hid a valid record"
    assert records[0]["probs"] == [0.7, 0.2, 0.1]


@pytest.mark.asyncio
async def test_scoping_still_picks_the_latest_row_within_one_generation(
    session: AsyncSession,
) -> None:
    """Scoping must not break same-generation recency selection."""

    await _settled_match(session, "m-1", home=0, away=3)
    await _log(session, "m-1", model_version="v5_phase7", created_at=KICKOFF - timedelta(days=5), probs=(0.5, 0.3, 0.2))
    await _log(session, "m-1", model_version="v5_phase7", created_at=KICKOFF - timedelta(days=1), probs=(0.2, 0.2, 0.6))

    records = await get_settled_predictions(session, model_version="v5_phase7")
    assert len(records) == 1
    assert records[0]["probs"] == [0.2, 0.2, 0.6]
    assert records[0]["outcome"] == 2  # away win
