"""Durable, sanitized provider-evidence observations.

Provider calls are product evidence, not log decoration. This service persists
only normalized outcomes and operational metadata into the provider observation
tables created by Alembic 0002. It never stores credentials, request headers,
credential-bearing URLs, or raw provider payloads.

Persistence is deliberately best-effort: provider data remains available to the
caller even when the observation database path is temporarily unavailable.
Absence of rows is represented as UNKNOWN by ``latest_provider_evidence`` and is
never interpreted as provider health.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import func, select

from ..core.redaction import redact_text
from ..db.models import ProviderHealthLog, ProviderQuotaObservation, ProviderRequestSummary
from ..providers.base import (
    ProviderResult,
    ProviderStatus,
    ProviderTransportError,
    TrustTier,
    stable_hash,
)

logger = logging.getLogger(__name__)

# Durable provider-operation evidence is not perpetual proof of current provider
# health. One hour matches the slowest production result-settlement observation
# cadence while remaining deliberately conservative for the five-minute odds
# capture path. Evidence older than this is surfaced as STALE regardless of the
# last underlying provider status; that raw status remains separately visible.
PROVIDER_EVIDENCE_STALE_SECONDS = 3600


def _utc_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _safe_warnings(values: Iterable[object]) -> list[str]:
    # Bound persisted warning volume so an upstream schema failure cannot turn
    # the telemetry table into an accidental raw-response sink.
    return [redact_text(value)[:500] for value in list(values)[:50]]


def _evidence_state(status: str | None) -> str:
    normalized = str(status or "").upper()
    if normalized == ProviderStatus.VERIFIED.value:
        return "LIVE_VERIFIED"
    if normalized == ProviderStatus.CONFIGURED_UNVERIFIED.value:
        return "CONFIGURED"
    if normalized == ProviderStatus.RATE_LIMITED.value:
        return "RATE_LIMITED"
    if normalized in {
        ProviderStatus.PARTIAL.value,
        ProviderStatus.INVALID.value,
        ProviderStatus.CONFLICTING.value,
    }:
        return "DEGRADED"
    if normalized in {
        ProviderStatus.UNAVAILABLE.value,
        ProviderStatus.UNCONFIGURED.value,
        ProviderStatus.CIRCUIT_OPEN.value,
    }:
        return "UNAVAILABLE"
    return "UNKNOWN"


def _record_identity(record: dict[str, Any]) -> str | None:
    """Return one provider/canonical event identity without guessing team matches."""
    for key in ("canonical_fixture_id", "provider_event_id", "fixture_id"):
        value = record.get(key)
        if value is None:
            continue
        normalized = str(value).strip()
        if normalized:
            return normalized
    return None


def _distinct_events(records: Iterable[dict[str, Any]]) -> int:
    identities = {identity for record in records if (identity := _record_identity(record))}
    return len(identities)


def _coverage_summary(result: ProviderResult) -> dict[str, Any]:
    """Derive usable coverage from normalized records, never raw count alone."""
    records = list(result.records)
    has_coherent = any("coherent" in record for record in records)
    coherent = [record for record in records if record.get("coherent") is True]
    has_executable = any("executable" in record for record in records)
    executable = [record for record in records if record.get("executable") is True]

    if result.operation == "odds" or has_executable:
        if has_executable:
            usable = executable
            basis = "executable"
        elif has_coherent:
            usable = coherent
            basis = "coherent"
        else:
            usable = []
            basis = "unavailable"
    elif has_coherent:
        usable = coherent
        basis = "coherent"
    else:
        usable = records
        basis = "records"

    if not records:
        state = "EMPTY"
    elif usable:
        state = "USABLE"
    else:
        state = "UNUSABLE"

    settled_records = sum(
        1
        for record in coherent if has_coherent
        if record.get("home_score") is not None and record.get("away_score") is not None
    )

    return {
        "state": state,
        "basis": basis,
        "total_records": len(records),
        "coherent_records": len(coherent) if has_coherent else None,
        "executable_records": len(executable) if has_executable else None,
        "usable_records": len(usable),
        "total_events": _distinct_events(records),
        "coherent_events": _distinct_events(coherent) if has_coherent else None,
        "executable_events": _distinct_events(executable) if has_executable else None,
        "usable_events": _distinct_events(usable),
        "settled_records": settled_records if has_coherent else None,
    }


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return _utc_naive(value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _utc_naive(parsed)


def _latest_source_timestamp(result: ProviderResult) -> datetime | None:
    """Return latest upstream update timestamp only when records expose one.

    Kickoff/event time is deliberately excluded: it describes the event, not
    freshness of the provider response. Odds bookmaker last-update timestamps are
    valid freshness evidence; explicit ProviderResult.provider_timestamp remains
    authoritative when a provider supplies it.
    """
    candidates: list[datetime] = []
    provider_timestamp = _utc_naive(result.provider_timestamp)
    if provider_timestamp is not None:
        candidates.append(provider_timestamp)

    for record in result.records:
        for key in ("bookmaker_last_update", "source_updated_at", "provider_timestamp", "last_update"):
            parsed = _parse_datetime(record.get(key))
            if parsed is not None:
                candidates.append(parsed)

    return max(candidates) if candidates else None


def _transport_summary(result: ProviderResult) -> dict[str, Any]:
    status_code = result.http_status_code
    category = result.http_status_category
    if status_code is not None:
        outcome = "SUCCESS" if 200 <= status_code < 300 else "FAILURE"
    elif str(result.error_code or "").startswith("TRANSPORT_"):
        outcome = "FAILURE"
    else:
        outcome = "UNKNOWN"
    return {
        "outcome": outcome,
        "http_status_code": status_code,
        "http_status_category": category,
    }


def _quota_summary(result: ProviderResult, quota_reset_at: datetime | None) -> dict[str, Any]:
    observed = any(
        value is not None
        for value in (
            result.quota.limit,
            result.quota.remaining,
            result.quota.reset_at,
            result.quota.cost,
        )
    )
    return {
        "observed": observed,
        "limit": result.quota.limit,
        "remaining": result.quota.remaining,
        "reset_at": quota_reset_at.isoformat() if quota_reset_at is not None else None,
        "cost": result.quota.cost,
        "rate_limited": result.status is ProviderStatus.RATE_LIMITED,
    }


class ProviderEvidenceRecorder:
    """Persist provider outcomes using the application async session factory."""

    async def record_result(
        self,
        result: ProviderResult,
        *,
        duration_ms: float,
        circuit_open: bool,
    ) -> bool:
        return await self._persist(
            result,
            duration_ms=max(0.0, float(duration_ms)),
            circuit_open=bool(circuit_open),
        )

    async def record_exception(
        self,
        *,
        provider: str,
        operation: str,
        trust_tier: TrustTier,
        error: Exception,
        duration_ms: float,
        circuit_open: bool,
    ) -> bool:
        if isinstance(error, ProviderTransportError):
            status = error.provider_status
            warnings = error.warning_tokens()
            error_code = error.error_code
            http_status_code = error.status_code
        else:
            safe_error = redact_text(error)
            status = ProviderStatus.CIRCUIT_OPEN if circuit_open else ProviderStatus.UNAVAILABLE
            warnings = [safe_error]
            error_code = type(error).__name__
            http_status_code = None

        result = ProviderResult(
            provider=provider,
            operation=operation,
            status=status,
            trust_tier=trust_tier,
            warnings=warnings,
            error_code=error_code,
            http_status_code=http_status_code,
            http_status_category=(
                _http_status_category(http_status_code) if http_status_code is not None else None
            ),
        )
        return await self._persist(
            result,
            duration_ms=max(0.0, float(duration_ms)),
            circuit_open=bool(circuit_open),
        )

    async def _persist(
        self,
        result: ProviderResult,
        *,
        duration_ms: float,
        circuit_open: bool,
    ) -> bool:
        # Lazy import avoids a provider -> DB-session import cycle during module
        # initialization and lets the registry be constructed before init_db().
        from ..db.session import AsyncSessionLocal

        if AsyncSessionLocal is None:
            logger.debug(
                "provider_evidence_skipped_db_not_ready provider=%s operation=%s",
                result.provider,
                result.operation,
            )
            return False

        warnings = _safe_warnings(result.warnings)
        error_code = redact_text(result.error_code)[:255] if result.error_code else None
        raw_snapshot_id = (
            redact_text(result.raw_snapshot_id)[:255]
            if result.raw_snapshot_id
            else None
        )
        acquired_at = _utc_naive(result.acquired_at) or datetime.now(timezone.utc).replace(tzinfo=None)
        provider_timestamp = _utc_naive(result.provider_timestamp)
        quota_reset_at = _utc_naive(result.quota.reset_at)
        coverage = _coverage_summary(result)
        source_latest_at = _latest_source_timestamp(result)
        transport = _transport_summary(result)
        quota_details = _quota_summary(result, quota_reset_at)
        response_hash = stable_hash(
            {
                "provider": result.provider,
                "operation": result.operation,
                "status": result.status.value,
                "trust_tier": result.trust_tier.value,
                "provider_timestamp": provider_timestamp,
                "records": result.records,
                "warnings": warnings,
                "error_code": error_code,
                "http_status_code": result.http_status_code,
                "http_status_category": result.http_status_category,
            }
        )

        summary = ProviderRequestSummary(
            provider=result.provider,
            operation=result.operation,
            status=result.status.value,
            trust_tier=result.trust_tier.value,
            acquired_at=acquired_at,
            provider_timestamp=provider_timestamp,
            quota_limit=result.quota.limit,
            quota_remaining=result.quota.remaining,
            quota_reset_at=quota_reset_at,
            quota_cost=result.quota.cost,
            warnings=warnings or None,
            error_code=error_code,
            raw_snapshot_id=raw_snapshot_id,
            response_hash=response_hash,
        )
        health = ProviderHealthLog(
            provider=result.provider,
            status=result.status.value,
            checked_at=acquired_at,
            latency_ms=duration_ms,
            warnings=warnings or None,
            error_code=error_code,
            details={
                "operation": result.operation,
                # Backward-compatible raw count; consumers must use `coverage`
                # for usable data instead of interpreting this field as coverage.
                "record_count": len(result.records),
                "coverage": coverage,
                "transport": transport,
                "quota": quota_details,
                "source_latest_at": (
                    source_latest_at.isoformat() if source_latest_at is not None else None
                ),
                "circuit_open": circuit_open,
                "raw_snapshot_present": bool(raw_snapshot_id),
                "quota_observed": quota_details["observed"],
            },
        )

        rows: list[Any] = [summary, health]
        if quota_details["observed"]:
            rows.append(
                ProviderQuotaObservation(
                    provider=result.provider,
                    observed_at=acquired_at,
                    quota_limit=result.quota.limit,
                    quota_remaining=result.quota.remaining,
                    quota_reset_at=quota_reset_at,
                    quota_cost=result.quota.cost,
                    source=f"provider_result:{result.operation}",
                )
            )

        try:
            async with AsyncSessionLocal() as session:
                try:
                    session.add_all(rows)
                    await session.commit()
                except Exception:
                    # Explicitly reset any failed DBAPI transaction before this
                    # short-lived telemetry session releases its connection.
                    await session.rollback()
                    raise
            return True
        except Exception as exc:
            # Never let telemetry persistence poison the provider path or the
            # caller's transaction. This recorder owns its own isolated session.
            logger.warning(
                "provider_evidence_persist_failed provider=%s operation=%s error=%s",
                result.provider,
                result.operation,
                redact_text(exc),
            )
            return False


async def latest_provider_evidence(
    session: Any,
    provider_ids: Iterable[str],
    *,
    now: datetime | None = None,
    stale_after_seconds: int = PROVIDER_EVIDENCE_STALE_SECONDS,
) -> dict[str, dict[str, Any]]:
    """Return latest persisted evidence per provider with deterministic freshness.

    Zero observations is explicitly UNKNOWN. Configuration state is intentionally
    not consulted here: this surface answers what has actually been observed.
    Any persisted observation older than ``stale_after_seconds`` is surfaced as
    STALE while its raw provider ``status`` remains available for audit.
    """
    if stale_after_seconds <= 0:
        raise ValueError("stale_after_seconds must be positive")

    provider_list = list(dict.fromkeys(str(provider) for provider in provider_ids))
    output: dict[str, dict[str, Any]] = {
        provider: {
            "state": "UNKNOWN",
            "status": None,
            "observations": 0,
            "last_observed_at": None,
            "age_seconds": None,
            "stale_after_seconds": stale_after_seconds,
            "latency_ms": None,
            "operation": None,
            "error_code": None,
            "transport": {
                "outcome": "UNKNOWN",
                "http_status_code": None,
                "http_status_category": None,
            },
            "coverage": {
                "state": "UNKNOWN",
                "basis": None,
                "total_records": None,
                "coherent_records": None,
                "executable_records": None,
                "usable_records": None,
                "total_events": None,
                "coherent_events": None,
                "executable_events": None,
                "usable_events": None,
                "settled_records": None,
            },
            "quota": {
                "observed": False,
                "limit": None,
                "remaining": None,
                "reset_at": None,
                "cost": None,
                "rate_limited": False,
            },
            "freshness": {
                "observation_age_seconds": None,
                "observation_stale_after_seconds": stale_after_seconds,
                "observation_stale": None,
                "source_latest_at": None,
                "source_age_seconds": None,
            },
        }
        for provider in provider_list
    }
    if not provider_list:
        return output

    counts = dict(
        (
            await session.execute(
                select(ProviderHealthLog.provider, func.count(ProviderHealthLog.id))
                .where(ProviderHealthLog.provider.in_(provider_list))
                .group_by(ProviderHealthLog.provider)
            )
        ).all()
    )

    ranked = (
        select(
            ProviderHealthLog.provider.label("provider"),
            ProviderHealthLog.status.label("status"),
            ProviderHealthLog.checked_at.label("checked_at"),
            ProviderHealthLog.latency_ms.label("latency_ms"),
            ProviderHealthLog.error_code.label("error_code"),
            ProviderHealthLog.details.label("details"),
            func.row_number()
            .over(
                partition_by=ProviderHealthLog.provider,
                order_by=[ProviderHealthLog.checked_at.desc(), ProviderHealthLog.id.desc()],
            )
            .label("rn"),
        )
        .where(ProviderHealthLog.provider.in_(provider_list))
        .subquery()
    )
    result = await session.execute(select(ranked).where(ranked.c.rn == 1))
    reference_now = _utc_naive(now or datetime.now(timezone.utc))
    if reference_now is None:  # defensive; the expression above is always a datetime
        raise RuntimeError("unable to derive provider evidence reference time")

    for row in result.mappings().all():
        provider = str(row["provider"])
        checked_at = row["checked_at"]
        age_seconds = None
        if isinstance(checked_at, datetime):
            checked_at_utc = _utc_naive(checked_at)
            if checked_at_utc is not None:
                age_seconds = max(0.0, (reference_now - checked_at_utc).total_seconds())
        details = row["details"] if isinstance(row["details"], dict) else {}
        state = _evidence_state(row["status"])
        is_stale = age_seconds is not None and age_seconds > stale_after_seconds
        if is_stale:
            state = "STALE"

        transport = details.get("transport") if isinstance(details.get("transport"), dict) else {
            "outcome": "UNKNOWN",
            "http_status_code": None,
            "http_status_category": None,
        }
        coverage = details.get("coverage") if isinstance(details.get("coverage"), dict) else {
            "state": "UNKNOWN",
            "basis": None,
            "total_records": details.get("record_count"),
            "coherent_records": None,
            "executable_records": None,
            "usable_records": None,
            "total_events": None,
            "coherent_events": None,
            "executable_events": None,
            "usable_events": None,
            "settled_records": None,
        }
        quota = details.get("quota") if isinstance(details.get("quota"), dict) else {
            "observed": bool(details.get("quota_observed")),
            "limit": None,
            "remaining": None,
            "reset_at": None,
            "cost": None,
            "rate_limited": str(row["status"] or "").upper() == ProviderStatus.RATE_LIMITED.value,
        }
        source_latest_at_raw = details.get("source_latest_at")
        source_latest_at = _parse_datetime(source_latest_at_raw)
        source_age_seconds = (
            max(0.0, (reference_now - source_latest_at).total_seconds())
            if source_latest_at is not None
            else None
        )

        output[provider] = {
            "state": state,
            "status": row["status"],
            "observations": int(counts.get(provider, 0)),
            "last_observed_at": checked_at.isoformat() if isinstance(checked_at, datetime) else None,
            "age_seconds": age_seconds,
            "stale_after_seconds": stale_after_seconds,
            "latency_ms": row["latency_ms"],
            "operation": details.get("operation"),
            "error_code": row["error_code"],
            "transport": transport,
            "coverage": coverage,
            "quota": quota,
            "freshness": {
                "observation_age_seconds": age_seconds,
                "observation_stale_after_seconds": stale_after_seconds,
                "observation_stale": is_stale,
                "source_latest_at": (
                    source_latest_at.isoformat() if source_latest_at is not None else None
                ),
                "source_age_seconds": source_age_seconds,
            },
        }

    return output


def _http_status_category(status_code: int) -> str:
    if 100 <= status_code < 200:
        return "INFORMATIONAL"
    if 200 <= status_code < 300:
        return "SUCCESS"
    if 300 <= status_code < 400:
        return "REDIRECTION"
    if 400 <= status_code < 500:
        return "CLIENT_ERROR"
    if 500 <= status_code < 600:
        return "SERVER_ERROR"
    return "UNKNOWN"


__all__ = [
    "PROVIDER_EVIDENCE_STALE_SECONDS",
    "ProviderEvidenceRecorder",
    "latest_provider_evidence",
]
