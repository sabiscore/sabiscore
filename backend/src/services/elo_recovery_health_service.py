"""Read-only durable Elo recovery coverage for release/readiness evidence.

This module never writes or replays Elo.  It quantifies how much deterministic
finished-match history is represented by PostgreSQL snapshots so a fresh database
bootstrap cannot look production-complete merely because some Elo rows exist.
"""
from __future__ import annotations

from sqlalchemy import and_, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import Match
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


async def elo_recovery_health(session: AsyncSession) -> dict[str, object]:
    """Return Elo authority plus deterministic historical recovery backlog.

    A match is counted as processed when at least one durable Elo row exists for
    it. Structural verification (exactly two team rows, no orphans, semantic
    identity) remains the responsibility of the production verification SQL; this
    health surface intentionally reports recovery progress, not certification.
    """
    base = await elo_state_health(session)
    predicates = _eligible_finished_predicates()
    has_snapshot = exists(
        select(EloRatingSnapshot.id).where(EloRatingSnapshot.match_id == Match.id)
    )

    eligible = int(
        (
            await session.execute(
                select(func.count(Match.id)).where(and_(*predicates))
            )
        ).scalar_one()
    )
    pending = int(
        (
            await session.execute(
                select(func.count(Match.id)).where(
                    and_(*predicates),
                    ~has_snapshot,
                )
            )
        ).scalar_one()
    )
    processed = max(0, eligible - pending)
    coverage_ratio = (processed / eligible) if eligible else None

    return {
        **base,
        "eligible_finished_matches": eligible,
        "processed_finished_matches": processed,
        "pending_finished_matches": pending,
        "recovery_complete": eligible > 0 and pending == 0,
        "coverage_ratio": coverage_ratio,
        "semantics": "recovery_progress_only_not_structural_or_semantic_certification",
    }


__all__ = ["elo_recovery_health"]
