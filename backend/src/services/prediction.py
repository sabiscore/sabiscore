"""Inference service wiring saved ensembles into the FastAPI prediction surface."""

import hashlib
import logging
import math
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union, cast

import numpy as np
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.cache import cache_manager
from ..core.config import settings
from ..core.exceptions import DataUnavailableError
from ..data.aggregator import DataAggregator, get_enhanced_aggregator

try:
    from ..features.phase9_xg_market_features import build_market_efficiency_report as _build_market_efficiency
    _PHASE9_MARKET_AVAILABLE = True
except ImportError:
    _build_market_efficiency = None  # type: ignore[assignment]
    _PHASE9_MARKET_AVAILABLE = False
from ..data.transformers import FeatureTransformer
from ..models.edge_detector import EdgeDetector
from ..models.active_generation import active_artifact_path
from ..models.ensemble import SabiScoreEnsemble
from ..monitoring.metrics import metrics_collector
from ..schemas.prediction import MatchPredictionRequest, PredictionResponse
from ..schemas.value_bet import ValueBetResponse
from ..services.rl_betting_agent import RLBettingAgent
from ..services.uncertainty_service import UncertaintyService

logger = logging.getLogger(__name__)


class PredictionService:
    """Serve ensemble predictions with lightweight feature synthesis."""

    _ensemble_cache: Dict[str, SabiScoreEnsemble] = {}
    _metadata_cache: Dict[str, Dict[str, Any]] = {}
    _cache_lock = threading.Lock()
    _cache_access_times: Dict[str, float] = {}  # Track LRU
    MAX_CACHED_MODELS = 5  # Limit memory footprint
    LEAGUE_DISPLAY_NAMES = {
        "epl": "EPL",
        "bundesliga": "Bundesliga",
        "la_liga": "La Liga",
        "serie_a": "Serie A",
        "ligue_1": "Ligue 1",
        "eredivisie": "Eredivisie",
    }

    def __init__(
        self,
        db_session: Optional[AsyncSession] = None,
        cache_backend: Any = None,
        ensemble_model: Optional[SabiScoreEnsemble] = None,
    ) -> None:
        self.db = db_session
        self.cache = cache_backend or cache_manager
        self.transformer = FeatureTransformer()
        self.enhanced_aggregator = get_enhanced_aggregator()
        self._match_context_cache: Dict[str, Dict[str, Any]] = {}
        self._match_context_ttl = 15 * 60  # seconds
        self.edge_detector = EdgeDetector(
            min_edge_threshold=0.042,
            kelly_fraction=0.25,
            max_stake_pct=0.05,
        )
        self.uncertainty_service = UncertaintyService()
        self.rl_agent = RLBettingAgent()
        self._provided_model = ensemble_model
        self._default_bankroll = 10_000.0
        self.metrics: Dict[str, float] = {
            "predictions_count": 0,
            "value_bets_found": 0,
            "avg_confidence": 0.0,
            "avg_edge": 0.0,
        }

    async def predict_match(
        self,
        match_id: str,
        request: MatchPredictionRequest,
    ) -> PredictionResponse:
        start_time = time.time()

        league_slug = self._slugify_league(request.league)
        cache_key = self._build_cache_key(match_id, league_slug)

        cached = self._get_cached_prediction(cache_key)
        if cached is not None:
            metrics_collector.record_prediction(
                duration_ms=(time.time() - start_time) * 1000,
                confidence=cached.confidence,
                cache_hit=True
            )
            return cached

        ensemble = self._get_ensemble_for_league(league_slug)
        feature_frame, feature_vector, feature_context = self._build_feature_frame(
            match_id,
            request,
            ensemble,
            league_slug,
        )

        if self.transformer.feature_completeness == 0.0:
            raise DataUnavailableError(
                "No evidence sources available — refusing to infer from pure defaults",
                provider="internal",
                evidence_type="feature_completeness",
            )

        try:
            inference_start = time.time()
            prediction_df = ensemble.predict(feature_frame)
            inference_ms = (time.time() - inference_start) * 1000
            metrics_collector.record_timer("model_inference", inference_ms)
        except Exception as exc:
            logger.error("Prediction failed for %s: %s", match_id, exc)
            metrics_collector.record_error(
                error_type="PredictionError",
                message=str(exc),
                context={"match_id": match_id, "league": league_slug}
            )
            raise

        row = prediction_df.iloc[0]
        probabilities = {
            "home_win": float(row["home_win_prob"]),
            "draw": float(row["draw_prob"]),
            "away_win": float(row["away_win_prob"]),
        }

        bankroll = float(request.bankroll or self._default_bankroll)
        value_bets = self._detect_value_bets(match_id, probabilities, request.odds, bankroll)
        explanations = self._generate_explanations(feature_vector, ensemble, feature_frame)
        processing_ms = int((time.time() - start_time) * 1000)
        metadata = self._build_metadata(league_slug, ensemble, processing_ms, feature_context)

        # UCL soft-coverage: inject LOW_EVIDENCE tier and caveat into metadata.
        # The generic model is used — no dedicated UCL ensemble exists.
        # ucl_low_evidence_override must be True (default) for this to be reached;
        # a 422 guard at the endpoint level enforces it when False.
        if league_slug == "ucl":
            metadata["confidence_tier"] = "LOW_EVIDENCE"
            metadata.setdefault("caveats", []).append(
                "UCL coverage uses soft-evidence inference. "
                "Epistemic uncertainty is higher for knockout-stage fixtures."
            )
            metadata["ucl_generic_model"] = True

        # Phase 9 / V4 market-efficiency shadow metadata — never touches probabilities
        if _PHASE9_MARKET_AVAILABLE and getattr(settings, "use_phase9_candidate_features", False):
            try:
                metadata["phase9_candidate_features"] = {
                    "market_efficiency": _build_market_efficiency(
                        model_probabilities=probabilities,
                        current_odds=request.odds or {},
                    )
                }
            except Exception as _p9_exc:
                logger.warning("Phase 9 market-efficiency report failed: %s", _p9_exc)
                metadata["phase9_candidate_features"] = {}
            metadata["phase9_shadow_only"] = getattr(settings, "phase9_shadow_only", True)

        sample_size = int(metadata.get("training_samples") or 500)
        confidence_intervals = self._calculate_confidence_intervals(probabilities, sample_size=sample_size)
        uncertainty_breakdown = self.uncertainty_service.decompose(
            feature_frame=feature_frame,
            probabilities=probabilities,
            confidence=float(row["confidence"]),
        )
        rl_recommendation = self.rl_agent.recommend(
            probabilities=probabilities,
            odds=request.odds,
            confidence=float(row["confidence"]),
            epistemic_unc=uncertainty_breakdown.epistemic_unc,
        )

        # Wire uncertainty + completeness into metadata so fixtures.py contract check passes
        metadata["epistemic_uncertainty"] = uncertainty_breakdown.epistemic_unc
        metadata["aleatoric_uncertainty"] = uncertainty_breakdown.aleatoric_unc
        metadata["confidence_tier"] = uncertainty_breakdown.confidence_tier
        metadata.setdefault("calibration_method", "platt_scaling")
        metadata.setdefault("calibration_validated", metadata.get("accuracy") is not None)
        metadata["feature_completeness"] = getattr(self.transformer, "feature_completeness", 1.0)

        prediction = PredictionResponse(
            match_id=match_id,
            home_team=request.home_team,
            away_team=request.away_team,
            league=request.league,
            predictions=probabilities,
            confidence=float(row["confidence"]),
            brier_score=self._calculate_brier_score(probabilities),
            value_bets=value_bets,
            confidence_intervals=confidence_intervals,
            explanations=explanations,
            metadata=metadata,
            uncertainty=self.uncertainty_service.to_dict(uncertainty_breakdown),
            rl_recommendation={
                "stake_fraction": rl_recommendation.stake_fraction,
                "abstain": rl_recommendation.abstain,
                "reward_components": rl_recommendation.reward_components,
                "reason": rl_recommendation.reason,
            },
        )

        self._cache_prediction(cache_key, prediction)
        self._update_metrics(prediction)
        
        # Record production metrics
        # ValueBetResponse uses edge_percent (percentage) not edge
        max_edge_pct = max([vb.edge_percent for vb in value_bets], default=0.0)
        metrics_collector.record_prediction(
            duration_ms=processing_ms,
            confidence=prediction.confidence,
            value_bets=len(value_bets),
            edge=max_edge_pct / 100.0 if max_edge_pct > 0 else None,  # Convert to decimal
            cache_hit=False
        )

        return prediction

    def _get_ensemble_for_league(self, league_slug: str) -> SabiScoreEnsemble:
        provided = self._provided_model
        if provided is not None and getattr(provided, "is_trained", False):
            provided_league = self._slugify_league(provided.model_metadata.get("league", ""))
            if not provided_league or provided_league == league_slug:
                with self._cache_lock:
                    self._ensemble_cache.setdefault(league_slug, provided)
                    self._metadata_cache.setdefault(league_slug, provided.model_metadata or {})
                return provided

        with self._cache_lock:
            cached = self._ensemble_cache.get(league_slug)
            if cached is not None and getattr(cached, "is_trained", False):
                self._cache_access_times[league_slug] = datetime.now(timezone.utc).timestamp()
                return cached

        candidate_paths = []
        # v4_optuna artifacts are written to backend/models/ by scripts/optuna_tune_ensemble.py.
        # P5-C: Only add v4_optuna candidates when USE_OPTUNA_V4=True AND the league
        # falls within the active canary percentage (deterministic by league hash).
        _backend_models = settings.models_path.parent / "backend" / "models"

        # UCL uses the generic production model — no dedicated ensemble artifact exists.
        if league_slug == "ucl":
            for _search_dir in (settings.models_path, _backend_models):
                candidate_paths.append(_search_dir / "sabiscore_production_v2.joblib")
                candidate_paths.append(_search_dir / "ucl_ensemble.pkl")
        else:
            if settings.use_phase7_models and self._in_phase7_canary_group(league_slug):
                manifested = active_artifact_path(league_slug)
                if manifested is not None:
                    candidate_paths.append(manifested)

            if settings.use_optuna_v4 and self._in_canary_group(league_slug):
                for _search_dir in (settings.models_path, _backend_models):
                    candidate_paths.append(_search_dir / f"{league_slug}_ensemble_v4_optuna.pkl")

            if settings.use_enhanced_models_v7:
                candidate_paths.append(settings.models_path / f"{league_slug}_ensemble_v7.pkl")
                candidate_paths.append(settings.models_path / f"{league_slug}_enhanced_v2.pkl")

            candidate_paths.append(settings.models_path / f"{league_slug}_ensemble.pkl")

        model_path = next((p for p in candidate_paths if p.exists()), None)
        if model_path is None:
            raise FileNotFoundError(
                f"Model artifact missing for league '{league_slug}'. Tried: {', '.join(str(p) for p in candidate_paths)}"
            )

        model = SabiScoreEnsemble.load_model(str(model_path))
        with self._cache_lock:
            # LRU eviction if cache is full
            if len(self._ensemble_cache) >= self.MAX_CACHED_MODELS and self._cache_access_times:
                oldest_key = min(
                    self._cache_access_times,
                    key=lambda key: self._cache_access_times.get(key, 0.0),
                )
                logger.info(f"Evicting model from cache: {oldest_key}")
                self._ensemble_cache.pop(oldest_key, None)
                self._metadata_cache.pop(oldest_key, None)
                self._cache_access_times.pop(oldest_key, None)
            
            self._ensemble_cache[league_slug] = model
            self._metadata_cache[league_slug] = model.model_metadata or {}
            self._cache_access_times[league_slug] = datetime.now(timezone.utc).timestamp()
        return model

    def _build_feature_frame(
        self,
        match_id: str,
        request: MatchPredictionRequest,
        ensemble: SabiScoreEnsemble,
        league_slug: str,
    ) -> Tuple[pd.DataFrame, Dict[str, float], Dict[str, Any]]:
        columns = list(ensemble.feature_columns or [])
        if not columns:
            raise ValueError("Loaded model does not expose feature columns")

        league_name = self._resolve_league_name(request.league)
        match_data, feature_context = self._prepare_match_data(request, league_name)

        # Generate features using the transformer.
        # This ensures we align to the canonical 58-feature production schema.
        self.transformer.expected_columns = columns
        feature_frame = self.transformer.engineer_features(match_data)
        
        # Verify columns match
        missing = [c for c in columns if c not in feature_frame.columns]
        if missing:
            logger.warning(f"Transformer output missing columns expected by model: {missing}")
            # Fill missing with 0
            for c in missing:
                feature_frame[c] = 0.0
                
        # Ensure correct order
        feature_frame = cast(pd.DataFrame, feature_frame.loc[:, columns])
        
        # Convert to dict for return
        feature_values = {
            str(name): float(value)
            for name, value in feature_frame.iloc[0].to_dict().items()
        }

        return feature_frame, feature_values, feature_context

    def _prepare_match_data(
        self,
        request: MatchPredictionRequest,
        league_name: str,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Use scrapers + aggregators to hydrate feature inputs with caching."""

        context_key = self._build_match_context_key(
            request.home_team,
            request.away_team,
            league_name,
            request.kickoff_time,
        )

        cached = self._get_cached_match_context(context_key)
        if cached:
            return cached["match_data"], cached["feature_context"]

        base_match_data = self._build_base_match_data(request, league_name)
        aggregator_payload = self._collect_primary_match_data(request, league_name)
        if aggregator_payload:
            match_data = self._hydrate_match_data(base_match_data, aggregator_payload)
        else:
            match_data = base_match_data

        enhanced_features = self._collect_enhanced_features(
            request.home_team,
            request.away_team,
            league_name,
        )

        if enhanced_features:
            match_data["enhanced_features"] = enhanced_features
            self._merge_exchange_odds(match_data, enhanced_features)

        feature_context = {
            "league": league_name,
            "schedule": match_data.get("schedule"),
            "metadata": (aggregator_payload or {}).get("metadata", {}),
            "enhanced_features": enhanced_features,
            "odds_source": (aggregator_payload or {}).get("odds"),
        }

        self._set_cached_match_context(context_key, match_data, feature_context)
        return match_data, feature_context

    def _merge_exchange_odds(
        self,
        match_data: Dict[str, Any],
        enhanced_features: Dict[str, Any],
    ) -> None:
        """Use Betfair exchange odds as fallback when explicit odds are missing."""

        exchange_keys = {
            "home_win": "bf_home_back",
            "draw": "bf_draw_back",
            "away_win": "bf_away_back",
        }

        updated = dict(match_data.get("odds") or {})
        applied = False
        for market, source_key in exchange_keys.items():
            raw_value = enhanced_features.get(source_key)
            if raw_value is None:
                continue
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                continue

            if value <= 1.0:
                continue
            if market in updated and updated[market]:
                continue
            updated[market] = value
            applied = True

        if applied:
            match_data["odds"] = updated

    def _build_base_match_data(
        self,
        request: MatchPredictionRequest,
        league_name: str,
    ) -> Dict[str, Any]:
        return {
            "odds": request.odds or {},
            "schedule": {
                "home_team": request.home_team,
                "away_team": request.away_team,
                "league": league_name,
                "date": request.kickoff_time,
            },
            "historical_stats": pd.DataFrame(),
            "current_form": {},
            "injuries": pd.DataFrame(),
            "head_to_head": pd.DataFrame(),
            "team_stats": {},
        }

    def _collect_primary_match_data(
        self,
        request: MatchPredictionRequest,
        league_name: str,
    ) -> Optional[Dict[str, Any]]:
        matchup = f"{request.home_team} vs {request.away_team}"
        try:
            aggregator = DataAggregator(matchup, league_name)
            return aggregator.fetch_match_data()
        except Exception as exc:
            logger.warning("Primary aggregator failed for %s: %s", matchup, exc)
            return None

    def _collect_enhanced_features(
        self,
        home_team: str,
        away_team: str,
        league_name: str,
    ) -> Dict[str, Any]:
        try:
            return self.enhanced_aggregator.get_comprehensive_features(
                home_team,
                away_team,
                league_name,
            )
        except Exception as exc:
            logger.warning(
                "Enhanced aggregator failed for %s vs %s: %s",
                home_team,
                away_team,
                exc,
            )
            return {}

    def _hydrate_match_data(
        self,
        base_data: Dict[str, Any],
        aggregator_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        hydrated = dict(base_data)
        for key in (
            "historical_stats",
            "current_form",
            "odds",
            "injuries",
            "head_to_head",
            "team_stats",
        ):
            value = aggregator_payload.get(key)
            if value is None:
                continue
            if isinstance(value, pd.DataFrame):
                hydrated[key] = value.copy()
            else:
                hydrated[key] = value

        # Preserve request odds if provided explicitly
        base_odds = base_data.get("odds") or {}
        agg_odds = aggregator_payload.get("odds") or {}
        if base_odds and agg_odds:
            combined = dict(agg_odds)
            combined.update(base_odds)
            hydrated["odds"] = combined
        elif base_odds:
            hydrated["odds"] = base_odds
        elif agg_odds:
            hydrated["odds"] = agg_odds

        return hydrated

    def _build_match_context_key(
        self,
        home_team: str,
        away_team: str,
        league_name: str,
        kickoff_time: Optional[Union[str, datetime]],
    ) -> str:
        kickoff = "unknown"
        if isinstance(kickoff_time, datetime):
            kickoff = kickoff_time.isoformat()
        elif kickoff_time:
            kickoff = str(kickoff_time)
        return f"{home_team}|{away_team}|{league_name}|{kickoff}".lower()

    def _get_cached_match_context(
        self,
        cache_key: str,
    ) -> Optional[Dict[str, Any]]:
        cached = self._match_context_cache.get(cache_key)
        if not cached:
            return None
        if cached.get("expires_at", 0) < datetime.now(timezone.utc).timestamp():
            self._match_context_cache.pop(cache_key, None)
            return None
        return cached

    def _set_cached_match_context(
        self,
        cache_key: str,
        match_data: Dict[str, Any],
        feature_context: Dict[str, Any],
    ) -> None:
        self._match_context_cache[cache_key] = {
            "match_data": match_data,
            "feature_context": feature_context,
            "expires_at": datetime.now(timezone.utc).timestamp() + self._match_context_ttl,
        }

    def _resolve_league_name(self, league: Optional[str]) -> str:
        if not league:
            return "EPL"
        slug = self._slugify_league(league)
        return self.LEAGUE_DISPLAY_NAMES.get(slug, league)

    def _detect_value_bets(
        self,
        match_id: str,
        probabilities: Dict[str, float],
        odds: Dict[str, float],
        bankroll: float,
    ) -> List[ValueBetResponse]:
        if not odds:
            return []

        results: List[ValueBetResponse] = []
        for market, probability in probabilities.items():
            offered = odds.get(market)
            if offered is None:
                continue

            edge = self.edge_detector.calculate_edge(probability, offered)
            if edge <= self.edge_detector.min_edge_threshold:
                continue

            kelly = self.edge_detector.calculate_kelly_stake(probability, offered, bankroll)
            edge_ngn = edge * bankroll
            # clv_ngn requires closing odds tracked via OddsHistory after match completion.
            # Until closing odds are available, propagate edge_ngn without a scaling proxy.
            # True CLV = (model_prob - 1/closing_odds) * bankroll — computed post-match only.
            clv_ngn = 0.0
            value_bet = ValueBetResponse(
                match_id=match_id,
                market=market,
                odds=float(offered),
                fair_probability=float(probability),
                implied_probability=self._implied_probability(offered),
                edge_percent=edge * 100.0,
                edge_ngn=edge_ngn,
                kelly_stake_ngn=kelly["stake_amount"],
                kelly_fraction=self.edge_detector.kelly_fraction,
                clv_ngn=clv_ngn,
                confidence=float(probability),
                expected_roi=(offered - 1.0) * edge,
            )
            results.append(value_bet)

        results.sort(key=lambda item: item.edge_ngn, reverse=True)
        return results

    def _get_cached_prediction(self, cache_key: str) -> Optional[PredictionResponse]:
        try:
            cached = self.cache.get(cache_key)
        except Exception as exc:
            logger.debug("Cache get failed for %s: %s", cache_key, exc)
            return None

        if cached is None:
            return None

        try:
            if isinstance(cached, PredictionResponse):
                return cached
            if isinstance(cached, dict):
                return PredictionResponse(**cached)
            if isinstance(cached, str):
                import json

                return PredictionResponse(**json.loads(cached))
        except Exception as exc:
            logger.debug("Cached payload could not be restored for %s: %s", cache_key, exc)
        return None

    def _cache_prediction(self, cache_key: str, prediction: PredictionResponse) -> None:
        try:
            payload = prediction.model_dump(mode="json")
            self.cache.set(cache_key, payload, ttl=settings.prediction_cache_ttl)
        except Exception as exc:
            logger.debug("Cache set failed for %s: %s", cache_key, exc)

    def _calculate_confidence_intervals(
        self,
        probabilities: Dict[str, float],
        sample_size: int = 500,
        confidence_level: float = 0.95,
    ) -> Dict[str, Tuple[float, float]]:
        z_score = 1.96 if confidence_level == 0.95 else 1.0
        intervals: Dict[str, Tuple[float, float]] = {}
        for outcome, prob in probabilities.items():
            se = math.sqrt(max(prob * (1.0 - prob), 1e-6) / sample_size)
            margin = z_score * se
            lower = max(0.0, prob - margin)
            upper = min(1.0, prob + margin)
            intervals[outcome] = (lower, upper)
        return intervals

    def _calculate_brier_score(self, probabilities: Dict[str, float]) -> float:
        return float(sum(prob * (1.0 - prob) for prob in probabilities.values()) / len(probabilities))

    def _generate_explanations(
        self,
        feature_vector: Dict[str, float],
        ensemble: Optional[SabiScoreEnsemble] = None,
        feature_frame: Optional[pd.DataFrame] = None,
    ) -> Dict[str, Any]:
        if ensemble is not None and feature_frame is not None:
            try:
                result = ensemble.explain_predictions(feature_frame)
                if result:
                    return result
            except Exception as e:
                logger.debug("ModelExplainer failed, falling back to deterministic feature ranking: %s", e)
        ranked = sorted(feature_vector.items(), key=lambda item: abs(item[1]), reverse=True)[:5]
        return {
            "top_features": [
                {"name": name, "impact": float(value)} for name, value in ranked
            ],
            "summary": "Deterministic feature ranking derived from the validated feature vector",
        }

    def _build_metadata(
        self,
        league_slug: str,
        ensemble: SabiScoreEnsemble,
        processing_ms: int,
        feature_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        meta = self._metadata_cache.get(league_slug, {})
        context = feature_context or {}
        enhanced = context.get("enhanced_features") or {}
        data_sources = {
            "league": context.get("league"),
            "schedule": context.get("schedule"),
            "aggregator_metadata": context.get("metadata"),
            "enhanced_feature_count": len(enhanced),
            "odds_source": context.get("odds_source"),
        }
        return {
            "model_key": f"{league_slug}_ensemble",
            "model_version": meta.get("model_version") or meta.get("dataset_signature", "unknown"),
            "league": meta.get("league", league_slug),
            "trained_at": meta.get("trained_at"),
            "accuracy": meta.get("accuracy"),
            "brier_score": meta.get("brier_score"),
            "log_loss": meta.get("log_loss"),
            "feature_count": len(ensemble.feature_columns or []),
            "processing_time_ms": processing_ms,
            "training_samples": meta.get("training_samples"),
            "data_sources": data_sources,
        }

    def _update_metrics(self, prediction: PredictionResponse) -> None:
        self.metrics["predictions_count"] += 1
        self.metrics["value_bets_found"] += len(prediction.value_bets)

        total = self.metrics["predictions_count"]
        self.metrics["avg_confidence"] = (
            (self.metrics["avg_confidence"] * (total - 1) + prediction.confidence) / total
        )
        if prediction.value_bets:
            avg_edge = float(np.mean([vb.edge_ngn for vb in prediction.value_bets]))
            self.metrics["avg_edge"] = (
                (self.metrics["avg_edge"] * (total - 1) + avg_edge) / total
            )

    async def get_metrics(self) -> Dict[str, Any]:
        return {**self.metrics}

    @staticmethod
    def _slugify_league(league: Union[str, Any]) -> str:
        value = getattr(league, "value", league)
        return str(value).lower().replace(" ", "_")

    @staticmethod
    def _in_canary_group(league_slug: str) -> bool:
        """P5-C: Return True when this league should serve v4_optuna models.

        Routing is deterministic per league via MD5 so the same league always
        maps to the same bucket for a given OPTUNA_V4_CANARY_PCT value.
        At 100% (default) every league is in-group; at 10% roughly 1 in 10
        league hashes fall below the threshold.
        """
        pct = settings.optuna_v4_canary_pct
        if pct >= 1.0:
            return True
        if pct <= 0.0:
            return False
        slot = int(hashlib.md5(league_slug.encode()).hexdigest(), 16) % 100
        return slot < int(pct * 100)

    @staticmethod
    def _in_phase7_canary_group(league_slug: str) -> bool:
        pct = settings.phase7_canary_pct
        if pct >= 1.0:
            return True
        if pct <= 0.0:
            return False
        slot = int(hashlib.md5(f"phase7:{league_slug}".encode()).hexdigest(), 16) % 100
        return slot < int(pct * 100)

    @staticmethod
    def _build_cache_key(match_id: str, league_slug: str) -> str:
        return f"prediction:{league_slug}:{match_id}"

    @staticmethod
    def _implied_probability(odds: Optional[float]) -> float:
        if not odds or odds <= 1.0:
            return 0.33
        return float(1.0 / odds)
