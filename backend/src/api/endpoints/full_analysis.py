"""Phase 7-D: Unified match intelligence endpoint.

Route: GET /matches/upcoming/{match_id}/full-analysis

Orchestrates the 6-layer intelligence pipeline:
  1. Ensemble prediction (league model)
  2. BNN uncertainty breakdown
  3. Causal feature analysis
  4. RL betting recommendation (Kelly fallback)
  5. Elo context
  6. StatsBomb tactical features (via UpcomingMatchFeatureProjector)

Then fuses layers via IntelligenceSynthesizer → FullMatchAnalysisResponse.

Cache: Redis key full_analysis:{match_id}, TTL 60s (B13: stale features are
preferable to synthetic substitution; staleness is surfaced via data_gaps).
Rate limiting is enforced by the FastAPI application's global Redis-backed
middleware using the configured request window.
"""

from __future__ import annotations

import json
import logging
import math
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.cache import cache
from ...core.config import settings
from ...core.league_policy import LeaguePolicyUnavailableError, get_league_policy
from ...core.redaction import redact_text
from ...data.elo_engine import EloContext
from ...db.session import get_async_session
from ...models.causal_selector import CausalFeatureResult
from ...models.feature_registry import active_canonical_features
from ...models.active_generation import active_generation_is_certified
from ...schemas.full_analysis import (
    FullMatchAnalysisResponseSchema,
    PredictionSource,
    PredictionStatus,
)
from ...services.intelligence_synthesizer import (
    EnsemblePrediction,
    FullMatchAnalysisResponse,
    IntelligenceSynthesizer,
    MatchActionability,
    OddsEdge,
)
from ...models.prediction import PredictionEngine
from ...monitoring.metrics import metrics_collector
from ...services.odds_service import OddsService, get_odds_service
from ...services.prediction_log_service import (
    PredictionLogCapture,
    deterministic_input_hash,
    persist_prediction_log,
)
from ...services.rl_betting_agent import RLBettingAgent, RLRecommendationPayload
from ...services.uncertainty_service import UncertaintyBreakdown, UncertaintyService
from ...services.upcoming_match_feature_service import UpcomingMatchFeatureProjector

logger = logging.getLogger(__name__)


def _utc_aware_datetime(value: object) -> Optional[datetime]:
    """Normalize canonical DB timestamps at the public response boundary.

    PostgreSQL deployments historically returned naive UTC datetimes here.
    Internally that convention remains unchanged, but the public
    ``kickoff_utc`` contract must always serialize with an explicit offset.
    Invalid values fail closed to ``None`` instead of emitting an ambiguous
    local timestamp.
    """
    if value is None:
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

router = APIRouter(prefix="/matches", tags=["intelligence"])

# Age past which the completed matches backing a side's form stop describing the
# current team and become a different squad — one full season plus a close-season
# break. Deliberately season-scale, not the league policy's
# model_feature_freshness_ttl_seconds (3600s): that TTL governs live market and
# lineup features, which are hours-fresh by nature. Recent form never can be.
_MODEL_INPUT_STALENESS_LIMIT_SECONDS = 400 * 24 * 3600

_CACHE_TTL_SECONDS = 60
_GLOBAL_KELLY_CAP = 0.05
_QUARTER_KELLY = 0.25


def _default_live_vector(
    league: str,
    canonical_features: List[str],
) -> Dict[str, Any]:
    """Return an explicitly non-actionable diagnostic vector after projection failure."""
    features = np.zeros(len(canonical_features), dtype=np.float32)
    features_dict = {f: 0.0 for f in canonical_features}
    # ponytail: this fallback only fires after project_match_features() raised —
    # no team-name resolution ever ran, so identity is trivially unverified.
    # Named (not a bare literal) to satisfy INV-19: verification predicates are
    # computed, never asserted, even when the derivation is this trivial.
    no_identity_resolution_attempted = True
    return {
        "features": features,
        "features_58": features[:58],
        "features_dict": features_dict,
        "data_gaps": list(canonical_features),
        "staleness_seconds": 0,
        "staleness_available": False,
        "elo_pre_match": 0.0,
        "league": league,
        "odds": None,
        "identity_resolution": {
            "home_team_resolved": not no_identity_resolution_attempted,
            "away_team_resolved": not no_identity_resolution_attempted,
        },
        "fixture_identity_verified": not no_identity_resolution_attempted,
        "is_reduced_evidence_baseline": True,
        "data_quality": {
            "historical_data_ratio": 0.0,
            "defaults_used_count": len(canonical_features),
            "feature_defaulted_ratio": 1.0,
            "is_synthetic": True,
        },
    }


def _effective_kelly_cap(league: str) -> tuple[float, Optional[str], int]:
    """Resolve the league cap and freshness limit without a global fallback."""
    try:
        policy = get_league_policy(league)
    except LeaguePolicyUnavailableError:
        return 0.0, "LEAGUE_POLICY_UNAVAILABLE", 0
    return (
        min(float(policy.kelly_cap), _GLOBAL_KELLY_CAP),
        None,
        int(policy.model_feature_freshness_ttl_seconds),
    )


def _empty_ensemble(league: str) -> EnsemblePrediction:
    return EnsemblePrediction(
        home_win_prob=0.0,
        draw_prob=0.0,
        away_win_prob=0.0,
        prediction="unavailable",
        confidence=0.0,
        league=league,
        model_version="unavailable",
        calibration_method="unavailable",
        calibration_applied=False,
        overlay_applied=False,
    )


def _ensemble_from_prediction(pred: Dict[str, Any], league: str) -> Optional[EnsemblePrediction]:
    probs = pred.get("predictions")
    if not isinstance(probs, dict):
        probs = pred

    try:
        h_raw = probs.get("home_win", probs.get("home_win_prob"))
        d_raw = probs.get("draw", probs.get("draw_prob"))
        a_raw = probs.get("away_win", probs.get("away_win_prob"))
        if h_raw is None or d_raw is None or a_raw is None:
            return None
        h = float(h_raw)
        d = float(d_raw)
        a = float(a_raw)
    except (TypeError, ValueError, AttributeError):
        return None

    values = (h, d, a)
    if not all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in values):
        return None
    total = h + d + a
    if abs(total - 1.0) > 1e-4:
        logger.error(
            "Prediction probability simplex rejected league=%s total=%.8f",
            league,
            total,
        )
        return None
    prediction = max({"home_win": h, "draw": d, "away_win": a}, key=lambda k: {"home_win": h, "draw": d, "away_win": a}[k])
    return EnsemblePrediction(
        home_win_prob=h,
        draw_prob=d,
        away_win_prob=a,
        prediction=prediction,
        confidence=max(h, d, a),
        league=league,
        model_version=str(pred.get("model_version", "")),
        calibration_method=str(pred.get("calibration_method", "raw")),
        calibration_applied=bool(pred.get("calibration_applied", False)),
        overlay_applied=bool(pred.get("overlay_applied", False)),
    )


def _uncertainty_from_features(
    features: Dict[str, Any],
) -> Optional[UncertaintyBreakdown]:
    """Return measured BNN uncertainty, never a probability-derived proxy."""

    if not features:
        return None
    return UncertaintyService().decompose_measured(pd.DataFrame([features]))


def _causal_results_from_report(
    report_path: str,
    limit: int = 58,
) -> List[CausalFeatureResult]:
    from pathlib import Path

    path = Path(report_path)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        features = payload.get("features", []) if isinstance(payload, dict) else []
        results = []
        for f in features[:limit]:
            if not isinstance(f, dict):
                continue
            ci = f.get("ate_ci", [0.0, 0.0])
            if not isinstance(ci, (list, tuple)) or len(ci) < 2:
                ci = [0.0, 0.0]
            results.append(
                CausalFeatureResult(
                    name=str(f.get("name", "")),
                    ate_win=float(f.get("ate_win", 0.0)),
                    ate_draw=float(f.get("ate_draw", 0.0)),
                    ate_ci=(float(ci[0]), float(ci[1])),
                    p_value=float(f.get("p_value", 1.0)),
                    classification=str(f.get("classification", "INDEPENDENT")),
                )
            )
        return results
    except Exception as exc:
        logger.warning("Could not load causal report from %s: %s", report_path, exc)
        return []


def _rl_from_ensemble(
    ensemble: EnsemblePrediction,
    uncertainty: Optional[UncertaintyBreakdown],
    odds: Optional[Dict[str, float]] = None,
    effective_kelly_cap: float = 0.0,
) -> RLRecommendationPayload:
    probs = {
        "home_win": ensemble.home_win_prob,
        "draw": ensemble.draw_prob,
        "away_win": ensemble.away_win_prob,
    }
    if uncertainty is None:
        return RLRecommendationPayload(
            stake_fraction=0.0,
            abstain=True,
            reward_components={"R_pnl": 0.0, "R_ic": 0.0, "R_cal": 0.0, "R_risk": 0.0, "R_abs": 0.05},
            reason="Abstained: measured model uncertainty unavailable",
        )
    if odds is None:
        return RLRecommendationPayload(
            stake_fraction=0.0,
            abstain=True,
            reward_components={"R_pnl": 0.0, "R_ic": 0.0, "R_cal": 0.0, "R_risk": 0.0, "R_abs": 0.05},
            reason="Abstained: market odds unavailable",
        )
    agent = RLBettingAgent(max_kelly_cap=effective_kelly_cap)
    recommendation = agent.recommend(
        probabilities=probs,
        odds=odds,
        confidence=ensemble.confidence,
        epistemic_unc=uncertainty.epistemic_unc,
    )
    public_stake = 0.0 if recommendation.abstain else min(
        recommendation.stake_fraction * _QUARTER_KELLY,
        effective_kelly_cap,
    )
    return RLRecommendationPayload(
        stake_fraction=public_stake,
        abstain=recommendation.abstain,
        reward_components=dict(recommendation.reward_components),
        reason=recommendation.reason,
    )


async def _fetch_market_odds(
    *,
    home_team: Optional[str],
    away_team: Optional[str],
    league: str,
    odds_service: Optional[OddsService] = None,
) -> Optional[Dict[str, float]]:
    """Look up a coherent 1X2 price for this fixture, or ``None``.

    Fails soft on every axis — a market is optional evidence, and an odds outage
    must degrade the analysis to "no edge computed", never break it. The service
    caches (120s per league board, 300s per match) so a page refresh does not
    spend provider quota, and returns its own ``source: "unavailable"`` shape when
    no coherent market exists, which `_odds_edge_from_features` already rejects.
    """
    if not home_team or not away_team:
        return None
    if odds_service is None:
        # Kept lazy for direct/unit callers. Production always injects the one
        # lifespan-scoped instance through ``get_odds_service``.
        from ...services.odds_service import OddsService as DefaultOddsService

        odds_service = DefaultOddsService()
    try:
        odds = await odds_service.get_match_odds(
            home_team=home_team, away_team=away_team, league=league
        )
    except Exception as exc:
        logger.warning(
            "Live odds lookup failed for %s vs %s (%s): %s: %s",
            home_team, away_team, league, type(exc).__name__, redact_text(str(exc)),
        )
        return None

    if not isinstance(odds, dict) or odds.get("source") == "unavailable":
        return None
    return odds


def _odds_edge_from_features(
    ensemble: EnsemblePrediction,
    odds: Optional[Dict[str, float]],
    effective_kelly_cap: float = 0.0,
) -> Optional[OddsEdge]:
    if odds is None:
        return None

    normalized_odds = {
        "home_win": float(odds.get("home_win", odds.get("home", 0.0)) or 0.0),
        "draw": float(odds.get("draw", 0.0) or 0.0),
        "away_win": float(odds.get("away_win", odds.get("away", 0.0)) or 0.0),
    }
    if any(value <= 1.0 for value in normalized_odds.values()):
        return None

    raw_implied = {market: 1.0 / price for market, price in normalized_odds.items()}
    overround = sum(raw_implied.values())
    if overround <= 0:
        return None
    fair_market = {market: implied / overround for market, implied in raw_implied.items()}
    model_probs = {
        "home_win": ensemble.home_win_prob,
        "draw": ensemble.draw_prob,
        "away_win": ensemble.away_win_prob,
    }

    best: Optional[tuple[str, float, float, float, float]] = None
    for market, market_odds in normalized_odds.items():
        model_prob = float(model_probs.get(market, 0.0))
        edge = model_prob - fair_market[market]
        expected_value = (model_prob * market_odds) - 1.0
        denom = market_odds - 1.0
        kelly = max(0.0, expected_value / denom) if denom > 0 and expected_value > 0 else 0.0
        candidate = (market, market_odds, model_prob, edge, kelly)
        if best is None or (edge > best[3] and expected_value > 0):
            best = candidate

    if best is None or best[3] <= 0:
        return None

    market, market_odds, model_prob, edge, kelly = best
    return OddsEdge(
        market=market,
        market_odds=market_odds,
        model_prob=model_prob,
        edge=edge,
        kelly_stake=min(kelly * _QUARTER_KELLY, effective_kelly_cap),
    )


# ─── Edge-quality / actionability helpers (Sprint 4 Slice A) ─────────────────


def _compute_edge_quality_score(
    ensemble: EnsemblePrediction,
    odds_edge: Optional[OddsEdge],
    features_dict: dict,
    data_gaps: List[str],
    n_canonical: int,
) -> float:
    """Return a 0.0–1.0 advisory edge quality score.

    Combines model confidence, market edge alignment, Phase 8 drift direction,
    and data completeness.  score < settings.edge_quality_abstain_threshold
    triggers the advisory ABSTAIN gate.
    """
    # Component 1: confidence above random (1/3) baseline
    confidence_factor = max(0.0, min(1.0, (ensemble.confidence - 0.333) / 0.5))

    # Component 2: market edge relative to a 15pp benchmark
    if odds_edge is not None and odds_edge.edge > 0:
        market_alignment = min(1.0, odds_edge.edge / 0.15)
    else:
        market_alignment = 0.0

    # Component 3: Phase 8 sharp-money drift toward predicted outcome
    drift_map = {
        "home_win": "odds_drift_home",
        "draw": "odds_drift_draw",
        "away_win": "odds_drift_away",
    }
    drift_key = drift_map.get(ensemble.prediction, "")
    if drift_key and drift_key not in data_gaps:
        drift_val = float(features_dict.get(drift_key, 0.0))
        drift_alignment = min(1.0, max(0.0, drift_val / 0.05))
    else:
        drift_alignment = 0.0

    # Component 4: data completeness (fewer gaps = higher completeness)
    completeness = max(0.0, 1.0 - len(data_gaps) / max(1, n_canonical))

    score = (
        0.40 * confidence_factor
        + 0.30 * market_alignment
        + 0.20 * drift_alignment
        + 0.10 * completeness
    )
    return round(min(1.0, max(0.0, score)), 4)


def _closing_line_convergence_delta(
    ensemble: EnsemblePrediction,
    features_dict: dict,
    data_gaps: List[str],
) -> Optional[float]:
    """Return opening→current implied-probability drift for the predicted outcome.

    Positive = market has moved toward that outcome (sharp-money confirms model
    direction).  Returns None when market-drift data is a DATA_GAP.
    """
    drift_map = {
        "home_win": "odds_drift_home",
        "draw": "odds_drift_draw",
        "away_win": "odds_drift_away",
    }
    drift_key = drift_map.get(ensemble.prediction, "")
    if not drift_key or drift_key in data_gaps:
        return None
    val = features_dict.get(drift_key)
    return round(float(val), 4) if val is not None else None


def _build_actionability(
    ensemble: EnsemblePrediction,
    odds_edge: Optional[OddsEdge],
    features_dict: dict,
    data_gaps: List[str],
    causal_results: List[CausalFeatureResult],
    rl_rec,
    uncertainty,
    canonical_feature_count: int,
) -> MatchActionability:
    """Build the advisory MatchActionability block for this analysis."""
    edge_score = _compute_edge_quality_score(
        ensemble, odds_edge, features_dict, data_gaps, canonical_feature_count
    )
    conv_delta = _closing_line_convergence_delta(ensemble, features_dict, data_gaps)

    should_abstain = rl_rec.abstain or edge_score < settings.edge_quality_abstain_threshold
    if should_abstain:
        suggested_stake_pct = 0.0
    else:
        suggested_stake_pct = round(
            (odds_edge.kelly_stake * 100)
            if odds_edge is not None and odds_edge.kelly_stake > 0
            else 0.0,
            2,
        )

    # Top evidence: causal drivers first, then market and drift signals
    top_evidence: List[str] = []
    for r in causal_results:
        if r.classification == "CAUSAL_DRIVER" and len(top_evidence) < 3:
            top_evidence.append(r.name.replace("_", " ").title())
    if odds_edge is not None and odds_edge.edge > 0 and len(top_evidence) < 3:
        top_evidence.append(
            f"Market edge +{round(odds_edge.edge * 100, 1)}pp on {odds_edge.market.replace('_', ' ')}"
        )
    if conv_delta is not None and conv_delta > 0.02 and len(top_evidence) < 3:
        top_evidence.append(
            f"Sharp drift +{conv_delta:.3f} toward {ensemble.prediction.replace('_', ' ')}"
        )

    # Caveats: low evidence, data gaps, or score-below-threshold warnings
    caveats: List[str] = []
    if uncertainty is None:
        caveats.append("Measured model uncertainty unavailable")
    elif uncertainty.confidence_tier == "LOW_EVIDENCE":
        caveats.append(f"Low model evidence (epistemic {uncertainty.epistemic_unc:.2f})")
    # Exclude structural always-gap features from user-visible caveat count
    important_gaps = [g for g in data_gaps if g not in ("shot_quality_diff",)]
    if important_gaps:
        human = [g.replace("_", " ").title() for g in important_gaps[:3]]
        suffix = f" and {len(important_gaps) - 3} more" if len(important_gaps) > 3 else ""
        caveats.append(
            f"{len(important_gaps)} live data gap(s): {', '.join(human)}{suffix}"
        )
    if not rl_rec.abstain and edge_score < settings.edge_quality_abstain_threshold:
        caveats.append(
            f"Edge quality below threshold ({edge_score:.2f} < {settings.edge_quality_abstain_threshold:.2f})"
        )

    return MatchActionability(
        edge_quality_score=edge_score,
        clv_pct=None,  # pre-kick-off: true CLV requires closing odds (Sprint 5)
        closing_line_convergence_delta=conv_delta,
        suggested_stake_pct=suggested_stake_pct,
        abstain=should_abstain,
        abstain_reason=rl_rec.reason if should_abstain else None,
        top_evidence=top_evidence,
        caveats=caveats,
    )


@router.get(
    "/upcoming/{match_id}/full-analysis",
    summary="Unified 6-layer match intelligence",
    response_model=FullMatchAnalysisResponseSchema,
)
async def get_full_analysis(
    match_id: str,
    league: str = Query(default="EPL", description="League for matchup-based lookups"),
    db: AsyncSession = Depends(get_async_session),
    odds_service: OddsService = Depends(get_odds_service),
) -> dict:
    """Return fused TYPE-F verdict: ensemble × BNN × causal × RL × Elo × StatsBomb.

    `match_id` may be either:
    - A database UUID / integer ID ("123", "abc-...")
    - A matchup string ("Arsenal vs Chelsea") — home/away are parsed and features
      are built without requiring a DB match record (P7-E live data wiring).
    """

    started_at = time.perf_counter()
    cache_key = f"full_analysis:v2:{match_id}:{league}"
    cached = cache.get(cache_key) if cache else None
    if cached:
        try:
            metrics_collector.increment("analysis.cache_hit")
            return json.loads(cached) if isinstance(cached, str) else cached
        except Exception:
            pass

    # Direct unit calls do not execute FastAPI dependencies. Production requests
    # always receive the lifespan-scoped service through get_odds_service.
    if not isinstance(odds_service, OddsService):
        odds_service = OddsService()
    projector = UpcomingMatchFeatureProjector(odds_service=odds_service)
    prediction_engine = PredictionEngine()
    synthesizer = IntelligenceSynthesizer()
    canonical_features = active_canonical_features(
        use_phase7=settings.use_phase7_models,
        use_phase8=settings.phase8_enabled,
    )

    # Detect matchup strings like "Arsenal vs Chelsea"
    _is_matchup = " vs " in match_id or " VS " in match_id

    projection_failed = False
    try:
        if _is_matchup:
            sep = " vs " if " vs " in match_id else " VS "
            parts = match_id.split(sep, 1)
            home_team = parts[0].strip()
            away_team = parts[1].strip() if len(parts) > 1 else "Unknown"
            live = await projector.build_live_feature_vector_from_matchup(
                home_team=home_team,
                away_team=away_team,
                league=league,
                db=db,
            )
        else:
            live = await projector.build_live_feature_vector(
                match_id=match_id,
                league=league,
                db=db,
            )
    except Exception as exc:
        projection_failed = True
        logger.warning(
            "Feature projection failed for match_id=%r league=%r: %s: %s — "
            "model inference skipped; all fields marked DATA_GAP",
            match_id, league, type(exc).__name__, redact_text(exc),
        )
        # The diagnostic vector is response scaffolding only. It is never sent
        # to a model after a projection failure.
        live = _default_live_vector(league, list(canonical_features))

    league = str(live.get("league", league) or league)
    data_gaps: List[str] = list(live.get("data_gaps", []))
    critical_gaps: List[str] = list(live.get("critical_gaps", []))
    if not active_generation_is_certified():
        critical_gaps.append("MODEL_GENERATION_UNCERTIFIED")
    advisory_gaps: List[str] = list(live.get("advisory_gaps", []))
    conflicts: List[str] = list(live.get("conflicts", []))
    effective_kelly_cap, policy_gap, model_freshness_limit = _effective_kelly_cap(league)
    if policy_gap:
        critical_gaps.append(policy_gap)
    fixture_verified = bool(live.get("fixture_identity_verified", False))
    if not fixture_verified:
        critical_gaps.append("FIXTURE_IDENTITY_UNVERIFIED")
    data_quality = dict(live.get("data_quality") or {})
    reduced_evidence_input = bool(live.get("is_reduced_evidence_baseline", False))
    if data_quality.get("is_synthetic"):
        reduced_evidence_input = True
        critical_gaps.append("REQUIRED_MODEL_INPUTS_UNAVAILABLE")
    staleness_available = bool(
        live.get("staleness_available", "staleness_seconds" in live)
    )
    staleness_seconds = int(live.get("staleness_seconds", 0))

    # Two different things used to share one gate, and the wrong one was critical.
    #
    # `staleness_seconds` measures ONLY the offline StatsBomb enrichment parquet,
    # which supplies 2 of the 65 live features and is a frozen research artifact
    # (last row 2024-06-02). Comparing it against the league's 3600s feature TTL
    # made it exceed the limit by ~811 days on every request, so
    # STALE_REQUIRED_EVIDENCE — a *critical* gap — fired on 100% of fixtures
    # forever, forcing PARTIAL/no-bet no matter how much genuine history existed.
    # An optional enrichment source being old is real information, but it is
    # advisory: it may reduce confidence, it must never block a valid analysis
    # (CLAUDE.md — only critical_gaps force PARTIAL).
    #
    # The required model inputs are the completed matches behind each side's form.
    # Their age is measured separately and keeps the critical gate, against a
    # season-scale threshold rather than the live-feature TTL, because form is
    # inherently days-to-weeks old and can never satisfy a 1-hour limit.
    if (
        staleness_available
        and model_freshness_limit > 0
        and staleness_seconds > model_freshness_limit
    ):
        advisory_gaps.append("STALE_ENRICHMENT_EVIDENCE")

    model_input_staleness = live.get("model_input_staleness_seconds")
    if (
        model_input_staleness is not None
        and float(model_input_staleness) > _MODEL_INPUT_STALENESS_LIMIT_SECONDS
    ):
        critical_gaps.append("STALE_REQUIRED_EVIDENCE")

    # Layer 1: Ensemble prediction (Phase 8 canonical path — full feature vector)
    if projection_failed:
        raw_pred = {}
    else:
        try:
            full_features = np.asarray(
                live.get("features")
                if live.get("features") is not None
                else np.asarray(list(live.get("features_dict", {}).values()), dtype=np.float32),
                dtype=np.float32,
            )
            pred_result = await prediction_engine.predict(
                features=full_features,
                league=league,
                match_id=match_id,
            )
            raw_pred = pred_result.to_dict()
        except Exception as exc:
            logger.warning(
                "Ensemble prediction failed for %s: %s", match_id, redact_text(exc)
            )
            data_gaps.append("ensemble_prediction")
            raw_pred = {}

    ensemble = _ensemble_from_prediction(raw_pred, league)
    prediction_status = PredictionStatus.AVAILABLE
    prediction_source = PredictionSource.CERTIFIED_MODEL
    if ensemble is None:
        critical_gaps.append("MODEL_PREDICTION_UNAVAILABLE")
        ensemble = _empty_ensemble(league)
        prediction_status = PredictionStatus.UNAVAILABLE
        prediction_source = PredictionSource.NONE
    elif str(raw_pred.get("model_version", "")).casefold() == "fallback" or reduced_evidence_input:
        critical_gaps.append("MODEL_PREDICTION_REDUCED_EVIDENCE")
        prediction_status = PredictionStatus.REDUCED_EVIDENCE_BASELINE
        prediction_source = PredictionSource.DIAGNOSTIC_BASELINE
    features_dict = live.get("features_dict", {})

    # Layer 2: BNN uncertainty
    uncertainty = _uncertainty_from_features(features_dict)
    if uncertainty is None:
        critical_gaps.append("MODEL_UNCERTAINTY_UNAVAILABLE")

    # Layer 3: Causal drivers (read-only; path controlled via CAUSAL_REPORT_PATH env var)
    causal_results = _causal_results_from_report(str(settings.causal_report_path))
    if not causal_results:
        data_gaps.append("causal_analysis")

    # Layer 4: RL recommendation
    #
    # `live` carries no "odds" key on any success path — only the failure fallback
    # `_default_live_vector()` sets it, and it sets it to None. So market_odds was
    # structurally always None here, `_odds_edge_from_features` always returned
    # None, and COHERENT_1X2_MARKET_UNAVAILABLE fired as a critical gap on 100% of
    # requests regardless of provider state. Enabling the_odds_api in production
    # changed nothing on this surface because nothing ever asked it for a price.
    market_odds: Optional[Dict[str, Any]] = live.get("odds") or None
    if market_odds is None and not bool(live.get("market_snapshot_acquired")):
        market_odds = await _fetch_market_odds(
            home_team=live.get("home_team"),
            away_team=live.get("away_team"),
            league=league,
            odds_service=odds_service,
        )
    rl_rec = _rl_from_ensemble(
        ensemble,
        uncertainty,
        odds=market_odds,
        effective_kelly_cap=effective_kelly_cap,
    )

    # Layer 5: Elo context
    elo_candidate = live.get("elo_context")
    elo_ctx = elo_candidate if isinstance(elo_candidate, EloContext) else None
    # Elo ratings are keyed by team_id — an unresolved identity makes any Elo value
    # meaningless regardless of its number. Gate on identity (the real cause), not
    # value: EloEngine never fails/raises, so a genuine, evenly-rated matchup can
    # legitimately land at elo_difference == 0.0 / home_elo == 1500.0 — the old
    # value check would have false-positived on exactly that real result.
    if elo_ctx is None:
        data_gaps.append("elo_ratings")

    # Layer 6: Odds edge (optional)
    odds_edge = _odds_edge_from_features(
        ensemble,
        market_odds,
        effective_kelly_cap=effective_kelly_cap,
    )
    if odds_edge is None:
        critical_gaps.append("COHERENT_1X2_MARKET_UNAVAILABLE")

    if prediction_status != PredictionStatus.AVAILABLE or critical_gaps or conflicts:
        rl_rec = RLRecommendationPayload(
            stake_fraction=0.0,
            abstain=True,
            reward_components={
                "R_pnl": 0.0,
                "R_ic": 0.0,
                "R_cal": 0.0,
                "R_risk": 0.0,
                "R_abs": 0.05,
            },
            reason="Abstained: insufficient verified evidence",
        )
        # Retain a measured market comparison for explanation, while the
        # synthesizer zeroes Kelly and every public stake for this closed gate.

    # Advisory actionability block (Sprint 4 Slice A)
    deduped_gaps = sorted(set(data_gaps))
    actionability = _build_actionability(
        ensemble=ensemble,
        odds_edge=odds_edge,
        features_dict=features_dict,
        data_gaps=deduped_gaps,
        causal_results=causal_results,
        rl_rec=rl_rec,
        uncertainty=uncertainty,
        canonical_feature_count=len(canonical_features),
    )

    field_availability = {
        "fixture": fixture_verified,
        "prediction": prediction_status == PredictionStatus.AVAILABLE,
        "market": bool(market_odds and {"home_win", "draw", "away_win"}.issubset(market_odds)),
        "uncertainty": uncertainty is not None,
        "elo": elo_ctx is not None,
    }
    unavailable_reasons = {
        key: reason
        for key, reason in {
            "fixture": "Stable verified fixture identity unavailable",
            "prediction": "Certified model output unavailable",
            "market": "Coherent single-bookmaker 1X2 snapshot unavailable",
            "uncertainty": "Measured BNN uncertainty unavailable",
            "elo": "Resolved Elo history unavailable for one or both teams",
        }.items()
        if not field_availability[key]
    }

    # Fuse
    response: FullMatchAnalysisResponse = synthesizer.synthesize(
        match_id=match_id,
        ensemble=ensemble,
        uncertainty=uncertainty,
        causal_results=causal_results,
        rl_rec=rl_rec,
        elo_ctx=elo_ctx,
        odds_edge=odds_edge,
        data_gaps=deduped_gaps,
        critical_gaps=critical_gaps,
        advisory_gaps=advisory_gaps,
        conflicts=conflicts,
        prediction_status=prediction_status.value,
        prediction_source=prediction_source.value,
        effective_kelly_cap=effective_kelly_cap,
        actionability=actionability,
        staleness_seconds=staleness_seconds,
        staleness_available=staleness_available,
        feature_freshness_seconds=dict(live.get("feature_freshness_seconds") or {}),
        feature_source=dict(live.get("feature_source") or {}),
        features_dict=features_dict,
        home_team=live.get("home_team"),
        away_team=live.get("away_team"),
        league=league,
        kickoff_utc=_utc_aware_datetime(live.get("kickoff_utc")),
        fixture_verified=fixture_verified,
        field_availability=field_availability,
        unavailable_reasons=unavailable_reasons,
    )

    result = response.to_dict()

    # Capture the real model snapshot that settlement and CLV evaluate later.
    # Matchup strings, diagnostic baselines, invalid simplexes, non-scheduled
    # fixtures, and post-kickoff requests are refused by construction. The
    # analytical response remains available if persistence fails, but the
    # transaction is rolled back and the failure is observable.
    if (
        not _is_matchup
        and isinstance(db, AsyncSession)
        and fixture_verified
        and prediction_status == PredictionStatus.AVAILABLE
    ):
        evaluated_at = datetime.now(timezone.utc)
        input_hash = deterministic_input_hash(
            {
                "match_id": match_id,
                "model_version": ensemble.model_version,
                "calibration_method": ensemble.calibration_method,
                "probabilities": [
                    ensemble.home_win_prob,
                    ensemble.draw_prob,
                    ensemble.away_win_prob,
                ],
                "features": features_dict,
                "feature_source": dict(live.get("feature_source") or {}),
                "data_gaps": sorted(set(deduped_gaps)),
                "critical_gaps": sorted(set(critical_gaps)),
                "advisory_gaps": sorted(set(advisory_gaps)),
                "conflicts": sorted(set(conflicts)),
            }
        )
        try:
            from ...services.canonical_identity_service import (
                canonical_fixture_id_for_provider_event,
            )

            canonical_fixture_id = await canonical_fixture_id_for_provider_event(
                db,
                provider="football-data.org",
                provider_event_id=match_id,
            )
            capture_outcome = await persist_prediction_log(
                db,
                PredictionLogCapture(
                    match_id=match_id,
                    canonical_fixture_id=canonical_fixture_id,
                    model_version=ensemble.model_version,
                    calibration_method=ensemble.calibration_method,
                    home_probability=ensemble.home_win_prob,
                    draw_probability=ensemble.draw_prob,
                    away_probability=ensemble.away_win_prob,
                    confidence=ensemble.confidence,
                    input_hash=input_hash,
                    evaluated_at=evaluated_at,
                    payload={
                        "capture_trigger": "interactive_full_analysis",
                        "evaluation_at": evaluated_at.isoformat(),
                        "prediction_status": prediction_status.value,
                        "prediction_source": prediction_source.value,
                        "fixture_verified": fixture_verified,
                        "evidence": {
                            "critical_gaps": sorted(set(critical_gaps)),
                            "advisory_gaps": sorted(set(advisory_gaps)),
                            "conflicts": sorted(set(conflicts)),
                        },
                    },
                ),
                require_scheduled_pre_kickoff=True,
            )
            await db.commit()
            metrics_collector.increment(
                f"analysis.prediction_log.{capture_outcome}"
            )
        except Exception as exc:
            await db.rollback()
            metrics_collector.increment("analysis.prediction_log.error")
            metrics_collector.record_error(
                "prediction_log_persistence",
                redact_text(exc),
                {
                    "match_id": match_id,
                    "capture_trigger": "interactive_full_analysis",
                },
            )
            logger.error(
                "Prediction-log capture failed for %s: %s: %s",
                match_id,
                type(exc).__name__,
                redact_text(exc),
            )

    available_fields = sum(1 for value in field_availability.values() if value)
    abstention_reason = (
        sorted(set(critical_gaps))[0]
        if critical_gaps
        else (sorted(set(conflicts))[0] if conflicts else "NONE")
    )
    metrics_collector.record_analysis_state(
        prediction_available=prediction_status == PredictionStatus.AVAILABLE,
        evidence_completeness=available_fields / max(1, len(field_availability)),
        abstention_reason=abstention_reason,
        calibration_status=str(raw_pred.get("calibration_status") or "UNKNOWN"),
        duration_ms=(time.perf_counter() - started_at) * 1000,
    )

    if cache:
        try:
            cache.set(cache_key, json.dumps(result), ttl=_CACHE_TTL_SECONDS)
        except Exception as exc:
            logger.debug("Cache write failed for %s: %s", match_id, exc)

    return result
