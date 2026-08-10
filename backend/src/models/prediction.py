"""PredictionEngine — canonical 86-dim inference surface for Phase 8.

Replaces the deprecated ``PredictionService`` in
``backend/src/services/prediction_service.py`` which hard-truncated feature
vectors to 58 dimensions.  All new callers should use this module.

Feature-dimension policy
------------------------
Trained models may expect 58, 65, or 86 features depending on the artifact
version.  ``PredictionEngine`` queries the model's ``n_features_in_`` attribute
(sklearn convention) and automatically pads or truncates the caller-supplied
vector to match.  A warning is emitted when truncation is needed so that a
future retraining on the full 86-dim set is visible in logs.

Phase D — Calibration integration
----------------------------------
v6_phase8 artifacts are dicts containing:
  - ``models``: dict of named base learners (RF, XGB, LGBM, optional CatBoost)
  - ``calibrator``: ``FittedCalibrator`` from ``calibration.py``
  - ``bivariate_poisson_overlay``: ``BivariatePoissonDrawOverlay``
  - ``feature_columns``: list of canonical feature names used during training

When these are present, ``_run_inference`` applies them after raw ensemble
prediction.  The calibration module is soft-imported so startup succeeds on
environments where scipy is absent.
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

# ── Soft import: calibration module (requires scipy / sklearn) ─────────────────
_apply_calibrator = None
_CAL_AVAILABLE = False
try:
    from .calibration import apply_calibrator as _apply_calibrator  # type: ignore
    _CAL_AVAILABLE = True
except ImportError:
    pass

# ── Soft import: OpenTelemetry tracing (Phase G) ───────────────────────────────
_tracer = None
try:
    from opentelemetry import trace as _otel_trace  # type: ignore
    _tracer = _otel_trace.get_tracer("sabiscore.prediction_engine", schema_url="https://opentelemetry.io/schemas/1.21.0")
except ImportError:
    pass

logger = logging.getLogger(__name__)

# Hard ceiling on any single recommended stake, independent literal by this
# codebase's own established convention (see insights/engine.py, betting_intelligence.py,
# core_engine.py — all currently 0.05, never a shared import).
MAX_KELLY_CAP = 0.05


def _kelly_cap_for_league(league: Optional[str]) -> float:
    """Per-league Kelly ceiling, defaulting to the conservative global cap.
    Mirrors insights/engine.py's _league_kelly_cap exactly."""
    if not league:
        return MAX_KELLY_CAP
    try:
        return min(get_league_policy(league).kelly_cap, MAX_KELLY_CAP)
    except LeaguePolicyUnavailableError:
        return MAX_KELLY_CAP


# ── League name → model file slug ─────────────────────────────────────────────

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


# ── Result type ────────────────────────────────────────────────────────────────

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
        }


@dataclass
class _ArtifactBundle:
    """Internal holder for a loaded v6_phase8 artifact or older direct model."""
    direct_model: Optional[Any]           # v5 and earlier: sklearn model with predict_proba
    models_dict: Optional[Dict[str, Any]] # v6: dict of named base learners
    calibrator: Optional[Any]             # FittedCalibrator | None
    overlay: Optional[Any]                # BivariatePoissonDrawOverlay | None
    feature_columns: Optional[List[str]]  # canonical feature list from artifact


# ── Engine ─────────────────────────────────────────────────────────────────────

class PredictionEngine:
    """Canonical Phase 8 inference engine.

    Thread-safe; model artifacts are cached in a class-level dict so a single
    load is shared across all instances (same pattern as the legacy
    ``PredictionService``).

    Usage::

        engine = PredictionEngine()
        result = await engine.predict(features=live_vector, league="EPL")
        probs = result.home_win, result.draw, result.away_win
    """

    _model_cache: Dict[str, "_ArtifactBundle"] = {}
    _lock = threading.Lock()

    # ── Public API ─────────────────────────────────────────────────────────────

    async def predict(
        self,
        features: np.ndarray,
        league: str,
        match_id: Optional[str] = None,
    ) -> PredictionResult:
        """Return calibrated outcome probabilities.

        Parameters
        ----------
        features:
            Live feature vector.  May be 58, 65, or 86 dimensions — the engine
            aligns to the model's actual ``n_features_in_`` automatically.
        league:
            League name (e.g. ``"EPL"``, ``"Premier League"``).
        match_id:
            Optional identifier used for prediction-level Redis cache.
        """
        cache_key = f"pe:{match_id}:{league}" if match_id else None
        if cache_key:
            cached = cache_manager.get(cache_key)
            if isinstance(cached, dict) and "home_win" in cached:
                try:
                    return PredictionResult(**cached)
                except TypeError:
                    pass  # cached dict missing new fields — re-run inference

        bundle = await self._load_model(league)
        result = await asyncio.to_thread(self._run_inference, bundle, features, league)

        if cache_key:
            try:
                cache_manager.set(cache_key, result.to_dict(), ttl=300)
            except Exception:
                pass

        return result

    # ── Model loading ──────────────────────────────────────────────────────────

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

        search_dirs = [settings.phase7_models_path, settings.models_path]
        for directory in search_dirs:
            if not directory.exists():
                continue
            for suffix in _SUFFIXES:
                for ext in (".pkl", ".joblib"):
                    candidate = directory / f"{slug}{suffix}{ext}"
                    if candidate.exists():
                        try:
                            # joblib.load first for BOTH extensions. Every committed
                            # artifact is joblib-serialised regardless of whether it
                            # is named .pkl or .joblib, and plain pickle.load cannot
                            # read one — it misreads the payload and raises
                            # "No module named 'random_forest'". Selecting the reader
                            # by file extension therefore failed to load every single
                            # .pkl artifact, so `bundle` was always None and every
                            # inference returned model_version="fallback" on every
                            # league. joblib.load also reads plain pickles, so the
                            # pickle path below is only a defensive fallback.
                            try:
                                raw = joblib.load(candidate)
                            except Exception:
                                with open(candidate, "rb") as handle:
                                    raw = pickle.load(handle)
                            bundle = self._wrap_artifact(raw, slug, candidate)
                            if bundle is not None:
                                logger.info("PredictionEngine: loaded %s from %s", slug, candidate)
                                return bundle
                        except Exception as exc:
                            logger.warning("PredictionEngine: failed to load %s: %s", candidate, exc)
        logger.warning("PredictionEngine: no model found for league=%r — will use fallback", slug)
        return None

    @staticmethod
    def _wrap_artifact(raw: Any, slug: str, path: Any) -> Optional["_ArtifactBundle"]:
        """Normalise a loaded artifact into an _ArtifactBundle.

        Handles two artifact shapes:
        - v6_phase8 dict: has ``models`` key (dict of named base learners)
        - v5 and earlier: direct sklearn model with ``predict_proba``
        """
        if isinstance(raw, dict) and "models" in raw:
            models_dict = raw.get("models")
            if not isinstance(models_dict, dict) or not models_dict:
                logger.warning("PredictionEngine: artifact %s has empty 'models' dict", path)
                return None
            # Verify at least one base learner is callable
            if not any(callable(getattr(m, "predict_proba", None)) for m in models_dict.values()):
                logger.warning("PredictionEngine: no callable predict_proba in 'models' dict at %s", path)
                return None
            return _ArtifactBundle(
                direct_model=None,
                models_dict=models_dict,
                calibrator=raw.get("calibrator"),
                overlay=raw.get("bivariate_poisson_overlay"),
                feature_columns=raw.get("feature_columns"),
            )
        if callable(getattr(raw, "predict_proba", None)):
            return _ArtifactBundle(
                direct_model=raw,
                models_dict=None,
                calibrator=None,
                overlay=None,
                feature_columns=None,
            )
        return None

    # ── Inference ──────────────────────────────────────────────────────────────

    def _run_inference(
        self,
        bundle: Optional["_ArtifactBundle"],
        features: np.ndarray,
        league: str,
    ) -> PredictionResult:
        _infer_t0 = time.perf_counter()
        features = np.asarray(features, dtype=np.float32).ravel()

        if bundle is None:
            return self._fallback_result(input_dim=len(features))

        is_dict_artifact = bundle.models_dict is not None

        # ── Determine expected feature width ───────────────────────────────
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

        # ── Align feature vector ───────────────────────────────────────────
        actual_dim = len(features)
        if actual_dim < expected_dim:
            # A narrower vector than the model expects means real feature slots
            # would be zero-filled — fabricating signal the model was trained to
            # receive, not just carrying forward an older-but-valid subset (that's
            # the truncation branch below, which stays as-is). Fail closed via the
            # same _fallback_result() this function already uses for "no bundle" /
            # "inference raised" — model_version="fallback" is the established,
            # already-checked signal (full_analysis.py, upcoming_match_service.py)
            # that a result is diagnostic-only, not a real prediction.
            logger.error(
                "PredictionEngine: SCHEMA_MISMATCH — %d features supplied, %s model expects %d; "
                "refusing to zero-pad the missing %d values into a live prediction",
                actual_dim, league, expected_dim, expected_dim - actual_dim,
            )
            return self._fallback_result(input_dim=actual_dim)
        elif actual_dim > expected_dim:
            features = features[:expected_dim]
            logger.warning(
                "PredictionEngine: truncated %d → %d for %s (retrain recommended)",
                actual_dim, expected_dim, league,
            )

        X = features.reshape(1, -1)

        # ── Raw ensemble prediction ────────────────────────────────────────
        try:
            if is_dict_artifact:
                proba = self._ensemble_predict_dict(bundle.models_dict, X)
            else:
                raw = bundle.direct_model.predict_proba(X)[0]
                if len(raw) == 2:
                    proba = np.array([[float(raw[1]), 0.0, float(raw[0])]], dtype=np.float64)
                elif len(raw) >= 3:
                    proba = np.array([[float(raw[0]), float(raw[1]), float(raw[2])]], dtype=np.float64)
                else:
                    return self._fallback_result(input_dim=expected_dim)
        except Exception as exc:
            logger.error(
                "PredictionEngine: inference error for %s: %s",
                league,
                redact_text(exc),
            )
            return self._fallback_result(input_dim=expected_dim)

        if not self._valid_probability_matrix(proba):
            logger.error(
                "PredictionEngine: invalid probability simplex for %s; failing closed",
                league,
            )
            return self._fallback_result(input_dim=expected_dim)

        model_version = "v6_phase8" if is_dict_artifact else "v5_phase7"
        calibration_method = "none"
        calibration_applied = False
        overlay_applied = False

        # ── Phase D+G: apply FittedCalibrator with OTel span ──────────────
        if _CAL_AVAILABLE and bundle.calibrator is not None:
            _span_ctx = (
                _tracer.start_as_current_span("sabiscore.calibrator.apply")
                if _tracer else nullcontext()
            )
            _t0 = time.perf_counter()
            with _span_ctx as _span:
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
                    _latency_ms = (time.perf_counter() - _t0) * 1000
                    if _span and hasattr(_span, "set_attribute"):
                        _span.set_attribute("calibration.method", calibration_method)
                        _span.set_attribute("calibration.league", league)
                        _span.set_attribute("calibration.ece_after", fitted_cal.ece_after.get("mean", 0.0))
                        _span.set_attribute("calibration.latency_ms", round(_latency_ms, 2))
                    logger.debug(
                        "PredictionEngine: calibrator applied method=%s league=%s "
                        "ece_after=%.4f latency_ms=%.2f",
                        calibration_method, league,
                        fitted_cal.ece_after.get("mean", 0.0), _latency_ms,
                    )
                except Exception as exc:
                    logger.warning(
                        "PredictionEngine: calibration failed for %s: %s",
                        league,
                        redact_text(exc),
                    )
        elif is_dict_artifact and not _CAL_AVAILABLE:
            logger.debug("PredictionEngine: calibration skipped — calibration module unavailable")

        # ── Phase D+G: apply BivariatePoissonDrawOverlay with OTel span ───
        if bundle.overlay is not None:
            _span_ctx = (
                _tracer.start_as_current_span("sabiscore.overlay.bivariate_poisson")
                if _tracer else nullcontext()
            )
            with _span_ctx as _span:
                try:
                    overlay = bundle.overlay
                    if getattr(overlay, "alpha", 0.0) > 0.0:
                        _t0 = time.perf_counter()
                        blended = overlay.apply(proba)
                        if not self._valid_probability_matrix(blended):
                            raise ValueError("overlay returned an invalid probability simplex")
                        proba = blended
                        overlay_applied = True
                        _latency_ms = (time.perf_counter() - _t0) * 1000
                        if _span and hasattr(_span, "set_attribute"):
                            _span.set_attribute("overlay.alpha", float(overlay.alpha))
                            _span.set_attribute("overlay.league", league)
                            _span.set_attribute("overlay.latency_ms", round(_latency_ms, 2))
                        logger.debug(
                            "PredictionEngine: Bivariate Poisson overlay applied "
                            "alpha=%.4f league=%s latency_ms=%.2f",
                            overlay.alpha, league, _latency_ms,
                        )
                except Exception as exc:
                    logger.warning(
                        "PredictionEngine: Bivariate Poisson overlay failed for %s: %s",
                        league,
                        redact_text(exc),
                    )

        h, d, a = float(proba[0, 0]), float(proba[0, 1]), float(proba[0, 2])
        confidence = max(0.0, min(1.0, max(h, d, a) - 0.333))
        _total_ms = (time.perf_counter() - _infer_t0) * 1000
        logger.debug(
            "PredictionEngine: inference complete league=%s version=%s "
            "calibration=%s overlay=%s total_ms=%.2f",
            league, model_version, calibration_applied, overlay_applied, _total_ms,
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
        """Infer expected feature count from a dict-artifact bundle."""
        if bundle.feature_columns:
            return len(bundle.feature_columns)
        for m in bundle.models_dict.values():
            dim = getattr(m, "n_features_in_", None)
            if dim is not None:
                return int(dim)
        return fallback

    @staticmethod
    def _ensemble_predict_dict(models_dict: Dict[str, Any], X: np.ndarray) -> np.ndarray:
        """Equal-weight average of all base learner class probabilities. Returns (1, 3)."""
        all_probs: List[np.ndarray] = []
        for m in models_dict.values():
            try:
                p = np.asarray(m.predict_proba(X), dtype=np.float64)
                if PredictionEngine._valid_probability_matrix(p):
                    all_probs.append(p)
            except Exception:
                pass
        if not all_probs:
            raise ValueError("no base learner returned a valid probability simplex")
        return np.mean(all_probs, axis=0)

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
        )

    # ── Cache management ───────────────────────────────────────────────────────

    # ── Value bet calculation (migrated from prediction_service.py) ───────────

    @staticmethod
    def calculate_value_bets(
        predictions: Dict[str, float],
        market_odds: Dict[str, float],
        kelly_fraction: float = 0.25,
        min_edge_pct: float = 3.0,
        closing_odds: Optional[Dict[str, float]] = None,
        league: Optional[str] = None,
    ) -> list:
        """Return value bets sorted by edge (highest first).

        Parameters match the legacy ``PredictionService.calculate_value_bets``
        signature so callers can swap imports without changing call sites.
        Per B-contract: ``clv_pct`` is null whenever ``closing_odds`` is absent.
        ``league`` (optional, backward-compatible) caps the raw Kelly fraction at
        the per-league policy cap — previously unbounded here, unlike every
        other Kelly computation in this codebase (insights/engine.py,
        betting_intelligence.py, core_engine.py all clamp).
        """
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
                    c = closing_odds.get(outcome)
                    if c and c > 1.01:
                        clv_pct = round((pred_prob - 1.0 / c) * 100, 2)
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
                logger.warning("Value bet calc error for %s: %s", outcome, exc)
        bets.sort(key=lambda x: x["edge_pct"], reverse=True)
        return bets

    @classmethod
    def prime_cache(cls, league: str, model: Any) -> None:
        """Pre-load a model artifact into the class cache (called from app startup).

        Accepts both a direct sklearn model (v5 artifacts) and a v6_phase8 artifact
        dict.  The raw value is normalised into an ``_ArtifactBundle`` before storage.
        """
        slug = _LEAGUE_SLUG.get(league, league.lower().replace(" ", "_"))
        bundle = cls._wrap_artifact(model, slug, "<startup>")
        if bundle is None:
            # Legacy path: treat as direct model if wrap fails
            bundle = _ArtifactBundle(
                direct_model=model if callable(getattr(model, "predict_proba", None)) else None,
                models_dict=None,
                calibrator=None,
                overlay=None,
                feature_columns=None,
            )
        with cls._lock:
            cls._model_cache[slug] = bundle

    @classmethod
    def clear_cache(cls) -> None:
        with cls._lock:
            cls._model_cache.clear()
