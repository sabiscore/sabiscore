"""Read-only durable Elo recovery and integrity evidence for release verification.

This module never writes or replays Elo. It quantifies deterministic recovery
progress and evaluates the same persisted structural/semantic invariants used by
the canonical production verification SQL so a freshly bootstrapped database
cannot look production-complete merely because it contains some Elo rows.
"""
from __future__ import annotations

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ..core.database import Match, Team
from ..db.models import EloRatingSnapshot
from .elo_state_service import elo_state_health


def _eligible_finished_predicates():
    return (
        func.lower(Match.status) == "finished",
        Match.home_score.is_not(None),
        Match.away_score.is_not(None),
        Match.league_id.is_not(None),
        Match.home_team_id.is_not(None),
        Match.away_team_id.is_not(None),
        Match.home_team_id != Match.away_team_id,
    )


async def _scalar_count(session: AsyncSession, statement) -> int:
    value = (await session.execute(statement)).scalar_one()
    return int(value or 0)


async def _structural_integrity(session: AsyncSession) -> dict[str, object]:
    """Evaluate mandatory persisted Elo structure without mutating state."""
    predicates = _eligible_finished_predicates()
    snapshot_counts = (
        select(
            EloRatingSnapshot.match_id.label("match_id"),
            func.count(EloRatingSnapshot.id).label("row_count"),
            func.count(func.distinct(EloRatingSnapshot.team_id)).label("team_count"),
        )
        .group_by(EloRatingSnapshot.match_id)
        .subquery()
    )
    duplicate_pairs = (
        select(EloRatingSnapshot.match_id, EloRatingSnapshot.team_id)
        .group_by(EloRatingSnapshot.match_id, EloRatingSnapshot.team_id)
        .having(func.count(EloRatingSnapshot.id) > 1)
        .subquery()
    )

    counters = {
        "processed_matches_not_exactly_two_rows": await _scalar_count(
            session,
            select(func.count(Match.id))
            .select_from(Match)
            .join(snapshot_counts, snapshot_counts.c.match_id == Match.id)
            .where(
                and_(*predicates),
                or_(snapshot_counts.c.row_count != 2, snapshot_counts.c.team_count != 2),
            ),
        ),
        "partial_one_row_matches": await _scalar_count(
            session,
            select(func.count()).select_from(snapshot_counts).where(snapshot_counts.c.row_count == 1),
        ),
        "duplicate_match_team_pairs": await _scalar_count(
            session,
            select(func.count()).select_from(duplicate_pairs),
        ),
        "orphan_snapshot_match_ids": await _scalar_count(
            session,
            select(func.count(EloRatingSnapshot.id))
            .select_from(EloRatingSnapshot)
            .outerjoin(Match, Match.id == EloRatingSnapshot.match_id)
            .where(Match.id.is_(None)),
        ),
        "orphan_snapshot_team_ids": await _scalar_count(
            session,
            select(func.count(EloRatingSnapshot.id))
            .select_from(EloRatingSnapshot)
            .outerjoin(Team, Team.id == EloRatingSnapshot.team_id)
            .where(Team.id.is_(None)),
        ),
        "snapshot_team_not_home_or_away": await _scalar_count(
            session,
            select(func.count(EloRatingSnapshot.id))
            .select_from(EloRatingSnapshot)
            .join(Match, Match.id == EloRatingSnapshot.match_id)
            .where(
                EloRatingSnapshot.team_id != Match.home_team_id,
                EloRatingSnapshot.team_id != Match.away_team_id,
            ),
        ),
        "snapshot_match_date_mismatch": await _scalar_count(
            session,
            select(func.count(EloRatingSnapshot.id))
            .select_from(EloRatingSnapshot)
            .join(Match, Match.id == EloRatingSnapshot.match_id)
            .where(EloRatingSnapshot.match_date != Match.match_date),
        ),
        "snapshot_league_mismatch": await _scalar_count(
            session,
            select(func.count(EloRatingSnapshot.id))
            .select_from(EloRatingSnapshot)
            .join(Match, Match.id == EloRatingSnapshot.match_id)
            .where(EloRatingSnapshot.league != Match.league_id),
        ),
        "self_play_matches": await _scalar_count(
            session,
            select(func.count(Match.id)).where(
                Match.home_team_id.is_not(None),
                Match.home_team_id == Match.away_team_id,
            ),
        ),
    }
    return {
        "status": "PASS" if all(value == 0 for value in counters.values()) else "FAIL",
        "counters": counters,
        "semantics": "canonical_persisted_structure_gate",
    }


async def _semantic_integrity(session: AsyncSession) -> dict[str, object]:
    """Detect historical cross-league Team identity contamination."""
    home_team = aliased(Team)
    away_team = aliased(Team)
    historical = Match.id.like("fdco-%")

    home_mismatch = await _scalar_count(
        session,
        select(func.count(Match.id))
        .select_from(Match)
        .outerjoin(home_team, home_team.id == Match.home_team_id)
        .where(
            historical,
            or_(home_team.league_id.is_(None), home_team.league_id != Match.league_id),
        ),
    )
    away_mismatch = await _scalar_count(
        session,
        select(func.count(Match.id))
        .select_from(Match)
        .outerjoin(away_team, away_team.id == Match.away_team_id)
        .where(
            historical,
            or_(away_team.league_id.is_(None), away_team.league_id != Match.league_id),
        ),
    )
    match_mismatch = await _scalar_count(
        session,
        select(func.count(Match.id))
        .select_from(Match)
        .outerjoin(home_team, home_team.id == Match.home_team_id)
        .outerjoin(away_team, away_team.id == Match.away_team_id)
        .where(
            historical,
            or_(
                home_team.league_id.is_(None),
                away_team.league_id.is_(None),
                home_team.league_id != Match.league_id,
                away_team.league_id != Match.league_id,
            ),
        ),
    )
    snapshot_mismatch = await _scalar_count(
        session,
        select(func.count(EloRatingSnapshot.id))
        .select_from(EloRatingSnapshot)
        .outerjoin(Team, Team.id == EloRatingSnapshot.team_id)
        .where(or_(Team.league_id.is_(None), Team.league_id != EloRatingSnapshot.league)),
    )

    counters = {
        "historical_match_home_team_league_mismatch": home_mismatch,
        "historical_match_away_team_league_mismatch": away_mismatch,
        "historical_matches_with_semantic_identity_mismatch": match_mismatch,
        "elo_snapshot_team_league_mismatch": snapshot_mismatch,
    }
    return {
        "status": "PASS" if all(value == 0 for value in counters.values()) else "FAIL",
        "counters": counters,
        "semantics": "canonical_historical_team_league_ownership_gate",
    }


async def elo_recovery_health(session: AsyncSession) -> dict[str, object]:
    """Return recovery progress plus direct structural/semantic integrity gates.

    Recovery considers an eligible finished match processed once any durable Elo
    row exists for that match. The nested integrity gates then independently prove
    whether persisted rows are structurally complete and semantically owned by the
    correct competition. This separation prevents one partial row from being
    mistaken for a certified replay.
    """
    base = await elo_state_health(session)
    predicates = _eligible_finished_predicates()
    has_snapshot = exists(
        select(EloRatingSnapshot.id).where(EloRatingSnapshot.match_id == Match.id)
    )

    eligible = await _scalar_count(
        session,
        select(func.count(Match.id)).where(and_(*predicates)),
    )
    pending = await _scalar_count(
        session,
        select(func.count(Match.id)).where(and_(*predicates), ~has_snapshot),
    )
    processed = max(0, eligible - pending)
    coverage_ratio = (processed / eligible) if eligible else None
    structural = await _structural_integrity(session)
    semantic = await _semantic_integrity(session)

    return {
        **base,
        "eligible_finished_matches": eligible,
        "processed_finished_matches": processed,
        "pending_finished_matches": pending,
        "recovery_complete": eligible > 0 and pending == 0,
        "coverage_ratio": coverage_ratio,
        "structural_integrity": structural,
        "semantic_integrity": semantic,
        "semantics": "recovery_progress_plus_direct_persisted_integrity_gates",
    }


__all__ = ["elo_recovery_health"]
