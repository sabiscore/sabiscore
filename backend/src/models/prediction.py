"""PredictionEngine — canonical manifest-governed inference surface.

DEBT-83 hardening contract
--------------------------
For dictionary/stacked artifacts the served probability domain is explicit:

    base learners -> meta features -> meta_model.predict_proba()
    -> serialized FittedCalibrator -> optional overlay -> PredictionResult

A serialized calibrator is never applied to a different probability domain.
If a meta-model is present but cannot run, or a serialized calibrator cannot be
loaded/applied, the engine fails closed to its diagnostic fallback instead of
substituting an unevaluated probability domain.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np

from ..core.cache import cache_manager
from ..core.config import settings
from ..core.league_policy import LeaguePolicyUnavailableError, get_league_policy
from ..core.redaction import redact_text
from .active_generation import ActiveGenerationError, load_active_generation

_apply_calibrator = None
_CAL_AVAILABLE = False
try:
    from .calibration import apply_calibrator as _apply_calibrator  # type: ignore
    _CAL_AVAILABLE = True
except ImportError:
    pass

_tracer = None
try:
    from opentelemetry import trace as _otel_trace  # type: ignore
    _tracer = _otel_trace.get_tracer(
        "sabiscore.prediction_engine",
        schema_url="https://opentelemetry.io/schemas/1.21.0",
    )
except ImportError:
    pass

logger = logging.getLogger(__name__)
MAX_KELLY_CAP = 0.05


def _kelly_cap_for_league(league: Optional[str]) -> float:
    if not league:
        return MAX_KELLY_CAP
    try:
        return min(get_league_policy(league).kelly_cap, MAX_KELLY_CAP)
    except LeaguePolicyUnavailableError:
        return MAX_KELLY_CAP


_LEAGUE_SLUG: Dict[str, str] = {
    "Premier League": "epl",
    "EPL": "epl",
    "La Liga": "la_liga",
    "LaLiga": "la_liga",
    "Bundesliga": "bundesliga",
    "Serie A": "serie_a",
    "SerieA": "serie_a",
    "Ligue 1": "ligue_1",
    "Ligue1": "ligue_1",
    "Championship": "championship",
    "Eredivisie": "eredivisie",
    "UCL": "ucl",
    "Europa League": "europa_league",
}

_SUFFIXES = [
    "_ensemble_v6_phase8",
    "_ensemble_v5_phase7",
    "_ensemble_v4_optuna",
    "_ensemble",
    "_model",
]

_META_MODEL_CALIBRATION_LABELS: Dict[str, str] = {
    "SoftmaxMetaModel": "none",
    "TemperatureScaledMetaModel": "temperature",
    "VectorScaledMetaModel": "vector",
    "BetaCalibratedMetaModel": "beta",
    "IsotonicMetaModel": "isotonic",
    "CalibratedClassifierCV": "isotonic",
    "LogisticRegression": "sigmoid",
}


@dataclass(frozen=True)
class PredictionResult:
    home_win: float
    draw: float
    away_win: float
    confidence: float
    model_dim: int
    model_version: str
    calibration_method: str
    calibration_applied: bool = False
    overlay_applied: bool = False
    generation: Optional[str] = None
    feature_schema_version: Optional[str] = None
    manifest_sha256: Optional[str] = None
    certification_state: str = "UNVERIFIED"
    artifact_sha256: Optional[str] = None
    coverage: str = "dedicated"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "home_win": self.home_win,
            "draw": self.draw,
            "away_win": self.away_win,
            "confidence": self.confidence,
            "model_dim": self.model_dim,
            "model_version": self.model_version,
            "calibration_method": self.calibration_method,
            "calibration_applied": self.calibration_applied,
            "overlay_applied": self.overlay_applied,
            "generation": self.generation,
            "feature_schema_version": self.feature_schema_version,
            "manifest_sha256": self.manifest_sha256,
            "certification_state": self.certification_state,
            "artifact_sha256": self.artifact_sha256,
            "coverage": self.coverage,
        }


@dataclass
class _ArtifactBundle:
    direct_model: Optional[Any]
    models_dict: Optional[Dict[str, Any]]
    calibrator: Optional[Any]
    overlay: Optional[Any]
    feature_columns: Optional[List[str]]
    meta_model: Optional[Any]
    model_version: str = "unknown"
    generation: Optional[str] = None
    feature_schema_version: Optional[str] = None
    manifest_sha256: Optional[str] = None
    certification_state: str = "UNVERIFIED"
    artifact_sha256: Optional[str] = None
    coverage: str = "dedicated"


class PredictionEngine:
    """Canonical Phase 8 inference engine with DEBT-83 fail-closed provenance."""

    _model_cache: Dict[str, "_ArtifactBundle"] = {}
    _lock = threading.Lock()

    async def predict(
        self,
        features: np.ndarray,
        league: str,
        match_id: Optional[str] = None,
    ) -> PredictionResult:
        cache_key = f"pe:{match_id}:{league}" if match_id else None
        if cache_key:
            cached = cache_manager.get(cache_key)
            if isinstance(cached, dict) and "home_win" in cached:
                try:
                    return PredictionResult(**cached)
                except TypeError:
                    pass

        bundle = await self._load_model(league)
        result = await asyncio.to_thread(self._run_inference, bundle, features, league)
        if cache_key:
            try:
                cache_manager.set(cache_key, result.to_dict(), ttl=300)
            except Exception:
                pass
        return result

    async def get_artifact_bundle(self, league: str) -> Optional["_ArtifactBundle"]:
        return await self._load_model(league)

    async def _load_model(self, league: str) -> Optional["_ArtifactBundle"]:
        slug = _LEAGUE_SLUG.get(league, league.lower().replace(" ", "_"))
        with self._lock:
            if slug in self._model_cache:
                return self._model_cache[slug]
        bundle = await asyncio.to_thread(self._load_from_disk, slug)
        if bundle is not None:
            with self._lock:
                self._model_cache[slug] = bundle
        return bundle

    def _load_from_disk(self, slug: str) -> Optional["_ArtifactBundle"]:
        import joblib
        import pickle

        try:
            generation = load_active_generation()
        except ActiveGenerationError as exc:
            logger.error("PredictionEngine: active generation rejected: %s", redact_text(exc))
            return None

        manifest_entry = generation.get("artifacts", {}).get(slug)
        manifested = manifest_entry.get("artifact_path") if manifest_entry else None
        provenance = {
            "model_version": str(generation.get("active_version") or "unknown"),
            "generation": generation.get("generation"),
            "feature_schema_version": generation.get("feature_schema_version"),
            "manifest_sha256": generation.get("manifest_sha256"),
            "certification_state": str(generation.get("certification_state") or "UNVERIFIED"),
            "artifact_sha256": manifest_entry.get("artifact_sha256") if manifest_entry else None,
            "coverage": "dedicated" if manifest_entry else "generic",
        }

        for directory in (settings.phase7_models_path, settings.models_path):
            if not directory.exists():
                continue
            for suffix in _SUFFIXES:
                for ext in (".pkl", ".joblib"):
                    candidate = directory / f"{slug}{suffix}{ext}"
                    if not candidate.exists():
                        continue
                    if manifested is not None and candidate.resolve() != manifested.resolve():
                        continue
                    try:
                        try:
                            raw = joblib.load(candidate)
                        except Exception:
                            with open(candidate, "rb") as handle:
                                raw = pickle.load(handle)
                        bundle = self._wrap_artifact(raw, slug, candidate, provenance=provenance)
                        if bundle is not None:
                            logger.info("PredictionEngine: loaded %s from %s", slug, candidate)
                            return bundle
                    except Exception as exc:
                        logger.warning("PredictionEngine: failed to load %s: %s", candidate, redact_text(exc))
        logger.warning("PredictionEngine: no model found for league=%r — will use fallback", slug)
        return None

    @staticmethod
    def _wrap_artifact(
        raw: Any,
        slug: str,
        path: Any,
        *,
        provenance: Optional[Dict[str, Any]] = None,
    ) -> Optional["_ArtifactBundle"]:
        if isinstance(raw, dict) and "models" in raw:
            models_dict = raw.get("models")
            if not isinstance(models_dict, dict) or not models_dict:
                logger.warning("PredictionEngine: artifact %s has empty 'models' dict", path)
                return None
            if not any(callable(getattr(m, "predict_proba", None)) for m in models_dict.values()):
                logger.warning("PredictionEngine: no callable predict_proba in 'models' dict at %s", path)
                return None
            return _ArtifactBundle(
                direct_model=None,
                models_dict=models_dict,
                calibrator=raw.get("calibrator"),
                overlay=raw.get("bivariate_poisson_overlay"),
                feature_columns=raw.get("feature_columns"),
                meta_model=raw.get("meta_model"),
                **(provenance or {}),
            )
        if callable(getattr(raw, "predict_proba", None)):
            return _ArtifactBundle(
                direct_model=raw,
                models_dict=None,
                calibrator=None,
                overlay=None,
                feature_columns=None,
                meta_model=None,
                **(provenance or {}),
            )
        return None

    def _run_inference(
        self,
        bundle: Optional["_ArtifactBundle"],
        features: np.ndarray,
        league: str,
    ) -> PredictionResult:
        infer_t0 = time.perf_counter()
        features = np.asarray(features, dtype=np.float32).ravel()
        if bundle is None:
            return self._fallback_result(input_dim=len(features))

        is_dict_artifact = bundle.models_dict is not None
        if is_dict_artifact:
            expected_dim = self._expected_dim_from_bundle(bundle, len(features))
        else:
            model = bundle.direct_model
            expected_dim = getattr(model, "n_features_in_", None)
            if expected_dim is None and hasattr(model, "estimators_"):
                try:
                    expected_dim = model.estimators_[0].n_features_in_
                except Exception:
                    pass
            if expected_dim is None:
                expected_dim = len(features)

        actual_dim = len(features)
        if actual_dim != expected_dim:
            logger.error(
                "PredictionEngine: SCHEMA_MISMATCH — %d features supplied, %s model expects %d; "
                "refusing to pad or truncate live evidence",
                actual_dim,
                league,
                expected_dim,
            )
            return self._fallback_result(input_dim=actual_dim)

        X = features.reshape(1, -1)
        calibration_method = "none"
        calibration_applied = False

        try:
            if is_dict_artifact:
                models_dict = bundle.models_dict
                assert models_dict is not None

                if bundle.meta_model is not None:
                    try:
                        proba = self._stacked_predict(models_dict, bundle.meta_model, X)
                        meta_method = _META_MODEL_CALIBRATION_LABELS.get(
                            type(bundle.meta_model).__name__, "none"
                        )
                        calibration_method = meta_method
                        calibration_applied = meta_method != "none"
                    except Exception as exc:
                        if bundle.calibrator is not None:
                            logger.error(
                                "PredictionEngine: DEBT-83 calibration-domain divergence for %s: "
                                "meta-model failed while a serialized calibrator exists; "
                                "refusing to substitute base-ensemble probabilities: %s",
                                league,
                                redact_text(exc),
                            )
                            return self._fallback_result(input_dim=expected_dim)
                        logger.warning(
                            "PredictionEngine: stacked meta-model failed for %s; "
                            "no serialized calibrator is present, so retaining the legacy "
                            "uncalibrated base-ensemble fallback: %s",
                            league,
                            redact_text(exc),
                        )
                        proba = self._ensemble_predict_dict(models_dict, X)
                else:
                    proba = self._ensemble_predict_dict(models_dict, X)
            else:
                raw = bundle.direct_model.predict_proba(X)[0]
                if len(raw) == 2:
                    proba = np.array([[float(raw[1]), 0.0, float(raw[0])]], dtype=np.float64)
                elif len(raw) >= 3:
                    proba = np.array([[float(raw[0]), float(raw[1]), float(raw[2])]], dtype=np.float64)
                else:
                    return self._fallback_result(input_dim=expected_dim)
        except Exception as exc:
            logger.error("PredictionEngine: inference error for %s: %s", league, redact_text(exc))
            return self._fallback_result(input_dim=expected_dim)

        if not self._valid_probability_matrix(proba):
            logger.error("PredictionEngine: invalid probability simplex for %s; failing closed", league)
            return self._fallback_result(input_dim=expected_dim)

        model_version = bundle.model_version
        overlay_applied = False

        if bundle.calibrator is not None:
            if not _CAL_AVAILABLE or _apply_calibrator is None:
                logger.error(
                    "PredictionEngine: serialized calibrator exists for %s but calibration "
                    "runtime is unavailable; failing closed",
                    league,
                )
                return self._fallback_result(input_dim=expected_dim)

            span_ctx = (
                _tracer.start_as_current_span("sabiscore.calibrator.apply")
                if _tracer
                else nullcontext()
            )
            t0 = time.perf_counter()
            with span_ctx as span:
                try:
                    fitted_cal = bundle.calibrator
                    calibrated = _apply_calibrator(
                        fitted_cal.method,
                        fitted_cal.calibrators,
                        proba,
                    )
                    if not self._valid_probability_matrix(calibrated):
                        raise ValueError("calibrator returned an invalid probability simplex")
                    proba = calibrated
                    calibration_method = str(fitted_cal.method)
                    calibration_applied = True
                    latency_ms = (time.perf_counter() - t0) * 1000
                    if span and hasattr(span, "set_attribute"):
                        span.set_attribute("calibration.method", calibration_method)
                        span.set_attribute("calibration.league", league)
                        span.set_attribute("calibration.ece_after", fitted_cal.ece_after.get("mean", 0.0))
                        span.set_attribute("calibration.latency_ms", round(latency_ms, 2))
                except Exception as exc:
                    logger.error(
                        "PredictionEngine: serialized calibrator failed for %s; failing closed: %s",
                        league,
                        redact_text(exc),
                    )
                    return self._fallback_result(input_dim=expected_dim)

        if bundle.overlay is not None:
            span_ctx = (
                _tracer.start_as_current_span("sabiscore.overlay.bivariate_poisson")
                if _tracer
                else nullcontext()
            )
            with span_ctx as span:
                try:
                    overlay = bundle.overlay
                    if getattr(overlay, "alpha", 0.0) > 0.0:
                        t0 = time.perf_counter()
                        blended = overlay.apply(proba)
                        if not self._valid_probability_matrix(blended):
                            raise ValueError("overlay returned an invalid probability simplex")
                        proba = blended
                        overlay_applied = True
                        latency_ms = (time.perf_counter() - t0) * 1000
                        if span and hasattr(span, "set_attribute"):
                            span.set_attribute("overlay.alpha", float(overlay.alpha))
                            span.set_attribute("overlay.league", league)
                            span.set_attribute("overlay.latency_ms", round(latency_ms, 2))
                except Exception as exc:
                    logger.warning(
                        "PredictionEngine: Bivariate Poisson overlay failed for %s: %s",
                        league,
                        redact_text(exc),
                    )

        h, d, a = float(proba[0, 0]), float(proba[0, 1]), float(proba[0, 2])
        confidence = max(0.0, min(1.0, max(h, d, a) - 0.333))
        logger.debug(
            "PredictionEngine: inference complete league=%s version=%s calibration=%s overlay=%s total_ms=%.2f",
            league,
            model_version,
            calibration_applied,
            overlay_applied,
            (time.perf_counter() - infer_t0) * 1000,
        )

        return PredictionResult(
            home_win=round(h, 4),
            draw=round(d, 4),
            away_win=round(a, 4),
            confidence=round(confidence, 4),
            model_dim=expected_dim,
            model_version=model_version,
            calibration_method=calibration_method if calibration_applied else "raw",
            calibration_applied=calibration_applied,
            overlay_applied=overlay_applied,
            generation=bundle.generation,
            feature_schema_version=bundle.feature_schema_version,
            manifest_sha256=bundle.manifest_sha256,
            certification_state=bundle.certification_state,
            artifact_sha256=bundle.artifact_sha256,
            coverage=bundle.coverage,
        )

    @staticmethod
    def _valid_probability_matrix(probabilities: np.ndarray) -> bool:
        values = np.asarray(probabilities, dtype=np.float64)
        if values.shape != (1, 3) or not np.isfinite(values).all():
            return False
        if np.any(values < 0.0) or np.any(values > 1.0):
            return False
        return bool(np.allclose(values.sum(axis=1), 1.0, atol=1e-6, rtol=0.0))

    @staticmethod
    def _expected_dim_from_bundle(bundle: "_ArtifactBundle", fallback: int) -> int:
        if bundle.feature_columns:
            return len(bundle.feature_columns)
        for model in bundle.models_dict.values():
            dim = getattr(model, "n_features_in_", None)
            if dim is not None:
                return int(dim)
        return fallback

    @staticmethod
    def _ensemble_predict_dict(models_dict: Dict[str, Any], X: np.ndarray) -> np.ndarray:
        all_probs: List[np.ndarray] = []
        for model in models_dict.values():
            try:
                probabilities = np.asarray(model.predict_proba(X), dtype=np.float64)
                if PredictionEngine._valid_probability_matrix(probabilities):
                    all_probs.append(probabilities)
            except Exception:
                pass
        if not all_probs:
            raise ValueError("no base learner returned a valid probability simplex")
        return np.mean(all_probs, axis=0)

    @staticmethod
    def _build_meta_features(models_dict: Dict[str, Any], X: np.ndarray) -> np.ndarray:
        columns: List[np.ndarray] = []
        for model in models_dict.values():
            probabilities = np.asarray(model.predict_proba(X), dtype=np.float64)
            if probabilities.ndim != 2 or probabilities.shape[1] < 3:
                raise ValueError("base learner returned invalid meta-feature probabilities")
            columns.extend(
                [
                    probabilities[:, 0:1],
                    probabilities[:, 1:2],
                    probabilities[:, 2:3],
                ]
            )
        if not columns:
            raise ValueError("no base learner available for meta-feature construction")
        return np.hstack(columns)

    @staticmethod
    def _stacked_predict(models_dict: Dict[str, Any], meta_model: Any, X: np.ndarray) -> np.ndarray:
        meta_features = PredictionEngine._build_meta_features(models_dict, X)
        proba = np.asarray(meta_model.predict_proba(meta_features), dtype=np.float64)
        if proba.ndim == 1:
            proba = proba.reshape(1, -1)
        return proba

    @staticmethod
    def _fallback_result(input_dim: int) -> PredictionResult:
        return PredictionResult(
            home_win=0.333,
            draw=0.333,
            away_win=0.334,
            confidence=0.0,
            model_dim=input_dim,
            model_version="fallback",
            calibration_method="uniform",
            calibration_applied=False,
            overlay_applied=False,
            coverage="fallback",
        )

    @staticmethod
    def calculate_value_bets(
        predictions: Dict[str, float],
        market_odds: Dict[str, float],
        kelly_fraction: float = 0.25,
        min_edge_pct: float = 3.0,
        closing_odds: Optional[Dict[str, float]] = None,
        league: Optional[str] = None,
    ) -> list:
        cap = _kelly_cap_for_league(league)
        bets = []
        for outcome in ("home_win", "draw", "away_win"):
            try:
                pred_prob = predictions.get(outcome, 0.33)
                odds = market_odds.get(outcome, 2.0)
                if not (0 < pred_prob < 1.0) or odds < 1.01:
                    continue
                implied = 1.0 / odds
                edge_pct = (pred_prob - implied) * 100
                if edge_pct < min_edge_pct:
                    continue
                kelly_pct = min((edge_pct / 100 / (odds - 1)) * kelly_fraction, cap)
                ev_cents = (pred_prob * odds - 1.0) * 100
                clv_pct: Optional[float] = None
                if closing_odds is not None:
                    closing = closing_odds.get(outcome)
                    if closing and closing > 1.01:
                        clv_pct = round((pred_prob - 1.0 / closing) * 100, 2)
                bets.append({
                    "outcome": outcome,
                    "edge_pct": round(edge_pct, 2),
                    "kelly_stake_pct": round(kelly_pct * 100, 2),
                    "ev_cents": round(ev_cents, 1),
                    "clv_pct": clv_pct,
                    "recommended_stake_ngn": int(10_000.0 * kelly_pct),
                    "confidence": round(min(1.0, pred_prob / 0.5), 2),
                })
            except Exception as exc:
                logger.warning("Value bet calc error for %s: %s", outcome, redact_text(exc))
        bets.sort(key=lambda item: item["edge_pct"], reverse=True)
        return bets

    @classmethod
    def prime_cache(
        cls,
        league: str,
        model: Any,
        *,
        generation: Optional[Dict[str, Any]] = None,
    ) -> bool:
        slug = _LEAGUE_SLUG.get(league, league.lower().replace(" ", "_"))
        provenance: Optional[Dict[str, Any]] = None
        if generation is not None:
            active_version = str(generation.get("active_version") or "").strip()
            if active_version != "v5_phase7":
                return False
            manifest_entry = generation.get("artifacts", {}).get(slug)
            if not isinstance(manifest_entry, dict):
                return False
            provenance = {
                "model_version": active_version,
                "generation": generation.get("generation"),
                "feature_schema_version": generation.get("feature_schema_version"),
                "manifest_sha256": generation.get("manifest_sha256"),
                "certification_state": str(generation.get("certification_state") or "UNVERIFIED"),
                "artifact_sha256": manifest_entry.get("artifact_sha256"),
                "coverage": "dedicated",
            }

        raw = model
        models_dict = getattr(model, "models", None)
        if not isinstance(model, dict) and isinstance(models_dict, dict) and models_dict:
            raw = {
                "models": dict(models_dict),
                "feature_columns": list(getattr(model, "feature_columns", []) or []),
                "meta_model": getattr(model, "meta_model", None),
                "calibrator": getattr(model, "calibrator", None),
                "bivariate_poisson_overlay": getattr(model, "bivariate_poisson_overlay", None),
            }

        bundle = cls._wrap_artifact(raw, slug, "<startup>", provenance=provenance)
        if bundle is None:
            bundle = _ArtifactBundle(
                direct_model=model if callable(getattr(model, "predict_proba", None)) else None,
                models_dict=None,
                calibrator=None,
                overlay=None,
                feature_columns=None,
                meta_model=None,
                **(provenance or {}),
            )
            if bundle.direct_model is None:
                return False

        with cls._lock:
            cls._model_cache[slug] = bundle
        return True

    @classmethod
    def clear_cache(cls) -> None:
        with cls._lock:
            cls._model_cache.clear()
