"""
API routes for upcoming matches with predictions and value bets.

Endpoints:
- GET /upcoming/matches - Fetch upcoming matches with predictions
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...core.season_calendar import next_season_start
from ...db.session import get_async_session
from ...models.feature_registry import active_canonical_features
from ...monitoring.metrics import metrics_collector
from ...services.upcoming_match_service import UpcomingMatchService
from ...services.odds_service import OddsService, get_odds_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/upcoming", tags=["upcoming"])

# Next-season start dates live in core.season_calendar — one provider-verified
# table shared with the leagues and offseason endpoints. Local copies here had
# drifted up to 14 days early against football-data.org's currentSeason.


def _compute_edge_quality_score(match: Dict[str, Any]) -> Optional[float]:
    """Compute a simplified 0-1 edge quality score from available upcoming-match data.

    Formula (approximation of the full Sprint 4 edge_quality_score):
      confidence  × 0.40  — model calibrated confidence
      market_edge × 0.30  — normalised best_value_bet.edge_pct (0%→0, 10%→1)
      freshness   × 0.20  — linear decay over LIVE_THRESHOLD_SECONDS
      completeness× 0.10  — 1 - (data_gaps / canonical features)

    `completeness` is the SAME gap-driven formula the full-analysis path uses
    (`full_analysis._compute_edge_quality_score`) — one concept, one definition.
    It previously read `historical_data_ratio` and fell back to a flat 0.5 when
    `data_quality` was absent, i.e. it credited an unmeasured fixture with half
    marks and could push it over the Top-Edge threshold on nothing (INV-01).
    Absent gap data now scores 0.0: unknown completeness can only lower the
    score, never inflate it.

    Returns None when neither predictions nor value bets are available.
    """
    predictions = match.get("predictions")
    best_bet = match.get("best_value_bet")
    staleness = int(match.get("staleness_seconds", 0))

    if predictions is None and best_bet is None:
        return None

    confidence = float(predictions.get("confidence", 0.0)) if predictions else 0.0
    edge_pct = float(best_bet.get("edge_pct", 0.0)) if best_bet else 0.0
    market_edge = min(1.0, edge_pct / 10.0)
    threshold = float(getattr(settings, "live_threshold_seconds", 3600))
    freshness = max(0.0, 1.0 - staleness / threshold) if threshold > 0 else 1.0
    # An explicitly-empty list means "computed, no gaps" (→1.0); a missing key
    # means "never computed" (→0.0). Distinct cases, deliberately not merged.
    data_gaps = match.get("data_gaps")
    if data_gaps is None:
        completeness = 0.0
    else:
        n_canonical = len(active_canonical_features(
            use_phase7=settings.use_phase7_models,
            use_phase8=settings.phase8_enabled,
        ))
        completeness = max(0.0, 1.0 - len(data_gaps) / max(1, n_canonical))

    score = 0.40 * confidence + 0.30 * market_edge + 0.20 * freshness + 0.10 * completeness
    return round(min(1.0, max(0.0, score)), 3)


def _next_season_start(league: Optional[str]) -> str:
    # Non-None by construction: season_calendar falls back to the earliest
    # supported opener for unknown/absent leagues.
    return str(next_season_start(league))


# Pydantic response models
class PredictionSchema(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    home_win: float
    draw: float
    away_win: float
    model_version: str = "1.0.0"
    calibration_method: str = "isotonic"
    confidence: float


class OddsSchema(BaseModel):
    home_win: float
    draw: float
    away_win: float
    source: str
    timestamp: Optional[str] = None
    bookmaker: Optional[str] = None


class ValueBetSchema(BaseModel):
    outcome: str
    edge_pct: float
    kelly_stake_pct: float
    clv_cents: float
    recommended_stake_ngn: int
    confidence: float


class DataQualitySchema(BaseModel):
    historical_data_ratio: float
    defaults_used_count: int
    feature_defaulted_ratio: float
    is_synthetic: bool


class PortfolioMatchSchema(BaseModel):
    """Per-fixture advisory exposure annotation (ADR-0005). Never influences
    value_bets/best_value_bet/kelly_stake_pct — additive display data only."""

    raw_kelly_stake_pct: float
    correlation_group_size: int
    correlation_haircut_multiplier: float
    adjusted_kelly_stake_pct: float
    exceeds_aggregate_cap: bool


class DrawdownStatusSchema(BaseModel):
    status: str
    realized_drawdown_pct: Optional[float] = None
    paused: bool = False


class PortfolioExposureSchema(BaseModel):
    """Batch-level advisory summary (ADR-0005)."""

    aggregate_recommended_pct: float
    aggregate_cap_pct: float
    exceeds_aggregate_cap: bool
    drawdown: DrawdownStatusSchema


class UpcomingMatchSchema(BaseModel):
    match_id: str
    home_team: str
    away_team: str
    league: str
    match_date: str
    venue: Optional[str] = None
    status: str
    predictions: Optional[PredictionSchema] = None
    odds: Optional[OddsSchema] = None
    value_bets: List[ValueBetSchema] = Field(default_factory=list)
    has_value: bool = False
    best_value_bet: Optional[ValueBetSchema] = None
    data_quality: Optional[DataQualitySchema] = None
    data_gaps: List[str] = Field(default_factory=list)
    staleness_seconds: int = 0
    source: str = "unknown"
    edge_quality_score: Optional[float] = None
    clv_pct: Optional[float] = None
    # UCL stage: group, r16, qf, sf, final. Null for domestic leagues.
    competition_stage: Optional[str] = None
    # Advisory portfolio-exposure annotation (ADR-0005). None on non-value fixtures.
    portfolio: Optional[PortfolioMatchSchema] = None


class UpcomingMatchesResponseSchema(BaseModel):
    upcoming_matches: List[UpcomingMatchSchema]
    total: int
    matches_with_value: int
    avg_edge_pct: float
    cache_hit: bool = False
    ttl_seconds: int = 300
    source: str
    offseason: bool = False
    next_season_start: Optional[str] = None
    data_gap: bool = False
    unavailable_reasons: List[str] = Field(default_factory=list)
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    # Batch-level advisory exposure summary (ADR-0005). None when predictions
    # weren't requested (include_predictions=False path never computes it).
    portfolio_exposure: Optional[PortfolioExposureSchema] = None


class UpcomingAllFixtureSchema(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    matchId: str
    homeTeam: str
    awayTeam: str
    kickoffUtc: str
    league: str
    homeLogoUrl: str = ""
    awayLogoUrl: str = ""
    predictionAvailable: bool
    unavailableReason: Optional[str] = None
    edge_pct: Optional[float] = None
    freshnessTag: Optional[str] = None
    partialData: bool = False
    model_votes: Optional[Dict[str, int]] = None
    matchImportance: Optional[str] = None
    matchRound: Optional[str] = None
    # UCL stage: group, r16, qf, sf, final. Null for domestic leagues.
    competition_stage: Optional[str] = None


class UpcomingAllResponseSchema(BaseModel):
    fixtures: List[UpcomingAllFixtureSchema]
    total: int
    days: int
    source: str
    cache_ttl_seconds: int


@router.get("/matches", response_model=UpcomingMatchesResponseSchema)
async def get_upcoming_matches(
    league: Optional[str] = Query(
        None,
        description="Filter by league (EPL, La Liga, Bundesliga, Serie A, Ligue 1, Eredivisie, UCL)",
        examples=["EPL"],
    ),
    days_ahead: int = Query(
        7, ge=1, le=30, description="Number of days ahead to fetch matches"
    ),
    limit: int = Query(
        20, ge=1, le=50, description="Maximum number of matches to return"
    ),
    include_predictions: bool = Query(
        False, description="Include bounded ML enrichment; fixture discovery is the default"
    ),
    include_value_bets: bool = Query(
        False, description="Include value bet calculations when predictions are requested"
    ),
    db: AsyncSession = Depends(get_async_session),
    odds_service: OddsService = Depends(get_odds_service),
) -> UpcomingMatchesResponseSchema:
    """
    Get upcoming football matches with optional ML predictions and value bets.

    **Response fields:**
    - `upcoming_matches`: List of matches with predictions
      - `predictions`: Calibrated probabilities (Home Win, Draw, Away Win)
      - `odds`: Market odds from bookmakers
      - `value_bets`: Recommended bets with positive edge
      - `data_quality`: Metadata about feature completeness
    - `total`: Total number of matches
    - `matches_with_value`: Matches with identified value bets
    - `avg_edge_pct`: Average edge across all value bets

    **Query Parameters:**
    - `league`: Filter by league (optional)
    - `days_ahead`: Forecast horizon (default: 7 days)
    - `limit`: Max matches (default: 20, max: 50)
    - `include_predictions`: Attach bounded ML enrichment (default: false)
    - `include_value_bets`: Calculate value bets only with predictions (default: false)

    **Source:** Redis cache then PostgreSQL. Provider acquisition is performed only
    by the periodic fixture-sync task, never by this request path.

    **Example:**
    ```
    GET /upcoming/matches?league=EPL&days_ahead=7&limit=10
    ```
    """

    started_at = time.perf_counter()
    timeout_seconds = 18.0 if include_predictions else 5.0
    try:
        service = UpcomingMatchService(
            odds_service=odds_service if isinstance(odds_service, OddsService) else None
        )

        async with asyncio.timeout(timeout_seconds):
            if include_predictions:
                response = await service.get_upcoming_matches_with_predictions(
                    db,
                    league=league,
                    days_ahead=days_ahead,
                    limit=limit,
                    include_value_bets=include_value_bets,
                )
            else:
                response = await service.get_upcoming_matches(
                    db, league=league, days_ahead=days_ahead, limit=limit
                )
                response["matches_with_value"] = 0
                response["avg_edge_pct"] = 0.0
                # get_upcoming_matches returns "matches"; normalise to "upcoming_matches"
                if "upcoming_matches" not in response and "matches" in response:
                    response["upcoming_matches"] = response.pop("matches")

        matches = response.get("upcoming_matches", [])

        # Inject edge_quality_score per match
        for match in matches:
            match["edge_quality_score"] = _compute_edge_quality_score(match)

        # Detect off-season: fixture list genuinely empty
        is_offseason = len(matches) == 0
        response["offseason"] = is_offseason
        response["next_season_start"] = _next_season_start(league) if is_offseason else None
        response.setdefault("data_gap", False)
        response.setdefault("unavailable_reasons", [])
        response.setdefault("generated_at", datetime.now(timezone.utc).isoformat())

        metrics_collector.increment("upcoming.request.success")
        return UpcomingMatchesResponseSchema.model_validate(response)

    except TimeoutError:
        metrics_collector.increment("upcoming.request.timeout")
        logger.warning(
            "Upcoming request exceeded bounded deadline",
            extra={"include_predictions": include_predictions, "limit": limit},
        )
        return UpcomingMatchesResponseSchema(
            upcoming_matches=[],
            total=0,
            matches_with_value=0,
            avg_edge_pct=0.0,
            cache_hit=False,
            ttl_seconds=0,
            source="timeout",
            offseason=False,
            data_gap=True,
            unavailable_reasons=["UPCOMING_REQUEST_TIMEOUT"],
        )
    except Exception as exc:
        metrics_collector.increment("upcoming.request.failure")
        logger.error("Error fetching upcoming matches: %s", type(exc).__name__, exc_info=True)
        # Carry the exception CLASS NAME (never the message — it can contain row
        # data) into the response. Without it this handler reported every distinct
        # failure as the same three words, and a schema-validation bug served an
        # empty fixture list that was indistinguishable from a real off-season for
        # as long as it took someone to read the logs. Class name only: no
        # payload, no query values, nothing user-supplied.
        return UpcomingMatchesResponseSchema(
            upcoming_matches=[],
            total=0,
            matches_with_value=0,
            avg_edge_pct=0.0,
            cache_hit=False,
            ttl_seconds=0,
            source="error",
            offseason=False,
            data_gap=True,
            unavailable_reasons=[
                "UPCOMING_SERVICE_UNAVAILABLE",
                f"EXC:{type(exc).__name__}",
            ],
        )
    finally:
        metrics_collector.record_timer(
            "upcoming.request.latency",
            (time.perf_counter() - started_at) * 1000,
        )


@router.get("/health")
async def health_check() -> Dict[str, Any]:
    """Health check endpoint for upcoming matches service."""
    return {
        "status": "healthy",
        "service": "upcoming_matches",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/all", response_model=UpcomingAllResponseSchema)
async def get_upcoming_all(
    days: int = Query(7, ge=1, le=14, description="Number of days ahead"),
    limit: int = Query(200, ge=1, le=200, description="Maximum number of fixtures"),
    db: AsyncSession = Depends(get_async_session),
    odds_service: OddsService = Depends(get_odds_service),
) -> UpcomingAllResponseSchema:
    """Get a bounded discovery list from the synchronized fixture database.

    Bulk prediction/odds enrichment used to run for up to 200 fixtures in this
    request. Discovery now stays cheap and users request authoritative analysis
    for one verified fixture at a time.
    """
    service = UpcomingMatchService(
        odds_service=odds_service if isinstance(odds_service, OddsService) else None
    )
    async with asyncio.timeout(5.0):
        payload = await service.get_upcoming_matches(
            db,
            league=None,
            days_ahead=days,
            limit=limit,
        )

    fixtures: List[UpcomingAllFixtureSchema] = []
    for match in payload.get("matches", []):
        league = str(match.get("league", ""))
        is_ucl = league.upper() in {"UCL", "CHAMPIONS LEAGUE", "UEFA CHAMPIONS LEAGUE"}
        gaps = list(match.get("data_gaps") or [])

        fixtures.append(
            UpcomingAllFixtureSchema(
                matchId=str(match.get("match_id") or match.get("id") or ""),
                homeTeam=str(match.get("home_team", "")),
                awayTeam=str(match.get("away_team", "")),
                kickoffUtc=str(match.get("match_date", "")),
                league=league,
                predictionAvailable=False,
                unavailableReason=(
                    ", ".join(gaps)
                    if gaps
                    else "Select this fixture to request authoritative analysis"
                ),
                edge_pct=None,
                freshnessTag="SYNCED",
                partialData=bool(gaps),
                model_votes=None,
                matchImportance="high" if is_ucl else "normal",
                matchRound="group" if is_ucl else None,
            )
        )

    fixtures.sort(key=lambda f: f.kickoffUtc)
    return UpcomingAllResponseSchema(
        fixtures=fixtures[:limit],
        total=min(len(fixtures), limit),
        days=days,
        source=str(payload.get("source", "unknown")),
        cache_ttl_seconds=int(payload.get("ttl_seconds", 300)),
    )
