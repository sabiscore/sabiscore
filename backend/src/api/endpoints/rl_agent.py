"""RL betting agent endpoint (Phase 6-C advisory mode)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Dict

from ...services.rl_betting_agent import RLBettingAgent
from ...schemas.prediction import RLRecommendation

router = APIRouter(prefix="/rl", tags=["rl-agent"])

_agent = RLBettingAgent()


class RLRecommendRequest(BaseModel):
    probabilities: Dict[str, float] = Field(
        ...,
        description="Outcome probabilities: home_win, draw, away_win",
        json_schema_extra={
            "example": {"home_win": 0.48, "draw": 0.27, "away_win": 0.25}
        },
    )
    odds: Dict[str, float] = Field(
        default_factory=dict,
        description="Decimal market odds: home_win, draw, away_win",
        json_schema_extra={"example": {"home_win": 2.1, "draw": 3.4, "away_win": 3.8}},
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Overall model confidence (top-class probability)",
    )
    epistemic_unc: float = Field(
        default=0.1,
        ge=0.0,
        description="Epistemic uncertainty from BNN; triggers abstention when above threshold",
    )
    aleatoric_unc: float = Field(default=0.0, ge=0.0)
    bankroll_pct: float = Field(default=1.0, ge=0.0, le=10.0)
    current_drawdown: float = Field(default=0.0, ge=0.0)
    rolling_sharpe: float = Field(default=0.0)
    win_rate_20: float = Field(default=0.5, ge=0.0, le=1.0)
    rolling_ece_20: float = Field(default=0.0, ge=0.0)


@router.post("/recommend", response_model=RLRecommendation)
async def get_rl_recommendation(request: RLRecommendRequest) -> RLRecommendation:
    """Return a Kelly-capped staking recommendation from the RL betting agent.

    When a trained SAC model is available at ``settings.rl_agent_path`` the
    recommendation is model-driven.  Otherwise the deterministic Kelly-fraction
    fallback is used — always available, no extra dependencies.

    The endpoint is **advisory only** and does not place bets.
    """
    probs = request.probabilities
    if not probs:
        raise HTTPException(
            status_code=422, detail="probabilities must be a non-empty mapping"
        )

    total = sum(probs.values())
    if not (0.90 <= total <= 1.10):
        raise HTTPException(
            status_code=422,
            detail=f"Probabilities must sum to ~1.0 (got {total:.3f})",
        )

    try:
        payload = _agent.recommend(
            probabilities=probs,
            odds=request.odds,
            confidence=request.confidence,
            epistemic_unc=request.epistemic_unc,
            aleatoric_unc=request.aleatoric_unc,
            bankroll_pct=request.bankroll_pct,
            current_drawdown=request.current_drawdown,
            rolling_sharpe=request.rolling_sharpe,
            win_rate_20=request.win_rate_20,
            rolling_ece_20=request.rolling_ece_20,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"RL agent error: {exc}") from exc

    return RLRecommendation(
        stake_fraction=payload.stake_fraction,
        abstain=payload.abstain,
        reward_components=payload.reward_components,
        reason=payload.reason,
    )
