"""Regression tests for PredictionEngine startup cache reuse.

The FastAPI lifespan eagerly deserializes and validates every active v5 league
artifact. The canonical request-path PredictionEngine must reuse those resident
estimators instead of deserializing the same artifact again, while preserving
manifest provenance and retaining a safe raw-loader fallback for future model
generations that may carry extra calibration/overlay payloads.
"""
from __future__ import annotations

import asyncio
from unittest.mock import Mock

import numpy as np

from src.models.prediction import PredictionEngine


class _Learner:
    n_features_in_ = 2

    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        assert features.shape == (1, 2)
        return np.array([[0.50, 0.25, 0.25]], dtype=np.float64)


class _StartupEnsemble:
    def __init__(self) -> None:
        self.models = {"rf": _Learner()}
        self.feature_columns = ["elo_home", "elo_away"]


def _generation(version: str = "v5_phase7") -> dict:
    return {
        "active_version": version,
        "generation": "generation-v5",
        "feature_schema_version": "phase7_68",
        "manifest_sha256": "manifest-sha",
        "certification_state": "UNVERIFIED",
        "artifacts": {
            "epl": {
                "artifact_sha256": "artifact-sha",
            }
        },
    }


def test_v5_startup_model_primes_engine_without_second_disk_load() -> None:
    PredictionEngine.clear_cache()
    startup_model = _StartupEnsemble()

    assert PredictionEngine.prime_cache(
        "EPL",
        startup_model,
        generation=_generation(),
    )

    engine = PredictionEngine()
    engine._load_from_disk = Mock(  # type: ignore[method-assign]
        side_effect=AssertionError("startup-primed model must not hit disk")
    )
    bundle = asyncio.run(engine._load_model("EPL"))

    assert bundle is not None
    assert bundle.models_dict is not None
    assert bundle.models_dict["rf"] is startup_model.models["rf"]
    assert bundle.feature_columns == startup_model.feature_columns
    assert bundle.model_version == "v5_phase7"
    assert bundle.generation == "generation-v5"
    assert bundle.feature_schema_version == "phase7_68"
    assert bundle.manifest_sha256 == "manifest-sha"
    assert bundle.artifact_sha256 == "artifact-sha"
    assert bundle.certification_state == "UNVERIFIED"
    assert bundle.coverage == "dedicated"

    PredictionEngine.clear_cache()


def test_startup_primed_bundle_preserves_prediction_semantics() -> None:
    PredictionEngine.clear_cache()
    startup_model = _StartupEnsemble()
    assert PredictionEngine.prime_cache(
        "epl",
        startup_model,
        generation=_generation(),
    )

    result = asyncio.run(
        PredictionEngine().predict(
            features=np.array([1500.0, 1500.0], dtype=np.float32),
            league="EPL",
        )
    )

    assert result.model_version == "v5_phase7"
    assert result.model_dim == 2
    assert result.home_win == 0.50
    assert result.draw == 0.25
    assert result.away_win == 0.25
    assert result.manifest_sha256 == "manifest-sha"
    assert result.artifact_sha256 == "artifact-sha"
    assert result.certification_state == "UNVERIFIED"

    PredictionEngine.clear_cache()


def test_future_generation_refuses_lossy_startup_priming() -> None:
    PredictionEngine.clear_cache()

    assert not PredictionEngine.prime_cache(
        "EPL",
        _StartupEnsemble(),
        generation=_generation("v6_phase8"),
    )
    assert PredictionEngine._model_cache == {}
