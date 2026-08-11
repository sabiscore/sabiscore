"""
GET /api/v1/models/status

Returns the active-generation manifest metadata consumed by the
ModelMetadataPanel on the frontend. Reads the committed JSON manifest
and the app.state loaded-model record; does not call providers or run inference.
"""
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/models", tags=["models"])

_MANIFEST_NAME = "active_generation.json"
# models/ sits three parents up from backend/src/api/endpoints/
_MODELS_DIR = Path(__file__).resolve().parents[3] / "models"


def _load_manifest() -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    path = _MODELS_DIR / _MANIFEST_NAME
    try:
        raw = path.read_text(encoding="utf-8")
        return json.loads(raw), hashlib.sha256(raw.encode()).hexdigest()
    except Exception as exc:
        logger.warning("active_generation.json unavailable: %s", exc)
        return None, None


def _feature_count_from_schema(schema_version: Optional[str]) -> Optional[int]:
    # e.g. "phase7_68" → 68
    if not schema_version:
        return None
    try:
        return int(schema_version.split("_")[-1])
    except (ValueError, IndexError):
        return None


@router.get("/status")
async def model_status(request: Request) -> Dict[str, Any]:
    manifest, manifest_hash = _load_manifest()

    app_state = getattr(request.app, "state", None)
    loaded_models: Dict[str, Any] = {}
    models_loaded = False
    if app_state is not None:
        loaded_models = getattr(app_state, "models", {}) or {}
        models_loaded = bool(getattr(app_state, "models_loaded", False))

    if manifest is None:
        return {
            "active_version": None,
            "generation": None,
            "generation_hash": None,
            "certification_state": "UNVERIFIED",
            "promotion_state": "UNKNOWN",
            "validation_status": "UNVERIFIED",
            "manifest_valid": False,
            "models_loaded": models_loaded,
            "stake_permitted": False,
            "models": {},
        }

    artifacts: Dict[str, Any] = manifest.get("artifacts", {})
    feature_schema = manifest.get("feature_schema_version")
    served_head = manifest.get("served_head")
    feature_count = _feature_count_from_schema(feature_schema)

    models: Dict[str, Any] = {}
    for league, artifact_info in artifacts.items():
        loaded = loaded_models.get(league)
        models[league] = {
            "feature_schema_version": feature_schema,
            "feature_count": feature_count,
            "served_head": served_head,
            "artifact": artifact_info.get("artifact"),
            "artifact_sha256": artifact_info.get("artifact_sha256"),
            "required": artifact_info.get("required", False),
            "loaded": loaded is not None,
        }

    cert = manifest.get("certification_state", "UNVERIFIED")
    return {
        "active_version": manifest.get("active_version"),
        "generation": manifest.get("generation"),
        "generation_hash": manifest_hash,
        "certification_state": cert,
        "promotion_state": manifest.get("promotion_state"),
        # Uppercase to match existing test contract: "VALIDATED" | "UNVERIFIED"
        "validation_status": "VALIDATED" if cert == "CERTIFIED" else "UNVERIFIED",
        "manifest_valid": True,
        "models_loaded": models_loaded,
        # Stake is only permitted when the generation is fully certified
        "stake_permitted": cert == "CERTIFIED",
        "models": models,
    }
