"""
Upcoming Match Feature Projection Service

Projects upcoming match data to 58-dimensional canonical feature space
for use with trained ML models. Handles missing historical data via defaults.

Phase 8 Sprint 4: _inject_phase8_features now wires real market drift (via
OddsHistory opening snapshot + current OddsService) and real match importance
(via LeagueStanding query), returning per-feature freshness metadata.
shot_quality_diff is permanently DATA_GAP per PHASE7_FEATURES_ALWAYS_DATA_GAP.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sqlalchemy import and_, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..core.database import Match, MatchStats, Team
from ..core.exceptions import SchemaMismatchError
from ..core.league_policy import canonical_league_id
from ..data.enrichment.statsbomb_aggregator import StatsBombAggregator
from ..features.berrar_ratings import BerrarRatingSystem
from ..features.form import weighted_form_features
from ..features.market import MARKET_FEATURE_NAMES, compute_market_drift
from ..features.match_context import CONTEXT_FEATURE_NAMES, compute_match_context
from ..features.pi_ratings import PiRatingSystem
from ..models.active_generation import ActiveGenerationError, active_feature_schema_version
from ..models.feature_registry import (
    APEX_MARKET_FEATURES_14,
    CANONICAL_FEATURES_58,
    PHASE7_FEATURES_7,
    PHASE7_FEATURES_ALWAYS_DATA_GAP,
    PHASE8_FEATURES_BERRAR,
    PHASE8_FEATURES_CONTEXT,
    PHASE8_FEATURES_FORM,
    PHASE8_FEATURES_MARKET,
    PHASE8_FEATURES_PI,
    COMBINATION_FEATURES,
    LEAGUE_ONEHOT_FEATURES,
    LEAGUE_RATE_FEATURES,
    MARKET_FEATURES_14,
    TEMPORAL_FEATURES,
    UnknownFeatureSchemaError,
    active_canonical_features,
    active_default_feature_values,
    derive_apex_market_features,
    derive_combination_features,
    derive_goals_gd_features,
    derive_last5_form_features,
    derive_league_features,
    derive_market_features,
    derive_temporal_features,
    is_apex_schema,
)
from ..utils.season import canonical_season
from .elo_state_service import get_elo_context
from .odds_service import OddsService
from .scraped_feature_store import ScrapedTeamFormStore
from .team_identity import resolve_team_id

logger = logging.getLogger(__name__)


def _model_input_staleness_seconds(
    home_stats: Optional[Dict[str, float]],
    away_stats: Optional[Dict[str, float]],
) -> Optional[float]:
    """Age of the newest completed match backing either side's form, in seconds.

    Distinct from the ``staleness_seconds`` reported alongside it, which measures
    the offline StatsBomb enrichment artifact and nothing else. Conflating the two
    made an enrichment file frozen in 2024 look like an absence of the model's
    *required* inputs, which forced a critical gap — and therefore PARTIAL / no
    bet — on every fixture regardless of how much real history existed.

    ``None`` when neither side resolved any history: that is the *missing* inputs
    case, already reported as ``is_synthetic`` / REQUIRED_MODEL_INPUTS_UNAVAILABLE,
    not a staleness case.
    """
    timestamps = [
        stats["last_finished_match_ts"]
        for stats in (home_stats, away_stats)
        if stats and stats.get("last_finished_match_ts") is not None
    ]
    if not timestamps:
        return None
    # Both sides must be usable, so the *oldest* of the two newest matches governs.
    newest_per_side = min(timestamps)
    now = datetime.now(timezone.utc).timestamp()
    return max(0.0, now - newest_per_side)

# Canonical features resolved entirely by the CALLER (build_live_feature_vector /
# build_live_feature_vector_from_matchup), not by project_match_features() itself:
# elo/statsbomb (PHASE7_FEATURES_7 minus the always-gap shot_quality_diff — elo_engine
# has no failure path and statsbomb gaps are tracked separately via
# sb_home/sb_away.data_gaps) and every Phase 8 family (_inject_phase8_features tracks
# its own gaps additively in phase8_gaps). Flagging these here, before the caller has
# run, would either be a stale false-positive (elo — always successfully computed one
# step later) or duplicate phase8's own tracking with the wrong default assumption.
_CALLER_RESOLVED_FEATURES = (
    frozenset(f for f in PHASE7_FEATURES_7 if f not in PHASE7_FEATURES_ALWAYS_DATA_GAP)
    | frozenset(PHASE8_FEATURES_PI)
    | frozenset(PHASE8_FEATURES_BERRAR)
    | frozenset(PHASE8_FEATURES_FORM)
    | frozenset(PHASE8_FEATURES_MARKET)
    | frozenset(PHASE8_FEATURES_CONTEXT)
)

# The four Elo features build_live_feature_vector* overlays from EloContext.
# They are excluded from project_match_features()'s own gap tracking via
# _CALLER_RESOLVED_FEATURES, on the assumption the caller always resolves them —
# but EloEngine falls back to a neutral 1500/1500 baseline for a team it has no
# rating for, which yields elo_difference == 0.0 and zero trends, numerically
# indistinguishable from two genuinely equal teams. The caller must therefore
# report these as gaps when the context is unresolved, or a neutral default is
# published as an observation (INV-01, the vΩ.24 defect class).
_ELO_OVERLAY_FEATURES = frozenset({
    "elo_difference",
    "elo_home_trend_5",
    "elo_away_trend_5",
    "elo_momentum_cross",
})

# WP-18/WP-10.3: the last5-form + goals/gd canonical fields rescued from
# unconditional-gap status once _get_team_stats()/to_projection_stats() data
# is available for that side and the remap in project_match_features() has
# run. Resolved per side, independently — one side having history doesn't
# rescue the other's.
_HOME_REMAP_FEATURES = frozenset({
    "home_form_last5_home", "home_wins_last5_home", "home_draws_last5_home",
    "home_losses_last5_home", "home_goals_for_avg", "home_goals_against_avg",
    "home_gd_recent",
})
_AWAY_REMAP_FEATURES = frozenset({
    "away_form_last5_away", "away_wins_last5_away", "away_draws_last5_away",
    "away_losses_last5_away", "away_goals_for_avg", "away_goals_against_avg",
    "away_gd_recent",
})

_H2H_FEATURES = frozenset({
    "h2h_home_wins", "h2h_away_wins", "h2h_draws", "h2h_matches", "h2h_dominance",
})
_VENUE_FEATURES = frozenset({
    "home_venue_win_rate", "home_venue_draw_rate", "home_venue_loss_rate",
    "home_advantage_strength",
})


class UpcomingMatchFeatureProjector:
    """Project upcoming matches to the active canonical feature schema."""

    def __init__(self, odds_service: OddsService | None = None) -> None:
        self._use_phase8 = settings.phase8_enabled
        self._is_apex = self._resolve_is_apex()
        self.canonical_features = active_canonical_features(
            use_phase7=settings.use_phase7_models,
            use_phase8=self._use_phase8,
            apex=self._is_apex,
        )
        self.defaults = active_default_feature_values(
            use_phase7=settings.use_phase7_models,
            use_phase8=self._use_phase8,
            apex=self._is_apex,
        )
        self.statsbomb = StatsBombAggregator()
        self.pi_engine = PiRatingSystem(
            parquet_path=settings.pi_ratings_parquet_path
        )
        self.berrar_engine = BerrarRatingSystem(
            parquet_path=settings.berrar_ratings_parquet_path
        )
        self.odds_service = odds_service or OddsService()
        self.scraped_form_store = ScrapedTeamFormStore()

    @staticmethod
    def _resolve_is_apex() -> bool:
        """Whether the active generation serves the Apex market block.

        docs/DEBT.md item 37's serving wire-up. Any resolution failure
        (missing manifest, unregistered schema string) falls back to
        ``False`` — today's exact behavior for every existing deployment,
        since the only generation active today declares ``phase7_68``.
        """
        try:
            return is_apex_schema(active_feature_schema_version())
        except (ActiveGenerationError, UnknownFeatureSchemaError):
            return False

    async def project_match_features(
        self,
        match_dict: Dict[str, Any],
        db: AsyncSession,
        match_date: datetime,
    ) -> Dict[str, Any]:
        """
        Project an upcoming match to the active canonical feature vector.

        Args:
            match_dict: Normalized match from FootballDataAPIClient
                {"id", "home_team", "away_team", "league", "match_date", ...}
            db: Database session
            match_date: Match datetime

        Returns:
            {
                "match_id": str,
                "home_team": str,
                "away_team": str,
                "features_68": np.ndarray (68,),
                "features_dict": Dict with feature names,
                "data_quality": {
                    "historical_data_ratio": float (0-1),
                    "defaults_used_count": int,
                    "feature_defaulted_ratio": float (0-1),
                    "is_synthetic": bool
                }
            }
        """

        # ponytail: Match.match_date is naive TIMESTAMP WITHOUT TIME ZONE — strip tz so asyncpg accepts range bounds
        match_date = match_date.replace(tzinfo=None)

        home_team_id_resolved = await self._get_team_id_by_name(match_dict["home_team"], db)
        away_team_id_resolved = await self._get_team_id_by_name(match_dict["away_team"], db)
        home_resolved = home_team_id_resolved is not None
        away_resolved = away_team_id_resolved is not None

        if not home_resolved or not away_resolved:
            logger.warning(
                "Could not find teams: %s vs %s",
                match_dict["home_team"],
                match_dict["away_team"],
            )
        home_team_id = home_team_id_resolved or match_dict["home_team"]
        away_team_id = away_team_id_resolved or match_dict["away_team"]

        home_stats = await self._get_team_stats(home_team_id, db, match_date, is_home=True)
        away_stats = await self._get_team_stats(away_team_id, db, match_date, is_home=False)

        # is_synthetic (below) gates public prediction publishing (WP-0/vΩ.32:
        # upcoming_match_service.py `publishable = not is_fallback and not
        # is_synthetic`) — it must reflect whether DB-native history existed, not
        # whether a scraped fallback was found. Captured before the fallback
        # reassigns home_stats/away_stats.
        home_db_missing = home_stats is None
        away_db_missing = away_stats is None
        league_hint = match_dict.get("league")
        home_stats, home_scraped_provenance = self._apply_scraped_fallback(
            home_stats, competition=league_hint, team=match_dict["home_team"], match_date=match_date, is_home=True
        )
        away_stats, away_scraped_provenance = self._apply_scraped_fallback(
            away_stats, competition=league_hint, team=match_dict["away_team"], match_date=match_date, is_home=False
        )

        # WP-18/WP-10.3: wire the canonical last5-form + goals/gd remap that
        # FeatureTransformer._project_to_canonical_features() has always used
        # elsewhere (data/transformers.py) into this pipeline, now that
        # _get_team_stats()/to_projection_stats() correctly prefix by side
        # (D8b fixed above). Mutates home_stats/away_stats in place so the
        # existing defaults_count bookkeeping below needs no changes — it
        # already generically credits any key also present in self.defaults,
        # and every new canonical key genuinely is.
        if home_stats:
            home_stats.update(derive_last5_form_features(
                home_stats.get("home_form_5", 0.5),
                home_stats.get("home_win_rate_5", 0.5),
                is_home=True,
                wins_5=home_stats.get("wins_5"),
                draws_5=home_stats.get("draws_5"),
                losses_5=home_stats.get("losses_5"),
            ))
            home_stats.update(
                derive_goals_gd_features(home_stats.get, is_home=True)
            )
        if away_stats:
            away_stats.update(derive_last5_form_features(
                away_stats.get("away_form_5", 0.45),
                away_stats.get("away_win_rate_5", 0.4),
                is_home=False,
                wins_5=away_stats.get("wins_5"),
                draws_5=away_stats.get("draws_5"),
                losses_5=away_stats.get("losses_5"),
            ))
            away_stats.update(
                derive_goals_gd_features(away_stats.get, is_home=False)
            )

        features_dict = dict(self.defaults)
        defaults_count = len(self.defaults)

        if home_stats:
            features_dict.update(home_stats)
            defaults_count -= sum(1 for k in home_stats if k in self.defaults)

        if away_stats:
            features_dict.update(away_stats)
            defaults_count -= sum(1 for k in away_stats if k in self.defaults)

        # Schedule + league features are always derivable — they need only the
        # kickoff and the competition, both of which are inputs to this call, so
        # they are never a gap. Same definitions as
        # FeatureTransformer._project_to_canonical_features(), via one shared
        # helper each, so the two pipelines cannot drift apart.
        derived_resolved: set = set()
        features_dict.update(derive_temporal_features(match_date))
        derived_resolved.update(TEMPORAL_FEATURES)
        features_dict.update(derive_league_features(match_dict.get("league") or ""))
        derived_resolved.update(LEAGUE_ONEHOT_FEATURES)
        derived_resolved.update(LEAGUE_RATE_FEATURES)

        # Combination features are pure arithmetic over the four per-side goal
        # averages — resolvable only when BOTH sides supplied real ones, since
        # mixing a real average with a registry default would present a
        # half-fabricated difference as a measurement.
        if home_stats and away_stats:
            features_dict.update(derive_combination_features(
                home_goals_for_avg=features_dict["home_goals_for_avg"],
                home_goals_against_avg=features_dict["home_goals_against_avg"],
                away_goals_for_avg=features_dict["away_goals_for_avg"],
                away_goals_against_avg=features_dict["away_goals_against_avg"],
            ))
            derived_resolved.update(COMBINATION_FEATURES)

        # H2H and home-venue features — pure DB queries, no external provider
        # needed. Called after home/away team IDs are resolved above.
        h2h_stats = await self._get_h2h_stats(home_team_id, away_team_id, db, match_date)
        venue_stats = await self._get_home_venue_stats(home_team_id, db, match_date)
        if h2h_stats:
            features_dict.update(h2h_stats)
            derived_resolved.update(_H2H_FEATURES)
        if venue_stats:
            features_dict.update(venue_stats)
            derived_resolved.update(_VENUE_FEATURES)

        # WP-A: 14 canonical market-odds features (market_prob_home, ev_home,
        # ...). Unconditional — unlike combination features, odds don't need
        # either side's history resolved, and are often the single most
        # valuable signal on a reduced-evidence fixture. OddsService already
        # caches this lookup (120s/league board, 300s/fixture — odds_service.py),
        # so a second call from full_analysis.py's _fetch_market_odds() for the
        # same fixture in the same request costs no extra provider quota.
        # get_match_odds() normalizes the league via canonical_league_id()
        # internally and never raises for an unsupported competition — no
        # extra normalization needed here.
        odds = await self.odds_service.get_match_odds(
            match_dict["home_team"], match_dict["away_team"], match_dict.get("league") or "",
        )
        if {"home_win", "draw", "away_win"}.issubset(odds):
            if self._is_apex:
                features_dict.update(derive_apex_market_features(
                    odds["home_win"], odds["draw"], odds["away_win"],
                ))
                derived_resolved.update(APEX_MARKET_FEATURES_14)
            else:
                features_dict.update(derive_market_features(
                    odds["home_win"], odds["draw"], odds["away_win"],
                ))
                derived_resolved.update(MARKET_FEATURES_14)
        # else: leave features_dict at its DEFAULT_FEATURE_VALUES_68 seed for
        # these 14 keys — they fall through to data_gaps below, same honest-gap
        # treatment Elo/StatsBomb already get.

        # Cross-signal features — same formulas as data/transformers.py:424-429
        # (train/serve parity). Only computed when both inputs are genuinely
        # resolved, never mixing a real value with a registry default.
        _market_resolved = "market_prob_home" in derived_resolved
        if _market_resolved:
            mph = features_dict["market_prob_home"]
            if h2h_stats:
                features_dict["h2h_market_agreement"] = h2h_stats["h2h_dominance"] * mph
                derived_resolved.add("h2h_market_agreement")
            if venue_stats:
                features_dict["venue_market_combo"] = venue_stats["home_venue_win_rate"] * mph
                derived_resolved.add("venue_market_combo")
            if home_stats:
                form_norm = features_dict.get("home_form_last5_home", 1.5) / 3.0
                features_dict["form_market_agreement_home"] = form_norm * mph
                features_dict["form_market_disagreement"] = abs(form_norm - mph)
                derived_resolved.update(("form_market_agreement_home", "form_market_disagreement"))

        features_array = np.array(
            [features_dict.get(f, self.defaults.get(f, 0.0)) for f in self.canonical_features],
            dtype=np.float32,
        )

        # A canonical feature is a gap here unless it's resolved by the caller
        # (_CALLER_RESOLVED_FEATURES — elo/statsbomb/phase8, tracked authoritatively
        # one layer up) or by the last5-form/goals/gd remap just above
        # (_HOME_REMAP_FEATURES/_AWAY_REMAP_FEATURES, WP-18/WP-10.3) — never
        # inferred from the numeric value. A value-equality check (old:
        # `in (None, 0.0)`) was both a false positive (a genuinely-computed 0.0
        # flagged as missing) and a false negative (a non-zero default like
        # home_berrar_rating=1500.0 silently never flagged) for exactly the
        # features that heuristic was meant to catch. Every remaining base
        # feature (market/h2h/combined — no remap wired for those yet) stays
        # unconditionally at its registry default, same as before WP-18.
        _remap_resolved: set = set()
        if home_stats and _HOME_REMAP_FEATURES.issubset(home_stats.keys()):
            _remap_resolved |= _HOME_REMAP_FEATURES
        if away_stats and _AWAY_REMAP_FEATURES.issubset(away_stats.keys()):
            _remap_resolved |= _AWAY_REMAP_FEATURES

        data_gaps = [
            feature for feature in self.canonical_features
            if feature not in _CALLER_RESOLVED_FEATURES
            and feature not in _remap_resolved
            and feature not in derived_resolved
        ]

        for always_gap in PHASE7_FEATURES_ALWAYS_DATA_GAP:
            features_dict[always_gap] = self.defaults.get(always_gap, 0.0)
            if always_gap not in data_gaps:
                data_gaps.append(always_gap)

        # Unreachable in practice: features_array is built one scalar per entry of
        # self.canonical_features (line ~153), so the lengths can never diverge
        # today. Kept as a fail-closed guard rather than silent zero-padding
        # (INV-10) in case a future edit breaks that invariant.
        if len(features_array) != len(self.canonical_features):
            raise SchemaMismatchError(
                actual_dim=len(features_array),
                expected_dim=len(self.canonical_features),
                provider="upcoming_match_feature_service",
            )

        data_quality = {
            "historical_data_ratio": max(0.0, 1.0 - (defaults_count / len(self.defaults)))
            if self.defaults
            else 0.0,
            "defaults_used_count": max(0, defaults_count),
            # WP-18/WP-10.3: fraction of canonical features still at their registry
            # default (derived from data_gaps, not defaults_count — defaults_count
            # was silently constant before this fix, since home_stats/away_stats
            # keys never intersected self.defaults at all until the remap wired
            # canonical names into them). 1.0 = fully defaulted, 0.0 = fully resolved.
            "feature_defaulted_ratio": (
                len(data_gaps) / len(self.canonical_features) if self.canonical_features else 0.0
            ),
            "is_synthetic": home_db_missing or away_db_missing,
            # Provenance-tagged (INV-10) — closes D12 (ScrapedTeamFormStore had zero
            # callers) without claiming these values as DB-native. No longer inert on
            # the canonical feature vector (WP-10.3 remap wired above): a scraped
            # fallback's last5-form/goals/gd fields now reach features_array the
            # same as DB-native ones, provenance-tagged here for auditability.
            "scraped_fallback": {
                k: v
                for k, v in {"home": home_scraped_provenance, "away": away_scraped_provenance}.items()
                if v is not None
            },
        }

        return {
            "match_id": match_dict["id"],
            "home_team": match_dict["home_team"],
            "away_team": match_dict["away_team"],
            "home_team_id": home_team_id,
            "away_team_id": away_team_id,
            "identity_resolution": {
                "home_team_resolved": home_resolved,
                "away_team_resolved": away_resolved,
            },
            "features_68": features_array,
            "features_58": features_array[: len(CANONICAL_FEATURES_58)],
            "features_dict": {f: float(features_array[i]) for i, f in enumerate(self.canonical_features)},
            "data_gaps": sorted(set(data_gaps)),
            "data_quality": data_quality,
            "model_input_staleness_seconds": _model_input_staleness_seconds(
                home_stats, away_stats
            ),
            "odds_snapshot": odds,
            "odds": odds if {"home_win", "draw", "away_win"}.issubset(odds) else None,
            "market_snapshot_acquired": True,
        }

    async def build_live_feature_vector(
        self,
        match_id: str,
        league: str,
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """Build a live canonical feature vector with gap and staleness metadata."""
        match = await self._get_match(match_id, db)
        if match is None:
            raise ValueError(f"Unknown match_id: {match_id}")

        home_team = await self._get_team_name(match.home_team_id, db)
        away_team = await self._get_team_name(match.away_team_id, db)
        match_date = pd.Timestamp(match.match_date).to_pydatetime()
        season = self._derive_season(match_date)

        projected = await self.project_match_features(
            {
                "id": str(match.id),
                "home_team": home_team or str(match.home_team_id),
                "away_team": away_team or str(match.away_team_id),
                "league": league,
                "match_date": match_date.isoformat(),
            },
            db,
            match_date,
        )

        elo = await get_elo_context(
            db,
            home_team_id=str(match.home_team_id),
            away_team_id=str(match.away_team_id),
            league=league,
            season=season,
            match_date=match_date,
        )
        sb_home = self.statsbomb.get_team_features(str(match.home_team_id), league, match_date)
        sb_away = self.statsbomb.get_team_features(str(match.away_team_id), league, match_date)

        features_dict = dict(projected["features_dict"])
        features_dict["elo_difference"] = float(elo.elo_difference)
        features_dict["elo_home_trend_5"] = float(elo.home_elo_trend_5)
        features_dict["elo_away_trend_5"] = float(elo.away_elo_trend_5)
        features_dict["elo_momentum_cross"] = float(elo.elo_momentum_cross)

        features_dict["home_pressing_intensity"] = float(
            sb_home.features.get("ppda_ratio", 1.0)
            / max(sb_away.features.get("ppda_ratio", 1.0), 1e-6)
        )
        features_dict["progressive_carry_diff"] = float(
            sb_home.features.get("progressive_carry_diff", 0.0)
            - sb_away.features.get("progressive_carry_diff", 0.0)
        )
        # shot_quality_diff is PHASE7_FEATURES_ALWAYS_DATA_GAP — use registry default,
        # never compute from proxy; the injector will enforce DATA_GAP below.
        features_dict["shot_quality_diff"] = self.defaults.get("shot_quality_diff", 0.0)

        match_competition_stage = getattr(match, "competition_stage", None) or "group"
        phase8_gaps, phase8_freshness, phase8_sources = await self._inject_phase8_features(
            features_dict=features_dict,
            home_team_id=str(match.home_team_id),
            away_team_id=str(match.away_team_id),
            home_team=home_team or str(match.home_team_id),
            away_team=away_team or str(match.away_team_id),
            league=league,
            match_id=str(match.id),
            db=db,
            match_date=match_date,
            competition_stage=match_competition_stage,
            current_odds=projected.get("odds_snapshot"),
        )

        features = np.array(
            [float(features_dict.get(name, self.defaults.get(name, 0.0))) for name in self.canonical_features],
            dtype=np.float32,
        )

        data_gaps = sorted(
            set(projected.get("data_gaps", []))
            | set(sb_home.data_gaps)
            | set(sb_away.data_gaps)
            | set(PHASE7_FEATURES_ALWAYS_DATA_GAP)
            | set(phase8_gaps)
            | (set() if elo.resolved else set(_ELO_OVERLAY_FEATURES))
        )
        staleness_seconds = max(sb_home.staleness_seconds, sb_away.staleness_seconds)

        identity_resolution = projected.get("identity_resolution") or {}
        fixture_identity_verified = bool(identity_resolution.get("home_team_resolved")) and bool(
            identity_resolution.get("away_team_resolved")
        )

        return {
            "features": features,
            "features_58": features[: len(CANONICAL_FEATURES_58)],
            "data_gaps": data_gaps,
            # StatsBomb enrichment artifact age only — NOT the age of the model's
            # required inputs. Kept under this name for the frontend freshness
            # pill; the gate in full_analysis.py reads the two keys below.
            "staleness_seconds": staleness_seconds,
            "enrichment_staleness_seconds": staleness_seconds,
            "model_input_staleness_seconds": projected.get("model_input_staleness_seconds"),
            "elo_pre_match": float(elo.elo_difference),
            "features_dict": features_dict,
            "league": league,
            # Propagated so callers can look up a live market without re-querying
            # the fixture — full_analysis.py needs them for the odds fetch.
            "home_team": projected.get("home_team"),
            "away_team": projected.get("away_team"),
            "odds": projected.get("odds"),
            "market_snapshot_acquired": bool(projected.get("market_snapshot_acquired")),
            "feature_freshness_seconds": phase8_freshness,
            "feature_source": phase8_sources,
            "data_quality": dict(projected.get("data_quality") or {}),
            "identity_resolution": identity_resolution,
            "fixture_identity_verified": fixture_identity_verified,
            "elo_context": elo if elo.resolved else None,
            "kickoff_utc": match_date.isoformat(),
            "is_reduced_evidence_baseline": bool(
                (projected.get("data_quality") or {}).get("is_synthetic", False)
            ),
        }

    async def build_live_feature_vector_from_matchup(
        self,
        home_team: str,
        away_team: str,
        league: str,
        db: AsyncSession,
        match_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Build the active canonical live feature vector from team names without a DB match record.

        Used by the full-analysis endpoint when the caller passes a matchup string
        ("Arsenal vs Chelsea") instead of a database match ID (P7-E live data wiring).
        Falls back gracefully to defaults; missing historical data is surfaced in
        data_gaps so the frontend can render the PARTIAL verdict and DATA_GAP badges.
        """
        if match_date is None:
            # ponytail: naive, not datetime.now(timezone.utc) — EloEngine/StatsBombAggregator
            # compare against persisted naive timestamps; a tz-aware value here raises inside
            # get_elo_context(), which the caller's broad except then silently reports
            # as "identity unverified" instead of the real cause.
            match_date = datetime.now(timezone.utc).replace(tzinfo=None)

        season = self._derive_season(match_date)

        home_team_id = await self._get_team_id_by_name(home_team, db) or home_team
        away_team_id = await self._get_team_id_by_name(away_team, db) or away_team
        synthetic_match_id = f"{home_team} vs {away_team}"

        projected = await self.project_match_features(
            {
                "id": synthetic_match_id,
                "home_team": home_team,
                "away_team": away_team,
                "league": league,
                "match_date": match_date.isoformat(),
            },
            db,
            match_date,
        )

        elo = await get_elo_context(
            db,
            home_team_id=str(home_team_id),
            away_team_id=str(away_team_id),
            league=league,
            season=season,
            match_date=match_date,
        )
        sb_home = self.statsbomb.get_team_features(str(home_team_id), league, match_date)
        sb_away = self.statsbomb.get_team_features(str(away_team_id), league, match_date)

        features_dict = dict(projected["features_dict"])
        features_dict["elo_difference"] = float(elo.elo_difference)
        features_dict["elo_home_trend_5"] = float(elo.home_elo_trend_5)
        features_dict["elo_away_trend_5"] = float(elo.away_elo_trend_5)
        features_dict["elo_momentum_cross"] = float(elo.elo_momentum_cross)

        features_dict["home_pressing_intensity"] = float(
            sb_home.features.get("ppda_ratio", 1.0)
            / max(sb_away.features.get("ppda_ratio", 1.0), 1e-6)
        )
        features_dict["progressive_carry_diff"] = float(
            sb_home.features.get("progressive_carry_diff", 0.0)
            - sb_away.features.get("progressive_carry_diff", 0.0)
        )
        features_dict["shot_quality_diff"] = self.defaults.get("shot_quality_diff", 0.0)

        phase8_gaps, phase8_freshness, phase8_sources = await self._inject_phase8_features(
            features_dict=features_dict,
            home_team_id=str(home_team_id),
            away_team_id=str(away_team_id),
            home_team=home_team,
            away_team=away_team,
            league=league,
            match_id=synthetic_match_id,
            db=db,
            match_date=match_date,
            current_odds=projected.get("odds_snapshot"),
        )

        features = np.array(
            [float(features_dict.get(name, self.defaults.get(name, 0.0))) for name in self.canonical_features],
            dtype=np.float32,
        )

        data_gaps = sorted(
            set(projected.get("data_gaps", []))
            | set(sb_home.data_gaps)
            | set(sb_away.data_gaps)
            | set(PHASE7_FEATURES_ALWAYS_DATA_GAP)
            | set(phase8_gaps)
            | (set() if elo.resolved else set(_ELO_OVERLAY_FEATURES))
        )
        staleness_seconds = max(sb_home.staleness_seconds, sb_away.staleness_seconds)

        identity_resolution = projected.get("identity_resolution") or {}
        fixture_identity_verified = bool(identity_resolution.get("home_team_resolved")) and bool(
            identity_resolution.get("away_team_resolved")
        )

        return {
            "features": features,
            "features_58": features[: len(CANONICAL_FEATURES_58)],
            "data_gaps": data_gaps,
            # StatsBomb enrichment artifact age only — NOT the age of the model's
            # required inputs. Kept under this name for the frontend freshness
            # pill; the gate in full_analysis.py reads the two keys below.
            "staleness_seconds": staleness_seconds,
            "enrichment_staleness_seconds": staleness_seconds,
            "model_input_staleness_seconds": projected.get("model_input_staleness_seconds"),
            "elo_pre_match": float(elo.elo_difference),
            "features_dict": features_dict,
            "league": league,
            # Propagated so callers can look up a live market without re-querying
            # the fixture — full_analysis.py needs them for the odds fetch.
            "home_team": projected.get("home_team"),
            "away_team": projected.get("away_team"),
            "odds": projected.get("odds"),
            "market_snapshot_acquired": bool(projected.get("market_snapshot_acquired")),
            "feature_freshness_seconds": phase8_freshness,
            "feature_source": phase8_sources,
            "data_quality": dict(projected.get("data_quality") or {}),
            "identity_resolution": identity_resolution,
            "fixture_identity_verified": fixture_identity_verified,
            "elo_context": elo if elo.resolved else None,
            "kickoff_utc": match_date.isoformat(),
            "is_reduced_evidence_baseline": bool(
                (projected.get("data_quality") or {}).get("is_synthetic", False)
            ),
        }

    async def _inject_phase8_features(
        self,
        features_dict: dict,
        home_team_id: str,
        away_team_id: str,
        home_team: str,
        away_team: str,
        league: str,
        match_id: str,
        db: AsyncSession,
        match_date: datetime,
        competition_stage: str = "group",
        current_odds: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[str], Dict[str, Optional[int]], Dict[str, str]]:
        """Inject Phase 8 features into features_dict in-place.

        Wires real market drift (via OddsHistory) and real match importance
        (via LeagueStanding). In shadow mode (PHASE8_ENRICHMENT_SHADOW=true)
        computed values are logged but not served — response stays DATA_GAP.

        Returns:
            (phase8_data_gaps, feature_freshness_seconds, feature_source)
            - phase8_data_gaps: feature names that could not be live-computed
            - feature_freshness_seconds: feature_name → seconds since source data
              was captured; None means DATA_GAP (not 0 — 0 means "fresh/parquet")
            - feature_source: feature_name → source identifier string
        """
        phase8_gaps: List[str] = []
        freshness: Dict[str, Optional[int]] = {}
        sources: Dict[str, str] = {}

        if not self._use_phase8:
            return phase8_gaps, freshness, sources

        # ── Pi-ratings ────────────────────────────────────────────────────────
        _pi_keys = ("home_pi_attack", "home_pi_defense", "away_pi_attack",
                    "away_pi_defense", "pi_attack_diff", "pi_defense_diff")
        try:
            pi = self.pi_engine.get_context(home_team_id, away_team_id)
            features_dict["home_pi_attack"] = pi.home_pi_attack
            features_dict["home_pi_defense"] = pi.home_pi_defense
            features_dict["away_pi_attack"] = pi.away_pi_attack
            features_dict["away_pi_defense"] = pi.away_pi_defense
            features_dict["pi_attack_diff"] = pi.pi_attack_diff
            features_dict["pi_defense_diff"] = pi.pi_defense_diff
            for k in _pi_keys:
                freshness[k] = 0
                sources[k] = "pi_ratings"
        except Exception:
            logger.warning("Pi-rating context unavailable for %s vs %s", home_team_id, away_team_id)
            for k in _pi_keys:
                features_dict.setdefault(k, self.defaults.get(k, 0.0))
                phase8_gaps.append(k)
                freshness[k] = None  # DATA_GAP — not a freshness value
                sources[k] = "pi_ratings"

        # ── Berrar ratings ────────────────────────────────────────────────────
        _berrar_keys = ("home_berrar_rating", "away_berrar_rating", "berrar_rating_diff")
        try:
            berrar = self.berrar_engine.get_context(home_team_id, away_team_id)
            features_dict["home_berrar_rating"] = berrar.home_berrar_rating
            features_dict["away_berrar_rating"] = berrar.away_berrar_rating
            features_dict["berrar_rating_diff"] = berrar.berrar_rating_diff
            for k in _berrar_keys:
                freshness[k] = 0
                sources[k] = "berrar_ratings"
        except Exception:
            logger.warning("Berrar rating context unavailable for %s vs %s", home_team_id, away_team_id)
            for k in _berrar_keys:
                features_dict.setdefault(k, self.defaults.get(k, 0.0))
                phase8_gaps.append(k)
                freshness[k] = None
                sources[k] = "berrar_ratings"

        # ── EWMA form ─────────────────────────────────────────────────────────
        _ewma_keys = ("home_weighted_win_rate", "home_weighted_draw_rate", "home_weighted_ppg",
                      "away_weighted_win_rate", "away_weighted_draw_rate", "away_weighted_ppg")
        _home_ewma_keys = _ewma_keys[:3]
        _away_ewma_keys = _ewma_keys[3:]
        try:
            home_results = await self._get_team_results_sequence(home_team_id, db, match_date)
            away_results = await self._get_team_results_sequence(away_team_id, db, match_date)
            home_form = weighted_form_features(home_results)
            away_form = weighted_form_features(away_results)
            features_dict["home_weighted_win_rate"] = home_form["weighted_win_rate"]
            features_dict["home_weighted_draw_rate"] = home_form["weighted_draw_rate"]
            features_dict["home_weighted_ppg"] = home_form["weighted_ppg"]
            features_dict["away_weighted_win_rate"] = away_form["weighted_win_rate"]
            features_dict["away_weighted_draw_rate"] = away_form["weighted_draw_rate"]
            features_dict["away_weighted_ppg"] = away_form["weighted_ppg"]
            # weighted_form_features([]) returns neutral priors without raising — an
            # empty results sequence (no completed match history found for that side)
            # is a genuine gap, not freshly-computed data, even though no exception
            # is thrown. Checked per side since one team can have history while the
            # other (e.g. a newly-promoted club) does not.
            for k in _home_ewma_keys:
                if home_results:
                    freshness[k] = 0
                    sources[k] = "match_history"
                else:
                    phase8_gaps.append(k)
                    freshness[k] = None
                    sources[k] = "match_history"
            for k in _away_ewma_keys:
                if away_results:
                    freshness[k] = 0
                    sources[k] = "match_history"
                else:
                    phase8_gaps.append(k)
                    freshness[k] = None
                    sources[k] = "match_history"
        except Exception:
            logger.warning("EWMA form unavailable for %s vs %s", home_team_id, away_team_id)
            for k in _ewma_keys:
                features_dict.setdefault(k, self.defaults.get(k, 0.0))
                phase8_gaps.append(k)
                freshness[k] = None
                sources[k] = "match_history"

        # ── Market drift (Phase 8 P1 live enrichment) ─────────────────────────
        try:
            if current_odds is None:
                current_odds = await self.odds_service.get_match_odds(home_team, away_team, league)
            drift_result = await compute_market_drift(
                current_odds=current_odds,
                match_id=match_id,
                db=db,
                max_staleness_hours=settings.odds_staleness_max_hours,
            )
        except Exception as exc:
            logger.warning("Market drift computation failed for %s: %s", match_id, exc)
            from ..features.market import MarketDriftResult
            drift_result = MarketDriftResult(
                features={k: 0.0 for k in MARKET_FEATURE_NAMES},
                data_gaps=list(MARKET_FEATURE_NAMES),
                per_feature_freshness_seconds={k: None for k in MARKET_FEATURE_NAMES},
            )

        if settings.phase8_enrichment_shadow:
            logger.info(
                "Phase8 SHADOW market_drift: match=%s features=%s gaps=%s",
                match_id,
                drift_result.features,
                drift_result.data_gaps,
            )
            for k in PHASE8_FEATURES_MARKET:
                features_dict[k] = self.defaults.get(k, 0.0)
                phase8_gaps.append(k)
                freshness[k] = None
                sources[k] = "odds_service"
        elif drift_result.data_gaps:
            for k in PHASE8_FEATURES_MARKET:
                features_dict[k] = self.defaults.get(k, 0.0)
            phase8_gaps.extend(drift_result.data_gaps)
            # drift_result freshness uses None for DATA_GAP; propagate as-is
            freshness.update(
                {k: v if k not in drift_result.data_gaps else None
                 for k, v in drift_result.per_feature_freshness_seconds.items()}
            )
            for k in PHASE8_FEATURES_MARKET:
                sources[k] = "odds_service"
        else:
            features_dict.update(drift_result.features)
            freshness.update(drift_result.per_feature_freshness_seconds)
            for k in PHASE8_FEATURES_MARKET:
                sources[k] = "odds_service"

        # ── Match importance (Phase 8 P1 live enrichment) ─────────────────────
        try:
            context_result = await compute_match_context(
                home_team_id=home_team_id,
                away_team_id=away_team_id,
                league=league,
                db=db,
                competition_stage=competition_stage,
            )
        except Exception as exc:
            logger.warning("Match context computation failed for %s: %s", match_id, exc)
            from ..features.match_context import MatchContextResult
            context_result = MatchContextResult(
                features={"match_importance_score": self.defaults.get("match_importance_score", 0.2)},
                data_gaps=list(CONTEXT_FEATURE_NAMES),
                per_feature_freshness_seconds={"match_importance_score": None},
            )

        if settings.phase8_enrichment_shadow:
            logger.info(
                "Phase8 SHADOW match_context: match=%s features=%s gaps=%s",
                match_id,
                context_result.features,
                context_result.data_gaps,
            )
            for k in PHASE8_FEATURES_CONTEXT:
                features_dict[k] = self.defaults.get(k, 0.2)
            phase8_gaps.extend(PHASE8_FEATURES_CONTEXT)
            for k in PHASE8_FEATURES_CONTEXT:
                freshness[k] = None
                sources[k] = "league_standings"
        elif context_result.data_gaps:
            for k in PHASE8_FEATURES_CONTEXT:
                features_dict[k] = self.defaults.get(k, 0.2)
            phase8_gaps.extend(context_result.data_gaps)
            freshness.update(
                {k: v if k not in context_result.data_gaps else None
                 for k, v in context_result.per_feature_freshness_seconds.items()}
            )
            for k in PHASE8_FEATURES_CONTEXT:
                sources[k] = "league_standings"
        else:
            features_dict.update(context_result.features)
            freshness.update(context_result.per_feature_freshness_seconds)
            for k in PHASE8_FEATURES_CONTEXT:
                sources[k] = "league_standings"

        return phase8_gaps, freshness, sources

    async def _get_h2h_stats(
        self,
        home_team_id: str,
        away_team_id: str,
        db: AsyncSession,
        match_date: datetime,
        n: int = 10,
    ) -> Optional[Dict[str, float]]:
        """Last N head-to-head meetings, scored from current home team's perspective."""
        query = (
            select(Match)
            .where(
                and_(
                    or_(
                        and_(Match.home_team_id == home_team_id, Match.away_team_id == away_team_id),
                        and_(Match.home_team_id == away_team_id, Match.away_team_id == home_team_id),
                    ),
                    Match.match_date < match_date,
                    Match.status == "finished",
                )
            )
            .order_by(desc(Match.match_date))
            .limit(n)
        )
        result = await db.execute(query)
        meetings = result.scalars().all()
        if not meetings:
            return None
        total = len(meetings)
        home_wins = away_wins = draws = total_goals = 0
        for m in meetings:
            if m.home_team_id == home_team_id:
                gf, ga = (m.home_score or 0), (m.away_score or 0)
            else:
                gf, ga = (m.away_score or 0), (m.home_score or 0)
            total_goals += gf + ga
            if gf > ga:
                home_wins += 1
            elif gf < ga:
                away_wins += 1
            else:
                draws += 1
        return {
            "h2h_home_wins": float(home_wins),
            "h2h_away_wins": float(away_wins),
            "h2h_draws": float(draws),
            "h2h_matches": float(total),
            "h2h_dominance": (home_wins - away_wins) / total,
        }

    async def _get_home_venue_stats(
        self,
        home_team_id: str,
        db: AsyncSession,
        match_date: datetime,
        n: int = 20,
    ) -> Optional[Dict[str, float]]:
        """Home-venue record for home_team_id from last n home matches before match_date."""
        query = (
            select(Match)
            .where(
                and_(
                    Match.home_team_id == home_team_id,
                    Match.match_date < match_date,
                    Match.status == "finished",
                )
            )
            .order_by(desc(Match.match_date))
            .limit(n)
        )
        result = await db.execute(query)
        home_matches = result.scalars().all()
        if not home_matches:
            return None
        total = len(home_matches)
        wins = sum(1 for m in home_matches if (m.home_score or 0) > (m.away_score or 0))
        draws = sum(1 for m in home_matches if (m.home_score or 0) == (m.away_score or 0))
        losses = total - wins - draws
        return {
            "home_venue_win_rate": wins / total,
            "home_venue_draw_rate": draws / total,
            "home_venue_loss_rate": losses / total,
            "home_advantage_strength": (wins - losses) / total,
        }

    async def _get_team_results_sequence(
        self,
        team_id: str,
        db: AsyncSession,
        match_date: datetime,
        n: int = 10,
    ) -> list:
        """Return last N results as 1=win, 0=draw, -1=loss (oldest→newest).

        No wall-clock lower bound — see _get_team_stats docstring; the same
        fixed-day-window bug silently starved EWMA form of history in the
        close season.
        """
        query = (
            select(Match)
            .where(
                and_(
                    (Match.home_team_id == team_id) | (Match.away_team_id == team_id),
                    Match.match_date < match_date,
                    Match.status == "finished",
                )
            )
            .order_by(desc(Match.match_date))
            .limit(n)
        )
        result = await db.execute(query)
        matches = result.scalars().all()
        results: list = []
        for match in reversed(matches):
            is_home = match.home_team_id == team_id
            gf = (match.home_score if is_home else match.away_score) or 0
            ga = (match.away_score if is_home else match.home_score) or 0
            results.append(1 if gf > ga else 0 if gf == ga else -1)
        return results

    async def _get_match(self, match_id: str, db: AsyncSession) -> Optional[Match]:
        query = select(Match).where(Match.id == match_id)
        result = await db.execute(query)
        return result.scalar_one_or_none()

    async def _get_team_name(self, team_id: str, db: AsyncSession) -> Optional[str]:
        query = select(Team.name).where(Team.id == team_id)
        result = await db.execute(query)
        return result.scalar_one_or_none()

    def _derive_season(self, match_date: datetime) -> str:
        return canonical_season(match_date)

    async def _get_team_id_by_name(
        self, team_name: str, db: AsyncSession
    ) -> Optional[str]:
        """Get team ID by team name (exact, affix-stripped, then fuzzy — see team_identity)."""
        return await resolve_team_id(team_name, db)

    async def _get_team_stats(
        self,
        team_id: str,
        db: AsyncSession,
        match_date: datetime,
        is_home: bool = True,
    ) -> Optional[Dict[str, float]]:
        """Fetch recent team statistics for feature engineering.

        No wall-clock lower bound — a fixed N-day window silently starves every
        team of history whenever the gap since the last completed match exceeds
        it (e.g. the close season). ``.limit(20)`` alone bounds the query; a team
        with a real but old last match still resolves instead of going synthetic.

        is_home controls only the home_/away_ prefix on the returned keys —
        matches data/team_database.py:get_team_stats()'s is_home convention
        (WP-18/D8b). Captured into `prefix` before the loop below, which binds
        its own unrelated per-match `is_home` local; never reference the
        parameter by name after this point.
        """
        prefix = "home" if is_home else "away"
        query = (
            select(Match)
            .where(
                and_(
                    (Match.home_team_id == team_id) | (Match.away_team_id == team_id),
                    Match.match_date < match_date,
                    Match.status == "finished",
                )
            )
            .order_by(desc(Match.match_date))
            .limit(20)
        )

        result = await db.execute(query)
        recent_matches = result.scalars().all()

        if not recent_matches:
            logger.debug("No historical matches found for team %s before %s", team_id, match_date)
            return None

        stats = {}
        points = []
        goals_for = []
        goals_against = []

        for match in recent_matches:
            is_home = match.home_team_id == team_id
            gf = (match.home_score if is_home else match.away_score) or 0
            ga = (match.away_score if is_home else match.home_score) or 0
            goals_for.append(gf)
            goals_against.append(ga)
            if gf > ga:
                points.append(3)
            elif gf == ga:
                points.append(1)
            else:
                points.append(0)

        if len(points) >= 5:
            stats[f"{prefix}_form_5"] = sum(points[:5]) / 15.0
            stats[f"{prefix}_win_rate_5"] = sum(1 for p in points[:5] if p == 3) / 5.0
        else:
            stats[f"{prefix}_form_5"] = sum(points) / (len(points) * 3.0) if points else 0.5
            stats[f"{prefix}_win_rate_5"] = (
                sum(1 for p in points if p == 3) / len(points) if points else 0.4
            )

        # WP-18: real last-5 win/draw/loss counts from the points list already
        # computed above — strictly more accurate than derive_last5_form_features()'s
        # round()/estimate fallback. Deliberately unprefixed, matching
        # ScrapedTeamForm.to_projection_stats()'s existing wins_5/draws_5/losses_5
        # convention — safe despite the shared name across home_stats/away_stats
        # because callers only ever read them off this per-side dict before the
        # features_dict merge in project_match_features(), never out of the
        # merged dict.
        stats["wins_5"] = float(sum(1 for p in points[:5] if p == 3))
        stats["draws_5"] = float(sum(1 for p in points[:5] if p == 1))
        stats["losses_5"] = float(sum(1 for p in points[:5] if p == 0))

        if len(points) >= 10:
            stats[f"{prefix}_form_10"] = sum(points[:10]) / 30.0
        else:
            stats[f"{prefix}_form_10"] = stats.get(f"{prefix}_form_5", 0.5)

        stats[f"{prefix}_goals_per_match_5"] = (
            np.mean(goals_for[:5]) if len(goals_for) >= 5 else np.mean(goals_for) if goals_for else 1.5
        )
        stats[f"{prefix}_goals_conceded_per_match_5"] = (
            np.mean(goals_against[:5]) if len(goals_against) >= 5 else np.mean(goals_against) if goals_against else 1.2
        )

        if recent_matches:
            last_match_date = recent_matches[0].match_date
            rest_days = (match_date - last_match_date).days
            stats[f"{prefix}_days_rest"] = min(rest_days, 10.0)
            stats[f"{prefix}_fatigue_index"] = max(0.0, 1.0 - (rest_days / 7.0))
            # How recent the newest match backing this side's form actually is.
            # Deliberately unprefixed, matching the wins_5/draws_5/losses_5
            # convention above: read off the per-side dict in
            # project_match_features() before the merge, never out of the merged
            # dict. Consumed to distinguish "form is genuinely old" from "an
            # offline enrichment artifact is old" — see _staleness_from_stats().
            # Match.match_date is naive TIMESTAMP WITHOUT TIME ZONE holding UTC;
            # bare .timestamp() would read it as *local* time and skew the age by
            # the host's UTC offset. Attach UTC explicitly (repo-wide convention).
            stats["last_finished_match_ts"] = float(
                last_match_date.replace(tzinfo=timezone.utc).timestamp()
            )
        else:
            stats[f"{prefix}_days_rest"] = 7.0
            stats[f"{prefix}_fatigue_index"] = 0.3

        clean_sheets = sum(1 for ga in goals_against[:5] if ga == 0)
        stats[f"{prefix}_clean_sheets_5"] = (
            clean_sheets / min(5, len(goals_against)) if goals_against else 0.3
        )

        gd = [f - a for f, a in zip(goals_for[:5], goals_against[:5])]
        stats[f"{prefix}_gd_avg_5"] = np.mean(gd) if gd else 0.0
        if len(gd) >= 2:
            try:
                trend = np.polyfit(range(len(gd)), gd, 1)[0]
                stats[f"{prefix}_gd_trend"] = float(trend)
            except Exception:
                stats[f"{prefix}_gd_trend"] = 0.0

        xg_values = await self._get_team_xg(team_id, db, recent_matches)
        if xg_values:
            stats[f"{prefix}_xg_avg_5"] = np.mean(xg_values[:5])
            stats[f"{prefix}_xg_consistency"] = np.std(xg_values[:5]) if len(xg_values) >= 5 else 0.75

        return stats if stats else None

    def _apply_scraped_fallback(
        self,
        stats: Optional[Dict[str, float]],
        *,
        competition: Optional[str],
        team: str,
        match_date: datetime,
        is_home: bool = True,
    ) -> Tuple[Optional[Dict[str, float]], Optional[Dict[str, Any]]]:
        """WP-10.1 — consult the scraped football-data.co.uk CSV artifact only when
        the DB has zero completed-match history for this team (``stats is None``).
        Supplementary, never a silent DB substitute (INV-10): callers get the
        provenance dict back separately and must not fold it into ``is_synthetic``.
        Never raises — a missing/corrupt artifact degrades to "no fallback", the
        same as if ``ScrapedTeamFormStore`` had never been called.

        is_home is forwarded to to_projection_stats() so the fallback's keys
        carry the correct home_/away_ prefix (WP-18/D8b) instead of always
        defaulting to "home_".
        """
        if stats is not None or not competition:
            return stats, None
        try:
            league_code = canonical_league_id(competition)
            record = self.scraped_form_store.get_team_form(
                competition=league_code, team=team, information_cutoff=match_date
            )
        except Exception:
            logger.debug("Scraped fallback lookup failed for %s (%s)", team, competition, exc_info=True)
            return stats, None
        if record is None:
            return stats, None
        return record.to_projection_stats(is_home=is_home), {
            "source": f"scraped:football-data-csv:{record.source_file.name}",
            "matches_sampled": record.matches_sampled,
            "acquired_at": record.latest_match_date.isoformat() if record.latest_match_date else None,
        }

    async def _get_team_xg(
        self,
        team_id: str,
        db: AsyncSession,
        matches: list,
    ) -> Optional[list]:
        """Get xG values for team across matches."""
        match_ids = [m.id for m in matches]
        if not match_ids:
            return None

        query = select(MatchStats.expected_goals).where(
            and_(
                MatchStats.match_id.in_(match_ids),
                MatchStats.team_id == team_id,
                MatchStats.expected_goals.isnot(None),
            )
        )

        result = await db.execute(query)
        xg_values = result.scalars().all()
        return list(xg_values) if xg_values else None
