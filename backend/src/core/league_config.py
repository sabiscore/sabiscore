"""Phase F: ACTIVE_LEAGUES inventory — per-league coverage tier and UCL soft-coverage config.

Each ``LeagueProfile`` describes the coverage level (FULL / SOFT / EXPERIMENTAL),
the minimum training seasons required to reach FULL confidence, and whether the
league may serve predictions when the model confidence tier is LOW_EVIDENCE.

UCL is intentionally SOFT: the training corpus is smaller than domestic leagues,
so epistemic uncertainty is higher for knockout-stage fixtures. Predictions are
allowed but surface an explicit ``caveat_text`` in the actionability block.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, Optional


@dataclass(frozen=True)
class LeagueProfile:
    id: str
    """Internal league identifier matching the ``league`` param on all API endpoints."""
    name: str
    """Human-readable display name."""
    coverage: str
    """
    Coverage tier:
      FULL         — ≥5 seasons of training data, full feature set, no LOW_EVIDENCE override.
      SOFT         — Reduced training corpus. Predictions allowed with LOW_EVIDENCE caveat.
      EXPERIMENTAL — Feature-incomplete; only available when UCL_LOW_EVIDENCE_OVERRIDE=true.
    """
    model_min_seasons: int
    """Seasons of walk-forward training data required before FULL coverage is declared."""
    low_evidence_allowed: bool
    """When True, requests that produce LOW_EVIDENCE confidence_tier are still served."""
    caveat_text: Optional[str] = None
    """Shown in actionability.caveats when low_evidence_allowed=True and tier is LOW_EVIDENCE."""


ACTIVE_LEAGUES: FrozenSet[LeagueProfile] = frozenset(
    [
        LeagueProfile(
            id="EPL",
            name="Premier League",
            coverage="FULL",
            model_min_seasons=5,
            low_evidence_allowed=False,
        ),
        LeagueProfile(
            id="La Liga",
            name="La Liga",
            coverage="FULL",
            model_min_seasons=5,
            low_evidence_allowed=False,
        ),
        LeagueProfile(
            id="Serie A",
            name="Serie A",
            coverage="FULL",
            model_min_seasons=5,
            low_evidence_allowed=False,
        ),
        LeagueProfile(
            id="Bundesliga",
            name="Bundesliga",
            coverage="FULL",
            model_min_seasons=5,
            low_evidence_allowed=False,
        ),
        LeagueProfile(
            id="Ligue 1",
            name="Ligue 1",
            coverage="FULL",
            model_min_seasons=5,
            low_evidence_allowed=False,
        ),
        LeagueProfile(
            id="Eredivisie",
            name="Eredivisie",
            coverage="SOFT",  # aligned with league_policy.py DEFAULT_PENDING_CALIBRATION
            model_min_seasons=5,
            low_evidence_allowed=True,
            caveat_text=(
                "Eredivisie coverage is pending full calibration. "
                "Predictions may carry higher epistemic uncertainty. "
                "Treat as informational and apply stricter personal thresholds."
            ),
        ),
        LeagueProfile(
            id="UCL",
            name="UEFA Champions League",
            coverage="SOFT",
            model_min_seasons=3,
            low_evidence_allowed=True,
            caveat_text=(
                "UCL coverage uses soft-evidence inference. "
                "Predictions may carry higher epistemic uncertainty than domestic league models. "
                "Treat as informational only and apply stricter personal thresholds."
            ),
        ),
    ]
)

# O(1) lookup by league ID
LEAGUE_BY_ID: Dict[str, LeagueProfile] = {
    league.id: league for league in ACTIVE_LEAGUES
}


def get_league_profile(league_id: str) -> Optional[LeagueProfile]:
    """Return the LeagueProfile for ``league_id``, or None if not found."""
    return LEAGUE_BY_ID.get(league_id)


def is_active_league(league_id: str) -> bool:
    """True when ``league_id`` is in the ACTIVE_LEAGUES inventory."""
    return league_id in LEAGUE_BY_ID


def allows_low_evidence(league_id: str) -> bool:
    """True when the league allows LOW_EVIDENCE predictions (soft coverage only)."""
    profile = LEAGUE_BY_ID.get(league_id)
    return profile is not None and profile.low_evidence_allowed
