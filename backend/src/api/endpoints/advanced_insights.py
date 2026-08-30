"""Advanced Match Insights API Endpoint (R4 of v5 directive).

Route: GET /api/v1/matches/{match_id}/advanced-insights
Provides an aggregation and read layer composing tactical metrics, match context,
market intelligence provenance, and certification invariants.
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.session import get_async_session
from ...schemas.advanced_insights import AdvancedInsightsResponse
from ...services.advanced_insights_service import AdvancedInsightsService
from ...services.odds_service import OddsService, get_odds_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/matches", tags=["intelligence"])


@router.get(
    "/{match_id}/advanced-insights",
    response_model=AdvancedInsightsResponse,
    summary="Get advanced tactical metrics, context, and market intelligence for a match",
    response_description="Unified analytical intelligence payload with full provenance",
)
async def get_match_advanced_insights(
    match_id: str,
    db: AsyncSession = Depends(get_async_session),
    odds_service: OddsService = Depends(get_odds_service),
) -> AdvancedInsightsResponse:
    """Retrieve advanced match intelligence.

    Composes:
    - Advanced tactical metrics (PPDA, PSxG, xT)
    - Contextual signals (weather, referee profile, fatigue)
    - Market intelligence with devigging provenance
    - Model certification invariants (fail-closed staking)
    """
    service = AdvancedInsightsService(odds_service=odds_service)
    try:
        insights = await service.get_advanced_insights(match_id=match_id, db=db)
    except Exception as exc:
        logger.exception("Failed to retrieve advanced insights for match %s: %s", match_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate advanced insights",
        )

    if insights is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Match with id '{match_id}' was not found",
        )

    return insights
