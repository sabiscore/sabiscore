"""Phase 8 feature-intelligence endpoint.

Route: GET /matches/upcoming/{match_id}/phase8-features

Returns the Phase 8 enriched feature values for a given match:
  - Pi-ratings (home/away attack+defense, diffs)
  - Berrar ratings (home/away + diff)
  - EWMA form metrics (weighted win-rate, draw-rate, PPG × 2 sides)
  - Market movement indicators (odds drift per outcome + sharp-money direction)
  - Match importance score

Feature availability depends on live data status:
  - Features with live data: returned at computed values.
  - Features without live data: returned at registry defaults, tagged DATA_GAP.

Cache: Redis key ``phase8:{match_id}:{league}``, TTL 60 s (same as full-analysis).
Feature flag: Phase 8 must be enabled in settings; when disabled, returns
    a degraded payload with ``status="disabled"`` and defaulted feature values.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.cache import cache
from ...core.config import settings
from ...db.session import get_async_session
from ...models.feature_registry import (
    DEFAULT_FEATURE_VALUES_86,
    PHASE8_FEATURES_BERRAR,
    PHASE8_FEATURES_CONTEXT,
    PHASE8_FEATURES_FORM,
    PHASE8_FEATURES_MARKET,
    PHASE8_FEATURES_PI,
    PHASE8_FEATURES_18,
)
from ...services.upcoming_match_feature_service import UpcomingMatchFeatureProjector
from ...services.odds_service import OddsService, get_odds_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/matches", tags=["phase8", "intelligence"])

_CACHE_TTL_SECONDS = 60

# ── Feature group metadata ─────────────────────────────────────────────────────

_GROUP_META: Dict[str, Dict[str, Any]] = {
    "pi_ratings": {
        "label": "Pi-Ratings",
        "description": "Adaptive ratings measuring attack and defense strength independently.",
        "features": PHASE8_FEATURES_PI,
        "reference": "Constantinou & Fenton (2013) pi-ratings methodology.",
    },
    "berrar_ratings": {
        "label": "Berrar Ratings",
        "description": "Probabilistic ratings calibrated to match outcomes (win/draw/loss).",
        "features": PHASE8_FEATURES_BERRAR,
        "reference": "Berrar et al. (2019) predictive rating system.",
    },
    "ewma_form": {
        "label": "EWMA Form",
        "description": "Exponentially-weighted moving-average form metrics, down-weighting older matches.",
        "features": PHASE8_FEATURES_FORM,
        "reference": "Decay factor λ=0.85 on last 10 matches.",
    },
    "market_movement": {
        "label": "Market Movement",
        "description": "Opening-to-current odds drift and inferred sharp-money direction.",
        "features": PHASE8_FEATURES_MARKET,
        "reference": "Opening odds window 72 h pre-match.",
    },
    "match_context": {
        "label": "Match Importance",
        "description": "Composite match-importance score based on league table position, relegation/title implications, and cup stakes.",
        "features": PHASE8_FEATURES_CONTEXT,
        "reference": "SabiScore Phase 8 match-context model.",
    },
}

# ── Pydantic models ────────────────────────────────────────────────────────────


class FeatureValue(BaseModel):
    name: str
    value: float
    is_data_gap: bool = False
    freshness_seconds: Optional[int] = None  # None = DATA_GAP; 0 = fresh; >0 = staleness in seconds
    source: Optional[str] = None


class FeatureGroup(BaseModel):
    group_id: str
    label: str
    description: str
    reference: str
    features: List[FeatureValue]
    all_available: bool
    group_freshness_seconds: int = 0  # max staleness across the group's live features


class Phase8FeaturesResponse(BaseModel):
    match_id: str
    league: str
    status: str = Field(description="'ok' or 'partial' when data gaps exist")
    data_gaps: List[str] = Field(default_factory=list)
    feature_groups: List[FeatureGroup]
    feature_freshness_seconds: Dict[str, Optional[int]] = Field(default_factory=dict)  # None = DATA_GAP
    feature_source: Dict[str, str] = Field(default_factory=dict)
    total_phase8_features: int = len(PHASE8_FEATURES_18)
    available_features: int
    phase8_enabled: bool
    source: str = "phase8_feature_endpoint"


# ── Helpers ────────────────────────────────────────────────────────────────────


def _is_phase8_enabled() -> bool:
    import os as _os
    raw = _os.environ.get("USE_PHASE8_FEATURES", "").lower()
    if raw in ("1", "true", "yes"):
        return True
    if raw in ("0", "false", "no"):
        return False
    return settings.phase8_enabled


def _build_feature_values(
    live_values: Dict[str, Any],
    data_gaps: List[str],
    per_feature_freshness: Optional[Dict[str, Optional[int]]] = None,
    per_feature_source: Optional[Dict[str, str]] = None,
) -> Dict[str, FeatureValue]:
    """Merge live values with defaults, tagging gaps and carrying freshness."""
    _freshness = per_feature_freshness or {}
    _sources = per_feature_source or {}
    result: Dict[str, FeatureValue] = {}
    for feat in PHASE8_FEATURES_18:
        freshness = _freshness.get(feat, None)
        src = _sources.get(feat, None)
        if feat in live_values and live_values[feat] is not None and feat not in data_gaps:
            result[feat] = FeatureValue(
                name=feat,
                value=float(live_values[feat]),
                is_data_gap=False,
                freshness_seconds=freshness,
                source=src or "live",
            )
        else:
            result[feat] = FeatureValue(
                name=feat,
                value=DEFAULT_FEATURE_VALUES_86.get(feat, 0.0),
                is_data_gap=True,
                freshness_seconds=None,  # DATA_GAP — no freshness value
                source=src or "registry_default",
            )
            if feat not in data_gaps:
                data_gaps.append(feat)
    return result


def _build_groups(fv_map: Dict[str, FeatureValue]) -> List[FeatureGroup]:
    groups: List[FeatureGroup] = []
    for group_id, meta in _GROUP_META.items():
        feats = [fv_map[f] for f in meta["features"] if f in fv_map]
        live_freshness = [
            f.freshness_seconds for f in feats
            if not f.is_data_gap and f.freshness_seconds is not None
        ]
        group_freshness = max(live_freshness) if live_freshness else 0
        groups.append(
            FeatureGroup(
                group_id=group_id,
                label=meta["label"],
                description=meta["description"],
                reference=meta["reference"],
                features=feats,
                all_available=all(not f.is_data_gap for f in feats),
                group_freshness_seconds=group_freshness,
            )
        )
    return groups


# ── Route ──────────────────────────────────────────────────────────────────────


@router.get(
    "/upcoming/{match_id}/phase8-features",
    response_model=Phase8FeaturesResponse,
    summary="Phase 8 feature values for a match",
    description=(
        "Returns the Phase 8 enriched feature values for a match, grouped by "
        "feature category (Pi-ratings, Berrar ratings, EWMA form, market movement, "
        "match context). Features missing from live data are returned at registry "
        "defaults and tagged `is_data_gap=true`. Requires Phase 8 to be enabled in settings."
    ),
)
async def get_phase8_features(
    match_id: str,
    league: str = Query(default="EPL", description="League slug (EPL, La Liga, …)"),
    db: AsyncSession = Depends(get_async_session),
    odds_service: OddsService = Depends(get_odds_service),
) -> Phase8FeaturesResponse:
    phase8_enabled = _is_phase8_enabled()

    if not phase8_enabled:
        defaults = {f: DEFAULT_FEATURE_VALUES_86.get(f, 0.0) for f in PHASE8_FEATURES_18}
        data_gaps = list(PHASE8_FEATURES_18)
        fv_map = _build_feature_values(defaults, data_gaps)
        groups = _build_groups(fv_map)
        return Phase8FeaturesResponse(
            match_id=match_id,
            league=league,
            status="disabled",
            data_gaps=data_gaps,
            feature_groups=groups,
            feature_freshness_seconds={},
            feature_source={},
            available_features=0,
            phase8_enabled=False,
        )

    cache_key = f"phase8:{match_id}:{league}"
    cached = cache.get(cache_key)
    if cached is not None:
        logger.debug("phase8 cache hit: %s", cache_key)
        return Phase8FeaturesResponse(**cached)

    live_values: Dict[str, Any] = {}
    data_gaps: List[str] = []
    per_feature_freshness: Dict[str, Optional[int]] = {}
    per_feature_source: Dict[str, str] = {}

    try:
        feature_projector = UpcomingMatchFeatureProjector(
            odds_service=odds_service if isinstance(odds_service, OddsService) else None
        )
        sep = " vs " if " vs " in match_id else (" VS " if " VS " in match_id else None)

        if sep is not None:
            parts = match_id.split(sep, 1)
            proj_result = await feature_projector.build_live_feature_vector_from_matchup(
                home_team=parts[0].strip(),
                away_team=parts[1].strip() if len(parts) > 1 else "Unknown",
                league=league,
                db=db,
            )
        else:
            proj_result = await feature_projector.build_live_feature_vector(
                match_id=match_id,
                league=league,
                db=db,
            )

        features_dict: Dict[str, Any] = proj_result.get("features_dict", {})
        live_values = {f: features_dict[f] for f in PHASE8_FEATURES_18 if f in features_dict}
        data_gaps = list(proj_result.get("data_gaps", []))
        per_feature_freshness = {
            k: v
            for k, v in proj_result.get("feature_freshness_seconds", {}).items()
            if k in PHASE8_FEATURES_18
        }
        per_feature_source = {
            k: v
            for k, v in proj_result.get("feature_source", {}).items()
            if k in PHASE8_FEATURES_18
        }
    except Exception as exc:
        logger.warning(
            "phase8 feature projection failed for %s (%s): %s — using defaults",
            match_id, type(exc).__name__, exc,
        )

    fv_map = _build_feature_values(live_values, data_gaps, per_feature_freshness, per_feature_source)
    groups = _build_groups(fv_map)
    available = sum(1 for fv in fv_map.values() if not fv.is_data_gap)
    deduped_gaps = sorted(set(data_gaps))
    phase8_freshness_out = {k: v for k, v in per_feature_freshness.items() if k in PHASE8_FEATURES_18}
    phase8_source_out = {k: v for k, v in per_feature_source.items() if k in PHASE8_FEATURES_18}

    response = Phase8FeaturesResponse(
        match_id=match_id,
        league=league,
        status="partial" if deduped_gaps else "ok",
        data_gaps=deduped_gaps,
        feature_groups=groups,
        feature_freshness_seconds=phase8_freshness_out,
        feature_source=phase8_source_out,
        available_features=available,
        phase8_enabled=True,
    )

    try:
        cache.set(cache_key, response.model_dump(), ttl=_CACHE_TTL_SECONDS)
    except Exception as exc:
        logger.warning("phase8 cache set failed: %s", exc)

    return response
