"""
SabiScore Core Engine - Strict Betting Intelligence HTTP Adapter
CONTRACT VERSION: 1.1.0

Routes:
  POST /api/v1/betting-intelligence/analyze
    Strict single or batch analysis. Accepts the versioned request contract.
    Returns the versioned response contract.

  POST /api/v1/betting-intelligence/analyze/single
    Convenience wrapper for single-match analysis.

  GET /api/v1/betting-intelligence/policy
    Returns current engine policy parameters (edge thresholds, Kelly caps).

  GET /api/v1/betting-intelligence/health
    Returns engine health (no external dependencies).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, status
from ...models.active_generation import active_generation_is_certified

from ...schemas.betting_intelligence import (
    BatchAnalysisRequest,
    BatchAnalysisResponse,
    MatchAnalysisRequest,
    MatchAnalysisResult,
)
from ...services.betting_intelligence import (
    KELLY_FRACTION,
    MAX_KELLY_CAP,
    MIN_ACTIONABLE_EDGE,
    HIGH_CONVICTION_EDGE,
    MODEL_FEATURES_FRESH_SECONDS,
    SPECULATIVE_STAKE_CAP,
    analyze_batch,
    analyze_match,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/betting-intelligence",
    tags=["betting-intelligence"],
)


def _with_server_generation(request: MatchAnalysisRequest) -> MatchAnalysisRequest:
    if request.model is None:
        return request
    return request.model_copy(
        update={
            "model": request.model.model_copy(
                update={"generation_certified": active_generation_is_certified()}
            )
        }
    )


@router.post(
    "/analyze",
    response_model=BatchAnalysisResponse,
    summary="Strict batch betting intelligence analysis",
    description=(
        "Submit 1-100 matches for deterministic betting analysis. "
        "Returns verdicts, edge calculations, de-vigged market probabilities, "
        "Kelly stakes, and ranked top opportunities. "
        "Missing or invalid critical inputs return PARTIAL - never substituted defaults."
    ),
)
async def analyze(
    request: BatchAnalysisRequest,
    causal_drivers: Optional[Dict[str, List[str]]] = None,
) -> BatchAnalysisResponse:
    """Strict batch analysis endpoint.

    The request body must conform to the BatchAnalysisRequest schema.
    Each match's model and market fields must be fully populated for a verdict
    above PARTIAL. Missing or invalid inputs return PARTIAL with explicit
    data_gaps - they are never substituted with defaults or averages.
    """
    try:
        evaluation_at = datetime.now(timezone.utc)
        governed_request = request.model_copy(
            update={"matches": [_with_server_generation(match) for match in request.matches]}
        )
        result = analyze_batch(
            request=governed_request,
            causal_drivers_map=causal_drivers,
            evaluation_at=evaluation_at,
        )
        logger.info(
            "Betting intelligence batch completed: %d matches, %d top opportunities",
            len(result.matches),
            len(result.top_opportunities),
        )
        return result
    except Exception as exc:
        logger.exception("Unexpected error in betting intelligence batch analysis: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "ENGINE_ERROR",
                "message": "Unexpected engine failure. All input evidence was rejected as a safety measure.",
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
        ) from exc


@router.post(
    "/analyze/single",
    response_model=MatchAnalysisResult,
    summary="Single-match betting intelligence analysis",
    description=(
        "Analyze a single match. Convenience wrapper around the batch endpoint. "
        "Returns a single MatchAnalysisResult."
    ),
)
async def analyze_single(
    request: MatchAnalysisRequest,
    causal_drivers: Optional[List[str]] = None,
) -> MatchAnalysisResult:
    """Single-match convenience endpoint."""
    try:
        result = analyze_match(
            request=_with_server_generation(request),
            causal_drivers=causal_drivers,
            evaluation_at=datetime.now(timezone.utc),
        )
        logger.info(
            "Single match analysis: %s -> %s",
            request.match_id,
            result.verdict.value,
        )
        return result
    except Exception as exc:
        logger.exception("Engine error for match %s: %s", request.match_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "ENGINE_ERROR",
                "message": "Unexpected engine failure.",
                "match_id": request.match_id,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
        ) from exc


@router.get(
    "/policy",
    summary="Current engine policy parameters",
    description="Returns the active staking and edge thresholds. No sensitive configuration is exposed.",
)
async def get_policy() -> Dict[str, Any]:
    """Return active engine policy parameters for client auditing."""
    return {
        "contract_version": "1.2.0",
        "engine_version": "1.1.0",
        "policy_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy": {
            "min_actionable_edge_pp": round(MIN_ACTIONABLE_EDGE * 100, 2),
            "high_conviction_edge_pp": round(HIGH_CONVICTION_EDGE * 100, 2),
            "kelly_fraction": KELLY_FRACTION,
            "max_kelly_cap": MAX_KELLY_CAP,
            "speculative_stake_cap": SPECULATIVE_STAKE_CAP,
            "minimum_acceptable_odds_method": "DE_VIGGED_1X2_EDGE_SOLVE_HOLDING_OTHER_PRICES",
            "target_expected_value": 0.0,
            "verdict_precedence": [
                "PARTIAL",
                "NO_BET",
                "HOLD",
                "SPECULATIVE",
                "ACTIONABLE",
                "HIGH_CONVICTION",
            ],
            "ucl_coverage": "SOFT - HIGH_CONVICTION excluded until dedicated model validated",
            "market_freshness_thresholds": {
                "fresh_seconds": 900,
                "recent_seconds": 3600,
                "stale_above_seconds": 3600,
            },
            "model_features_fresh_seconds": MODEL_FEATURES_FRESH_SECONDS,
            "null_rules": {
                "missing_quantitative_data": "null - never 0 or league average",
                "stake_under_partial_hold_no_bet": "pass",
                "probabilities_under_partial": "null when model did not produce valid prediction",
            },
        },
    }


@router.get(
    "/health",
    summary="Engine health check",
    description="Returns engine health status. No external dependencies queried.",
)
async def health() -> Dict[str, Any]:
    """Engine health - no external I/O, always fast."""
    return {
        "status": "healthy",
        "engine_version": "1.1.0",
        "engine_type": "deterministic",
        "external_dependencies": "none",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
