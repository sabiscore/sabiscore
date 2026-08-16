"""ml_ultra package - optional advanced ML components for SabiScore.

Uses lazy imports so the canonical production API can run without research-only
packages such as CatBoost. Optional dependency absence is a capability state,
not a production startup failure.
"""

import logging
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

__version__ = "3.0.0"

if TYPE_CHECKING:
    from .meta_learner import DiverseEnsemble
    from .feature_engineering import AdvancedFeatureEngineer
    from .training_pipeline import ProductionMLPipeline
    from .ultra_predictor import UltraPredictor, LegacyPredictorAdapter

# Cache both successful imports and known-unavailable components. Caching None
# prevents every availability probe from re-importing and re-logging the same
# optional dependency failure during startup.
_available_components: dict[str, Any | None] = {}


def _lazy_import(name: str) -> Any | None:
    """Return an optional component, caching both success and unavailability."""

    if name in _available_components:
        return _available_components[name]

    try:
        if name == "DiverseEnsemble":
            from .meta_learner import DiverseEnsemble

            component = DiverseEnsemble
        elif name == "AdvancedFeatureEngineer":
            from .feature_engineering import AdvancedFeatureEngineer

            component = AdvancedFeatureEngineer
        elif name == "ProductionMLPipeline":
            from .training_pipeline import ProductionMLPipeline

            component = ProductionMLPipeline
        elif name == "UltraPredictor":
            from .ultra_predictor import UltraPredictor

            component = UltraPredictor
        elif name == "LegacyPredictorAdapter":
            from .ultra_predictor import LegacyPredictorAdapter

            component = LegacyPredictorAdapter
        else:
            raise ImportError(f"Unknown component: {name}")

        _available_components[name] = component
        return component
    except ImportError as exc:
        _available_components[name] = None
        logger.info("Ultra ML optional component '%s' disabled: %s", name, exc)
        return None


def __getattr__(name: str) -> Any:
    """Module-level lazy attribute access for optional Ultra components."""

    if name in (
        "DiverseEnsemble",
        "AdvancedFeatureEngineer",
        "ProductionMLPipeline",
        "UltraPredictor",
        "LegacyPredictorAdapter",
    ):
        result = _lazy_import(name)
        if result is None:
            raise ImportError(
                f"Ultra ML component '{name}' requires additional dependencies. "
                "Install the research/Ultra dependency set before enabling this path."
            )
        return result
    raise AttributeError(f"module 'ml_ultra' has no attribute '{name}'")


def is_ultra_available() -> bool:
    """Return True only when the two core Ultra inference components load."""

    diverse_ensemble = _lazy_import("DiverseEnsemble")
    ultra_predictor = _lazy_import("UltraPredictor")
    return diverse_ensemble is not None and ultra_predictor is not None


__all__ = [
    "DiverseEnsemble",
    "AdvancedFeatureEngineer",
    "ProductionMLPipeline",
    "UltraPredictor",
    "LegacyPredictorAdapter",
    "is_ultra_available",
    "__version__",
]
