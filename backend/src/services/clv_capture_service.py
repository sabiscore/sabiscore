"""Capture the closing 1X2 market snapshot for each fixture approaching kickoff.

docs/adr/0004-clv-capture.md: CLV here is model-probability vs. closing
de-vigged market-probability (this platform never executes a placed bet). A
kickoff that passes uncaptured is unrecoverable, independent of settled-
prediction volume — see docs/DEBT.md item 6. This module is the capture job
the ADR scoped out as "post-approval work, not designed here".

Enumerates the legacy `matches` table (fixture_sync_service's actual write
target), not `canonical_fixtures` — nothing populates canonical_fixtures for
an ordinary upcoming fixture today, so a job keyed on it would silently
capture nothing for any fixture currently in the database. See the ADR
addendum for the full reasoning; MarketSnapshot.match_id is the real join key
until identity resolution work populates canonical_fixtures.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

# A fixture becomes eligible only shortly before kickoff. There is deliberately
# no post-kickoff grace period: a price observed at/after kickoff is not a closing
# pre-match line and must never be relabelled as one. The scheduler may miss a
# kickoff after a sleep/restart; that evidence is irrecoverable and is preferable
# to fabricating temporal provenance.
_CAPTURE_LOOKAHEAD_MINUTES = 10
_KICKOFF_MATCH_TOLERANCE_MINUTES = 10

_last_result: dict[str, Any] = {"outcome": "never_run"}


def _utc_naive(value: datetime) -> datetime:
    """Return ``value`` as naive UTC for timezone-naive PostgreSQL columns.

    SabiScore's legacy ``matches.match_date`` and ``market_snapshots`` timestamp
    columns are ``TIMESTAMP WITHOUT TIME ZONE``. asyncpg rejects an aware
    ``datetime`` bound to those columns (``can't subtract offset-naive and
    offset-aware datetimes``), while SQLite accepts it and therefore hid the
    production-only failure.

    Naive inputs are already interpreted as UTC by the existing storage
    contract. Aware inputs are converted to UTC *before* dropping tzinfo;
    simply calling ``replace(tzinfo=None)`` on a non-UTC offset would change the
    instant represented by the timestamp.
    """
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _is_strictly_pre_kickoff(captured_at: datetime, kickoff: datetime) -> bool:
    """True only when the observation happened strictly before kickoff.

    Equality is rejected. This helper centralizes the temporal evidence rule so
    the write path and its regression tests cannot disagree about the boundary.
    """
    return _utc_naive(captured_at) < _utc_naive(kickoff)


def last_clv_capture_result() -> dict[str, Any]:
    """Sync accessor for /health — a copy, never the live dict (matches
    settlement_service.last_settlement_result's convention)."""
    return dict(_last_result)


def _fd_code_to_canonical() -> dict[str, str]:
    """Canonical league ID (Match.league_id) → canonical league ID.

    After migration 0006_canonical_league_ids, _LEAGUE_META stores canonical
    SabiScore IDs directly (e.g. "EREDIVISIE") instead of fd.org codes ("DED").
    This function is now an identity map that validates which IDs are supported —
    derived from _LEAGUE_META so it stays in sync with what fixture_sync writes.

    Kept as a dict lookup (rather than set membership) so callers that use the
    return value as a translation table continue to work without code changes.
    """
    from .fixture_sync_service import _LEAGUE_META

    return {code: code for _name, (code, _country) in _LEAGUE_META.items()}


def _match_events_to_fixtures(
    records: list[dict[str, Any]], candidates: list[Any]
) -> dict[Any, list[dict[str, Any]]]:
    """Group odds-board records by provider_event_id, then match each event's
    kickoff timestamp to the single nearest candidate Match within tolerance.

    the_odds_api never returns team names in the normalized OddsMarketRecord
    (only per-bookmaker odds + provider_event_id + provider_event_timestamp),
    so kickoff-time proximity is the only signal available without touching
    the provider's existing, tested response contract. Ambiguous matches
    (zero or multiple candidates within tolerance) are skipped rather than
    guessed — a wrong match would misattribute a closing price to the wrong
    fixture, which is a provenance violation, not a missed capture.
    """
    by_event: dict[str, list[dict[str, Any]]] = {}
    event_kickoff: dict[str, datetime] = {}
    for record in records:
        event_id = record.get("provider_event_id")
        if not event_id:
            continue
        by_event.setdefault(event_id, []).append(record)
        ts = record.get("provider_event_timestamp")
        if ts and event_id not in event_kickoff:
            try:
                parsed = datetime.fromisoformat(ts) if isinstance(ts, str) else ts
                if isinstance(parsed, datetime):
                    event_kickoff[event_id] = _utc_naive(parsed)
            except (TypeError, ValueError):
                logger.warning(
                    "clv_capture: ignoring invalid provider event timestamp",
                    extra={"provider_event_id": event_id},
                )

    matched: dict[Any, list[dict[str, Any]]] = {}
    for event_id, event_records in by_event.items():
        kickoff = event_kickoff.get(event_id)
        if kickoff is None:
            continue
        close = [
            m
            for m in candidates
            if abs((m.match_date - kickoff).total_seconds()) <= _KICKOFF_MATCH_TOLERANCE_MINUTES * 60
        ]
        if len(close) == 1:
            matched[close[0]] = event_records
    return matched


async def run_clv_capture_pass(provider: Any = None) -> dict[str, Any]:
    """Never raises — every failure lands in the returned/stored dict,
    matching run_settlement_pass()'s swallow-and-log convention."""
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
                # A DBAPI/flush/commit failure leaves SQLAlchemy in partial-
                # rollback state until rollback() is called. Do this explicitly
                # before the pooled connection is released; relying only on
                # context-manager close made the production failure harder to
                # reason about and can surface later as PendingRollbackError.
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

    from ..core.config import settings
    from ..core.database import Match
    from ..core.league_policy import LeaguePolicyUnavailableError, canonical_league_id
    from ..db.models import MarketSnapshot
    from ..providers.the_odds_api import TheOddsAPIProvider, devig_probabilities

    now = _utc_naive(datetime.now(timezone.utc))  # Match.match_date is naive UTC
    window_end = now + timedelta(minutes=_CAPTURE_LOOKAHEAD_MINUTES)

    # Strictly future fixtures only. A scheduler wake after kickoff cannot recover
    # a pre-match close and must not manufacture one from an in-play observation.
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
        "unsupported_league": 0,
        "unmatched": 0,
        "post_kickoff_rejected": 0,
    }
    if not due:
        return counts

    already_captured_ids = set(
        (
            await session.execute(
                select(MarketSnapshot.match_id).where(
                    MarketSnapshot.match_id.in_([m.id for m in due]),
                    MarketSnapshot.is_closing_line.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )

    fd_to_canonical = _fd_code_to_canonical()
    by_league: dict[str, list[Match]] = {}
    for match in due:
        if match.id in already_captured_ids:
            counts["already_captured"] += 1
            continue
        league = fd_to_canonical.get(match.league_id)
        if league is None:
            counts["unsupported_league"] += 1
            continue
        by_league.setdefault(league, []).append(match)

    if not by_league:
        return counts

    provider = provider or TheOddsAPIProvider(
        api_key=settings.the_odds_api_key,
        enabled=settings.enable_the_odds_api_provider,
        live_tests=settings.provider_live_tests,
    )

    for league, matches in by_league.items():
        try:
            competition = canonical_league_id(league)
        except LeaguePolicyUnavailableError:
            counts["unsupported_league"] += len(matches)
            continue

        result = await provider.odds(competition=competition)
        records: list[dict[str, Any]] = result.records or []
        matched = _match_events_to_fixtures(records, matches)

        for match, event_records in matched.items():
            coherent = [r for r in event_records if r.get("coherent")]
            if not coherent:
                counts["unmatched"] += 1
                continue

            # Persist one bookmaker's complete 1X2 record. Independent medians
            # per outcome create a synthetic cross-bookmaker market.
            selected = min(coherent, key=lambda record: str(record.get("bookmaker", "")))
            home = selected["home_odds"]
            draw = selected["draw_odds"]
            away = selected["away_odds"]
            h_prob, d_prob, a_prob = devig_probabilities(home, draw, away)

            # Re-check the boundary after the provider request. A fixture can be
            # selected pre-kickoff and cross kickoff while network I/O is in
            # flight. Such a response is in-play evidence and must be rejected.
            captured_at = _utc_naive(datetime.now(timezone.utc))
            if not _is_strictly_pre_kickoff(captured_at, match.match_date):
                counts["post_kickoff_rejected"] += 1
                logger.warning(
                    "clv_capture: rejected observation at/after kickoff",
                    extra={"match_id": match.id, "league": league},
                )
                continue

            session.add(
                MarketSnapshot(
                    canonical_fixture_id=None,
                    match_id=match.id,
                    provider="the_odds_api",
                    bookmaker=str(selected.get("bookmaker") or "unknown"),
                    market_type="1X2",
                    home_odds=home,
                    draw_odds=draw,
                    away_odds=away,
                    home_implied_prob_devigged=h_prob,
                    draw_implied_prob_devigged=d_prob,
                    away_implied_prob_devigged=a_prob,
                    is_closing_line=True,
                    captured_at=captured_at,
                    coherent=True,
                    executable=False,
                    provenance={
                        "source": "the_odds_api",
                        "bookmaker": selected.get("bookmaker"),
                        "provider_event_id": selected.get("provider_event_id"),
                        "provider_captured_at": selected.get("captured_at"),
                        "evidence_class": "PRE_MATCH_CLOSING",
                    },
                )
            )
            counts["captured"] += 1

        counts["unmatched"] += len(matches) - len(matched)

    await session.commit()
    return counts