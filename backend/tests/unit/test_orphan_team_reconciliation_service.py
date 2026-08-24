"""docs/DEBT.md item 39: orphan-team repair manifest replays the real resolver.

Production's orphan rows predate PR #82's mojibake guard, which now correctly
refuses to let ``sync_upcoming_fixtures`` mint a *new* corrupted orphan — so
these tests seed the orphan Match/Team rows directly (mimicking the
pre-existing production state) and use ``ensure_canonical_fixture`` for the
``ProviderEventMapping``/``ProviderTeamMapping`` side, exactly like
production's per-tick refresh (which has no name-quality guard and keeps
``ProviderTeamMapping.provider_team_name`` current regardless).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, League, Match, Team
from src.db.models import EloRatingSnapshot, MatchPredictionLog
from src.services.canonical_identity_service import ensure_canonical_fixture
from src.services.orphan_team_reconciliation_service import (
    build_orphan_team_repair_manifest,
)

_FUTURE = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=3)
_PAST = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=3)


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as value:
        yield value
    await engine.dispose()


async def _seed_elo_history(
    session: AsyncSession, *, team_id: str, name: str, league_id: str, opponent_index: int
) -> None:
    """A team with real durable Elo history — the legitimate repair target."""
    if await session.get(League, league_id) is None:
        session.add(League(id=league_id, name=league_id, country="test"))
        await session.flush()

    opponent_id = f"opponent-{league_id.lower()}-{opponent_index}"
    if await session.get(Team, team_id) is None:
        session.add(Team(id=team_id, name=name, league_id=league_id))
    if await session.get(Team, opponent_id) is None:
        session.add(Team(id=opponent_id, name=f"Opponent {opponent_index}", league_id=league_id))
    await session.flush()

    match_id = f"history-{league_id.lower()}-{opponent_index}"
    match_date = datetime(2025, 9, min(opponent_index, 28), 15, 0)
    session.add(
        Match(
            id=match_id,
            league_id=league_id,
            home_team_id=team_id,
            away_team_id=opponent_id,
            match_date=match_date,
            season="2025/2026",
            status="finished",
            home_score=2,
            away_score=1,
        )
    )
    await session.flush()
    session.add(
        EloRatingSnapshot(
            match_id=match_id,
            team_id=team_id,
            pre_match_elo=1500.0,
            post_match_elo=1520.0,
            league=league_id,
            season="2025/2026",
            match_date=match_date,
            created_at=match_date,
        )
    )
    await session.commit()


async def _seed_orphan_fixture(
    session: AsyncSession,
    *,
    match_id: str,
    league_id: str,
    home_provider_id: str,
    away_provider_id: str,
    observed_home_name: str,
    observed_away_name: str,
    kickoff: datetime = _FUTURE,
) -> None:
    """Directly seed an Elo-less orphan Match/Team pair (bypassing sync_upcoming_fixtures,
    which #82 now correctly refuses to do for a corrupt name), then run the real
    ensure_canonical_fixture() to populate ProviderEventMapping/ProviderTeamMapping
    with the CURRENT observed name — exactly the per-tick refresh production performs
    independently of the Match/Team upsert logic.
    """
    orphan_home_id = f"fd-team-{league_id.lower()}:home-{match_id}"
    orphan_away_id = f"fd-team-{league_id.lower()}:away-{match_id}"
    if await session.get(League, league_id) is None:
        session.add(League(id=league_id, name=league_id, country="test"))
    session.add(Team(id=orphan_home_id, name=observed_home_name, league_id=league_id))
    session.add(Team(id=orphan_away_id, name=observed_away_name, league_id=league_id))
    await session.flush()
    session.add(
        Match(
            id=match_id,
            league_id=league_id,
            home_team_id=orphan_home_id,
            away_team_id=orphan_away_id,
            match_date=kickoff,
            season="2026/2027",
            status="scheduled",
        )
    )
    await session.flush()
    await ensure_canonical_fixture(
        session,
        provider="football-data.org",
        provider_event_id=match_id,
        competition_id=league_id,
        competition_name=league_id,
        home_provider_id=home_provider_id,
        home_name=observed_home_name,
        away_provider_id=away_provider_id,
        away_name=observed_away_name,
        kickoff_utc=kickoff,
        season="2026/2027",
        status="scheduled",
        evidence={
            "home_provider_team_id": home_provider_id,
            "away_provider_team_id": away_provider_id,
        },
    )
    await session.commit()


async def test_orphan_with_now_clean_name_resolves_to_the_real_history_bearing_team(
    session: AsyncSession,
) -> None:
    await _seed_elo_history(
        session, team_id="fdco-team-la_liga-malaga", name="Malaga",
        league_id="LA_LIGA", opponent_index=1,
    )
    # Orphan created at a corrupted moment; a later tick refreshed the observed
    # name to clean — exactly production's shape.
    await _seed_orphan_fixture(
        session, match_id="fd-1", league_id="LA_LIGA",
        home_provider_id="500", away_provider_id="501",
        observed_home_name="Malaga CF", observed_away_name="Clean Opponent CF",
    )

    manifest = await build_orphan_team_repair_manifest(session)

    assert manifest.summary["total_candidates"] == 1
    assert manifest.summary["repair_ready_count"] == 1
    assert manifest.summary["distinct_orphan_teams"] == 1
    entry = manifest.entries[0]
    assert entry.match_id == "fd-1"
    assert entry.side == "home"
    assert entry.orphan_team_id == "fd-team-la_liga:home-fd-1"
    assert entry.target_team_id == "fdco-team-la_liga-malaga"
    assert entry.target_team_name == "Malaga"
    assert entry.target_elo_snapshot_count == 1
    assert entry.repair_ready is True
    assert entry.blockers == ()


async def test_orphan_still_carrying_a_corrupt_freshest_name_is_not_proposed(
    session: AsyncSession,
) -> None:
    await _seed_elo_history(
        session, team_id="fdco-team-la_liga-malaga", name="Malaga",
        league_id="LA_LIGA", opponent_index=2,
    )
    await _seed_orphan_fixture(
        session, match_id="fd-2", league_id="LA_LIGA",
        home_provider_id="510", away_provider_id="511",
        observed_home_name="M??laga CF", observed_away_name="Clean Opponent CF",
    )

    manifest = await build_orphan_team_repair_manifest(session)

    assert manifest.entries == ()


async def test_team_with_real_history_is_never_flagged_as_an_orphan(
    session: AsyncSession,
) -> None:
    await _seed_elo_history(
        session, team_id="fdco-team-la_liga-malaga", name="Malaga",
        league_id="LA_LIGA", opponent_index=3,
    )
    # Match already uses the real, history-bearing id on both sides.
    session.add(League(id="LA_LIGA", name="LA_LIGA", country="test")) if await session.get(League, "LA_LIGA") is None else None
    opponent_id = "opponent-la_liga-3"
    session.add(
        Match(
            id="fd-3", league_id="LA_LIGA",
            home_team_id="fdco-team-la_liga-malaga", away_team_id=opponent_id,
            match_date=_FUTURE, season="2026/2027", status="scheduled",
        )
    )
    await session.commit()

    manifest = await build_orphan_team_repair_manifest(session)

    assert manifest.entries == ()


async def test_kickoff_passed_blocker(session: AsyncSession) -> None:
    await _seed_elo_history(
        session, team_id="fdco-team-la_liga-malaga", name="Malaga",
        league_id="LA_LIGA", opponent_index=4,
    )
    await _seed_orphan_fixture(
        session, match_id="fd-4", league_id="LA_LIGA",
        home_provider_id="530", away_provider_id="531",
        observed_home_name="Malaga CF", observed_away_name="Clean Opponent CF",
        kickoff=_PAST,
    )

    manifest = await build_orphan_team_repair_manifest(session)

    assert len(manifest.entries) == 1
    assert "KICKOFF_PASSED" in manifest.entries[0].blockers
    assert manifest.entries[0].repair_ready is False


async def test_existing_predictions_blocker(session: AsyncSession) -> None:
    await _seed_elo_history(
        session, team_id="fdco-team-la_liga-malaga", name="Malaga",
        league_id="LA_LIGA", opponent_index=5,
    )
    await _seed_orphan_fixture(
        session, match_id="fd-5", league_id="LA_LIGA",
        home_provider_id="540", away_provider_id="541",
        observed_home_name="Malaga CF", observed_away_name="Clean Opponent CF",
    )
    session.add(
        MatchPredictionLog(
            match_id="fd-5",
            model_version="v5_phase7",
            home_probability=0.4,
            draw_probability=0.3,
            away_probability=0.3,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
    )
    await session.commit()

    manifest = await build_orphan_team_repair_manifest(session)

    assert len(manifest.entries) == 1
    assert "HAS_EXISTING_PREDICTIONS" in manifest.entries[0].blockers


async def test_manifest_sha256_is_deterministic(session: AsyncSession) -> None:
    await _seed_elo_history(
        session, team_id="fdco-team-la_liga-malaga", name="Malaga",
        league_id="LA_LIGA", opponent_index=6,
    )
    await _seed_orphan_fixture(
        session, match_id="fd-6", league_id="LA_LIGA",
        home_provider_id="550", away_provider_id="551",
        observed_home_name="Malaga CF", observed_away_name="Clean Opponent CF",
    )

    first = await build_orphan_team_repair_manifest(session)
    second = await build_orphan_team_repair_manifest(session)

    assert first.manifest_sha256 == second.manifest_sha256
    assert first.manifest_sha256 != ""


async def test_unrepaired_orphan_sides_diagnostics_distinguish_failure_reasons(
    session: AsyncSession,
) -> None:
    """An orphan that fails to resolve must not be silently indistinguishable
    from 'there was never an orphan here' — the diagnostic breakdown is what
    a human uses to tell those apart from outside this function."""
    league_id = "LA_LIGA"
    session.add(League(id=league_id, name=league_id, country="test"))
    # No opponent with Elo history exists in this league at all, so
    # resolve_team_id has nothing to match against — ORPHAN_NO_RESOLVER_MATCH.
    await _seed_orphan_fixture(
        session, match_id="fd-8", league_id=league_id,
        home_provider_id="600", away_provider_id="601",
        observed_home_name="Unmatched Club CF", observed_away_name="Also Unmatched",
    )

    manifest = await build_orphan_team_repair_manifest(session)

    assert manifest.entries == ()
    diag = manifest.summary["unrepaired_orphan_sides"]
    assert diag.get("ORPHAN_NO_RESOLVER_MATCH") == 2  # both home and away

    # Identity detail lets a caller diagnose *which* side is stuck without a
    # direct DB query — the aggregate count above stays the count-of-record.
    detail = manifest.summary["unrepaired_orphan_side_detail"]
    assert len(detail) == 2
    sides = {record["side"] for record in detail}
    assert sides == {"home", "away"}
    for record in detail:
        assert record["match_id"] == "fd-8"
        assert record["league_id"] == league_id
        assert record["reason"] == "ORPHAN_NO_RESOLVER_MATCH"
        assert record["orphan_team_id"] in {
            "fd-team-la_liga:home-fd-8",
            "fd-team-la_liga:away-fd-8",
        }
    home_record = next(r for r in detail if r["side"] == "home")
    assert home_record["orphan_team_name"] == "Unmatched Club CF"
    assert home_record["freshest_observed_name"] == "Unmatched Club CF"


async def test_target_that_would_collide_with_the_other_side_is_refused(
    session: AsyncSession,
) -> None:
    """If the resolved target already equals the OTHER side's team id, refuse
    rather than propose a self-play collision."""
    await _seed_elo_history(
        session, team_id="fdco-team-la_liga-malaga", name="Malaga",
        league_id="LA_LIGA", opponent_index=7,
    )
    league_id = "LA_LIGA"
    orphan_home_id = "fd-team-la_liga:home-fd-7"
    session.add(Team(id=orphan_home_id, name="Malaga CF", league_id=league_id))
    await session.flush()
    session.add(
        Match(
            id="fd-7", league_id=league_id,
            home_team_id=orphan_home_id,
            away_team_id="fdco-team-la_liga-malaga",  # already the resolve target
            match_date=_FUTURE, season="2026/2027", status="scheduled",
        )
    )
    await session.flush()
    await ensure_canonical_fixture(
        session,
        provider="football-data.org",
        provider_event_id="fd-7",
        competition_id=league_id,
        competition_name=league_id,
        home_provider_id="560",
        home_name="Malaga CF",
        away_provider_id="561",
        away_name="Malaga Away Placeholder",
        kickoff_utc=_FUTURE,
        season="2026/2027",
        status="scheduled",
        evidence={"home_provider_team_id": "560", "away_provider_team_id": "561"},
    )
    await session.commit()

    manifest = await build_orphan_team_repair_manifest(session)

    assert manifest.entries == ()
