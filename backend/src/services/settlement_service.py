"""Compose the settlement-join pipeline: sync recent results, then validate
predictions against them.

get_settled_predictions() (repositories/fixtures.py) and walk_forward_validate()
(models/model_registry.py) were both correct and unit-tested but had zero
production callers — see docs/DEBT.md item 2. This module is that caller,
invoked periodically from api/main.py's background task.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..models.model_registry import ModelRegistry

logger = logging.getLogger(__name__)

_last_result: dict[str, Any] = {
    "outcome": "never_run",
    "consecutive_failures": 0,
    "total_failures": 0,
    "last_success_at": None,
    "settled_predictions_total": 0,
}
_registry_instance: "ModelRegistry | None" = None


def get_walk_forward_registry() -> "ModelRegistry":
    """Memoized ModelRegistry — its constructor does real I/O (mkdir + a
    metadata.json read); walk_forward_validate() doesn't touch self, so one
    process-lifetime instance is safe to share across ticks and requests.
    """
    global _registry_instance
    if _registry_instance is None:
        from ..core.config import settings
        from ..models.model_registry import ModelRegistry

        registry_path = str(settings.models_path / "_walk_forward_registry")
        _registry_instance = ModelRegistry(registry_path=registry_path)
    return _registry_instance


def last_settlement_result() -> dict[str, Any]:
    """Sync accessor for /health — a copy, never the live dict (health_check()
    is a sync function; this must never be awaited or block on I/O)."""
    result = dict(_last_result)
    last_success_at = result.get("last_success_at")
    if isinstance(last_success_at, str):
        try:
            observed = datetime.fromisoformat(last_success_at.replace("Z", "+00:00"))
            result["last_success_age_seconds"] = max(
                0, int((datetime.now(timezone.utc) - observed).total_seconds())
            )
        except ValueError:
            result["last_success_age_seconds"] = None
    else:
        result["last_success_age_seconds"] = None
    return result


async def run_settlement_pass() -> dict[str, Any]:
    """sync_settled_results() -> get_settled_predictions() -> walk_forward_validate(),
    against one session. Never raises — every failure lands in the returned/stored
    dict, matching the swallow-and-log convention run_fixture_sync() already uses.
    """
    global _last_result

    from ..db.session import AsyncSessionLocal

    checked_at = datetime.now(timezone.utc).isoformat()

    if AsyncSessionLocal is None:
        _last_result = {
            **_last_result,
            "outcome": "db_not_ready",
            "checked_at": checked_at,
        }
        return _last_result

    try:
        from .fixture_sync_service import sync_settled_results
        from ..models.active_generation import active_model_version
        from ..repositories.fixtures import get_settled_predictions

        # Scope accuracy evidence to the generation actually serving. Pooling
        # generations would report a walk-forward score for a model that never
        # existed and would inflate the sample size gating certification.
        # Raises if the active generation cannot be resolved, which the outer
        # handler records as an error — no metric beats a cross-generation one.
        model_version = active_model_version()

        async with AsyncSessionLocal() as session:
            sync_counts = await sync_settled_results(session)
            # Elo is a derived state transition from authoritative finished-match
            # results. Keep it coupled to settlement so retries are ordered and
            # idempotent instead of introducing a second independent scheduler.
            from .elo_state_service import sync_elo_from_finished_matches

            elo_counts = await sync_elo_from_finished_matches(session)
            records = await get_settled_predictions(
                session, model_version=model_version
            )

        # Pure Python, no DB — deliberately outside the session block above.
        validation = get_walk_forward_registry().walk_forward_validate(records)

        _last_result = {
            "outcome": "ok",
            "checked_at": checked_at,
            "last_success_at": checked_at,
            "sync": sync_counts,
            "elo": elo_counts,
            "model_version": model_version,
            "settled_predictions_total": len(records),
            "walk_forward": validation,
            "consecutive_failures": 0,
            "total_failures": int(_last_result.get("total_failures", 0)),
        }
    except Exception as exc:
        logger.exception("settlement_pass: unhandled error")
        consecutive_failures = int(_last_result.get("consecutive_failures", 0)) + 1
        from ..core.redaction import redact_text

        _last_result = {
            **_last_result,
            "outcome": "error",
            "checked_at": checked_at,
            "message": redact_text(exc),
            "consecutive_failures": consecutive_failures,
            "total_failures": int(_last_result.get("total_failures", 0)) + 1,
        }

    return _last_result
