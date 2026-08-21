# API module initialization
from fastapi import APIRouter

# Import the aggregated router from the endpoints package (endpoints/__init__.py)
from .endpoints import router as modular_router

# Import legacy standalone routes from legacy_endpoints.py file
from .legacy_endpoints import router as legacy_router

# Import monitoring endpoints for health checks and metrics
from .endpoints.monitoring import router as monitoring_router
from .endpoints.data_authority import router as data_authority_router
from .routes.predictions import router as certified_predictions_router


api_router = APIRouter()

# Include monitoring routes (health checks, metrics)
api_router.include_router(monitoring_router)

# Include release-verification data authority routes.
api_router.include_router(data_authority_router)

# Include certified analytics prediction routes before legacy prediction routes.
api_router.include_router(certified_predictions_router)

# Include the new modular routes (matches, predictions, odds)
api_router.include_router(modular_router)

# Include legacy routes (/health, /insights, /models/status, /metrics/cache, /matches/search)
api_router.include_router(legacy_router)


__all__ = ["api_router"]
