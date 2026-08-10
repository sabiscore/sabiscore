"""Backend-owned analytics orchestration for certified match predictions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import MatchPredictionLog
from ..schemas.betting_intelligence import (
    CompetitionEnum,
    EvidenceTierEnum,
    FreshnessInput,
    LineupStatusEnum,
    MarketInput,
    MatchAnalysisRequest,
    MatchAnalysisResult,
    ModelInput,
    SharpSignalEnum,
    SignalsInput,
    SourceStatusEnum,
    SourceStatusInput,
)
from .betting_intelligence import analyze_match


def _competition(value: str) -> CompetitionEnum:
    normalized = value.strip().upper().replace("-", "_")
    aliases = {
        "EPL": CompetitionEnum.EPL,
        "PREMIER_LEAGUE": CompetitionEnum.EPL,
        "LALIGA": CompetitionEnum.LA_LIGA,
        "LA_LIGA": CompetitionEnum.LA_LIGA,
        "SERIEA": CompetitionEnum.SERIE_A,
        "SERIE_A": CompetitionEnum.SERIE_A,
        "BUNDESLIGA": CompetitionEnum.BUNDESLIGA,
        "LIGUE1": CompetitionEnum.LIGUE_1,
        "LIGUE_1": CompetitionEnum.LIGUE_1,
        "EREDIVISIE": CompetitionEnum.EREDIVISIE,
        "UCL": CompetitionEnum.UCL,
    }
    try:
        return aliases[normalized]
    except KeyError as exc:
        raise ValueError(f"Unsupported competition: {value}") from exc


class CertifiedAnalyticsService:
    """Build strict engine inputs and persist certified prediction logs."""

    def __init__(self, db: AsyncSession | None = None) -> None:
        self.db = db

    async def analyze_payload(
        self,
        payload: dict[str, Any],
        *,
        trusted_backend: bool = False,
    ) -> MatchAnalysisResult:
        evaluation_at = datetime.now(timezone.utc)
        request = self._build_request(payload, trusted_backend=trusted_backend)
        result = analyze_match(request, evaluation_at=evaluation_at)
        if trusted_backend:
            await self._persist_prediction_log(result)
        return result

    def _build_request(
        self,
        payload: dict[str, Any],
        *,
        trusted_backend: bool = False,
    ) -> MatchAnalysisRequest:
        model_payload = payload.get("model") or {}
        market_payload = payload.get("market")
        source_payload = payload.get("source_status") or {}
        freshness_payload = payload.get("freshness") or {}
        signals_payload = payload.get("signals") or {}

        required_model_metadata = (
            "model_version",
            "calibration_method",
            "calibration_validated",
            "epistemic_uncertainty",
            "aleatoric_uncertainty",
            "confidence_tier",
        )
        model = None
        if all(model_payload.get(field) is not None for field in required_model_metadata):
            model = ModelInput(
                home_probability=float(model_payload["home_probability"]),
                draw_probability=float(model_payload["draw_probability"]),
                away_probability=float(model_payload["away_probability"]),
                model_version=str(model_payload["model_version"]),
                calibration_method=str(model_payload["calibration_method"]),
                calibration_validated=bool(model_payload["calibration_validated"]),
                epistemic_uncertainty=float(model_payload["epistemic_uncertainty"]),
                aleatoric_uncertainty=float(model_payload["aleatoric_uncertainty"]),
                confidence_tier=EvidenceTierEnum(model_payload["confidence_tier"]),
            )

        market = None
        if market_payload:
            market = MarketInput(
                bookmaker=str(market_payload["bookmaker"]),
                market_type=str(market_payload.get("market_type") or "1X2"),
                home_odds=float(market_payload["home_odds"]),
                draw_odds=float(market_payload["draw_odds"]),
                away_odds=float(market_payload["away_odds"]),
                opening_home_odds=market_payload.get("opening_home_odds"),
                opening_draw_odds=market_payload.get("opening_draw_odds"),
                opening_away_odds=market_payload.get("opening_away_odds"),
                captured_at=market_payload["captured_at"],
            )

        if trusted_backend:
            source_status = SourceStatusInput(
                model=SourceStatusEnum(source_payload.get("model") or SourceStatusEnum.DATA_GAP.value),
                market=SourceStatusEnum(source_payload.get("market") or SourceStatusEnum.DATA_GAP.value),
                team_metrics=SourceStatusEnum(source_payload.get("team_metrics") or SourceStatusEnum.DATA_GAP.value),
                availability=SourceStatusEnum(source_payload.get("availability") or SourceStatusEnum.DATA_GAP.value),
            )
            declared_gaps = list(payload.get("data_gaps") or [])
            verified_providers = payload.get("verified_evidence_providers")
        else:
            source_status = SourceStatusInput()
            declared_gaps = [
                *list(payload.get("data_gaps") or []),
                "EXTERNAL_INPUT_UNVERIFIED",
            ]
            verified_providers = []

        return MatchAnalysisRequest(
            match_id=str(payload["match_id"]),
            home_team=str(payload["home_team"]),
            away_team=str(payload["away_team"]),
            competition=_competition(str(payload.get("competition") or payload.get("league") or "EPL")),
            kickoff_utc=payload["kickoff_utc"],
            model=model,
            market=market,
            signals=SignalsInput(
                xg_differential=signals_payload.get("xg_differential"),
                xga_differential=signals_payload.get("xga_differential"),
                opponent_adjusted_form=signals_payload.get("opponent_adjusted_form"),
                club_elo_difference=signals_payload.get("club_elo_difference"),
                schedule_congestion=signals_payload.get("schedule_congestion"),
                travel_load=signals_payload.get("travel_load"),
                confirmed_absences=list(signals_payload.get("confirmed_absences") or []),
                lineup_status=LineupStatusEnum(signals_payload.get("lineup_status") or LineupStatusEnum.UNKNOWN.value),
                sharp_market_signal=SharpSignalEnum(signals_payload.get("sharp_market_signal") or SharpSignalEnum.UNKNOWN.value),
            ),
            freshness=FreshnessInput(
                model_features_seconds=freshness_payload.get("model_features_seconds"),
                market_seconds=freshness_payload.get("market_seconds"),
                injury_news_seconds=freshness_payload.get("injury_news_seconds"),
                lineup_seconds=freshness_payload.get("lineup_seconds"),
            ),
            source_status=source_status,
            data_gaps=declared_gaps,
            known_risks=list(payload.get("known_risks") or []),
            verified_evidence_providers=verified_providers,
        )

    async def _persist_prediction_log(self, result: MatchAnalysisResult) -> None:
        if self.db is None or result.probabilities is None:
            return

        from .canonical_identity_service import canonical_fixture_id_for_provider_event

        canonical_fixture_id = await canonical_fixture_id_for_provider_event(
            self.db,
            provider="football-data.org",
            provider_event_id=result.match_id,
        )

        log = MatchPredictionLog(
            match_id=result.match_id,
            canonical_fixture_id=canonical_fixture_id,
            model_version=result.calculation_audit.model_version if result.calculation_audit else "unknown",
            calibration_method=result.calculation_audit.calibration_method if result.calculation_audit else None,
            home_probability=float(result.probabilities.home or 0.0),
            draw_probability=float(result.probabilities.draw or 0.0),
            away_probability=float(result.probabilities.away or 0.0),
            confidence=float(result.confidence_adjusted_value or 0.0),
            input_hash=result.input_hash,
            decision_id=result.decision_id,
            payload=result.model_dump(mode="json"),
            created_at=result.evaluation_at or datetime.now(timezone.utc),
        )
        self.db.add(log)
        await self.db.flush()
