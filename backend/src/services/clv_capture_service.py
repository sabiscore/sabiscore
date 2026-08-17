"""Capture deterministic pre-match 1X2 market lifecycle evidence.

The existing five-minute CLV loop remains the network owner. For each league
that has at least one fixture approaching kickoff it fetches one already-observed
The Odds API board and hands that board to ``market_observation_service``.

That service writes the existing ``OddsHistory`` numerical stream and classifies
real observations as PRE_MATCH_OPENING, PRE_MATCH_INTERMEDIATE, or the strict
final PRE_MATCH_CLOSING. A first observation inside the closing window is *not*
relabelled as opening evidence. Observations at/after kickoff are rejected.

Canonical fixture identity is now populated by fixture sync, and normalized Odds
API records contain home/away team names. Fixture matching therefore uses team
identity plus kickoff tolerance and fails closed on ambiguity rather than using
timestamp proximity alone.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from .market_observation_service import persist_market_board, utc_naive

logger = logging.getLogger(__name__)

# One provider board can opportunistically persist opening/intermediate evidence
# for every scheduled fixture in that league, but network I/O is still triggered
# only when at least one fixture enters this near-kickoff window.
_CAPTURE_LOOKAHEAD_MINUTES = 10

_last_result: dict[str, Any] = {"outcome": "never_run"}


def _utc_naive(value: datetime) -> datetime:
    """Backward-compatible alias for the shared UTC normalization contract."""
    return utc_naive(value)


def _is_strictly_pre_kickoff(captured_at: datetime, kickoff: datetime) -> bool:
    """True only when the observation happened strictly before kickoff."""
    return _utc_naive(captured_at) < _utc_naive(kickoff)


def last_clv_capture_result() -> dict[str, Any]:
    """Sync accessor for /health; return a copy, never the live result dict."""
    return dict(_last_result)


def _fd_code_to_canonical() -> dict[str, str]:
    """Canonical league ID (Match.league_id) -> canonical league ID.

    After migration 0006_canonical_league_ids, ``_LEAGUE_META`` stores canonical
    SabiScore IDs directly. Keep this identity-map helper for compatibility and
    to derive the supported set from the same fixture-sync policy.
    """
    from .fixture_sync_service import _LEAGUE_META

    return {code: code for _name, (code, _country) in _LEAGUE_META.items()}


async def run_clv_capture_pass(provider: Any = None) -> dict[str, Any]:
    """Run one market-evidence capture pass without leaking DB failures.

    A failed DBAPI transaction is explicitly rolled back before the short-lived
    session returns to the pool, preventing the historical PendingRollbackError
    cascade into unrelated requests.
    """
    global _last_result

    from ..db.session import AsyncSessionLocal

    checked_at = datetime.now(timezone.utc).isoformat()

    if AsyncSessionLocal is None:
        _last_result = {"outcome": "db_not_ready", "checked_at": checked_at}
        return _last_result

    try:
        async with AsyncSessionLocal() as session:
            try:
                counts = await _capture_due_fixtures(session, provider=provider)
            except Exception:
                try:
                    await session.rollback()
                except Exception:
                    logger.exception("clv_capture_pass: rollback failed")
                raise
        _last_result = {"outcome": "ok", "checked_at": checked_at, **counts}
    except Exception as exc:
        logger.exception("clv_capture_pass: unhandled error")
        from ..core.redaction import redact_text

        _last_result = {
            "outcome": "error",
            "checked_at": checked_at,
            "message": redact_text(str(exc)),
        }

    return _last_result


async def _capture_due_fixtures(session: Any, provider: Any = None) -> dict[str, int]:
    from sqlalchemy import select

    from ..core.database import Match
    from ..core.league_policy import LeaguePolicyUnavailableError, canonical_league_id
    from ..db.models import MarketSnapshot

    now = _utc_naive(datetime.now(timezone.utc))
    window_end = now + timedelta(minutes=_CAPTURE_LOOKAHEAD_MINUTES)

    # Strictly future fixtures only. A scheduler wake after kickoff cannot
    # reconstruct a missing pre-match close from in-play market evidence.
    due = (
        (
            await session.execute(
                select(Match).where(
                    Match.status == "scheduled",
                    Match.match_date > now,
                    Match.match_date <= window_end,
                )
            )
        )
        .scalars()
        .all()
    )

    counts = {
        "due": len(due),
        "captured": 0,
        "already_captured": 0,
        "refreshed_closing": 0,
        "unsupported_league": 0,
        "unmatched": 0,
        "opening": 0,
        "intermediate": 0,
        "closing": 0,
        "deduped": 0,
        "post_kickoff_rejected": 0,
        "invalid_market": 0,
        "unmatched_market": 0,
        "ambiguous_market": 0,
        "write_errors": 0,
    }
    if not due:
        return counts

    due_ids = {match.id for match in due}
    already_captured_ids = set(
        (
            await session.execute(
                select(MarketSnapshot.match_id).where(
                    MarketSnapshot.match_id.in_(due_ids),
                    MarketSnapshot.is_closing_line.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    counts["already_captured"] = len(already_captured_ids)

    fd_to_canonical = _fd_code_to_canonical()
    by_league: dict[str, list[Match]] = {}
    pending_due_ids: set[str] = set()
    for match in due:
        league = fd_to_canonical.get(match.league_id)
        if league is None:
            counts["unsupported_league"] += 1
            continue
        # A current closing does not itself trigger another provider request.
        # If another due fixture in the same league triggers a board fetch, the
        # lifecycle writer may still replace this row with a later valid close.
        if match.id in already_captured_ids:
            continue
        pending_due_ids.add(match.id)
        by_league.setdefault(league, []).append(match)

    if not by_league:
        return counts

    if provider is None:
        # Production passes the lifespan-owned instrumented provider explicitly.
        # Direct/test callers use the same observed registry boundary instead of
        # constructing a telemetry-blind provider instance.
        from ..providers.registry import build_provider_registry

        provider = build_provider_registry().get("the_odds_api")

    matched_due_ids: set[str] = set()
    for league, matches in by_league.items():
        try:
            competition = canonical_league_id(league)
        except LeaguePolicyUnavailableError:
            counts["unsupported_league"] += len(matches)
            continue

        result = await provider.odds(competition=competition)
        records: list[dict[str, Any]] = result.records or []
        observed_at = _utc_naive(datetime.now(timezone.utc))
        board = await persist_market_board(
            session,
            league=league,
            records=records,
            observed_at=observed_at,
        )

        board_counts = board.as_counts()
        for key in (
            "opening",
            "intermediate",
            "closing",
            "deduped",
            "post_kickoff_rejected",
            "invalid_market",
            "unmatched_market",
            "ambiguous_market",
            "write_errors",
        ):
            counts[key] += board_counts[key]

        matched_due_ids.update(board.matched_match_ids & pending_due_ids)
        counts["captured"] += len(board.closing_match_ids & pending_due_ids)
        counts["refreshed_closing"] += len(board.closing_match_ids & already_captured_ids)

    counts["unmatched"] = len(pending_due_ids - matched_due_ids)
    await session.commit()
    return counts
