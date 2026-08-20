"""Model performance and value bet scan endpoints."""

from __future__ import annotations

import asyncio
from functools import lru_cache
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ...db.session import get_async_session
from ...models.active_generation import (
    ActiveGenerationError,
    CERTIFIED,
    active_model_version,
    load_active_generation,
)
from ...repositories.fixtures import get_clv_records, get_settled_predictions
from ...services.clv_service import compute_clv_summary
from ...services.settlement_service import get_walk_forward_registry
from ...core.league_policy import canonical_league_id
from ...core.database import Match, Team
from ...db.models import MatchPredictionLog
from ...monitoring.metrics import metrics_collector

router = APIRouter(tags=["performance"])
_VALUE_SCAN_DB_DEADLINE_SECONDS = 2.5


class ValueBetScanFixture(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
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
    generated_at: str
    status: str = "OK"
    reason: Optional[str] = None
    retryable: bool = False
    source: str = "persisted_prediction_logs"
    freshness: Dict[str, Any] = Field(default_factory=dict)
    provenance: List[str] = Field(default_factory=list)
    deadline_ms: int = 2500


@lru_cache(maxsize=1)
def _certified_value_generation() -> tuple[bool, str | None, str]:
    """Return the immutable serving generation only when certification is valid.

    Persisted prediction payloads are not an authority for production activation:
    a stale/legacy row may still contain ``stake_permitted=true``.  The
    hash-validated active-generation manifest is the release gate.
    """
    try:
        generation = load_active_generation()
    except ActiveGenerationError:
        return False, None, "active_generation_invalid"
    if generation.get("certification_state") != CERTIFIED:
        return False, None, "model_not_certified"
    model_version = str(generation.get("active_version") or "").strip()
    if not model_version:
        return False, None, "active_generation_missing_version"
    return True, model_version, "certified"


@router.get("/value-bet-scan", response_model=ValueBetScanResponse)
async def value_bet_scan(
    days: int = Query(7, ge=1, le=14),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_async_session),
) -> ValueBetScanResponse | JSONResponse:
    """Return only fresh, persisted, fully gated candidates.

    This endpoint intentionally performs no provider calls and no inference.
    Repeated prediction requests are de-duplicated to the newest persisted log
    for each upcoming fixture.
    """

    certified, model_version, gate_reason = _certified_value_generation()
    if not certified or not model_version:
        # Public market-value candidates remain unavailable until immutable
        # certification evidence is active.  Do not trust a persisted payload to
        # switch this endpoint on.
        return ValueBetScanResponse(
            fixtures=[],
            total=0,
            days=days,
            data_gap=False,
            generated_at=datetime.now(timezone.utc).isoformat(),
            status="RESEARCH_ONLY",
            reason=gate_reason,
            retryable=False,
            source="certification_gate",
            freshness={},
            provenance=["models/active_generation.json"],
            deadline_ms=int(_VALUE_SCAN_DB_DEADLINE_SECONDS * 1000),
        )

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    end = now + timedelta(days=days)
    max_age_seconds = 900
    cutoff = now - timedelta(seconds=max_age_seconds)

    latest = (
        select(
            MatchPredictionLog.match_id.label("match_id"),
            func.max(MatchPredictionLog.created_at).label("created_at"),
        )
        .where(
            MatchPredictionLog.created_at >= cutoff,
            MatchPredictionLog.model_version == model_version,
        )
        .group_by(MatchPredictionLog.match_id)
        .subquery()
    )
    home = aliased(Team)
    away = aliased(Team)
    query = (
        select(
            MatchPredictionLog,
            Match,
            home.name.label("home_name"),
            away.name.label("away_name"),
        )
        .join(
            latest,
            and_(
                MatchPredictionLog.match_id == latest.c.match_id,
                MatchPredictionLog.created_at == latest.c.created_at,
            ),
        )
        .join(Match, Match.id == MatchPredictionLog.match_id)
        .outerjoin(home, home.id == Match.home_team_id)
        .outerjoin(away, away.id == Match.away_team_id)
        .where(
            Match.match_date >= now,
            Match.match_date <= end,
            MatchPredictionLog.model_version == model_version,
        )
        .order_by(MatchPredictionLog.created_at.desc())
        .limit(500)
    )
    started = time.perf_counter()
    try:
        records = (
            await asyncio.wait_for(db.execute(query), timeout=_VALUE_SCAN_DB_DEADLINE_SECONDS)
        ).all()
    except TimeoutError:
        metrics_collector.increment("value_scan.db_deadline_exceeded")
        return JSONResponse(
            status_code=503,
            content={
                "fixtures": [],
                "total": 0,
                "days": days,
                "data_gap": True,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "status": "UNAVAILABLE",
                "reason": "database_deadline_exceeded",
                "retryable": True,
                "source": "persisted_prediction_logs",
                "freshness": {"max_age_seconds": max_age_seconds},
                "provenance": ["match_prediction_logs", "matches"],
                "deadline_ms": int(_VALUE_SCAN_DB_DEADLINE_SECONDS * 1000),
            },
        )

    rows: List[ValueBetScanFixture] = []
    for prediction, match, home_name, away_name in records:
        payload = prediction.payload if isinstance(prediction.payload, dict) else {}
        evidence = payload.get("evidence_quality") or {}
        odds_edge = payload.get("odds_edge") or {}
        if payload.get("verdict") not in {"ACTIONABLE", "HIGH_CONVICTION"}:
            continue
        if payload.get("stake_permitted") is not True:
            continue
        if payload.get("partial_intelligence") is True:
            continue
        if evidence.get("critical_gaps") or evidence.get("conflicts"):
            continue
        if payload.get("staleness_available") is not True:
            continue
        if int(payload.get("staleness_seconds") or 0) > max_age_seconds:
            continue

        try:
            edge_fraction = float(odds_edge["edge"])
            market_odds = float(odds_edge["market_odds"])
            model_prob = float(odds_edge["model_prob"])
        except (KeyError, TypeError, ValueError):
            continue
        if edge_fraction <= 0 or market_odds <= 1:
            continue

        ensemble = payload.get("ensemble") or {}
        confidence = ensemble.get("confidence", prediction.confidence)

        rows.append(
            ValueBetScanFixture(
                match_id=str(match.id),
                home_team=str(home_name or match.home_team_id or ""),
                away_team=str(away_name or match.away_team_id or ""),
                league=str(match.league_id or payload.get("league") or ""),
                kickoff_utc=match.match_date.replace(tzinfo=timezone.utc).isoformat(),
                edge_pct=round(edge_fraction * 100.0, 4),
                confidence=float(confidence) if confidence is not None else None,
                outcome=str(odds_edge.get("market") or "") or None,
                model_prob=model_prob,
                implied_prob=round(1.0 / market_odds, 6),
                created_at=prediction.created_at.replace(tzinfo=timezone.utc).isoformat(),
            )
        )

    rows.sort(key=lambda row: row.edge_pct, reverse=True)
    rows = rows[:limit]

    data_gap = len(records) == 0
    metrics_collector.record_timer(
        "value_scan.db_and_filter_ms", (time.perf_counter() - started) * 1000
    )

    return ValueBetScanResponse(
        fixtures=rows,
        total=len(rows),
        days=days,
        data_gap=data_gap,
        generated_at=datetime.now(timezone.utc).isoformat(),
        status="DATA_GAP" if data_gap else "OK",
        reason="no_fresh_persisted_predictions" if data_gap else None,
        retryable=data_gap,
        freshness={"max_age_seconds": max_age_seconds},
        provenance=["match_prediction_logs", "matches"],
        deadline_ms=int(_VALUE_SCAN_DB_DEADLINE_SECONDS * 1000),
    )


_FD_CODE_TO_CANONICAL = {
    "PL": "EPL",
    "PD": "LA_LIGA",
    "BL1": "BUNDESLIGA",
    "SA": "SERIE_A",
    "FL1": "LIGUE_1",
    "DED": "EREDIVISIE",
    "CL": "UCL",
}


def _resolve_league_filter(league: Optional[str]) -> Optional[str]:
    """Return the canonical league id used by persisted match rows.

    Accepts canonical ids (``EREDIVISIE``), display forms (``Eredivisie``),
    and legacy football-data.org codes (``DED``) for backward compatibility.
    """
    if not league:
        return None
    value = league.strip()
    if not value:
        return None
    code = _FD_CODE_TO_CANONICAL.get(value.upper())
    if code is not None:
        return code
    return canonical_league_id(value)


async def _walk_forward_summary(
    db: AsyncSession, *, league: Optional[str], window: Optional[int]
) -> Dict[str, Any]:
    started_at = None
    if window is not None:
        started_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=window)

    # Scope to the serving generation. Pooling generations would report an
    # accuracy/RPS series for a model that never existed — see
    # build_settled_predictions_query. Raising here is deliberate: the caller
    # surfaces it rather than silently publishing a cross-generation metric.
    model_version = active_model_version()

    records = await get_settled_predictions(
        db,
        league=_resolve_league_filter(league),
        started_at=started_at,
        model_version=model_version,
    )
    return {
        "records": records,
        "model_version": model_version,
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
    model_version = str(result["model_version"])
    # CLV has its own data floor, independent of walk-forward's — a season can
    # have plenty of captured closing lines and too few *finished* matches for
    # RPS, or vice versa. Computed unconditionally so neither gates the other.
    started_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=window)
    clv_records = await get_clv_records(
        db,
        league=_resolve_league_filter(league),
        started_at=started_at,
        model_version=model_version,
    )
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
