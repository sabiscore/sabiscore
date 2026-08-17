"""Deterministic pre-match 1X2 observation lifecycle persistence.

Accepted numerical observations are written to the existing ``OddsHistory``
time-series consumed by Phase-8 market-drift features. ``MarketSnapshot`` is the
existing evidence/provenance surface and records whether an accepted observation
is the first SabiScore observation, an intermediate change, or the strict final
pre-kickoff closing observation.

No bookmaker "opening line" is fabricated: PRE_MATCH_OPENING means only the
first real observation SabiScore saw *before* the closing window. If the first
observation arrives inside the closing window it is classified as closing and
opening evidence remains absent.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ..core.database import Match, OddsHistory, Team
from ..db.models import MarketSnapshot
from ..providers.the_odds_api import devig_probabilities
from .canonical_identity_service import canonical_fixture_id_for_provider_event

logger = logging.getLogger(__name__)

PRE_MATCH_OPENING = "PRE_MATCH_OPENING"
PRE_MATCH_INTERMEDIATE = "PRE_MATCH_INTERMEDIATE"
PRE_MATCH_CLOSING = "PRE_MATCH_CLOSING"
POST_KICKOFF_REJECTED = "POST_KICKOFF_REJECTED"
_PRE_MATCH_CLOSING_SUPERSEDED = "PRE_MATCH_CLOSING_SUPERSEDED"
_STALE_CLOSING_REJECTED = "STALE_CLOSING_REJECTED"

_KICKOFF_MATCH_TOLERANCE_MINUTES = 10
_CLOSING_WINDOW_MINUTES = 5


@dataclass
class MarketBoardCaptureResult:
    opening: int = 0
    intermediate: int = 0
    closing: int = 0
    deduped: int = 0
    rejected_post_kickoff: int = 0
    invalid: int = 0
    unmatched: int = 0
    ambiguous: int = 0
    write_errors: int = 0
    matched_match_ids: set[str] = field(default_factory=set)
    closing_match_ids: set[str] = field(default_factory=set)

    def as_counts(self) -> dict[str, int]:
        return {
            "opening": self.opening,
            "intermediate": self.intermediate,
            "closing": self.closing,
            "deduped": self.deduped,
            "post_kickoff_rejected": self.rejected_post_kickoff,
            "invalid_market": self.invalid,
            "unmatched_market": self.unmatched,
            "ambiguous_market": self.ambiguous,
            "write_errors": self.write_errors,
        }


@dataclass(frozen=True)
class _FixtureCandidate:
    match_id: str
    kickoff: datetime
    home_name: str
    away_name: str


def utc_naive(value: datetime) -> datetime:
    """Normalize a datetime to naive UTC for legacy PostgreSQL columns."""
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return utc_naive(value)
    if isinstance(value, str) and value.strip():
        try:
            return utc_naive(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def _team_key(value: object) -> str:
    """Conservative team-name key used only to narrow fixture identity."""
    key = re.sub(r"[^a-z0-9]", "", str(value).casefold())
    for prefix in ("afc", "cf"):
        if key.startswith(prefix) and len(key) > len(prefix) + 2:
            key = key[len(prefix) :]
            break
    for suffix in ("footballclub", "soccerclub", "afc", "fc", "cf", "sc"):
        if key.endswith(suffix) and len(key) > len(suffix) + 2:
            key = key[: -len(suffix)]
            break
    return key


def _same_prices(row: Any, *, home: float, draw: float, away: float) -> bool:
    return bool(row.home_win == home and row.draw == draw and row.away_win == away)


def _classify_observation(
    *,
    captured_at: datetime,
    kickoff: datetime,
    has_prior_observation: bool,
) -> str:
    captured = utc_naive(captured_at)
    kickoff_utc = utc_naive(kickoff)
    if captured >= kickoff_utc:
        return POST_KICKOFF_REJECTED
    if kickoff_utc - captured <= timedelta(minutes=_CLOSING_WINDOW_MINUTES):
        return PRE_MATCH_CLOSING
    if not has_prior_observation:
        return PRE_MATCH_OPENING
    return PRE_MATCH_INTERMEDIATE


async def _fixture_candidates(
    session: AsyncSession,
    *,
    league: str,
    observed_at: datetime,
) -> list[_FixtureCandidate]:
    home = aliased(Team)
    away = aliased(Team)
    lower_bound = utc_naive(observed_at) - timedelta(minutes=_KICKOFF_MATCH_TOLERANCE_MINUTES)
    rows = (
        await session.execute(
            select(Match, home.name, away.name)
            .join(home, Match.home_team_id == home.id)
            .join(away, Match.away_team_id == away.id)
            .where(
                Match.status == "scheduled",
                Match.league_id == league,
                Match.match_date >= lower_bound,
            )
        )
    ).all()

    candidates: list[_FixtureCandidate] = []
    for row in rows:
        runtime_match = cast(Any, row[0])
        if not isinstance(runtime_match.match_date, datetime):
            continue
        candidates.append(
            _FixtureCandidate(
                match_id=str(runtime_match.id),
                kickoff=utc_naive(runtime_match.match_date),
                home_name=str(row[1]),
                away_name=str(row[2]),
            )
        )
    return candidates


def _match_record(
    record: dict[str, Any], candidates: list[_FixtureCandidate]
) -> tuple[_FixtureCandidate | None, bool]:
    event_kickoff = _parse_datetime(record.get("provider_event_timestamp"))
    home_key = _team_key(record.get("home_team", ""))
    away_key = _team_key(record.get("away_team", ""))
    if event_kickoff is None or not home_key or not away_key:
        return None, False

    matches = [
        candidate
        for candidate in candidates
        if _team_key(candidate.home_name) == home_key
        and _team_key(candidate.away_name) == away_key
        and abs((candidate.kickoff - event_kickoff).total_seconds())
        <= _KICKOFF_MATCH_TOLERANCE_MINUTES * 60
    ]
    if len(matches) == 1:
        return matches[0], False
    return None, len(matches) > 1


def _valid_record(record: dict[str, Any]) -> tuple[float, float, float] | None:
    if not record.get("coherent") or not record.get("executable"):
        return None
    try:
        home = float(record["home_odds"])
        draw = float(record["draw_odds"])
        away = float(record["away_odds"])
    except (KeyError, TypeError, ValueError):
        return None
    if any(value <= 1.0 for value in (home, draw, away)):
        return None
    return home, draw, away


async def _current_closings(
    session: AsyncSession,
    *,
    match_id: str,
) -> list[MarketSnapshot]:
    return list(
        (
            (
                await session.execute(
                    select(MarketSnapshot)
                    .where(
                        MarketSnapshot.match_id == match_id,
                        MarketSnapshot.is_closing_line.is_(True),
                    )
                    .order_by(MarketSnapshot.captured_at.desc(), MarketSnapshot.id.desc())
                )
            )
            .scalars()
            .all()
        )
    )


async def _supersede_previous_closings(
    session: AsyncSession,
    *,
    match_id: str,
    captured_at: datetime,
) -> str | None:
    """Supersede every earlier current close; reject out-of-order close writes."""
    previous_rows = await _current_closings(session, match_id=match_id)
    if any(row.captured_at >= captured_at for row in previous_rows):
        return _STALE_CLOSING_REJECTED

    for previous in previous_rows:
        provenance = dict(previous.provenance or {})
        provenance["evidence_class"] = _PRE_MATCH_CLOSING_SUPERSEDED
        provenance["superseded_at"] = captured_at.isoformat()
        previous.provenance = provenance
        previous.is_closing_line = False
    return None


async def _persist_record(
    session: AsyncSession,
    *,
    candidate: _FixtureCandidate,
    record: dict[str, Any],
    observed_at: datetime,
) -> str:
    prices = _valid_record(record)
    if prices is None:
        return "INVALID"
    home, draw, away = prices
    bookmaker = str(record.get("bookmaker") or "unknown")[:255]

    latest = (
        (
            await session.execute(
                select(OddsHistory)
                .where(
                    OddsHistory.match_id == candidate.match_id,
                    OddsHistory.bookmaker == bookmaker,
                    OddsHistory.market_type == "match_odds",
                )
                .order_by(OddsHistory.timestamp.desc(), OddsHistory.id.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )

    captured_at = utc_naive(observed_at)
    classification = _classify_observation(
        captured_at=captured_at,
        kickoff=candidate.kickoff,
        has_prior_observation=latest is not None,
    )
    if classification == POST_KICKOFF_REJECTED:
        return classification

    # Unchanged opening/intermediate prices are not new numerical evidence.
    # Closing is different: even an unchanged price needs a fresh observation
    # timestamp proving it was still the final eligible pre-kickoff line.
    if (
        classification != PRE_MATCH_CLOSING
        and latest is not None
        and _same_prices(latest, home=home, draw=draw, away=away)
    ):
        return "DEDUPED"

    if classification == PRE_MATCH_CLOSING:
        closing_guard = await _supersede_previous_closings(
            session,
            match_id=candidate.match_id,
            captured_at=captured_at,
        )
        if closing_guard is not None:
            return closing_guard

    history = OddsHistory(
        match_id=candidate.match_id,
        bookmaker=bookmaker,
        market_type="match_odds",
        home_win=home,
        draw=draw,
        away_win=away,
        timestamp=captured_at,
        created_at=captured_at,
    )
    session.add(history)
    await session.flush()
    runtime_history = cast(Any, history)

    canonical_fixture_id = await canonical_fixture_id_for_provider_event(
        session,
        provider="football-data.org",
        provider_event_id=candidate.match_id,
    )
    provider_timestamp = _parse_datetime(record.get("bookmaker_last_update"))
    h_prob, d_prob, a_prob = devig_probabilities(home, draw, away)

    provenance: dict[str, Any] = {
        "source": "the_odds_api",
        "evidence_class": classification,
        "provider_event_id": record.get("provider_event_id"),
        "provider_event_timestamp": record.get("provider_event_timestamp"),
        "provider_captured_at": record.get("captured_at"),
        "bookmaker_last_update": record.get("bookmaker_last_update"),
        "odds_history_id": runtime_history.id,
        "fixture_match_method": "home_away_identity_plus_kickoff_tolerance",
        "provider_executable": bool(record.get("executable")),
    }
    if classification == PRE_MATCH_OPENING:
        provenance["opening_semantics"] = "first_observed_by_sabiscore"

    session.add(
        MarketSnapshot(
            canonical_fixture_id=canonical_fixture_id,
            match_id=candidate.match_id,
            provider="the_odds_api",
            bookmaker=bookmaker,
            market_type="1X2",
            home_odds=home,
            draw_odds=draw,
            away_odds=away,
            home_implied_prob_devigged=h_prob,
            draw_implied_prob_devigged=d_prob,
            away_implied_prob_devigged=a_prob,
            is_closing_line=classification == PRE_MATCH_CLOSING,
            provider_timestamp=provider_timestamp,
            captured_at=captured_at,
            coherent=True,
            # This field is not a staking gate. Keep false so persisted market
            # evidence cannot be misconstrued as permission to execute a bet.
            executable=False,
            provenance=provenance,
        )
    )
    return classification


async def persist_market_board(
    session: AsyncSession,
    *,
    league: str,
    records: list[dict[str, Any]],
    observed_at: datetime | None = None,
) -> MarketBoardCaptureResult:
    """Persist changed real observations from one already-fetched league board.

    The caller owns the provider request. This function deliberately performs no
    network I/O, so capturing opening/intermediate rows from the same board does
    not increase provider quota consumption.
    """
    result = MarketBoardCaptureResult()
    observed = utc_naive(observed_at or datetime.now(timezone.utc))
    candidates = await _fixture_candidates(session, league=league, observed_at=observed)

    # The Odds API returns one record per bookmaker. Preserve the existing CLV
    # convention of one deterministic bookmaker per provider event rather than
    # synthesizing a cross-bookmaker 1X2 market or multiplying closing joins.
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        event_id = str(record.get("provider_event_id") or "")
        if not event_id:
            result.invalid += 1
            continue
        grouped.setdefault(event_id, []).append(record)

    for event_records in grouped.values():
        coherent = [record for record in event_records if _valid_record(record) is not None]
        if not coherent:
            result.invalid += 1
            continue
        selected = min(coherent, key=lambda record: str(record.get("bookmaker") or ""))
        candidate, ambiguous = _match_record(selected, candidates)
        if candidate is None:
            if ambiguous:
                result.ambiguous += 1
            else:
                result.unmatched += 1
            continue

        result.matched_match_ids.add(candidate.match_id)
        try:
            async with session.begin_nested():
                classification = await _persist_record(
                    session,
                    candidate=candidate,
                    record=selected,
                    observed_at=observed,
                )
        except Exception:
            result.write_errors += 1
            logger.exception(
                "market_observation: isolated observation write failed",
                extra={"match_id": candidate.match_id, "league": league},
            )
            continue

        if classification == PRE_MATCH_OPENING:
            result.opening += 1
        elif classification == PRE_MATCH_INTERMEDIATE:
            result.intermediate += 1
        elif classification == PRE_MATCH_CLOSING:
            result.closing += 1
            result.closing_match_ids.add(candidate.match_id)
        elif classification == POST_KICKOFF_REJECTED:
            result.rejected_post_kickoff += 1
            logger.warning(
                "market_observation: rejected observation at/after kickoff",
                extra={"match_id": candidate.match_id, "league": league},
            )
        elif classification in {"DEDUPED", _STALE_CLOSING_REJECTED}:
            result.deduped += 1
        else:
            result.invalid += 1

    return result


__all__ = [
    "MarketBoardCaptureResult",
    "POST_KICKOFF_REJECTED",
    "PRE_MATCH_CLOSING",
    "PRE_MATCH_INTERMEDIATE",
    "PRE_MATCH_OPENING",
    "persist_market_board",
    "utc_naive",
]
