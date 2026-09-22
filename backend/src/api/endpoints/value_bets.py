"""Value bet discovery and analysis endpoints."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from ...db.session import get_async_session
from ...core.cache import cache_manager
from ...schemas.value_bet import ValueBetResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/value-bets", tags=["value-bets"])

# Minimum edge threshold for a value bet (4.2% as per PRD)
MIN_EDGE_THRESHOLD = 4.2


class ValueBetFilter(BaseModel):
    """Filtering criteria for value bet discovery."""

    league: Optional[str] = Field(
        None, description="Filter by league (e.g., EPL, LaLiga)"
    )
    min_edge: float = Field(
        MIN_EDGE_THRESHOLD, ge=0, description="Minimum edge percentage"
    )
    min_confidence: float = Field(
        0.70, ge=0, le=1, description="Minimum confidence threshold"
    )
    max_results: int = Field(20, ge=1, le=100, description="Maximum results to return")
    markets: Optional[List[str]] = Field(
        None, description="Markets to include (home_win, draw, away_win)"
    )


class ValueBetSummary(BaseModel):
    """Summary statistics for value bets."""

    total_bets: int
    avg_edge: float
    avg_confidence: float
    total_potential_edge_ngn: float
    by_league: Dict[str, int]
    by_market: Dict[str, int]


class ValueBetListResponse(BaseModel):
    """Paginated value bet list with data-gap signalling."""

    items: List[ValueBetResponse]
    total: int
    data_gap: bool = Field(
        default=False,
        description=(
            "True when no predictions exist in the DB within the last 6 hours. "
            "Scanner requires at least one prediction to surface value bets. "
            "Link users to /match to generate a prediction first."
        ),
    )


@router.get("/", response_model=ValueBetListResponse)
async def list_value_bets(
    league: Optional[str] = Query(None, description="Filter by league"),
    min_edge: float = Query(MIN_EDGE_THRESHOLD, ge=0, description="Minimum edge %"),
    min_confidence: float = Query(0.70, ge=0, le=1, description="Minimum confidence"),
    max_results: int = Query(20, ge=1, le=100, description="Max results"),
    db: AsyncSession = Depends(get_async_session),
) -> ValueBetListResponse:
    """
    Retrieve active value bets meeting the specified criteria.

    Default thresholds:
    - Edge ≥ 4.2% (aligned with research on long-term profitability)
    - Confidence ≥ 70%

    The ``data_gap`` flag is ``true`` when no predictions exist within the last 6 hours.
    When ``data_gap=true`` the scanner is empty because it has nothing to derive bets from.
    Direct users to ``/match`` to generate a prediction first.

    Results ordered by edge (descending) to surface highest-value opportunities first.
    """
    cache_key = (
        f"value_bets:{league or 'all'}:{min_edge}:{min_confidence}:{max_results}"
    )

    cached = cache_manager.get(cache_key)
    if cached and isinstance(cached, dict):
        logger.debug("Cache hit for value bets: %s", cache_key)
        return ValueBetListResponse(**cached)

    try:
        from ...core.database import Prediction as PredictionModel
        import json

        cutoff = datetime.now(timezone.utc) - timedelta(hours=6)

        query = select(PredictionModel).where(PredictionModel.created_at >= cutoff)
        result = await db.execute(query)
        predictions = result.scalars().all()

        data_gap = len(predictions) == 0

        value_bets: List[ValueBetResponse] = []

        for pred in predictions:
            features = pred.features
            if isinstance(features, str):
                try:
                    features = json.loads(features)
                except json.JSONDecodeError:
                    continue

            if not isinstance(features, dict):
                continue

            vb_data = features.get("value_bets", [])
            if isinstance(vb_data, list):
                for vb in vb_data:
                    if not isinstance(vb, dict):
                        continue

                    edge = vb.get("edge_percent", 0)
                    conf = vb.get("confidence", 0)

                    if edge >= min_edge and conf >= min_confidence:
                        if (
                            league
                            and vb.get("league", features.get("league")) != league
                        ):
                            continue
                        try:
                            value_bets.append(ValueBetResponse(**vb))
                        except Exception as parse_err:
                            logger.debug("Skipping malformed value bet: %s", parse_err)

        value_bets.sort(key=lambda x: x.edge_percent, reverse=True)
        value_bets = value_bets[:max_results]

        response = ValueBetListResponse(
            items=value_bets,
            total=len(value_bets),
            data_gap=data_gap,
        )
        cache_manager.set(cache_key, response.model_dump(mode="json"), ttl=300)
        return response

    except Exception as exc:
        logger.error("Failed to retrieve value bets: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500, detail="Failed to retrieve value bets"
        ) from exc


@router.get("/summary", response_model=ValueBetSummary)
async def value_bet_summary(
    db: AsyncSession = Depends(get_async_session),
) -> ValueBetSummary:
    """
    Get aggregate statistics for currently active value bets.

    Useful for dashboard displays and alerting thresholds.
    """
    cache_key = "value_bets:summary"
    cached = cache_manager.get(cache_key)
    if cached:
        return ValueBetSummary(**cached)

    try:
        # Fetch all value bets without stringent filters for summary
        value_bets = await list_value_bets(
            league=None,
            min_edge=0,
            min_confidence=0,
            max_results=100,
            db=db,
        )

        if not value_bets:
            summary = ValueBetSummary(
                total_bets=0,
                avg_edge=0.0,
                avg_confidence=0.0,
                total_potential_edge_ngn=0.0,
                by_league={},
                by_market={},
            )
        else:
            by_league: Dict[str, int] = {}
            by_market: Dict[str, int] = {}
            total_edge_ngn = 0.0

            for vb in value_bets:
                # Aggregate by league (if available in match_id prefix or similar)
                league_key = (
                    vb.match_id.split("_")[0].upper()
                    if "_" in vb.match_id
                    else "unknown"
                )
                by_league[league_key] = by_league.get(league_key, 0) + 1

                by_market[vb.market] = by_market.get(vb.market, 0) + 1
                total_edge_ngn += vb.edge_ngn

            summary = ValueBetSummary(
                total_bets=len(value_bets),
                avg_edge=sum(vb.edge_percent for vb in value_bets) / len(value_bets),
                avg_confidence=sum(vb.confidence for vb in value_bets)
                / len(value_bets),
                total_potential_edge_ngn=total_edge_ngn,
                by_league=by_league,
                by_market=by_market,
            )

        cache_manager.set(cache_key, summary.model_dump(), ttl=300)
        return summary

    except Exception as exc:
        logger.error("Failed to compute value bet summary: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500, detail="Failed to compute summary"
        ) from exc


@router.get("/{match_id}", response_model=List[ValueBetResponse])
async def get_value_bets_for_match(
    match_id: str,
    db: AsyncSession = Depends(get_async_session),
) -> List[ValueBetResponse]:
    """
    Retrieve all value bets detected for a specific match.

    Returns empty list if no value bets found (prediction may exist but have no edge).
    """
    cache_key = f"value_bets:match:{match_id}"
    cached = cache_manager.get(cache_key)
    if cached:
        return [ValueBetResponse(**vb) for vb in cached]

    try:
        from ...core.database import Prediction as PredictionModel
        import json

        query = select(PredictionModel).where(PredictionModel.match_id == match_id)
        result = await db.execute(query)
        prediction = result.scalar_one_or_none()

        if not prediction:
            raise HTTPException(
                status_code=404, detail=f"No prediction found for match {match_id}"
            )

        features = prediction.features
        if isinstance(features, str):
            try:
                features = json.loads(features)
            except json.JSONDecodeError:
                return []

        if not isinstance(features, dict):
            return []

        vb_data = features.get("value_bets", [])
        value_bets = []

        if isinstance(vb_data, list):
            for vb in vb_data:
                if isinstance(vb, dict):
                    try:
                        value_bets.append(ValueBetResponse(**vb))
                    except Exception:
                        continue

        cache_manager.set(cache_key, [vb.model_dump() for vb in value_bets], ttl=300)
        return value_bets

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "Failed to get value bets for match %s: %s", match_id, exc, exc_info=True
        )
        raise HTTPException(
            status_code=500, detail="Failed to retrieve value bets"
        ) from exc


__all__ = ["router"]
