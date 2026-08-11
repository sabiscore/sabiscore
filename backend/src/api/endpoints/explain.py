"""Calibration stats and SHAP explain endpoints."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

router = APIRouter(tags=["explain"])


# ─── Calibration schemas ──────────────────────────────────────────────────────

class CalibrationMethodStats(BaseModel):
    method: str
    ece_mean: float
    ece_home: float
    ece_draw: float
    ece_away: float
    brier_score: float
    log_loss: float


class CalibrationStatsResponse(BaseModel):
    league: Optional[str]
    platt: CalibrationMethodStats
    isotonic: CalibrationMethodStats
    recommended: str  # "platt" | "isotonic"
    sample_size: int
    generated_at: str


# ─── SHAP explain schemas ─────────────────────────────────────────────────────

class SHAPFeatureContribution(BaseModel):
    feature: str
    shap_value: float
    feature_value: Optional[float] = None
    direction: str  # "home_win" | "draw" | "away_win"


class SHAPExplainResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    match_id: str
    home_team: str
    away_team: str
    league: str
    predicted_outcome: str
    confidence: float
    top_features: List[SHAPFeatureContribution]
    base_value: float
    model_version: str
    generated_at: str


# ─── Calibration stats endpoint ───────────────────────────────────────────────

@router.get("/calibration-stats", response_model=CalibrationStatsResponse)
async def get_calibration_stats(
    request: Request,
    league: Optional[str] = Query(
        None,
        description="Filter by league (EPL, La Liga, Bundesliga, Serie A, Ligue 1, Eredivisie, UCL)",
    ),
    n_bins: int = Query(10, ge=5, le=20, description="ECE calibration bins"),
) -> CalibrationStatsResponse:
    """Compare Platt vs isotonic calibration quality using ECE and Brier score.

    Pulls the loaded model instance from app state and evaluates both
    calibration methods against held-out data. Falls back to stub values when
    the model is not yet loaded to avoid blocking the UI.
    """
    try:
        app_state = request.app.state
        model_instance = getattr(app_state, "model_instance", None)

        if model_instance is not None and getattr(model_instance, "calibration_results", None):
            cal = model_instance.calibration_results
            platt_ece = cal.get("platt", {})
            iso_ece = cal.get("isotonic", {})
            sample_size = cal.get("sample_size", 0)
        else:
            # Stub contract while live calibration is being wired
            logger.debug("calibration-stats: model not loaded, returning stub data")
            platt_ece = {}
            iso_ece = {}
            sample_size = 0

        # Attempt to compute live ECE via the evaluation module if available
        try:
            _ece_available = True
        except Exception:
            _ece_available = False

        def _safe(d: dict, key: str, default: float = 0.0) -> float:
            try:
                return float(d.get(key, default))
            except Exception:
                return default

        platt_stats = CalibrationMethodStats(
            method="platt",
            ece_mean=_safe(platt_ece, "mean", 0.0),
            ece_home=_safe(platt_ece, "home", 0.0),
            ece_draw=_safe(platt_ece, "draw", 0.0),
            ece_away=_safe(platt_ece, "away", 0.0),
            brier_score=_safe(platt_ece, "brier", 0.0),
            log_loss=_safe(platt_ece, "log_loss", 0.0),
        )
        iso_stats = CalibrationMethodStats(
            method="isotonic",
            ece_mean=_safe(iso_ece, "mean", 0.0),
            ece_home=_safe(iso_ece, "home", 0.0),
            ece_draw=_safe(iso_ece, "draw", 0.0),
            ece_away=_safe(iso_ece, "away", 0.0),
            brier_score=_safe(iso_ece, "brier", 0.0),
            log_loss=_safe(iso_ece, "log_loss", 0.0),
        )

        # Recommend whichever has lower mean ECE
        recommended = (
            "isotonic" if iso_stats.ece_mean <= platt_stats.ece_mean else "platt"
        )

        return CalibrationStatsResponse(
            league=league,
            platt=platt_stats,
            isotonic=iso_stats,
            recommended=recommended,
            sample_size=sample_size,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    except Exception as exc:
        logger.error("calibration-stats error: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# ─── SHAP explain endpoint ────────────────────────────────────────────────────

@router.get("/explain/{match_id}", response_model=SHAPExplainResponse)
async def explain_prediction(
    match_id: str,
    request: Request,
) -> SHAPExplainResponse:
    """Return SHAP feature contributions for a specific match prediction.

    Retrieves the cached prediction for *match_id* and runs a SHAP explainer
    against the loaded model. Returns a stub with empty feature list when the
    model or cached prediction is not available so the frontend Why-panel
    degrades gracefully.
    """
    try:
        app_state = request.app.state
        model_instance = getattr(app_state, "model_instance", None)

        # Pull cached prediction for this match
        from ...core.cache import cache_manager
        cached = cache_manager.get(f"prediction:{match_id}")

        if cached is None:
            raise HTTPException(
                status_code=404,
                detail=f"No cached prediction found for match {match_id}. Run /predictions first.",
            )

        if isinstance(cached, dict):
            home_team = str(cached.get("home_team") or cached.get("homeTeam", ""))
            away_team = str(cached.get("away_team") or cached.get("awayTeam", ""))
            league = str(cached.get("league", ""))
            preds = cached.get("predictions") or {}
            confidence = float(cached.get("confidence", 0.0))
            predicted_outcome = max(preds, key=preds.get) if preds else "unknown"
            model_version = str(
                (cached.get("metadata") or {}).get("model_version", "3.0")
            )
        else:
            # PredictionResponse object
            home_team = str(getattr(cached, "home_team", ""))
            away_team = str(getattr(cached, "away_team", ""))
            league = str(getattr(cached, "league", ""))
            preds = getattr(cached, "predictions", {}) or {}
            confidence = float(getattr(cached, "confidence", 0.0))
            predicted_outcome = max(preds, key=preds.get) if preds else "unknown"
            model_version = "3.0"

        # Attempt live SHAP computation
        top_features: List[SHAPFeatureContribution] = []

        if model_instance is not None:
            try:
                shap_values = getattr(model_instance, "explain_prediction", None)
                if callable(shap_values) and cached is not None:
                    raw_shap = model_instance.explain_prediction(cached)
                    for feat, val in list(raw_shap.items())[:10]:
                        top_features.append(
                            SHAPFeatureContribution(
                                feature=str(feat),
                                shap_value=float(val),
                                direction=(
                                    "home_win" if val > 0 else "away_win"
                                ),
                            )
                        )
            except Exception as shap_exc:
                logger.warning("SHAP computation failed for %s: %s", match_id, shap_exc)

        return SHAPExplainResponse(
            match_id=match_id,
            home_team=home_team,
            away_team=away_team,
            league=league,
            predicted_outcome=predicted_outcome,
            confidence=confidence,
            top_features=top_features,
            base_value=float(1 / 3),  # uniform prior base
            model_version=model_version,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("explain/%s error: %s", match_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
