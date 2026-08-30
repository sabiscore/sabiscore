from fastapi import APIRouter
import logging

logger = logging.getLogger(__name__)

# Aggregate sub-routers inside the endpoints package so imports like
# `from .endpoints import router` resolve to this package's router.
router = APIRouter()

# Import sub-routers (these live in the same directory)
from .auth import router as auth_router  # noqa: E402
from .matches import router as matches_router  # noqa: E402
from .predictions import router as predictions_router  # noqa: E402
from .odds import router as odds_router  # noqa: E402
from .value_bets import router as value_bets_router  # noqa: E402
from .health import router as health_router  # noqa: E402
from .upcoming_matches import router as upcoming_matches_router  # noqa: E402
from .uncertainty import router as uncertainty_router  # noqa: E402
from .causal import router as causal_router  # noqa: E402
from .rl_agent import router as rl_agent_router  # noqa: E402
from .full_analysis import router as full_analysis_router  # noqa: E402
from .performance import router as performance_router  # noqa: E402
from .explain import router as explain_router  # noqa: E402
from .phase8_features import router as phase8_features_router  # noqa: E402
from .offseason import router as offseason_router  # noqa: E402
from .team_intelligence import router as team_intelligence_router  # noqa: E402
from .leagues import router as leagues_router  # noqa: E402
from .sources import router as sources_router  # noqa: E402
from .core_engine import router as core_engine_router  # noqa: E402
from .betting_intelligence import router as betting_intelligence_router  # noqa: E402
from .fixtures import router as fixtures_router  # noqa: E402
from .model_status import router as model_status_router  # noqa: E402
from .providers import router as providers_router  # noqa: E402
from .advanced_insights import router as advanced_insights_router  # noqa: E402

# Ultra predictions are optional - depends on catboost/xgboost/lightgbm
try:
    from .ultra_predictions import router as ultra_predictions_router  # noqa: E402
    _ultra_available = True
except ImportError as e:
    logger.warning(f"Ultra predictions endpoint not available: {e}")
    ultra_predictions_router = None
    _ultra_available = False

# Include sub-routers without adding additional prefixes here. The application
# will apply the API version prefix (e.g. /api/v1) at the app level.
router.include_router(auth_router)
router.include_router(matches_router)
router.include_router(predictions_router)
router.include_router(odds_router)
router.include_router(value_bets_router)
router.include_router(health_router)
router.include_router(upcoming_matches_router)
router.include_router(uncertainty_router)
router.include_router(causal_router)
router.include_router(rl_agent_router)
router.include_router(full_analysis_router)
router.include_router(performance_router)
router.include_router(explain_router)
router.include_router(phase8_features_router)
router.include_router(offseason_router)
router.include_router(team_intelligence_router)
router.include_router(leagues_router)
router.include_router(sources_router)
router.include_router(core_engine_router)
router.include_router(betting_intelligence_router)
router.include_router(fixtures_router)
router.include_router(model_status_router)
router.include_router(providers_router)
router.include_router(advanced_insights_router)

if _ultra_available and ultra_predictions_router is not None:
    router.include_router(ultra_predictions_router)
    logger.info("✅ Ultra predictions endpoint enabled")

__all__ = ["router"]
