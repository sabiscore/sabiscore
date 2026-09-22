"""Causal analysis endpoint (Phase 6 advisory mode)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ...core.config import settings
from ...schemas.responses import (
    CausalClassification,
    CausalFeatureResponse,
    CausalFeaturesResponse,
)


router = APIRouter(prefix="/causal", tags=["causal"])


def _normalize_classification(value: object) -> CausalClassification:
    raw = str(value or "").strip().upper()
    for item in CausalClassification:
        if raw == item.value:
            return item
    return CausalClassification.INDEPENDENT


def _normalize_ci(value: object) -> tuple[float, float]:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            lo = float(value[0])
            hi = float(value[1])
            return (lo, hi)
        except (TypeError, ValueError):
            pass
    return (0.0, 0.0)


@router.get("/features", response_model=CausalFeaturesResponse)
async def get_causal_features(limit: int = 58):
    report_path = settings.data_path / "causal_feature_report.json"
    if not report_path.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "Causal feature report not found. Run scripts/causal_feature_analysis.py "
                "to generate data/processed/causal_feature_report.json"
            ),
        )

    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500, detail=f"Invalid causal feature report JSON: {exc}"
        ) from exc

    features = payload.get("features", []) if isinstance(payload, dict) else []
    if not isinstance(features, list):
        features = []

    typed: list[CausalFeatureResponse] = []
    for item in features:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        try:
            typed.append(
                CausalFeatureResponse(
                    name=name,
                    ate_win=float(item.get("ate_win", 0.0)),
                    ate_draw=float(item.get("ate_draw", 0.0)),
                    ate_ci=_normalize_ci(item.get("ate_ci")),
                    p_value=float(item.get("p_value", 1.0)),
                    classification=_normalize_classification(
                        item.get("classification")
                    ),
                )
            )
        except (TypeError, ValueError):
            continue

    capped = typed[: max(1, min(limit, 200))]
    return CausalFeaturesResponse(
        features=capped,
        source=str(Path(report_path).as_posix()),
        count=len(typed),
    )
