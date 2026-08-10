"""SabiScore Core Engine v2.1 API endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from ...models.active_generation import active_generation_is_certified
from ...schemas.core_engine import CoreEngineAnalyzeRequest, CoreEngineResponse
from ...services.core_engine import analyze_core_matches


router = APIRouter(prefix="/core-engine", tags=["core-engine"])


@router.post("/analyze", response_model=CoreEngineResponse)
async def analyze_core_engine(payload: CoreEngineAnalyzeRequest) -> CoreEngineResponse:
    """Analyze supplied pre-match betting intelligence inputs without live fetches."""

    certified = active_generation_is_certified()
    governed_matches = [
        match.model_copy(
            update={
                "model": match.model.model_copy(update={"generation_certified": certified})
                if match.model is not None
                else None
            }
        )
        for match in payload.matches
    ]
    return analyze_core_matches(governed_matches)


__all__ = ["router"]
