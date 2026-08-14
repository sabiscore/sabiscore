"""Offseason metadata endpoint — GET /leagues/{league}/offseason-status.

Returns season calendar metadata for a domestic league or competition.
Designed to let the frontend surface an off-season notice and suppress
prediction calls when live fixtures are unavailable.

No live DB query is required for this endpoint — it is driven by a hardcoded
season-boundary table that mirrors known kick-off schedules.  The table
is intentionally conservative: ``IN_SEASON`` is preferred over ``OFF_SEASON``
when the boundary is ambiguous.
"""

from __future__ import annotations

from datetime import date
from typing import Dict, Tuple

from fastapi import APIRouter

from ...core.season_calendar import (
    next_season_start as _canonical_start,
    next_season_start_estimated as _canonical_start_estimated,
)

router = APIRouter(prefix="/leagues", tags=["offseason", "seasons"])

# Start dates for the seven supported competitions come from
# core.season_calendar (provider-verified). Leagues outside that closed set
# keep their local estimates — they are not synced and have no authority to
# check against.
_EPL_START = _canonical_start("EPL")
_LA_LIGA_START = _canonical_start("LA_LIGA")
_BUNDESLIGA_START = _canonical_start("BUNDESLIGA")
_SERIE_A_START = _canonical_start("SERIE_A")
_LIGUE_1_START = _canonical_start("LIGUE_1")
_EREDIVISIE_START = _canonical_start("EREDIVISIE")
_UCL_START = _canonical_start("UCL")

# ---------------------------------------------------------------------------
# Season boundary table
# Keys: normalised league slug (lowercase, underscores)
# Values: dict with per-season end date and next-season start date (YYYY-MM-DD)
# ---------------------------------------------------------------------------

_SEASON_TABLE: Dict[str, Dict[str, str]] = {
    # ── England ──────────────────────────────────────────────────────────────
    "epl": {
        "current_season_label": "2025-26",
        "current_season_end": "2026-05-19",
        "next_season_start": _EPL_START,
        "display_name": "Premier League",
    },
    "premier_league": {
        "current_season_label": "2025-26",
        "current_season_end": "2026-05-19",
        "next_season_start": _EPL_START,
        "display_name": "Premier League",
    },
    "championship": {
        "current_season_label": "2025-26",
        "current_season_end": "2026-05-09",
        "next_season_start": "2026-08-01",
        "display_name": "EFL Championship",
    },
    # ── Spain ────────────────────────────────────────────────────────────────
    "la_liga": {
        "current_season_label": "2025-26",
        "current_season_end": "2026-05-24",
        "next_season_start": _LA_LIGA_START,
        "display_name": "La Liga",
    },
    "laliga": {
        "current_season_label": "2025-26",
        "current_season_end": "2026-05-24",
        "next_season_start": _LA_LIGA_START,
        "display_name": "La Liga",
    },
    # ── Germany ──────────────────────────────────────────────────────────────
    "bundesliga": {
        "current_season_label": "2025-26",
        "current_season_end": "2026-05-16",
        "next_season_start": _BUNDESLIGA_START,
        "display_name": "Bundesliga",
    },
    # ── Italy ────────────────────────────────────────────────────────────────
    "serie_a": {
        "current_season_label": "2025-26",
        "current_season_end": "2026-05-24",
        "next_season_start": _SERIE_A_START,
        "display_name": "Serie A",
    },
    "seriea": {
        "current_season_label": "2025-26",
        "current_season_end": "2026-05-24",
        "next_season_start": _SERIE_A_START,
        "display_name": "Serie A",
    },
    # ── France ───────────────────────────────────────────────────────────────
    "ligue_1": {
        "current_season_label": "2025-26",
        "current_season_end": "2026-05-17",
        "next_season_start": _LIGUE_1_START,
        "display_name": "Ligue 1",
    },
    "ligue1": {
        "current_season_label": "2025-26",
        "current_season_end": "2026-05-17",
        "next_season_start": _LIGUE_1_START,
        "display_name": "Ligue 1",
    },
    # ── Netherlands ──────────────────────────────────────────────────────────
    "eredivisie": {
        "current_season_label": "2025-26",
        "current_season_end": "2026-05-15",
        "next_season_start": _EREDIVISIE_START,
        "display_name": "Eredivisie",
    },
    # ── Portugal ─────────────────────────────────────────────────────────────
    "primeira_liga": {
        # Outside the supported seven — local estimate, no provider authority.
        "current_season_label": "2025-26",
        "current_season_end": "2026-05-17",
        "next_season_start": "2026-08-08",
        "display_name": "Primeira Liga",
    },
    # ── UEFA ─────────────────────────────────────────────────────────────────
    "ucl": {
        "current_season_label": "2025-26",
        "current_season_end": "2026-05-30",
        "next_season_start": _UCL_START,
        "display_name": "UEFA Champions League",
    },
    "champions_league": {
        "current_season_label": "2025-26",
        "current_season_end": "2026-05-30",
        "next_season_start": _UCL_START,
        "display_name": "UEFA Champions League",
    },
    "uel": {
        "current_season_label": "2025-26",
        "current_season_end": "2026-05-20",
        "next_season_start": "2026-09-17",
        "display_name": "UEFA Europa League",
    },
}


def _normalise_league(league: str) -> str:
    return league.lower().strip().replace(" ", "_").replace("-", "_")


def _compute_status(
    today: date,
    current_season_end: str,
    next_season_start: str,
) -> Tuple[str, int]:
    """Return (season_status, days_until_next_season).

    season_status is one of: ``IN_SEASON`` | ``OFF_SEASON``.
    ``days_until_next_season`` is 0 when IN_SEASON.
    """
    end_date = date.fromisoformat(current_season_end)
    start_date = date.fromisoformat(next_season_start)

    if today <= end_date:
        # Matches are still being played
        return "IN_SEASON", 0
    if today >= start_date:
        # Next season has already kicked off
        return "IN_SEASON", 0
    days_until = (start_date - today).days
    return "OFF_SEASON", days_until


def _data_availability(season_status: str) -> Dict[str, bool]:
    """Return per-source data availability flags given season status."""
    live = season_status == "IN_SEASON"
    return {
        "historical_data": True,           # always available from DB
        "live_odds": live,
        "live_standings": live,
        "live_form": live,
        "pi_ratings": True,                # computed offline, always available
        "berrar_ratings": True,            # computed offline, always available
        "market_drift": live,
        "match_context": live,
    }


def _prediction_advisory(season_status: str, days_until: int) -> str:
    if season_status == "IN_SEASON":
        return "Full live-enrichment pipeline active. Predictions use all Phase 8 signals."
    if days_until > 60:
        return (
            f"Off-season: {days_until} days until next season. "
            "Historical model is active; live enrichment unavailable."
        )
    if days_until > 14:
        return (
            f"Pre-season: {days_until} days until kick-off. "
            "Fixture schedule and odds may be available soon."
        )
    return (
        f"Season starting in {days_until} day(s). "
        "Fixture data should be available shortly."
    )


@router.get(
    "/{league}/offseason-status",
    summary="League season calendar and off-season metadata",
    response_model=None,
)
async def get_offseason_status(league: str) -> dict:
    """Return season status, next season start date, and data availability flags.

    Designed for frontend components that need to decide whether to suppress
    prediction calls or surface an off-season notice to users.

    ``season_status`` is one of:
    - ``IN_SEASON`` — fixtures are live; full pipeline is active
    - ``OFF_SEASON`` — inter-season break; live enrichment unavailable
    - ``UNKNOWN`` — league not in the season calendar (unsupported slug)
    """
    slug = _normalise_league(league)
    today = date.today()

    entry = _SEASON_TABLE.get(slug)
    if entry is None:
        return {
            "league": league,
            "league_slug": slug,
            "season_status": "UNKNOWN",
            "message": (
                f"League '{league}' is not in the season calendar. "
                "Supported leagues: "
                + ", ".join(sorted({v['display_name'] for v in _SEASON_TABLE.values()}))
            ),
            "current_season_label": None,
            "current_season_end": None,
            "next_season_start": None,
            "next_season_start_estimated": None,
            "days_until_next_season": None,
            "data_availability": _data_availability("UNKNOWN"),
            "prediction_advisory": "Season calendar unavailable for this league.",
        }

    season_status, days_until = _compute_status(
        today,
        entry["current_season_end"],
        entry["next_season_start"],
    )

    return {
        "league": entry["display_name"],
        "league_slug": slug,
        "season_status": season_status,
        "current_season_label": entry["current_season_label"],
        "current_season_end": entry["current_season_end"],
        "next_season_start": entry["next_season_start"],
        "next_season_start_estimated": _canonical_start_estimated(slug),
        "days_until_next_season": days_until if season_status == "OFF_SEASON" else 0,
        "data_availability": _data_availability(season_status),
        "prediction_advisory": _prediction_advisory(season_status, days_until),
        "queried_at": today.isoformat(),
    }
