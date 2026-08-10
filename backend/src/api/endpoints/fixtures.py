"""Fixture evidence and manual odds endpoints for production intelligence."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...db.models import Match, Odds, Prediction
from ...db.session import get_async_session
from ...models.active_generation import active_generation_is_certified
from ...schemas.betting_intelligence import (
    CompetitionEnum,
    EvidenceTierEnum,
    FreshnessInput,
    LineupStatusEnum,
    MarketInput,
    MatchAnalysisRequest,
    ModelInput,
    SharpSignalEnum,
    SignalsInput,
    SourceStatusEnum,
    SourceStatusInput,
)
from ...services.betting_intelligence import analyze_match
from ...providers import ProviderRegistry
from ...providers.registry import get_provider_registry
from ...providers.orchestrator import EvidenceOrchestrator, EvidenceProfile


router = APIRouter(prefix="/fixtures", tags=["fixtures"])

MODEL_FEATURES_FRESH_SECONDS = 3600
AVAILABILITY_CRITICAL_HOURS = 24
LINEUP_CRITICAL_MINUTES = 90


class FixtureSummary(BaseModel):
    fixture_id: str
    competition: str
    home_team: str
    away_team: str
    kickoff_utc: datetime
    status: str
    venue: Optional[str] = None
    evidence_status: str
    odds_status: str


class UpcomingFixturesResponse(BaseModel):
    fixtures: List[FixtureSummary]
    total: int
    source: str = "database"


class EvidenceResponse(BaseModel):
    fixture: FixtureSummary
    model: Optional[Dict[str, Any]] = None
    market: Optional[Dict[str, Any]] = None
    freshness: Dict[str, Any]
    source_status: Dict[str, str]
    data_gaps: List[str] = Field(default_factory=list)
    retrieval_timeline: List[Dict[str, Any]] = Field(default_factory=list)
    readiness: List[Dict[str, Any]] = Field(default_factory=list)
    source_comparison: List[Dict[str, Any]] = Field(default_factory=list)


class RefreshEvidenceRequest(BaseModel):
    profile: EvidenceProfile = EvidenceProfile.PREMATCH_STANDARD


class RefreshEvidenceResponse(BaseModel):
    fixture_id: str
    profile: EvidenceProfile
    provider_results: List[Dict[str, Any]]
    refreshed_at: datetime


class ProviderOddsCandidate(BaseModel):
    bookmaker: str
    home_odds: float
    draw_odds: float
    away_odds: float
    captured_at: datetime
    provider: str = "stored_snapshot"
    executable: bool = True


class ProviderOddsCandidatesResponse(BaseModel):
    fixture_id: str
    candidates: List[ProviderOddsCandidate]
    warnings: List[str] = Field(default_factory=list)


class ManualOddsSnapshotRequest(BaseModel):
    bookmaker: str = Field(..., min_length=2, max_length=120)
    home_odds: float = Field(..., gt=1.0)
    draw_odds: float = Field(..., gt=1.0)
    away_odds: float = Field(..., gt=1.0)
    observed_at: datetime
    opening_home_odds: Optional[float] = Field(default=None, gt=1.0)
    opening_draw_odds: Optional[float] = Field(default=None, gt=1.0)
    opening_away_odds: Optional[float] = Field(default=None, gt=1.0)
    source_label: Optional[str] = Field(default=None, max_length=180)
    source_url: Optional[str] = Field(default=None, max_length=500)
    user_confirmed: bool = False

    @field_validator("source_url")
    @classmethod
    def reject_fetchable_user_urls(cls, value: Optional[str]) -> Optional[str]:
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("source_url must be an http(s) URL label when provided")
        return value

    @model_validator(mode="after")
    def validate_confirmation_and_time(self) -> "ManualOddsSnapshotRequest":
        if not self.user_confirmed:
            raise ValueError("User confirmation is required before odds evaluation")
        observed = self.observed_at
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if observed > now:
            raise ValueError("observed_at cannot be in the future")
        return self


class ManualOddsSnapshotResponse(BaseModel):
    fixture_id: str
    bookmaker: str
    home_odds: float
    draw_odds: float
    away_odds: float
    observed_at: datetime
    received_at: datetime
    executable: bool
    provenance: Dict[str, Any]


def _competition_to_enum(raw: Optional[str]) -> CompetitionEnum:
    normalized = (raw or "").upper().replace(" ", "_").replace("-", "_")
    aliases = {
        "PREMIER_LEAGUE": "EPL",
        "LALIGA": "LA_LIGA",
        "LA_LIGA": "LA_LIGA",
        "SERIE_A": "SERIE_A",
        "BUNDESLIGA": "BUNDESLIGA",
        "LIGUE_1": "LIGUE_1",
        "EREDIVISIE": "EREDIVISIE",
        "CHAMPIONS_LEAGUE": "UCL",
        "UEFA_CHAMPIONS_LEAGUE": "UCL",
    }
    candidate = aliases.get(normalized, normalized)
    if candidate not in CompetitionEnum.__members__:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported or unavailable competition for strict engine: {raw or 'unknown'}",
        )
    return CompetitionEnum(candidate)


def _team_label(value: Any) -> str:
    return str(value or "Unknown")


async def _get_fixture_or_404(db: AsyncSession, fixture_id: str) -> Match:
    result = await db.execute(
        select(Match)
        .options(selectinload(Match.home_team), selectinload(Match.away_team))
        .where(Match.id == fixture_id)
    )
    fixture = result.scalar_one_or_none()
    if fixture is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fixture not found")
    return fixture


async def _latest_prediction(db: AsyncSession, fixture_id: str) -> Optional[Prediction]:
    result = await db.execute(
        select(Prediction)
        .where(Prediction.match_id == fixture_id)
        .order_by(desc(Prediction.created_at), desc(Prediction.id))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _latest_odds(db: AsyncSession, fixture_id: str) -> Optional[Odds]:
    result = await db.execute(
        select(Odds)
        .where(Odds.match_id == fixture_id)
        .order_by(desc(Odds.timestamp), desc(Odds.id))
        .limit(1)
    )
    return result.scalar_one_or_none()


def _fixture_summary(fixture: Match, odds: Optional[Odds], prediction: Optional[Prediction]) -> FixtureSummary:
    kickoff = fixture.match_date
    if kickoff.tzinfo is None:
        kickoff = kickoff.replace(tzinfo=timezone.utc)
    prediction_contract_gaps = _prediction_contract_gaps(prediction)
    return FixtureSummary(
        fixture_id=str(fixture.id),
        competition=str(fixture.league_id or "EPL"),
        home_team=str(fixture.home_team.name) if fixture.home_team else _team_label(fixture.home_team_id),
        away_team=str(fixture.away_team.name) if fixture.away_team else _team_label(fixture.away_team_id),
        kickoff_utc=kickoff,
        status=str(fixture.status or "scheduled"),
        venue=fixture.venue,
        evidence_status="MODEL_READY" if prediction and not prediction_contract_gaps else "MODEL_UNAVAILABLE",
        odds_status="SNAPSHOT_READY" if odds else "MANUAL_ODDS_REQUIRED",
    )


def _market_age_seconds(odds: Optional[Odds]) -> Optional[int]:
    if odds is None or odds.timestamp is None:
        return None
    captured = odds.timestamp
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=timezone.utc)
    return max(0, int((datetime.now(timezone.utc) - captured).total_seconds()))


def _prediction_age_seconds(prediction: Optional[Prediction]) -> Optional[int]:
    if prediction is None or prediction.created_at is None:
        return None
    created = prediction.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return max(0, int((datetime.now(timezone.utc) - created).total_seconds()))


def _critical_availability_gaps(fixture: Match) -> List[str]:
    kickoff = fixture.match_date
    if kickoff.tzinfo is None:
        kickoff = kickoff.replace(tzinfo=timezone.utc)
    seconds_to_kickoff = (kickoff - datetime.now(timezone.utc)).total_seconds()
    gaps: List[str] = []
    if seconds_to_kickoff <= AVAILABILITY_CRITICAL_HOURS * 3600:
        gaps.append("DATA_GAP: availability_status")
    if seconds_to_kickoff <= LINEUP_CRITICAL_MINUTES * 60:
        gaps.append("DATA_GAP: confirmed_lineup_status")
    return gaps


def _prediction_metadata(prediction: Optional[Prediction]) -> Dict[str, Any]:
    if prediction is None or not isinstance(prediction.features, dict):
        return {}
    bi = prediction.features.get("betting_intelligence")
    if isinstance(bi, dict):
        return bi
    # PredictionResponse stores contract fields under prediction.features["metadata"]
    nested = prediction.features.get("metadata")
    return nested if isinstance(nested, dict) else prediction.features


def _prediction_contract_gaps(prediction: Optional[Prediction]) -> List[str]:
    gaps: List[str] = []
    if prediction is None:
        return ["DATA_GAP: model_prediction"]
    values = (prediction.home_win_prob, prediction.draw_prob, prediction.away_win_prob)
    if any(value is None for value in values):
        gaps.append("DATA_GAP: model_probabilities")

    metadata = _prediction_metadata(prediction)
    required = (
        "calibration_method",
        "calibration_validated",
        "epistemic_uncertainty",
        "aleatoric_uncertainty",
        "confidence_tier",
    )
    for field in required:
        if metadata.get(field) is None:
            gaps.append(f"DATA_GAP: model_metadata.{field}")
    if metadata.get("calibration_validated") is not None and not isinstance(metadata.get("calibration_validated"), bool):
        gaps.append("DATA_GAP: model_metadata.calibration_validated_invalid")
    if metadata.get("confidence_tier") is not None:
        try:
            EvidenceTierEnum(str(metadata["confidence_tier"]))
        except ValueError:
            gaps.append("DATA_GAP: model_metadata.confidence_tier_invalid")
    for field in ("epistemic_uncertainty", "aleatoric_uncertainty"):
        if metadata.get(field) is not None:
            try:
                float(metadata[field])
            except (TypeError, ValueError):
                gaps.append(f"DATA_GAP: model_metadata.{field}_invalid")
    return gaps


def _model_from_prediction(prediction: Optional[Prediction]) -> Optional[ModelInput]:
    if prediction is None:
        return None
    values = (prediction.home_win_prob, prediction.draw_prob, prediction.away_win_prob)
    if any(value is None for value in values):
        return None
    metadata = _prediction_metadata(prediction)
    contract_gaps = _prediction_contract_gaps(prediction)
    if contract_gaps:
        return None
    return ModelInput(
        home_probability=float(prediction.home_win_prob),
        draw_probability=float(prediction.draw_prob),
        away_probability=float(prediction.away_win_prob),
        model_version=str(prediction.model_version or "unknown"),
        calibration_method=str(metadata["calibration_method"]),
        calibration_validated=bool(metadata["calibration_validated"]),
        generation_certified=active_generation_is_certified(),
        epistemic_uncertainty=float(metadata["epistemic_uncertainty"]),
        aleatoric_uncertainty=float(metadata["aleatoric_uncertainty"]),
        confidence_tier=EvidenceTierEnum(str(metadata["confidence_tier"])),
    )


def _market_from_odds(odds: Optional[Odds]) -> Optional[MarketInput]:
    if odds is None or odds.home_win is None or odds.draw is None or odds.away_win is None:
        return None
    captured = odds.timestamp or datetime.now(timezone.utc)
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=timezone.utc)
    return MarketInput(
        bookmaker=str(odds.bookmaker or "Manual Snapshot"),
        market_type="1X2",
        home_odds=float(odds.home_win),
        draw_odds=float(odds.draw),
        away_odds=float(odds.away_win),
        captured_at=captured,
    )


async def _build_evidence(db: AsyncSession, fixture_id: str) -> tuple[Match, Optional[Prediction], Optional[Odds], EvidenceResponse]:
    fixture = await _get_fixture_or_404(db, fixture_id)
    prediction = await _latest_prediction(db, fixture_id)
    odds = await _latest_odds(db, fixture_id)
    summary = _fixture_summary(fixture, odds, prediction)
    data_gaps: List[str] = []
    if prediction is None:
        data_gaps.append("DATA_GAP: model_prediction")
    else:
        data_gaps.extend(_prediction_contract_gaps(prediction))
        _fc = _prediction_metadata(prediction).get("feature_completeness", 1.0)
        if isinstance(_fc, (int, float)) and _fc < 0.5:
            data_gaps.append("DATA_GAP: model_feature_completeness_critical")
    if odds is None:
        data_gaps.append("DATA_GAP: coherent_1x2_market_snapshot")
    model_age = _prediction_age_seconds(prediction)
    if prediction is not None and model_age is None:
        data_gaps.append("DATA_GAP: model_features_freshness_unknown")
    elif model_age is not None and model_age > MODEL_FEATURES_FRESH_SECONDS:
        data_gaps.append(f"STALE: model_features ({model_age}s old)")
    data_gaps.extend(_critical_availability_gaps(fixture))

    model_status = "DATA_GAP"
    if prediction is not None and not _prediction_contract_gaps(prediction):
        model_status = "STALE" if model_age is None or model_age > MODEL_FEATURES_FRESH_SECONDS else "VERIFIED"

    evidence = EvidenceResponse(
        fixture=summary,
        model={
            "model_version": prediction.model_version,
            "home_probability": prediction.home_win_prob,
            "draw_probability": prediction.draw_prob,
            "away_probability": prediction.away_win_prob,
            "created_at": prediction.created_at,
            "metadata_complete": not _prediction_contract_gaps(prediction),
        } if prediction else None,
        market={
            "bookmaker": odds.bookmaker,
            "home_odds": odds.home_win,
            "draw_odds": odds.draw,
            "away_odds": odds.away_win,
            "captured_at": odds.timestamp,
        } if odds else None,
        freshness={"market_seconds": _market_age_seconds(odds), "model_features_seconds": model_age},
        source_status={
            "model": model_status,
            "market": "VERIFIED" if odds else "DATA_GAP",
            "team_metrics": "DATA_GAP",
            "availability": "DATA_GAP",
        },
        data_gaps=data_gaps,
        retrieval_timeline=[
            {"step": "fixture", "status": "VERIFIED", "source": "database"},
            {"step": "model", "status": model_status, "source": "predictions"},
            {"step": "market", "status": "VERIFIED" if odds else "DATA_GAP", "source": "manual odds snapshot"},
            {"step": "availability", "status": "DATA_GAP", "source": "lineup and injury provider unavailable"},
        ],
        readiness=[
            {"stage": "Fixture identity", "state": "VERIFIED", "source": "database", "timestamp": summary.kickoff_utc, "reason": None},
            {"stage": "Team metrics", "state": model_status, "source": "model features", "timestamp": prediction.created_at if prediction else None, "reason": None if prediction else "model prediction missing"},
            {"stage": "Availability", "state": "DATA_GAP", "source": None, "timestamp": None, "reason": "availability provider evidence not verified"},
            {"stage": "Lineup", "state": "DATA_GAP", "source": None, "timestamp": None, "reason": "confirmed lineup unavailable"},
            {"stage": "Model", "state": model_status, "source": "SabiScore backend", "timestamp": prediction.created_at if prediction else None, "reason": None if model_status == "VERIFIED" else "model metadata incomplete or stale"},
            {"stage": "Market", "state": "VERIFIED" if odds else "DATA_GAP", "source": odds.bookmaker if odds else None, "timestamp": odds.timestamp if odds else None, "reason": None if odds else "one coherent bookmaker snapshot required"},
            {"stage": "Risk gate", "state": "PARTIAL" if data_gaps else "VERIFIED", "source": "strict engine", "timestamp": datetime.now(timezone.utc), "reason": "; ".join(data_gaps[:3]) if data_gaps else None},
        ],
        source_comparison=[
            {
                "field": "market",
                "selected_source": odds.bookmaker if odds else None,
                "status": "VERIFIED" if odds else "DATA_GAP",
                "reason": "single coherent 1X2 bookmaker snapshot" if odds else "no coherent market snapshot stored",
                "timestamp": odds.timestamp if odds else None,
            },
            {
                "field": "model",
                "selected_source": prediction.model_version if prediction else None,
                "status": model_status,
                "reason": "backend-only calibrated probabilities" if prediction else "model prediction unavailable",
                "timestamp": prediction.created_at if prediction else None,
            },
        ],
    )
    return fixture, prediction, odds, evidence


@router.get("/upcoming", response_model=UpcomingFixturesResponse)
async def fixtures_upcoming(
    competition: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_async_session),
) -> UpcomingFixturesResponse:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    query = (
        select(Match)
        .options(selectinload(Match.home_team), selectinload(Match.away_team))
        .where(and_(Match.match_date >= now, Match.status == "scheduled"))
        .order_by(Match.match_date.asc())
        .limit(limit)
    )
    if competition:
        query = query.where(Match.league_id == competition)
    result = await db.execute(query)
    fixtures = result.scalars().all()
    fixture_ids = [str(fixture.id) for fixture in fixtures]

    # Batch-fetch latest prediction/odds per fixture instead of one query pair
    # per row (N+1). Rows are ordered match_id, then newest-first within each
    # match_id, so the first row seen per match_id via setdefault is the latest.
    predictions_by_fixture: Dict[str, Prediction] = {}
    odds_by_fixture: Dict[str, Odds] = {}
    if fixture_ids:
        pred_result = await db.execute(
            select(Prediction)
            .where(Prediction.match_id.in_(fixture_ids))
            .order_by(Prediction.match_id, desc(Prediction.created_at), desc(Prediction.id))
        )
        for prediction_row in pred_result.scalars().all():
            predictions_by_fixture.setdefault(prediction_row.match_id, prediction_row)

        odds_result = await db.execute(
            select(Odds)
            .where(Odds.match_id.in_(fixture_ids))
            .order_by(Odds.match_id, desc(Odds.timestamp), desc(Odds.id))
        )
        for odds_row in odds_result.scalars().all():
            odds_by_fixture.setdefault(odds_row.match_id, odds_row)

    rows: List[FixtureSummary] = []
    for fixture in fixtures:
        fixture_id = str(fixture.id)
        prediction = predictions_by_fixture.get(fixture_id)
        odds = odds_by_fixture.get(fixture_id)
        rows.append(_fixture_summary(fixture, odds, prediction))
    return UpcomingFixturesResponse(fixtures=rows, total=len(rows))


@router.get("/{fixture_id}/evidence", response_model=EvidenceResponse)
async def fixture_evidence(
    fixture_id: str,
    db: AsyncSession = Depends(get_async_session),
) -> EvidenceResponse:
    _, _, _, evidence = await _build_evidence(db, fixture_id)
    return evidence


@router.post("/{fixture_id}/refresh", response_model=RefreshEvidenceResponse)
async def refresh_fixture_evidence(
    fixture_id: str,
    payload: RefreshEvidenceRequest,
    db: AsyncSession = Depends(get_async_session),
    registry: ProviderRegistry = Depends(get_provider_registry),
) -> RefreshEvidenceResponse:
    fixture = await _get_fixture_or_404(db, fixture_id)
    orchestrator = EvidenceOrchestrator(registry)
    results = await orchestrator.collect(
        {
            "fixture_id": fixture_id,
            "competition": str(fixture.league_id or "EPL"),
            "home_team": str(fixture.home_team.name) if fixture.home_team else _team_label(fixture.home_team_id),
            "away_team": str(fixture.away_team.name) if fixture.away_team else _team_label(fixture.away_team_id),
            "kickoff_utc": fixture.match_date,
        },
        payload.profile,
    )
    return RefreshEvidenceResponse(
        fixture_id=fixture_id,
        profile=payload.profile,
        provider_results=[result.model_dump(mode="json") for result in results],
        refreshed_at=datetime.now(timezone.utc),
    )


@router.get("/{fixture_id}/odds-snapshots", response_model=ProviderOddsCandidatesResponse)
async def provider_odds_candidates(
    fixture_id: str,
    db: AsyncSession = Depends(get_async_session),
) -> ProviderOddsCandidatesResponse:
    await _get_fixture_or_404(db, fixture_id)
    result = await db.execute(
        select(Odds)
        .where(Odds.match_id == fixture_id)
        .order_by(desc(Odds.timestamp), desc(Odds.id))
        .limit(25)
    )
    candidates: List[ProviderOddsCandidate] = []
    seen: set[str] = set()
    for odds in result.scalars().all():
        if not odds.bookmaker or odds.bookmaker in seen:
            continue
        if odds.home_win is None or odds.draw is None or odds.away_win is None:
            continue
        seen.add(odds.bookmaker)
        captured = odds.timestamp or datetime.now(timezone.utc)
        if captured.tzinfo is None:
            captured = captured.replace(tzinfo=timezone.utc)
        candidates.append(
            ProviderOddsCandidate(
                bookmaker=odds.bookmaker,
                home_odds=float(odds.home_win),
                draw_odds=float(odds.draw),
                away_odds=float(odds.away_win),
                captured_at=captured,
            )
        )
    return ProviderOddsCandidatesResponse(
        fixture_id=fixture_id,
        candidates=candidates,
        warnings=[] if candidates else ["no_provider_or_stored_bookmaker_snapshot_available"],
    )


@router.post("/{fixture_id}/odds-snapshot", response_model=ManualOddsSnapshotResponse)
async def create_manual_odds_snapshot(
    fixture_id: str,
    payload: ManualOddsSnapshotRequest,
    db: AsyncSession = Depends(get_async_session),
) -> ManualOddsSnapshotResponse:
    await _get_fixture_or_404(db, fixture_id)
    observed = payload.observed_at
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    received_at = datetime.now(timezone.utc)

    record = Odds(
        match_id=fixture_id,
        bookmaker=payload.bookmaker,
        home_win=payload.home_odds,
        draw=payload.draw_odds,
        away_win=payload.away_odds,
        timestamp=observed.replace(tzinfo=None),
    )
    db.add(record)
    await db.commit()

    return ManualOddsSnapshotResponse(
        fixture_id=fixture_id,
        bookmaker=payload.bookmaker,
        home_odds=payload.home_odds,
        draw_odds=payload.draw_odds,
        away_odds=payload.away_odds,
        observed_at=observed,
        received_at=received_at,
        executable=True,
        provenance={
            "source_label": payload.source_label,
            "source_url_label": payload.source_url,
            "client_confirmed": payload.user_confirmed,
            "server_fetch_performed": False,
        },
    )


@router.post("/{fixture_id}/analyze")
async def analyze_fixture(
    fixture_id: str,
    db: AsyncSession = Depends(get_async_session),
):
    fixture, prediction, odds, evidence = await _build_evidence(db, fixture_id)
    model = _model_from_prediction(prediction)
    market = _market_from_odds(odds)
    data_gaps = list(evidence.data_gaps)
    model_age = _prediction_age_seconds(prediction)
    model_status = evidence.source_status.get("model", "DATA_GAP")

    _fc = _prediction_metadata(prediction).get("feature_completeness", 1.0) if prediction else 1.0
    known_risks: List[str] = []
    if isinstance(_fc, (int, float)) and 0.5 <= _fc < 0.8:
        known_risks.append(f"ADVISORY: {round((1 - _fc) * 100)}% of model features used league-average defaults")

    req = MatchAnalysisRequest(
        match_id=fixture_id,
        home_team=str(fixture.home_team.name) if fixture.home_team else _team_label(fixture.home_team_id),
        away_team=str(fixture.away_team.name) if fixture.away_team else _team_label(fixture.away_team_id),
        competition=_competition_to_enum(str(fixture.league_id or "EPL")),
        kickoff_utc=fixture.match_date.replace(tzinfo=timezone.utc)
        if fixture.match_date.tzinfo is None
        else fixture.match_date,
        model=model,
        market=market,
        signals=SignalsInput(
            lineup_status=LineupStatusEnum.UNKNOWN,
            sharp_market_signal=SharpSignalEnum.UNKNOWN,
        ),
        freshness=FreshnessInput(
            market_seconds=_market_age_seconds(odds),
            model_features_seconds=model_age,
        ),
        source_status=SourceStatusInput(
            model=SourceStatusEnum(model_status) if model else SourceStatusEnum.DATA_GAP,
            market=SourceStatusEnum.VERIFIED if market else SourceStatusEnum.DATA_GAP,
            team_metrics=SourceStatusEnum.DATA_GAP,
            availability=SourceStatusEnum.DATA_GAP,
        ),
        data_gaps=data_gaps,
        known_risks=known_risks,
    )
    return analyze_match(req, evaluation_at=datetime.now(timezone.utc))
