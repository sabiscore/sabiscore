"""Model performance and value bet scan endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.session import get_async_session
from ...repositories.fixtures import get_clv_records, get_settled_predictions
from ...services.clv_service import compute_clv_summary
from ...services.settlement_service import get_walk_forward_registry
from ...monitoring.metrics import metrics_collector

router = APIRouter(tags=["performance"])


class ValueBetScanFixture(BaseModel):
    match_id: str
    home_team: str
    away_team: str
    league: str
    kickoff_utc: str
    edge_pct: float
    confidence: Optional[float] = None
    outcome: Optional[str] = None
    model_prob: Optional[float] = None
    implied_prob: Optional[float] = None
    created_at: Optional[str] = None


class ValueBetScanResponse(BaseModel):
    fixtures: List[ValueBetScanFixture]
    total: int
    days: int
    data_gap: bool = False
    reason: Optional[str] = None
    source: str = "persisted_decisions"
    generated_at: str


@router.get("/value-bet-scan", response_model=ValueBetScanResponse)
async def value_bet_scan(
    days: int = Query(7, ge=1, le=14),
    limit: int = Query(50, ge=1, le=100),
) -> ValueBetScanResponse:
    """Return only persisted, independently gated opportunities.

    The previous request path performed fresh model and odds work across 200
    fixtures and repeatedly exceeded Vercel's function limit. The legacy
    ``value_bets`` table does not store the evidence passport, certification
    state, coherent snapshot identity, or stake-permission gate needed to prove
    executability. Until an authoritative persisted decision exists, the only
    honest bulk result is an explicit empty data gap.
    """
    del limit  # retained as a compatible public query parameter
    metrics_collector.increment("value_bet_scan.no_persisted_decisions")
    return ValueBetScanResponse(
        fixtures=[],
        total=0,
        days=days,
        data_gap=True,
        reason="NO_PERSISTED_EXECUTABLE_OPPORTUNITIES",
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def _resolve_league_code(league: Optional[str]) -> Optional[str]:
    """Match.league_id stores football-data.org competition codes (PL/PD/DED/...),
    not the canonical vocabulary (EPL/LA_LIGA/EREDIVISIE) used elsewhere in the app.
    Accepts either form (or the code itself) and returns the code get_settled_
    predictions()'s filter actually needs. An unrecognized value passes through
    unchanged — an honest empty result, never a silently wrong league's data."""
    if not league:
        return None
    from ...data.loaders.football_data_api import FootballDataAPIClient

    normalized = league.strip().lower().replace("-", "_").replace(" ", "_")
    for code, display_name in FootballDataAPIClient.TOP_COMPETITIONS.items():
        if normalized == code.lower() or normalized == display_name.lower().replace(" ", "_"):
            return code
    return league


async def _walk_forward_summary(
    db: AsyncSession, *, league: Optional[str], window: Optional[int]
) -> Dict[str, Any]:
    started_at = None
    if window is not None:
        started_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=window)

    records = await get_settled_predictions(db, league=_resolve_league_code(league), started_at=started_at)
    return {
        "records": records,
        "validation": get_walk_forward_registry().walk_forward_validate(records),
    }


def _accuracy_series(validation: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Chronological chart series, read straight off walk_forward_validate's folds.

    The folds are already temporally ordered and already carry their own scored
    population, so this is a projection, not a second computation — the metric a
    chart draws and the metric the model is certified on cannot drift apart.
    """
    return [
        {
            "date": fold.get("date_range", {}).get("to"),
            "accuracy": fold.get("accuracy"),
            "rps": fold.get("rps_mean"),
            "n_matches": fold.get("test_size"),
        }
        for fold in validation.get("folds", [])
    ]


@router.get("/model-performance")
async def model_performance(
    league: Optional[str] = Query(None),
    window: int = Query(30, ge=7, le=180),
    db: AsyncSession = Depends(get_async_session),
) -> Dict[str, Any]:
    from fastapi.responses import JSONResponse

    result = await _walk_forward_summary(db, league=league, window=window)
    records, validation = result["records"], result["validation"]

    # CLV has its own data floor, independent of walk-forward's — a season can
    # have plenty of captured closing lines and too few *finished* matches for
    # RPS, or vice versa. Computed unconditionally so neither gates the other.
    started_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=window)
    clv_records = await get_clv_records(db, league=_resolve_league_code(league), started_at=started_at)
    clv = compute_clv_summary(clv_records)

    if not records or validation.get("skipped"):
        return JSONResponse(
            status_code=503,
            content={
                "status": "METRICS_UNAVAILABLE",
                "reason": "insufficient_settled_predictions",
                "league": league,
                "window": window,
                "settled_predictions": len(records),
                "clv": clv,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    return {
        "status": "OK",
        "league": league,
        "window": window,
        "settled_predictions": len(records),
        "series": _accuracy_series(validation),
        "current_accuracy": validation.get("accuracy_overall"),
        # Uniform choice across a 3-outcome market. A property of the problem, not a
        # measurement of anything — emitted so the chart's reference line has one
        # owner instead of a hardcoded copy on the client.
        "baseline_accuracy": 1.0 / 3.0,
        "walk_forward": validation,
        "clv": clv,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/model-performance/summary")
async def model_performance_summary(
    db: AsyncSession = Depends(get_async_session),
) -> Dict[str, Any]:
    from fastapi.responses import JSONResponse

    result = await _walk_forward_summary(db, league=None, window=None)
    records, validation = result["records"], result["validation"]

    if not records or validation.get("skipped"):
        return JSONResponse(
            status_code=503,
            content={
                "status": "METRICS_UNAVAILABLE",
                "reason": "insufficient_settled_predictions",
                "settled_predictions": len(records),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    return {
        "status": "OK",
        "total_settled": len(records),
        "accuracy_overall": validation.get("accuracy_overall"),
        "rps_overall": validation.get("rps_overall"),
        "n_splits": validation.get("n_splits"),
        "validated_at": validation.get("validated_at"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
