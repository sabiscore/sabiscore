"""Shared persistence for model predictions used by settlement and CLV."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from numbers import Real
from typing import Any, Literal, Mapping, Sequence, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import Match
from ..db.models import MatchPredictionLog

PredictionLogOutcome = Literal["created", "duplicate", "ineligible"]


def _utc_naive(value: datetime) -> datetime:
    """Normalize an instant for the repository's UTC-naive DB columns."""

    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _stable_value(value: Any) -> Any:
    """Return a deterministic JSON-safe representation for snapshot hashing."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, Real):
        number = float(value)
        return number if math.isfinite(number) else str(number)
    if isinstance(value, datetime):
        normalized = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return normalized.astimezone(timezone.utc).isoformat()
    if isinstance(value, Mapping):
        return {
            str(key): _stable_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_stable_value(item) for item in value]
    return str(value)


def deterministic_input_hash(payload: Mapping[str, Any]) -> str:
    """Hash a model-input snapshot without including request/evaluation time."""

    encoded = json.dumps(
        _stable_value(payload),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _valid_simplex(probabilities: Sequence[float]) -> bool:
    values = tuple(float(value) for value in probabilities)
    return (
        len(values) == 3
        and all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in values)
        and math.isclose(sum(values), 1.0, rel_tol=0.0, abs_tol=1e-4)
    )


@dataclass(frozen=True)
class PredictionLogCapture:
    match_id: str
    model_version: str
    home_probability: float
    draw_probability: float
    away_probability: float
    input_hash: str
    evaluated_at: datetime
    calibration_method: str | None = None
    confidence: float | None = None
    decision_id: str | None = None
    canonical_fixture_id: str | None = None
    payload: dict[str, Any] | None = None


async def persist_prediction_log(
    session: AsyncSession,
    capture: PredictionLogCapture,
    *,
    require_scheduled_pre_kickoff: bool = False,
) -> PredictionLogOutcome:
    """Flush one immutable snapshot, or report why none was added.

    Interactive full analysis enables ``require_scheduled_pre_kickoff``.  The
    fixture-row lock serializes deduplication on PostgreSQL without a migration.
    The caller owns commit/rollback so the write remains transactional.
    """

    probabilities = (
        capture.home_probability,
        capture.draw_probability,
        capture.away_probability,
    )
    if (
        not capture.match_id
        or not capture.model_version
        or capture.model_version.casefold() in {"fallback", "unavailable", "unknown"}
        or not capture.input_hash
        or not _valid_simplex(probabilities)
    ):
        return "ineligible"

    if require_scheduled_pre_kickoff:
        fixture = (
            await session.execute(
                select(Match).where(Match.id == capture.match_id).with_for_update()
            )
        ).scalar_one_or_none()
        if fixture is None or str(fixture.status or "").casefold() != "scheduled":
            return "ineligible"
        if _utc_naive(capture.evaluated_at) >= _utc_naive(
            cast(datetime, fixture.match_date)
        ):
            return "ineligible"

    existing = (
        await session.execute(
            select(MatchPredictionLog.id).where(
                MatchPredictionLog.match_id == capture.match_id,
                MatchPredictionLog.model_version == capture.model_version,
                MatchPredictionLog.input_hash == capture.input_hash,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return "duplicate"

    session.add(
        MatchPredictionLog(
            match_id=capture.match_id,
            canonical_fixture_id=capture.canonical_fixture_id,
            model_version=capture.model_version,
            calibration_method=capture.calibration_method,
            home_probability=float(capture.home_probability),
            draw_probability=float(capture.draw_probability),
            away_probability=float(capture.away_probability),
            confidence=(
                float(capture.confidence) if capture.confidence is not None else None
            ),
            input_hash=capture.input_hash,
            decision_id=capture.decision_id,
            payload=capture.payload,
            created_at=_utc_naive(capture.evaluated_at),
        )
    )
    await session.flush()
    return "created"


__all__ = [
    "PredictionLogCapture",
    "PredictionLogOutcome",
    "deterministic_input_hash",
    "persist_prediction_log",
]
