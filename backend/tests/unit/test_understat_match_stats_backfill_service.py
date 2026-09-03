"""docs/DEBT.md item 56: the Class C Understat -> ``match_stats`` xG executor.

These run on SQLite, so the PostgreSQL lock acquisition is bypassed by calling
``apply_understat_match_stats_backfill`` through a patched lock helper — the
same arrangement, for the same reason, as
``test_orphan_team_rebind_service.py``. The lock path itself is asserted
separately (it must *refuse* a non-PostgreSQL bind); everything else worth
testing — digest verification, the two-rows-per-fixture shape, idempotency
without a unique constraint, the refusal to overwrite a differing value, and
the row-delta postcondition — is dialect-independent.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, Match, MatchStats, Team
from src.db.models import EloRatingSnapshot
from src.services.understat_match_stats_backfill_service import (
    acquire_match_stats_backfill_locks,
    apply_understat_match_stats_backfill,
)
from src.services.understat_match_stats_reconciliation_service import (
    build_understat_match_stats_manifest,
)

LEAGUE = "EPL"
KICKOFF = datetime(2024, 8, 16, 19, 0)
HOME_XG = 1.75
AWAY_XG = 0.92


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as value:
        yield value
    await engine.dispose()


async def _seed_team_with_history(
    session: AsyncSession,
    *,
    team_id: str,
    name: str,
    opponent_id: str,
    match_date: datetime,
) -> None:
    """A team with a settled match + Elo snapshot — ``resolve_team_id``'s
    ``require_elo_history=True`` floor."""
    session.add(Team(id=team_id, name=name, league_id=LEAGUE, active=True))
    await session.flush()
    match_id = f"seed-{team_id}"
    session.add(
        Match(
            id=match_id,
            league_id=LEAGUE,
            home_team_id=team_id,
            away_team_id=opponent_id,
            match_date=match_date,
            season="2023/2024",
            status="finished",
            home_score=1,
            away_score=0,
        )
    )
    await session.flush()
    session.add(
        EloRatingSnapshot(
            match_id=match_id,
            team_id=team_id,
            pre_match_elo=1500.0,
            post_match_elo=1510.0,
            league=LEAGUE,
            season="2023/2024",
            match_date=match_date,
            created_at=match_date,
        )
    )


def _write_corpus(tmp_path: Path, rows: list[dict]) -> Path:
    sources_dir = tmp_path / "v4_sources"
    sources_dir.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_parquet(sources_dir / "understat_matches_epl_2024.parquet")
    return sources_dir


async def _seed_reconcilable_fixture(session: AsyncSession, tmp_path: Path) -> Path:
    """One corpus row that resolves cleanly onto one finished ``Match``."""
    prior = KICKOFF - timedelta(days=30)
    await _seed_team_with_history(
        session, team_id="team-arsenal", name="Arsenal", opponent_id="team-chelsea",
        match_date=prior,
    )
    await _seed_team_with_history(
        session, team_id="team-chelsea", name="Chelsea", opponent_id="team-arsenal",
        match_date=prior,
    )
    session.add(
        Match(
            id="match-target",
            league_id=LEAGUE,
            home_team_id="team-arsenal",
            away_team_id="team-chelsea",
            match_date=KICKOFF,
            season="2024/2025",
            status="finished",
            home_score=2,
            away_score=1,
        )
    )
    await session.commit()
    return _write_corpus(
        tmp_path,
        [
            {
                "home_team": "Arsenal",
                "away_team": "Chelsea",
                "date": KICKOFF,
                "home_xg": HOME_XG,
                "away_xg": AWAY_XG,
                "has_data": True,
            }
        ],
    )


async def _noop() -> None:
    return None


async def _apply(session: AsyncSession, sha: str, sources_dir: Path, **kwargs):
    """Invoke the executor with the PostgreSQL-only lock step neutralised."""
    with patch(
        "src.services.understat_match_stats_backfill_service"
        ".acquire_match_stats_backfill_locks",
        new=lambda *a, **k: _noop(),
    ):
        return await apply_understat_match_stats_backfill(
            session,
            expected_manifest_sha256=sha,
            sources_dir=sources_dir,
            **kwargs,
        )


async def _stats_rows(session: AsyncSession) -> list[tuple[str, str, float]]:
    rows = (
        await session.execute(
            select(MatchStats.match_id, MatchStats.team_id, MatchStats.expected_goals)
        )
    ).all()
    return sorted((str(m), str(t), x) for m, t, x in rows)


# ---------------------------------------------------------------------------
# The write itself
# ---------------------------------------------------------------------------


async def test_writes_two_rows_per_fixture_one_per_side(
    session: AsyncSession, tmp_path: Path
) -> None:
    sources_dir = await _seed_reconcilable_fixture(session, tmp_path)
    manifest = await build_understat_match_stats_manifest(session, sources_dir)
    assert manifest.summary["ready_rows"] == 1

    result = await _apply(session, manifest.manifest_sha256, sources_dir)
    await session.commit()

    assert result.inserted_rows == 2
    assert result.matches_written == 1
    assert result.leagues == (LEAGUE,)
    assert await _stats_rows(session) == [
        ("match-target", "team-arsenal", HOME_XG),
        ("match-target", "team-chelsea", AWAY_XG),
    ]


async def test_only_expected_goals_is_populated(
    session: AsyncSession, tmp_path: Path
) -> None:
    """The Understat match frame carries no shot counts. Every other column must
    stay NULL — a zero there reads downstream as an observed zero-shot match."""
    sources_dir = await _seed_reconcilable_fixture(session, tmp_path)
    manifest = await build_understat_match_stats_manifest(session, sources_dir)
    await _apply(session, manifest.manifest_sha256, sources_dir)
    await session.commit()

    row = (await session.execute(select(MatchStats))).scalars().first()
    assert row is not None
    assert row.expected_goals is not None
    for column in (
        "possession", "shots", "shots_on_target", "corners",
        "fouls", "yellow_cards", "red_cards", "offsides",
    ):
        assert getattr(row, column) is None, column


async def test_batching_writes_every_row(session: AsyncSession, tmp_path: Path) -> None:
    """batch_size is a connection-overhead knob, never a row filter."""
    sources_dir = await _seed_reconcilable_fixture(session, tmp_path)
    manifest = await build_understat_match_stats_manifest(session, sources_dir)
    result = await _apply(session, manifest.manifest_sha256, sources_dir, batch_size=1)
    await session.commit()
    assert result.inserted_rows == 2
    assert len(await _stats_rows(session)) == 2


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


async def test_a_stale_manifest_digest_writes_nothing(
    session: AsyncSession, tmp_path: Path
) -> None:
    sources_dir = await _seed_reconcilable_fixture(session, tmp_path)
    with pytest.raises(RuntimeError, match="manifest changed since review"):
        await _apply(session, "0" * 64, sources_dir)
    await session.rollback()
    assert await _stats_rows(session) == []


async def test_rerunning_is_idempotent_without_a_unique_constraint(
    session: AsyncSession, tmp_path: Path
) -> None:
    """``match_stats`` has only a non-unique index, so a blind re-INSERT would
    double every row and silently double-count it in the rolling xG mean."""
    sources_dir = await _seed_reconcilable_fixture(session, tmp_path)
    manifest = await build_understat_match_stats_manifest(session, sources_dir)

    await _apply(session, manifest.manifest_sha256, sources_dir)
    await session.commit()

    second = await _apply(session, manifest.manifest_sha256, sources_dir)
    await session.commit()

    assert second.inserted_rows == 0
    assert second.already_present_rows == 2
    assert len(await _stats_rows(session)) == 2


async def test_refuses_to_overwrite_a_differing_existing_value(
    session: AsyncSession, tmp_path: Path
) -> None:
    sources_dir = await _seed_reconcilable_fixture(session, tmp_path)
    manifest = await build_understat_match_stats_manifest(session, sources_dir)
    session.add(
        MatchStats(
            match_id="match-target",
            team_id="team-arsenal",
            expected_goals=HOME_XG + 0.5,
        )
    )
    await session.commit()

    with pytest.raises(RuntimeError, match="refuses to overwrite"):
        await _apply(session, manifest.manifest_sha256, sources_dir)
    await session.rollback()
    assert await _stats_rows(session) == [("match-target", "team-arsenal", HOME_XG + 0.5)]


async def test_a_manifest_with_no_ready_entries_is_refused(
    session: AsyncSession, tmp_path: Path
) -> None:
    """Nothing resolvable is a review failure, not a zero-row success."""
    sources_dir = _write_corpus(
        tmp_path,
        [
            {
                "home_team": "Unknown United",
                "away_team": "Unknown City",
                "date": KICKOFF,
                "home_xg": 1.0,
                "away_xg": 1.0,
                "has_data": True,
            }
        ],
    )
    manifest = await build_understat_match_stats_manifest(session, sources_dir)
    assert manifest.summary["ready_rows"] == 0
    with pytest.raises(RuntimeError, match="no READY entries"):
        await _apply(session, manifest.manifest_sha256, sources_dir)


async def test_unresolved_entries_are_skipped_and_counted_not_fatal(
    session: AsyncSession, tmp_path: Path
) -> None:
    """A club with no fixture in ``matches`` can never resolve. Refusing the
    whole 12k-row run over it would mean the backfill can never be applied."""
    await _seed_reconcilable_fixture(session, tmp_path)
    sources_dir = _write_corpus(
        tmp_path,
        [
            {
                "home_team": "Arsenal", "away_team": "Chelsea", "date": KICKOFF,
                "home_xg": HOME_XG, "away_xg": AWAY_XG, "has_data": True,
            },
            {
                "home_team": "Never Heard Of FC", "away_team": "Nor This One FC",
                "date": KICKOFF, "home_xg": 1.0, "away_xg": 1.0, "has_data": True,
            },
        ],
    )
    manifest = await build_understat_match_stats_manifest(session, sources_dir)
    result = await _apply(session, manifest.manifest_sha256, sources_dir)
    await session.commit()

    assert result.inserted_rows == 2
    assert result.skipped_unresolved_entries == 1


async def test_lock_acquisition_refuses_a_non_postgresql_bind(
    session: AsyncSession,
) -> None:
    with pytest.raises(RuntimeError, match="requires PostgreSQL"):
        await acquire_match_stats_backfill_locks(session)


async def test_reversals_carry_the_delete_key_for_every_inserted_row(
    session: AsyncSession, tmp_path: Path
) -> None:
    sources_dir = await _seed_reconcilable_fixture(session, tmp_path)
    manifest = await build_understat_match_stats_manifest(session, sources_dir)
    result = await _apply(session, manifest.manifest_sha256, sources_dir)
    await session.commit()

    assert sorted(result.reversals) == [
        ("match-target", "team-arsenal"),
        ("match-target", "team-chelsea"),
    ]
