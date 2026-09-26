"""Scheduled pre-kickoff prediction capture (directive v9 §2.3, L4).

``persist_prediction_log`` used to run only when a person opened a fixture, so
settled evidence grew with traffic rather than with fixtures: on 2026-09-25 the
served generation had 0 settled predictions. This pass rides the five-minute
CLV tick and captures one forecast per scheduled fixture shortly before kickoff.

It runs the endpoint's own analysis path (``get_full_analysis``) rather than a
copy, so the captured snapshot is exactly what a user would have been served.
That path already refuses matchups, diagnostic baselines, non-scheduled fixtures
and post-kickoff requests, and deduplicates by input hash; this pass adds only
fixture selection. It writes research evidence, never a stake.

Never backfill: a prediction made after the result is known is leakage. The
window below starts in the future for exactly that reason.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import select

from ..core.database import Match
from ..core.league_policy import LeaguePolicyUnavailableError, canonical_league_id
from ..core.redaction import redact_text
from ..db.models import MatchPredictionLog
from ..models.active_generation import (
    ActiveGenerationError,
    read_active_manifest,
    served_identity,
)
from ..monitoring.metrics import metrics_collector

logger = logging.getLogger(__name__)

# A fixture is captured once, somewhere in [kickoff - 3h, kickoff - 15min]. The
# five-minute tick gives each fixture ~33 chances, and the 15-minute margin keeps
# the (sub-second) analysis clear of kickoff.
CAPTURE_WINDOW_START = timedelta(minutes=15)
CAPTURE_WINDOW_END = timedelta(hours=3)

Analyze = Callable[..., Awaitable[Any]]

_last_result: dict[str, Any] = {"outcome": "never_run"}

# Directive v11 §1: the matchday burst is read after the fact, not by polling
# /health every five minutes. Passes that had work to do (or failed), with the
# process RSS after each; idle passes are skipped, so 48 entries cover a whole
# matchday window (about 45 five-minute ticks). Lost on restart, like _last_result.
_RECENT_PASSES: deque[dict[str, Any]] = deque(maxlen=48)


def _rss_mb() -> Optional[int]:
    try:
        import psutil  # type: ignore[import-untyped]

        return int(psutil.Process().memory_info().rss // (1024 * 1024))
    except Exception:
        return None


def last_prediction_capture_result() -> dict[str, Any]:
    """Sync accessor for /health; return a copy, never the live result dict."""
    return {**_last_result, "recent": list(_RECENT_PASSES)}


def _utc_naive(value: datetime) -> datetime:
    """``Match.match_date`` is a naive UTC column; a naive input is already UTC."""
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _supported_leagues(manifest: dict[str, Any]) -> set[str]:
    """Leagues the served generation has an artifact for (UCL has none)."""
    leagues: set[str] = set()
    for slug in manifest.get("artifacts") or {}:
        try:
            leagues.add(canonical_league_id(str(slug)))
        except LeaguePolicyUnavailableError:
            continue
    return leagues


async def _identity_has_log(session: Any, match_id: str, identity: str) -> bool:
    row = (
        await session.execute(
            select(MatchPredictionLog.id)
            .where(
                MatchPredictionLog.match_id == match_id,
                MatchPredictionLog.model_version == identity,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


async def capture_due_predictions(
    session: Any,
    *,
    analyze: Analyze,
    odds_service: Any = None,
    now: Optional[datetime] = None,
) -> dict[str, int]:
    """Capture one forecast per due fixture that has none under the served identity."""

    manifest = read_active_manifest()
    identity = served_identity(manifest)
    supported = _supported_leagues(manifest)

    current = _utc_naive(now or datetime.now(timezone.utc))
    due = (
        (
            await session.execute(
                select(Match)
                .where(
                    Match.status == "scheduled",
                    Match.match_date >= current + CAPTURE_WINDOW_START,
                    Match.match_date <= current + CAPTURE_WINDOW_END,
                )
                .order_by(Match.match_date, Match.id)
            )
        )
        .scalars()
        .all()
    )

    counts = {
        "due": len(due),
        "captured": 0,
        "already_captured": 0,
        "not_captured": 0,
        "unsupported_league": 0,
        "errors": 0,
    }
    # Plain values before any analysis: a rollback below expires ORM instances.
    fixtures = [(str(m.id), str(m.league_id or "")) for m in due]

    for match_id, raw_league in fixtures:
        try:
            league = canonical_league_id(raw_league)
        except LeaguePolicyUnavailableError:
            league = ""
        if league not in supported:
            counts["unsupported_league"] += 1
            continue
        if await _identity_has_log(session, match_id, identity):
            counts["already_captured"] += 1
            continue

        try:
            await analyze(
                match_id=match_id, league=league, db=session, odds_service=odds_service
            )
        except Exception as exc:
            # One fixture must never cost the rest of the round.
            counts["errors"] += 1
            try:
                await session.rollback()
            except Exception:
                logger.exception("prediction_capture: rollback failed")
            logger.warning(
                "prediction_capture: analysis failed for %s: %s: %s",
                match_id,
                type(exc).__name__,
                redact_text(exc),
            )
            continue

        # The endpoint commits its own capture, or declines it (baseline,
        # unverified identity, unavailable prediction). Read which happened.
        if await _identity_has_log(session, match_id, identity):
            counts["captured"] += 1
        else:
            counts["not_captured"] += 1

    for key in ("captured", "not_captured", "errors"):
        if counts[key]:
            metrics_collector.increment(f"prediction_capture.{key}", counts[key])
    return counts


async def run_prediction_capture_pass(
    odds_service: Any = None, *, analyze: Optional[Analyze] = None
) -> dict[str, Any]:
    """One capture pass in a short-lived session; never raises."""
    global _last_result

    from ..db.session import AsyncSessionLocal

    checked_at = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()
    if AsyncSessionLocal is None:
        _last_result = {"outcome": "db_not_ready", "checked_at": checked_at}
        return _last_result

    if analyze is None:
        # ponytail: a service importing an endpoint inverts the layering, but it is
        # the only way to capture exactly what users are served. Move the body of
        # get_full_analysis into a service when a second caller needs it.
        from ..api.endpoints.full_analysis import get_full_analysis

        analyze = get_full_analysis

    try:
        async with AsyncSessionLocal() as session:
            counts = await capture_due_predictions(
                session, analyze=analyze, odds_service=odds_service
            )
        _last_result = {"outcome": "ok", "checked_at": checked_at, **counts}
    except ActiveGenerationError as exc:
        # A row whose generation cannot be named is not evidence for any one.
        _last_result = {
            "outcome": "manifest_unreadable",
            "checked_at": checked_at,
            "message": redact_text(str(exc)),
        }
    except Exception as exc:
        logger.exception("prediction_capture: unhandled error")
        _last_result = {
            "outcome": "error",
            "checked_at": checked_at,
            "message": redact_text(str(exc)),
        }
    # Directive v10 D1: a matchday burst runs sequentially inside the CLV tick,
    # so its wall time is what to watch against the five-minute cadence.
    _last_result["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
    if _last_result.get("due") or _last_result["outcome"] != "ok":
        _RECENT_PASSES.append(
            {
                key: _last_result.get(key)
                for key in ("checked_at", "outcome", "due", "captured", "errors", "duration_ms")
            }
            | {"rss_mb": _rss_mb()}
        )
    return _last_result


__all__ = [
    "CAPTURE_WINDOW_END",
    "CAPTURE_WINDOW_START",
    "capture_due_predictions",
    "last_prediction_capture_result",
    "run_prediction_capture_pass",
]
