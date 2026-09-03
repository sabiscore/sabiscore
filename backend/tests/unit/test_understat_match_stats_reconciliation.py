"""Read-only reconciliation of Understat corpus rows against canonical identity.

docs/DEBT.md item 56 Finding 5's second prerequisite: nothing carries the
tracked corpus's xG into ``match_stats``. This is the review half of that
write, and this file is its regression suite — entity resolution (via the
one production resolver, never a second normalizer), match resolution within
a bounded kickoff window, ambiguity failing closed rather than guessing, and
the COVID-cancelled-row exclusion already established in
``measure_xg_feature_ate.py``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, Match, Team
from src.db.models import EloRatingSnapshot
from src.services.understat_match_stats_reconciliation_service import (
    _kickoff_window,
    build_understat_match_stats_manifest,
    load_corpus_matches,
)

LEAGUE = "EPL"
KICKOFF = datetime(2024, 8, 16, 19, 0)


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _seed_team_with_history(
    session: AsyncSession, *, team_id: str, name: str, opponent_id: str, match_date: datetime
) -> None:
    """A team with a real settled match + Elo snapshot — resolve_team_id's
    require_elo_history=True floor."""
    session.add(Team(id=team_id, name=name, league_id=LEAGUE, active=True))
    await session.flush()
    match_id = f"seed-{team_id}-{match_date.isoformat()}"
    session.add(
        Match(
            id=match_id, league_id=LEAGUE, home_team_id=team_id, away_team_id=opponent_id,
            match_date=match_date, season="2023/2024", status="finished",
            home_score=1, away_score=0,
        )
    )
    await session.flush()
    session.add(
        EloRatingSnapshot(
            match_id=match_id, team_id=team_id, pre_match_elo=1500.0, post_match_elo=1510.0,
            league=LEAGUE, season="2023/2024", match_date=match_date, created_at=match_date,
        )
    )


def _write_corpus_parquet(tmp_path: Path, *, league: str, season: int, rows: list[dict]) -> Path:
    sources_dir = tmp_path / "v4_sources"
    sources_dir.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_parquet(sources_dir / f"understat_matches_{league}_{season}.parquet")
    return sources_dir


def _row(*, home_team: str, away_team: str, date: datetime, home_xg=1.5, away_xg=1.0, has_data=True) -> dict:
    return {
        "home_team": home_team, "away_team": away_team, "date": date,
        "home_xg": home_xg if has_data else None, "away_xg": away_xg if has_data else None,
        "has_data": has_data,
    }


# ---------------------------------------------------------------------------
# Corpus loading: the COVID-null-xG filter, matching measure_xg_feature_ate.py
# ---------------------------------------------------------------------------


def test_kickoff_window_strips_tzinfo() -> None:
    """asyncpg raises DataError binding a tz-aware datetime against
    Match.match_date (a naive TIMESTAMP WITHOUT TIME ZONE column). SQLite —
    this module's own test DB — accepts either and would never catch a
    regression here; this test exists precisely because that gap is real
    (found by code review, not by the SQLite-backed suite)."""
    from datetime import timezone

    start, end = _kickoff_window(datetime(2024, 8, 16, 19, 0, tzinfo=timezone.utc))
    assert start.tzinfo is None
    assert end.tzinfo is None
    assert end - start == 2 * timedelta(hours=36)


def test_load_corpus_drops_null_xg_rows(tmp_path: Path) -> None:
    sources_dir = _write_corpus_parquet(
        tmp_path, league="ligue_1", season=2019,
        rows=[
            _row(home_team="Lyon", away_team="Nice", date=datetime(2019, 9, 1)),
            _row(home_team="Lyon", away_team="Nice", date=datetime(2020, 4, 1), has_data=False),
        ],
    )
    corpus = load_corpus_matches(sources_dir)
    assert len(corpus) == 1
    assert corpus.iloc[0]["date"] == pd.Timestamp(datetime(2019, 9, 1))


# ---------------------------------------------------------------------------
# End-to-end manifest building
# ---------------------------------------------------------------------------


async def test_resolvable_pair_is_ready(session: AsyncSession, tmp_path: Path) -> None:
    await _seed_team_with_history(
        session, team_id="home-id", name="Arsenal", opponent_id="away-id", match_date=KICKOFF - timedelta(days=200)
    )
    await _seed_team_with_history(
        session, team_id="away-id", name="Chelsea", opponent_id="home-id", match_date=KICKOFF - timedelta(days=200)
    )
    session.add(
        Match(
            id="the-real-fixture", league_id=LEAGUE, home_team_id="home-id", away_team_id="away-id",
            match_date=KICKOFF, season="2024/2025", status="finished", home_score=2, away_score=1,
        )
    )
    await session.commit()

    sources_dir = _write_corpus_parquet(
        tmp_path, league="epl", season=2024,
        rows=[_row(home_team="Arsenal", away_team="Chelsea", date=KICKOFF, home_xg=1.8, away_xg=0.9)],
    )

    manifest = await build_understat_match_stats_manifest(session, sources_dir)

    assert manifest.summary["total_rows"] == 1
    assert manifest.summary["ready_rows"] == 1
    entry = manifest.entries[0]
    assert entry.status == "READY"
    assert entry.match_id == "the-real-fixture"
    assert entry.home_team_id == "home-id"
    assert entry.away_team_id == "away-id"
    assert entry.home_xg == pytest.approx(1.8)
    assert entry.away_xg == pytest.approx(0.9)
    assert entry.blockers == ()


async def test_unknown_team_name_is_team_unresolved_not_guessed(
    session: AsyncSession, tmp_path: Path
) -> None:
    await _seed_team_with_history(
        session, team_id="home-id", name="Arsenal", opponent_id="away-id", match_date=KICKOFF - timedelta(days=200)
    )
    await session.commit()

    sources_dir = _write_corpus_parquet(
        tmp_path, league="epl", season=2024,
        rows=[_row(home_team="Arsenal", away_team="A Club That Does Not Exist FC", date=KICKOFF)],
    )

    manifest = await build_understat_match_stats_manifest(session, sources_dir)

    entry = manifest.entries[0]
    assert entry.status == "TEAM_UNRESOLVED"
    assert entry.home_team_id == "home-id"
    assert entry.away_team_id is None
    assert entry.match_id is None
    assert any("away_team_unresolved" in b for b in entry.blockers)
    assert not entry.repair_ready


async def test_resolved_teams_with_no_matching_fixture_is_match_unresolved(
    session: AsyncSession, tmp_path: Path
) -> None:
    await _seed_team_with_history(
        session, team_id="home-id", name="Arsenal", opponent_id="away-id", match_date=KICKOFF - timedelta(days=200)
    )
    await _seed_team_with_history(
        session, team_id="away-id", name="Chelsea", opponent_id="home-id", match_date=KICKOFF - timedelta(days=200)
    )
    await session.commit()
    # No Match row for Arsenal vs Chelsea at KICKOFF — only the seed matches
    # exist, and those are 200 days earlier, well outside the tolerance window.

    sources_dir = _write_corpus_parquet(
        tmp_path, league="epl", season=2024,
        rows=[_row(home_team="Arsenal", away_team="Chelsea", date=KICKOFF)],
    )

    manifest = await build_understat_match_stats_manifest(session, sources_dir)

    entry = manifest.entries[0]
    assert entry.status == "MATCH_UNRESOLVED"
    assert entry.match_id is None
    assert not entry.repair_ready


async def test_two_candidate_matches_in_window_is_ambiguous_not_guessed(
    session: AsyncSession, tmp_path: Path
) -> None:
    await _seed_team_with_history(
        session, team_id="home-id", name="Arsenal", opponent_id="away-id", match_date=KICKOFF - timedelta(days=200)
    )
    await _seed_team_with_history(
        session, team_id="away-id", name="Chelsea", opponent_id="home-id", match_date=KICKOFF - timedelta(days=200)
    )
    # Two distinct Match rows for the same pairing, both inside the 36h window
    # around KICKOFF — a data-quality scenario the resolver must refuse to
    # pick between rather than silently choosing the first.
    session.add_all([
        Match(
            id="dup-a", league_id=LEAGUE, home_team_id="home-id", away_team_id="away-id",
            match_date=KICKOFF, season="2024/2025", status="finished", home_score=2, away_score=1,
        ),
        Match(
            id="dup-b", league_id=LEAGUE, home_team_id="home-id", away_team_id="away-id",
            match_date=KICKOFF + timedelta(hours=10), season="2024/2025", status="finished",
            home_score=1, away_score=1,
        ),
    ])
    await session.commit()

    sources_dir = _write_corpus_parquet(
        tmp_path, league="epl", season=2024,
        rows=[_row(home_team="Arsenal", away_team="Chelsea", date=KICKOFF)],
    )

    manifest = await build_understat_match_stats_manifest(session, sources_dir)

    entry = manifest.entries[0]
    assert entry.status == "MATCH_AMBIGUOUS"
    assert entry.match_id is None
    assert not entry.repair_ready


async def test_kickoff_tolerance_absorbs_a_same_day_timezone_style_offset(
    session: AsyncSession, tmp_path: Path
) -> None:
    """A 30-hour gap between the two sources' recorded kickoff still resolves —
    inside the 36h tolerance window."""
    real_kickoff = KICKOFF
    understat_recorded = KICKOFF - timedelta(hours=30)

    await _seed_team_with_history(
        session, team_id="home-id", name="Arsenal", opponent_id="away-id", match_date=KICKOFF - timedelta(days=200)
    )
    await _seed_team_with_history(
        session, team_id="away-id", name="Chelsea", opponent_id="home-id", match_date=KICKOFF - timedelta(days=200)
    )
    session.add(
        Match(
            id="the-fixture", league_id=LEAGUE, home_team_id="home-id", away_team_id="away-id",
            match_date=real_kickoff, season="2024/2025", status="finished", home_score=2, away_score=1,
        )
    )
    await session.commit()

    sources_dir = _write_corpus_parquet(
        tmp_path, league="epl", season=2024,
        rows=[_row(home_team="Arsenal", away_team="Chelsea", date=understat_recorded)],
    )

    manifest = await build_understat_match_stats_manifest(session, sources_dir)

    entry = manifest.entries[0]
    assert entry.status == "READY"
    assert entry.match_id == "the-fixture"


async def test_manifest_sha256_is_deterministic_across_repeated_review_runs(
    session: AsyncSession, tmp_path: Path
) -> None:
    """Read-only means idempotent: reviewing twice against the same snapshot
    must produce the same hash — the property a future --apply gate would
    check against."""
    await _seed_team_with_history(
        session, team_id="home-id", name="Arsenal", opponent_id="away-id", match_date=KICKOFF - timedelta(days=200)
    )
    await _seed_team_with_history(
        session, team_id="away-id", name="Chelsea", opponent_id="home-id", match_date=KICKOFF - timedelta(days=200)
    )
    session.add(
        Match(
            id="the-fixture", league_id=LEAGUE, home_team_id="home-id", away_team_id="away-id",
            match_date=KICKOFF, season="2024/2025", status="finished", home_score=2, away_score=1,
        )
    )
    await session.commit()

    sources_dir = _write_corpus_parquet(
        tmp_path, league="epl", season=2024,
        rows=[_row(home_team="Arsenal", away_team="Chelsea", date=KICKOFF)],
    )

    first = await build_understat_match_stats_manifest(session, sources_dir)
    second = await build_understat_match_stats_manifest(session, sources_dir)

    assert first.manifest_sha256 == second.manifest_sha256
    assert first.summary == second.summary


# ---------------------------------------------------------------------------
# Production-shaped regression: the near-orphaned duplicate defect
# (docs/DEBT.md item 56, Finding 6). Fails closed, does not misattribute.
# ---------------------------------------------------------------------------


async def test_near_orphaned_duplicate_resolves_to_the_real_identity(
    session: AsyncSession, tmp_path: Path
) -> None:
    """Reproduces the exact production shape found by probing sabiscore-db-v3:
    two Team rows for the same real club, one holding almost all of its match
    history, one a near-orphan with a handful of matches (and therefore a
    handful of Elo rows too, so require_elo_history=True cannot exclude it).

    Before docs/DEBT.md item 56 Finding 6 was fixed, resolve_team_id(
    "Manchester City", ...) resolved to the near-orphan: the affix-strip
    stage matched "Manchester City FC" before the audited-alias stage —
    which already maps "manchester city" -> "man city" — ever ran. The
    resolver now checks the alias immediately after an exact match, ahead of
    affix-stripping, so this now resolves to the real identity and the
    fixture write-target end to end.
    """
    # The near-orphan: matches the input via affix-stripping, wins the
    # resolution, but has almost no real match history.
    session.add(Team(id="fd-team-epl:manchester_city_fc", name="Manchester City FC", league_id=LEAGUE, active=True))
    # The real, high-usage identity for the same club.
    session.add(Team(id="fdco-team-epl-man_city", name="Man City", league_id=LEAGUE, active=True))
    session.add(Team(id="opponent", name="Arsenal", league_id=LEAGUE, active=True))
    await session.flush()

    # The near-orphan's one real match — just enough Elo history to survive
    # require_elo_history=True.
    orphan_match_date = KICKOFF - timedelta(days=900)
    session.add(
        Match(
            id="orphan-match", league_id=LEAGUE, home_team_id="fd-team-epl:manchester_city_fc",
            away_team_id="opponent", match_date=orphan_match_date, season="2019/2020",
            status="finished", home_score=1, away_score=1,
        )
    )
    await session.flush()
    session.add_all([
        EloRatingSnapshot(
            match_id="orphan-match", team_id="fd-team-epl:manchester_city_fc",
            pre_match_elo=1500.0, post_match_elo=1500.0, league=LEAGUE,
            season="2019/2020", match_date=orphan_match_date, created_at=orphan_match_date,
        ),
        # "opponent" (Arsenal) needs its own Elo history too, or
        # require_elo_history=True excludes it and the away side fails to
        # resolve for an unrelated reason (no Elo row), masking the defect
        # this test exists to reproduce.
        EloRatingSnapshot(
            match_id="orphan-match", team_id="opponent",
            pre_match_elo=1500.0, post_match_elo=1500.0, league=LEAGUE,
            season="2019/2020", match_date=orphan_match_date, created_at=orphan_match_date,
        ),
    ])

    # The real identity's actual match — the one this Understat row describes.
    session.add(
        Match(
            id="the-real-fixture", league_id=LEAGUE, home_team_id="fdco-team-epl-man_city",
            away_team_id="opponent", match_date=KICKOFF, season="2024/2025",
            status="finished", home_score=3, away_score=1,
        )
    )
    await session.flush()
    session.add(
        EloRatingSnapshot(
            match_id="the-real-fixture", team_id="fdco-team-epl-man_city",
            pre_match_elo=1800.0, post_match_elo=1815.0, league=LEAGUE,
            season="2024/2025", match_date=KICKOFF, created_at=KICKOFF,
        )
    )
    await session.commit()

    sources_dir = _write_corpus_parquet(
        tmp_path, league="epl", season=2024,
        rows=[_row(home_team="Manchester City", away_team="Arsenal", date=KICKOFF, home_xg=2.4, away_xg=1.1)],
    )

    manifest = await build_understat_match_stats_manifest(session, sources_dir)

    entry = manifest.entries[0]
    assert entry.home_team_id == "fdco-team-epl-man_city"
    assert entry.match_id == "the-real-fixture"
    assert entry.status == "READY"
    assert entry.repair_ready


async def test_unaliased_near_orphan_still_fails_closed(
    session: AsyncSession, tmp_path: Path
) -> None:
    """The alias reordering fix only helps pairs an audited alias actually
    covers. For a club with no alias entry, the same near-orphan shape must
    still fail closed (MATCH_UNRESOLVED) rather than resolve to whichever
    duplicate the affix stage happens to prefer.
    """
    # A synthetic near-orphan pair, deliberately not a real club name, so this
    # test's outcome depends only on there being no _AUDITED_ALIASES entry —
    # not on which real clubs happen to be aliased today. Mirrors the real
    # shape exactly: the real row uses an abbreviated name ("Man City"), the
    # near-orphan the decorated legal name ("Manchester City FC"), and the
    # corpus sends the undecorated full name ("Manchester City") -- which
    # exact-matches neither row but affix-strips to match the orphan.
    session.add(Team(id="fd-team-epl:fictional_rovers_fc", name="Fictional Rovers FC", league_id=LEAGUE, active=True))
    session.add(Team(id="fdco-team-epl-fictional-rovers", name="Fic Rovers", league_id=LEAGUE, active=True))
    session.add(Team(id="opponent", name="Arsenal", league_id=LEAGUE, active=True))
    await session.flush()

    orphan_match_date = KICKOFF - timedelta(days=900)
    session.add(
        Match(
            id="orphan-match", league_id=LEAGUE, home_team_id="fd-team-epl:fictional_rovers_fc",
            away_team_id="opponent", match_date=orphan_match_date, season="2019/2020",
            status="finished", home_score=1, away_score=1,
        )
    )
    await session.flush()
    session.add_all([
        EloRatingSnapshot(
            match_id="orphan-match", team_id="fd-team-epl:fictional_rovers_fc",
            pre_match_elo=1500.0, post_match_elo=1500.0, league=LEAGUE,
            season="2019/2020", match_date=orphan_match_date, created_at=orphan_match_date,
        ),
        EloRatingSnapshot(
            match_id="orphan-match", team_id="opponent",
            pre_match_elo=1500.0, post_match_elo=1500.0, league=LEAGUE,
            season="2019/2020", match_date=orphan_match_date, created_at=orphan_match_date,
        ),
    ])

    session.add(
        Match(
            id="the-real-fixture", league_id=LEAGUE, home_team_id="fdco-team-epl-fictional-rovers",
            away_team_id="opponent", match_date=KICKOFF, season="2024/2025",
            status="finished", home_score=3, away_score=1,
        )
    )
    await session.flush()
    session.add(
        EloRatingSnapshot(
            match_id="the-real-fixture", team_id="fdco-team-epl-fictional-rovers",
            pre_match_elo=1800.0, post_match_elo=1815.0, league=LEAGUE,
            season="2024/2025", match_date=KICKOFF, created_at=KICKOFF,
        )
    )
    await session.commit()

    sources_dir = _write_corpus_parquet(
        tmp_path, league="epl", season=2024,
        rows=[_row(home_team="Fictional Rovers", away_team="Arsenal", date=KICKOFF, home_xg=2.4, away_xg=1.1)],
    )

    manifest = await build_understat_match_stats_manifest(session, sources_dir)

    entry = manifest.entries[0]
    # "Fictional Rovers FC" affix-strips to an exact match on the corpus's
    # "Fictional Rovers" -- the same trap Manchester City and Newcastle hit
    # -- and with no audited alias to redirect it, the near-orphan wins.
    assert entry.home_team_id == "fd-team-epl:fictional_rovers_fc"
    # The safety property that actually matters: no match found for the
    # near-orphan within the tolerance window, so nothing is misattributed.
    assert entry.status == "MATCH_UNRESOLVED"
    assert entry.match_id is None
    assert not entry.repair_ready
