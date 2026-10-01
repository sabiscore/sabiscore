"""C6 adapter over the production prediction and settlement ledgers.

Only rows written by the V21 scheduled capture trigger enter the live sample.
There is deliberately no mutable in-memory N counter: restarts and historical
replay cannot change the count of settled live observations.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

try:  # Container runtime exposes backend/src as ``src``.
    from src.models.active_generation import active_served_identity
except ModuleNotFoundError:  # Repository tests import through ``backend.src``.
    from backend.src.models.active_generation import active_served_identity


# Frozen by reports/research/c6-served-generation-vs-close-protocol.json. Do
# not mint a new writer tag for V21; that would change the registered sample.
LIVE_CAPTURE_TRIGGER = "interactive_full_analysis"


class C6LiveCollector:
    def __init__(self, *, target: int = 200):
        self.target = target

    async def capture_pre_kickoff_predictions(self, *, odds_service: Any = None) -> dict[str, Any]:
        try:
            from src.services.prediction_capture_service import run_prediction_capture_pass
        except ModuleNotFoundError:
            from backend.src.services.prediction_capture_service import run_prediction_capture_pass

        return await run_prediction_capture_pass(
            odds_service=odds_service,
            capture_trigger=LIVE_CAPTURE_TRIGGER,
        )

    async def settle_predictions(self) -> dict[str, Any]:
        try:
            from src.db.session import AsyncSessionLocal
        except ModuleNotFoundError:
            from backend.src.db.session import AsyncSessionLocal

        if AsyncSessionLocal is None:
            return {"status": "DB_NOT_READY", "live_n": None, "target": self.target}
        model_version = active_served_identity()
        async with AsyncSessionLocal() as session:
            try:
                from src.repositories.fixtures import get_clv_records, get_settled_predictions
            except ModuleNotFoundError:
                from backend.src.repositories.fixtures import get_clv_records, get_settled_predictions

            joined = await get_clv_records(
                session,
                model_version=model_version,
                capture_trigger=LIVE_CAPTURE_TRIGGER,
                limit=5000,
            )
            records = [row for row in joined if row.get("outcome") in (0, 1, 2)]
            settled = await get_settled_predictions(
                session,
                model_version=model_version,
                capture_trigger=LIVE_CAPTURE_TRIGGER,
                limit=5000,
            )
            count = len(records)
            total_live = len(settled)
        status = "MILESTONE_READY" if count >= self.target else "INSUFFICIENT_SAMPLE"
        return {
            "status": status,
            "live_n": count,
            "live_captured_fixtures": total_live,
            "replay_n": None,
            "target": self.target,
            "model_version": model_version,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }


__all__ = ["C6LiveCollector", "LIVE_CAPTURE_TRIGGER"]
