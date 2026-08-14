"""Single source of truth for next-season start dates.

Verified 2026-08-04 against football-data.org ``GET /v4/competitions/{code}``
→ ``currentSeason.startDate`` — the same provider the fixture sync ingests
from, so the date the UI promises and the date fixtures actually appear
cannot drift apart.

Three endpoint modules (``upcoming_matches``, ``leagues``, ``offseason``) each
carried an independent copy of this table and had drifted badly: EPL and
Ligue 1 both read ``2026-08-08`` against real openers of ``2026-08-21`` and
``2026-08-22``, so the off-season notice promised fixtures nearly two weeks
before the provider had any. Same duplicated-vocabulary defect class as the
season-label fracture that ``utils/season.py`` was created to close.
"""

from __future__ import annotations

from typing import Dict, Optional

# Canonical league id -> ISO date of the first fixture of the 2026/27 season.
_NEXT_SEASON_START: Dict[str, str] = {
    "EPL": "2026-08-21",
    "LA_LIGA": "2026-08-16",
    "BUNDESLIGA": "2026-08-28",
    "SERIE_A": "2026-08-23",
    "LIGUE_1": "2026-08-22",
    "EREDIVISIE": "2026-08-07",
    # ESTIMATE — football-data.org still reports 2025/26 as CL's current season,
    # so 2026/27 has no published start date yet. Mid-September mirrors the last
    # two league-phase openers (2024-09-17, 2025-09-16). Re-derive from
    # currentSeason.startDate once the provider publishes it.
    "UCL": "2026-09-15",
}

# Dates whose provider authority has not yet published the next-season value.
# Keep this metadata beside the date itself so every consumer tells the same
# truth about the calendar confidence.
_ESTIMATED_STARTS = {"UCL"}

# Earliest supported opener. Used when the league is unknown or absent so the
# caller still gets a plausible, soon re-checked date rather than None.
_DEFAULT_START: str = min(_NEXT_SEASON_START.values())

# Alias forms that do not upper-case cleanly into a canonical id.
_ALIASES: Dict[str, str] = {
    "premier_league": "EPL",
    "laliga": "LA_LIGA",
    "seriea": "SERIE_A",
    "ligue1": "LIGUE_1",
    "champions_league": "UCL",
    "uefa_champions_league": "UCL",
}


def canonical_key(league: Optional[str]) -> Optional[str]:
    """Fold any accepted league spelling to its canonical id, or None if absent.

    Accepts every vocabulary in use: canonical (``LA_LIGA``), display
    (``La Liga``), and slug (``la_liga`` / ``laliga``).
    """
    if league is None or not str(league).strip():
        return None
    slug = str(league).strip().lower().replace("-", "_").replace(" ", "_")
    return _ALIASES.get(slug, slug.upper())


def next_season_start(
    league: Optional[str],
    default: Optional[str] = _DEFAULT_START,
) -> Optional[str]:
    """ISO date the given league's next season starts.

    Unknown or absent leagues fall back to ``default`` (the earliest supported
    opener) rather than None, preserving the pre-existing endpoint contract.
    """
    key = canonical_key(league)
    if key is None:
        return default
    return _NEXT_SEASON_START.get(key, default)


def next_season_start_estimated(league: Optional[str]) -> Optional[bool]:
    """Whether the canonical next-season date is an estimate.

    ``None`` means the league is not represented in the authoritative table;
    callers must not attach confidence metadata to a fallback date.
    """
    key = canonical_key(league)
    if key not in _NEXT_SEASON_START:
        return None
    return key in _ESTIMATED_STARTS


__all__ = ["canonical_key", "next_season_start", "next_season_start_estimated"]
