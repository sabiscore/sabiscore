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
from typing import Any, Iterable, Mapping

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

# Context is intentionally tiny and whitelisted. Providers may attach only these
# non-secret request dimensions; everything else is dropped before persistence.
_PROVIDER_REQUEST_CONTEXT_KEYS = (
    "competition",
    "query_intent",
    "match_status",
    "date_from",
    "date_to",
    "season",
    "market_type",
)
# A context-aware health surface needs only the latest observation per small set
# of operation/competition/intent streams. Bound the query so telemetry cannot
# turn a health request into an unbounded historical scan.
_PROVIDER_CONTEXT_LOOKBACK_PER_PROVIDER = 128


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


def _safe_request_context(values: Mapping[str, object] | None) -> dict[str, str]:
    if not isinstance(values, Mapping):
        return {}
    context: dict[str, str] = {}
    for key in _PROVIDER_REQUEST_CONTEXT_KEYS:
        value = values.get(key)
        if value is None:
            continue
        normalized = redact_text(value).strip()[:100]
        if normalized:
            context[key] = normalized
    return context


def _evidence_state(
    status: str | None,
    *,
    transport: Mapping[str, object] | None = None,
    coverage: Mapping[str, object] | None = None,
) -> str:
    """Map one observation to operational state without hiding data coverage.

    A successful HTTP request returning zero records is real provider liveness and
    real EMPTY coverage at the same time. Treating that as provider-wide failure
    caused the final UCL/FINISHED request in a multi-competition cycle to erase
    six successful requests. EMPTY remains explicit in ``coverage``/``contexts``;
    transport availability is not fabricated from record count.
    """
    normalized = str(status or "").upper()
    if normalized == ProviderStatus.VERIFIED.value:
        return "LIVE_VERIFIED"
    if normalized == ProviderStatus.CONFIGURED_UNVERIFIED.value:
        return "CONFIGURED"
    if normalized == ProviderStatus.RATE_LIMITED.value:
        return "RATE_LIMITED"
    if normalized == ProviderStatus.PARTIAL.value:
        transport_outcome = str((transport or {}).get("outcome") or "").upper()
        coverage_state = str((coverage or {}).get("state") or "").upper()
        if transport_outcome == "SUCCESS" and coverage_state == "EMPTY":
            return "LIVE_VERIFIED"
        return "DEGRADED"
    if normalized in {
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
        for record in coherent
        if has_coherent
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
        for key in (
            "bookmaker_last_update",
            "source_updated_at",
            "provider_timestamp",
            "last_update",
        ):
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


def _default_transport() -> dict[str, Any]:
    return {
        "outcome": "UNKNOWN",
        "http_status_code": None,
        "http_status_category": None,
    }


def _default_coverage(record_count: object = None) -> dict[str, Any]:
    return {
        "state": "UNKNOWN",
        "basis": None,
        "total_records": record_count,
        "coherent_records": None,
        "executable_records": None,
        "usable_records": None,
        "total_events": None,
        "coherent_events": None,
        "executable_events": None,
        "usable_events": None,
        "settled_records": None,
    }


def _default_quota() -> dict[str, Any]:
    return {
        "observed": False,
        "limit": None,
        "remaining": None,
        "reset_at": None,
        "cost": None,
        "rate_limited": False,
    }


def _materialize_evidence_row(
    row: Mapping[str, Any],
    *,
    reference_now: datetime,
    stale_after_seconds: int,
) -> dict[str, Any]:
    checked_at = row.get("checked_at")
    age_seconds = None
    if isinstance(checked_at, datetime):
        checked_at_utc = _utc_naive(checked_at)
        if checked_at_utc is not None:
            age_seconds = max(0.0, (reference_now - checked_at_utc).total_seconds())

    details_raw = row.get("details")
    details = details_raw if isinstance(details_raw, dict) else {}
    transport_raw = details.get("transport")
    transport = transport_raw if isinstance(transport_raw, dict) else _default_transport()
    coverage_raw = details.get("coverage")
    coverage = (
        coverage_raw
        if isinstance(coverage_raw, dict)
        else _default_coverage(details.get("record_count"))
    )
    quota_raw = details.get("quota")
    quota = quota_raw if isinstance(quota_raw, dict) else _default_quota()
    if not isinstance(quota_raw, dict):
        quota["observed"] = bool(details.get("quota_observed"))
        quota["rate_limited"] = (
            str(row.get("status") or "").upper() == ProviderStatus.RATE_LIMITED.value
        )

    state = _evidence_state(row.get("status"), transport=transport, coverage=coverage)
    is_stale = age_seconds is not None and age_seconds > stale_after_seconds
    if is_stale:
        state = "STALE"

    source_latest_at = _parse_datetime(details.get("source_latest_at"))
    source_age_seconds = (
        max(0.0, (reference_now - source_latest_at).total_seconds())
        if source_latest_at is not None
        else None
    )
    request_context_raw = details.get("request_context")
    request_context = _safe_request_context(
        request_context_raw if isinstance(request_context_raw, Mapping) else None
    )

    return {
        "state": state,
        "status": row.get("status"),
        "last_observed_at": (
            checked_at.isoformat() if isinstance(checked_at, datetime) else None
        ),
        "age_seconds": age_seconds,
        "stale_after_seconds": stale_after_seconds,
        "latency_ms": row.get("latency_ms"),
        "operation": details.get("operation"),
        "request_context": request_context,
        "error_code": row.get("error_code"),
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


def _context_identity(evidence: Mapping[str, Any]) -> tuple[str, str, str, str] | None:
    context_raw = evidence.get("request_context")
    if not isinstance(context_raw, Mapping) or not context_raw:
        return None
    operation = str(evidence.get("operation") or "")
    competition = str(context_raw.get("competition") or "")
    query_intent = str(context_raw.get("query_intent") or "")
    match_status = str(context_raw.get("match_status") or "")
    if not any((competition, query_intent, match_status)):
        return None
    return operation, competition, query_intent, match_status


def _aggregate_context_state(contexts: Iterable[Mapping[str, Any]]) -> str:
    states = [str(context.get("state") or "UNKNOWN") for context in contexts]
    if not states:
        return "UNKNOWN"
    if "RATE_LIMITED" in states:
        return "RATE_LIMITED"
    if all(state == "LIVE_VERIFIED" for state in states):
        return "LIVE_VERIFIED"
    if all(state == "STALE" for state in states):
        return "STALE"
    if all(state == "UNAVAILABLE" for state in states):
        return "UNAVAILABLE"
    if all(state == "CONFIGURED" for state in states):
        return "CONFIGURED"
    if all(state == "UNKNOWN" for state in states):
        return "UNKNOWN"
    return "DEGRADED"


def _aggregate_context_coverage(contexts: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(contexts)
    coverage_states = [
        str((row.get("coverage") or {}).get("state") or "UNKNOWN")
        if isinstance(row.get("coverage"), Mapping)
        else "UNKNOWN"
        for row in rows
    ]
    usable = coverage_states.count("USABLE")
    empty = coverage_states.count("EMPTY")
    unusable = coverage_states.count("UNUSABLE")
    unknown = coverage_states.count("UNKNOWN")
    if rows and usable == len(rows):
        state = "USABLE"
    elif usable > 0:
        state = "PARTIAL"
    elif unusable > 0:
        state = "UNUSABLE"
    elif empty > 0 and unknown == 0:
        state = "EMPTY"
    else:
        state = "UNKNOWN"
    return {
        "state": state,
        "contexts": len(rows),
        "usable_contexts": usable,
        "empty_contexts": empty,
        "unusable_contexts": unusable,
        "unknown_contexts": unknown,
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
        request_context = _safe_request_context(result.request_context)
        error_code = redact_text(result.error_code)[:255] if result.error_code else None
        raw_snapshot_id = (
            redact_text(result.raw_snapshot_id)[:255]
            if result.raw_snapshot_id
            else None
        )
        acquired_at = _utc_naive(result.acquired_at) or datetime.now(timezone.utc).replace(
            tzinfo=None
        )
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
                "request_context": request_context,
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
                "request_context": request_context,
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
    """Return persisted provider evidence with deterministic freshness/context.

    Zero observations is explicitly UNKNOWN. Configuration state is intentionally
    not consulted here: this surface answers what has actually been observed.
    Request-context streams are aggregated independently so one final empty UCL
    or FINISHED request cannot replace evidence from every other competition.
    EMPTY coverage remains visible and is never re-labeled as fixture coverage.
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
            "request_context": {},
            "contexts": [],
            "context_count": 0,
            "coverage_summary": {
                "state": "UNKNOWN",
                "contexts": 0,
                "usable_contexts": 0,
                "empty_contexts": 0,
                "unusable_contexts": 0,
                "unknown_contexts": 0,
            },
            "error_code": None,
            "transport": _default_transport(),
            "coverage": _default_coverage(),
            "quota": _default_quota(),
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
            ProviderHealthLog.id.label("id"),
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
    reference_now = _utc_naive(now or datetime.now(timezone.utc))
    if reference_now is None:  # defensive; the expression above is always a datetime
        raise RuntimeError("unable to derive provider evidence reference time")

    latest_result = await session.execute(select(ranked).where(ranked.c.rn == 1))
    for row in latest_result.mappings().all():
        provider = str(row["provider"])
        latest = _materialize_evidence_row(
            row,
            reference_now=reference_now,
            stale_after_seconds=stale_after_seconds,
        )
        output[provider].update(latest)
        output[provider]["observations"] = int(counts.get(provider, 0))

    # Retain a bounded recent slice per provider, then select the newest row per
    # stable context identity in Python. Date windows remain visible metadata but
    # are deliberately excluded from identity so each scheduled/results stream
    # evolves instead of creating an unbounded new context on every day.
    recent_result = await session.execute(
        select(ranked).where(ranked.c.rn <= _PROVIDER_CONTEXT_LOOKBACK_PER_PROVIDER)
    )
    contexts_by_provider: dict[
        str,
        dict[tuple[str, str, str, str], tuple[int, dict[str, Any]]],
    ] = {provider: {} for provider in provider_list}
    for row in recent_result.mappings().all():
        provider = str(row["provider"])
        evidence = _materialize_evidence_row(
            row,
            reference_now=reference_now,
            stale_after_seconds=stale_after_seconds,
        )
        identity = _context_identity(evidence)
        if identity is None:
            continue
        rank = int(row["rn"])
        current = contexts_by_provider[provider].get(identity)
        if current is None or rank < current[0]:
            contexts_by_provider[provider][identity] = (rank, evidence)

    for provider, context_map in contexts_by_provider.items():
        contexts = [entry[1] for entry in context_map.values()]
        contexts.sort(
            key=lambda row: (
                str(row.get("operation") or ""),
                str((row.get("request_context") or {}).get("competition") or ""),
                str((row.get("request_context") or {}).get("query_intent") or ""),
                str((row.get("request_context") or {}).get("match_status") or ""),
            )
        )
        output[provider]["contexts"] = contexts
        output[provider]["context_count"] = len(contexts)
        output[provider]["coverage_summary"] = _aggregate_context_coverage(contexts)
        if contexts:
            output[provider]["state"] = _aggregate_context_state(contexts)

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
