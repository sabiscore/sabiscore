"""Repository queries for canonical and legacy fixture records."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Final, List, Sequence

from sqlalchemy import Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import Match
from ..db.models import MarketSnapshot, MatchPredictionLog

# ``finished`` is the canonical status. The additional values cover historical
# loaders that pre-date the normalized schema; scores are still required, so a
# status alias alone can never qualify an unresolved fixture as settled.
SETTLED_MATCH_STATUSES: Final[tuple[str, ...]] = (
    "finished",
    "completed",
    "settled",
    "final",
)

MAX_SETTLED_FIXTURE_LIMIT: Final[int] = 20_000


def _validated_limit(limit: int) -> int:
    if not isinstance(limit, int):
        raise TypeError("limit must be an integer")
    if limit < 1 or limit > MAX_SETTLED_FIXTURE_LIMIT:
        raise ValueError(
            f"limit must be between 1 and {MAX_SETTLED_FIXTURE_LIMIT}"
        )
    return limit


def build_settled_fixtures_query(
    *,
    limit: int = 5_000,
    league: str | None = None,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    newest_first: bool = False,
) -> Select[tuple[Match]]:
    """Build the authoritative settled-fixture query.

    A fixture is settled only when its normalized/legacy final status is known
    *and* both final scores are present. This prevents postponed, abandoned, or
    partially ingested matches from entering evaluation datasets.
    """

    validated_limit = _validated_limit(limit)
    statement = select(Match).where(
        func.lower(Match.status).in_(SETTLED_MATCH_STATUSES),
        Match.home_score.is_not(None),
        Match.away_score.is_not(None),
    )

    if league:
        statement = statement.where(func.lower(Match.league_id) == league.lower())
    if started_at is not None:
        statement = statement.where(Match.match_date >= started_at)
    if ended_at is not None:
        statement = statement.where(Match.match_date <= ended_at)

    ordering = Match.match_date.desc() if newest_first else Match.match_date.asc()
    return statement.order_by(ordering, Match.id.asc()).limit(validated_limit)


async def get_settled_fixtures(
    session: AsyncSession,
    *,
    limit: int = 5_000,
    league: str | None = None,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    newest_first: bool = False,
) -> Sequence[Match]:
    """Return score-verified settled fixtures in deterministic date order."""

    result = await session.execute(
        build_settled_fixtures_query(
            limit=limit,
            league=league,
            started_at=started_at,
            ended_at=ended_at,
            newest_first=newest_first,
        )
    )
    return tuple(result.scalars().unique().all())


# ---------------------------------------------------------------------------
# WP-3.3: settled-prediction join for walk_forward_validate() (model_registry.py)
# ---------------------------------------------------------------------------
#
# match_prediction_logs.match_id is a free-text column (no FK) sharing the
# legacy Match.id namespace — the same one WP-1's resolve_team_id()/
# canonical_season() operate on. canonical_fixture_id targets the separate
# canonical_fixtures spine, which nothing in this codebase populates today, so
# joining through it here would silently return zero rows forever.
#
# A prediction is eligible only when it was created before kickoff. This is
# enforced inside latest_per_match so the chosen row cannot be a post-kickoff
# re-request.


def build_settled_predictions_query(
    *,
    limit: int = 5_000,
    league: str | None = None,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    model_version: str | None = None,
) -> Select[Any]:
    """Join the most recent logged prediction per settled fixture to its result.

    ``model_version`` restricts the join to a single model generation. Pooling
    generations is a zero-fabrication violation: accuracy/RPS computed across
    two models describes a system that never existed, and it silently inflates
    the sample size gating certification. Production callers pass the active
    generation; ``None`` is for ad-hoc research queries only.

    The filter is applied inside ``latest_per_match`` as well as on the outer
    select. Filtering only the outer select would first pick the newest
    prediction per match across *all* generations and then discard it, losing a
    match that holds a valid prediction for the requested generation behind a
    newer one from a different generation. This is not hypothetical: production
    match ``fd-564632`` carries both a ``v5_phase7`` and a ``v6_phase8`` row.
    """

    validated_limit = _validated_limit(limit)

    latest_per_match_filters = [MatchPredictionLog.created_at < Match.match_date]
    if model_version:
        latest_per_match_filters.append(
            MatchPredictionLog.model_version == model_version
        )

    latest_per_match = (
        select(
            MatchPredictionLog.match_id,
            func.max(MatchPredictionLog.created_at).label("latest_created_at"),
        )
        .join(Match, MatchPredictionLog.match_id == Match.id)
        .where(*latest_per_match_filters)
        .group_by(MatchPredictionLog.match_id)
        .subquery()
    )

    statement = (
        select(
            Match.match_date,
            Match.home_score,
            Match.away_score,
            MatchPredictionLog.home_probability,
            MatchPredictionLog.draw_probability,
            MatchPredictionLog.away_probability,
        )
        .select_from(MatchPredictionLog)
        .join(Match, MatchPredictionLog.match_id == Match.id)
        .join(
            latest_per_match,
            and_(
                MatchPredictionLog.match_id == latest_per_match.c.match_id,
                MatchPredictionLog.created_at == latest_per_match.c.latest_created_at,
            ),
        )
        .where(
            func.lower(Match.status).in_(SETTLED_MATCH_STATUSES),
            Match.home_score.is_not(None),
            Match.away_score.is_not(None),
        )
    )

    if model_version:
        statement = statement.where(MatchPredictionLog.model_version == model_version)
    if league:
        statement = statement.where(func.lower(Match.league_id) == league.lower())
    if started_at is not None:
        statement = statement.where(Match.match_date >= started_at)
    if ended_at is not None:
        statement = statement.where(Match.match_date <= ended_at)

    return statement.order_by(Match.match_date.asc()).limit(validated_limit)


async def get_settled_predictions(
    session: AsyncSession,
    *,
    limit: int = 5_000,
    league: str | None = None,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    model_version: str | None = None,
) -> List[Dict[str, Any]]:
    """Return settled-fixture records shaped for
    ``model_registry.ModelRegistry.walk_forward_validate()``:
    ``{"date": ISO str, "outcome": 0|1|2, "probs": [p_home, p_draw, p_away]}``,
    where outcome is 0=home_win, 1=draw, 2=away_win.

    Pass ``model_version`` to scope the records to one model generation — see
    ``build_settled_predictions_query`` for why pooling generations is a
    zero-fabrication violation rather than a larger sample.
    """

    result = await session.execute(
        build_settled_predictions_query(
            limit=limit,
            league=league,
            started_at=started_at,
            ended_at=ended_at,
            model_version=model_version,
        )
    )

    records: List[Dict[str, Any]] = []
    for match_date, home_score, away_score, home_prob, draw_prob, away_prob in result.all():
        if home_score > away_score:
            outcome = 0
        elif home_score == away_score:
            outcome = 1
        else:
            outcome = 2
        records.append(
            {
                "date": match_date.isoformat(),
                "outcome": outcome,
                "probs": [home_prob, draw_prob, away_prob],
            }
        )
    return records


# ---------------------------------------------------------------------------
# CLV computation: join logged predictions to captured closing lines
# ---------------------------------------------------------------------------
#
# Joins on match_id, not canonical_fixture_id. clv_capture_service.py and both
# MatchPredictionLog write sites (api/endpoints/predictions.py,
# services/analytics.py) all hardcode canonical_fixture_id=None — a join
# through that FK would return zero rows forever. match_id is populated on
# every row on both tables and already indexed on each
# (ix_match_prediction_logs_match_time, ix_market_snapshots_match_id). See
# docs/adr/0004-clv-capture.md, Addendum 2.
#
# Temporal integrity is strict on both sides of the join:
# - prediction.created_at must be before the selected closing snapshot;
# - closing_snapshot.captured_at must be strictly before fixture kickoff.
# Historical rows observed at or after kickoff remain in storage for audit but
# are structurally incapable of entering CLV evaluation.


def build_clv_records_query(
    *,
    limit: int = 5_000,
    league: str | None = None,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
) -> Select[Any]:
    """Join the most recent pre-close prediction per match to its latest valid
    pre-kickoff closing line.

    Unlike build_settled_predictions_query, this does NOT require the match to
    be finished — a legitimate closing line exists as soon as capture runs
    before kickoff, independent of the result.
    """

    validated_limit = _validated_limit(limit)

    latest_closing_line = (
        select(
            MarketSnapshot.match_id,
            func.max(MarketSnapshot.captured_at).label("latest_captured_at"),
        )
        .join(Match, MarketSnapshot.match_id == Match.id)
        .where(
            MarketSnapshot.is_closing_line.is_(True),
            MarketSnapshot.coherent.is_(True),
            MarketSnapshot.captured_at < Match.match_date,
        )
        .group_by(MarketSnapshot.match_id)
        .subquery()
    )
    latest_prediction = (
        select(
            MatchPredictionLog.match_id,
            func.max(MatchPredictionLog.created_at).label("latest_created_at"),
        )
        .join(
            latest_closing_line,
            latest_closing_line.c.match_id == MatchPredictionLog.match_id,
        )
        .where(
            MatchPredictionLog.created_at
            < latest_closing_line.c.latest_captured_at
        )
        .group_by(MatchPredictionLog.match_id)
        .subquery()
    )

    statement = (
        select(
            MatchPredictionLog.home_probability,
            MatchPredictionLog.draw_probability,
            MatchPredictionLog.away_probability,
            MarketSnapshot.home_implied_prob_devigged,
            MarketSnapshot.draw_implied_prob_devigged,
            MarketSnapshot.away_implied_prob_devigged,
        )
        .select_from(MatchPredictionLog)
        .join(Match, MatchPredictionLog.match_id == Match.id)
        .join(
            latest_prediction,
            and_(
                MatchPredictionLog.match_id == latest_prediction.c.match_id,
                MatchPredictionLog.created_at == latest_prediction.c.latest_created_at,
            ),
        )
        .join(
            latest_closing_line,
            latest_closing_line.c.match_id == MatchPredictionLog.match_id,
        )
        .join(
            MarketSnapshot,
            and_(
                MarketSnapshot.match_id == latest_closing_line.c.match_id,
                MarketSnapshot.captured_at == latest_closing_line.c.latest_captured_at,
            ),
        )
        .where(
            MarketSnapshot.is_closing_line.is_(True),
            MarketSnapshot.coherent.is_(True),
            MarketSnapshot.captured_at < Match.match_date,
            MarketSnapshot.home_implied_prob_devigged.is_not(None),
            MarketSnapshot.draw_implied_prob_devigged.is_not(None),
            MarketSnapshot.away_implied_prob_devigged.is_not(None),
        )
    )

    if league:
        statement = statement.where(func.lower(Match.league_id) == league.lower())
    if started_at is not None:
        statement = statement.where(Match.match_date >= started_at)
    if ended_at is not None:
        statement = statement.where(Match.match_date <= ended_at)

    return statement.order_by(Match.match_date.asc()).limit(validated_limit)


async def get_clv_records(
    session: AsyncSession,
    *,
    limit: int = 5_000,
    league: str | None = None,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
) -> List[Dict[str, Any]]:
    """Return prediction/closing-line pairs shaped for
    ``services.clv_service.compute_clv_summary()``:
    ``{"model_probs": [h, d, a], "closing_probs": [h, d, a]}``.
    """

    result = await session.execute(
        build_clv_records_query(
            limit=limit,
            league=league,
            started_at=started_at,
            ended_at=ended_at,
        )
    )

    return [
        {
            "model_probs": [home_prob, draw_prob, away_prob],
            "closing_probs": [home_implied, draw_implied, away_implied],
        }
        for (
            home_prob,
            draw_prob,
            away_prob,
            home_implied,
            draw_implied,
            away_implied,
        ) in result.all()
    ]


async def get_next_upcoming_fixture(
    session: AsyncSession,
    *,
    leagues: Sequence[str] | None = None,
    within_days: int = 7,
) -> Match | None:
    """Earliest scheduled fixture in the horizon — feeds the readiness capability probe."""

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    end_date = now + timedelta(days=within_days)
    statement = select(Match).where(
        Match.match_date >= now,
        Match.match_date <= end_date,
        Match.status == "scheduled",
    )
    if leagues:
        statement = statement.where(func.lower(Match.league_id).in_([league.lower() for league in leagues]))

    result = await session.execute(statement.order_by(Match.match_date.asc()).limit(1))
    return result.scalars().first()