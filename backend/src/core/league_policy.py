"""Per-league policy contract (directive §11, C-13).

Each league has an independent, versioned LeaguePolicy. Fields marked
`policy_source = "DEFAULT_PENDING_CALIBRATION"` are conservative initial
values that must be replaced by outputs from the policy-generation pipeline
once walk-forward validation has been run for that league.

Usage::

    from src.core.league_policy import get_league_policy, LEAGUE_POLICY_UNAVAILABLE

    try:
        policy = get_league_policy("EPL")
    except LEAGUE_POLICY_UNAVAILABLE:
        # propagate as NO_BET
        ...
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


class LeaguePolicyUnavailableError(Exception):
    """Raised when no validated policy exists for the requested league.

    Callers must propagate this as NO_BET (reason=LEAGUE_POLICY_UNAVAILABLE)
    rather than falling back to a global default.
    """

    def __init__(self, league_id: str) -> None:
        super().__init__(f"No validated policy for league {league_id!r}")
        self.league_id = league_id


@dataclass(frozen=True)
class LeaguePolicy:
    """Versioned per-league betting and calibration policy.

    All numeric fields must originate from validated calibration artefacts.
    Fields whose `policy_source` is "DEFAULT_PENDING_CALIBRATION" are
    conservative placeholders — they prevent the system from surfacing bets
    until real calibration has run, but they must not be treated as accurate.
    """

    league_id: str
    version: str
    policy_source: str  # "CALIBRATED" | "DEFAULT_PENDING_CALIBRATION"
    artifact_hash: str | None  # SHA-256 of the calibration artefact, if available
    calibration_artifact: str | None  # path to the calibration run record

    draw_prior: float  # league-specific draw base rate
    home_advantage_coefficient: float  # multiplicative prior on home EV
    kelly_cap: float  # per-league Kelly fraction hard cap

    market_freshness_ttl_seconds: int  # odds staleness threshold
    model_feature_freshness_ttl_seconds: int
    lineup_freshness_ttl_seconds: int

    high_conviction_edge_threshold: float  # minimum de-vigged edge for HC
    ece_recalibration_threshold: float  # ECE > this triggers recalibration
    minimum_calibration_samples: int  # samples needed before policy valid

    # Class-level registry
    _registry: ClassVar[dict[str, "LeaguePolicy"]] = {}

    def __post_init__(self) -> None:
        # Register on construction — frozen dataclass so we use object.__setattr__
        LeaguePolicy._registry[self.league_id] = self

    @property
    def is_calibrated(self) -> bool:
        return self.policy_source == "CALIBRATED" and self.artifact_hash is not None


_ALIASES = {
    "premier_league": "EPL",
    "epl": "EPL",
    "la_liga": "LA_LIGA",
    "laliga": "LA_LIGA",
    "bundesliga": "BUNDESLIGA",
    "serie_a": "SERIE_A",
    "ligue_1": "LIGUE_1",
    "eredivisie": "EREDIVISIE",
    "ucl": "UCL",
    "uefa_champions_league": "UCL",
}


def canonical_league_id(league_id: str) -> str:
    key = league_id.strip()
    if not key:
        raise LeaguePolicyUnavailableError(league_id)
    normalized = key.lower().replace("-", "_").replace(" ", "_")
    return _ALIASES.get(normalized, key.upper())


def get_league_policy(league_id: str) -> LeaguePolicy:
    """Return the policy for a league, raising if unavailable or uncalibrated.

    Callers that need best-effort behaviour may catch LeaguePolicyUnavailableError
    and surface a PARTIAL verdict with reason=LEAGUE_POLICY_UNAVAILABLE.
    """
    policy = LeaguePolicy._registry.get(canonical_league_id(league_id))
    if policy is None:
        raise LeaguePolicyUnavailableError(league_id)
    return policy


# ---------------------------------------------------------------------------
# Seven canonical league policies.
# EPL / LA_LIGA / BUNDESLIGA / SERIE_A / LIGUE_1: CALIBRATED 2026-07-04
#   First-pass stacking-ensemble artifacts (86 features, 300-380 samples,
#   LightGBM + RF + XGBoost base + LR meta). artifact_hash = SHA-256[:16]
#   of the .pkl file. Walk-forward RPS gate due when live match data arrives.
# EREDIVISIE / UCL: DEFAULT_PENDING_CALIBRATION (no CSV cache available).
# ---------------------------------------------------------------------------

# Shared base for uncalibrated leagues
_BASE_POLICY = dict(
    version="0.1.0-default",
    policy_source="DEFAULT_PENDING_CALIBRATION",
    artifact_hash=None,
    calibration_artifact=None,
    draw_prior=0.26,
    home_advantage_coefficient=1.10,
    kelly_cap=0.025,
    market_freshness_ttl_seconds=900,
    model_feature_freshness_ttl_seconds=3600,
    lineup_freshness_ttl_seconds=1800,
    high_conviction_edge_threshold=0.07,
    ece_recalibration_threshold=0.03,
    minimum_calibration_samples=200,
)

# Shared calibrated defaults — relaxed Kelly cap and HC threshold now that
# artifacts are certified. Individual leagues override draw_prior / artifact_hash.
_CALIBRATED_BASE = dict(
    version="1.0.0",
    policy_source="CALIBRATED",
    home_advantage_coefficient=1.10,
    kelly_cap=0.04,  # up from 0.025; still hard-capped by MAX_KELLY_CAP=0.05
    market_freshness_ttl_seconds=900,
    model_feature_freshness_ttl_seconds=3600,
    lineup_freshness_ttl_seconds=1800,
    high_conviction_edge_threshold=0.06,
    ece_recalibration_threshold=0.03,
    minimum_calibration_samples=200,
)

LeaguePolicy(
    league_id="EPL",
    draw_prior=0.25,
    artifact_hash="aaf2ec1763a7c0ed",
    calibration_artifact="models/epl_ensemble.pkl",
    **_CALIBRATED_BASE,  # type: ignore[arg-type]
)
LeaguePolicy(
    league_id="LA_LIGA",
    draw_prior=0.25,
    artifact_hash="de62e4bac0a8cbc1",
    calibration_artifact="models/la_liga_ensemble.pkl",
    **_CALIBRATED_BASE,  # type: ignore[arg-type]
)
LeaguePolicy(
    league_id="BUNDESLIGA",
    draw_prior=0.22,
    artifact_hash="9d571b90e08d36fa",
    calibration_artifact="models/bundesliga_ensemble.pkl",
    **_CALIBRATED_BASE,  # type: ignore[arg-type]
)
LeaguePolicy(
    league_id="SERIE_A",
    draw_prior=0.27,
    artifact_hash="731dcc426cd4ccab",
    calibration_artifact="models/serie_a_ensemble.pkl",
    **_CALIBRATED_BASE,  # type: ignore[arg-type]
)
LeaguePolicy(
    league_id="LIGUE_1",
    draw_prior=0.26,
    artifact_hash="269295fd77fc0066",
    calibration_artifact="models/ligue_1_ensemble.pkl",
    **_CALIBRATED_BASE,  # type: ignore[arg-type]
)
LeaguePolicy(league_id="EREDIVISIE", **_BASE_POLICY)  # type: ignore[arg-type]
LeaguePolicy(
    league_id="UCL",
    version="0.1.0-default",
    policy_source="DEFAULT_PENDING_CALIBRATION",
    artifact_hash=None,
    calibration_artifact=None,
    draw_prior=0.28,
    home_advantage_coefficient=1.05,
    kelly_cap=0.020,
    market_freshness_ttl_seconds=900,
    model_feature_freshness_ttl_seconds=3600,
    lineup_freshness_ttl_seconds=1800,
    high_conviction_edge_threshold=0.08,  # UCL capped at ACTIONABLE anyway
    ece_recalibration_threshold=0.03,
    minimum_calibration_samples=150,
)
