"""Provider gateway discovery, health, capabilities, quota, and evidence endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.session import get_async_session
from ...providers import ProviderRegistry
from ...providers.registry import get_provider_registry
from ...services.provider_evidence_service import (
    PROVIDER_EVIDENCE_STALE_SECONDS,
    latest_provider_evidence,
)

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("")
async def list_providers(
    registry: ProviderRegistry = Depends(get_provider_registry),
) -> dict[str, Any]:
    providers = []
    for provider in registry.list():
        health = await provider.health()
        providers.append(
            {
                "id": provider.provider_id,
                "name": provider.display_name,
                "enabled": health.enabled,
                "configured": health.configured,
                "status": health.status.value,
                "trust_tier": health.trust_tier.value,
                "requires_key": provider.requires_key,
            }
        )
    return {"providers": providers, "generated_at": datetime.now(timezone.utc).isoformat()}


@router.get("/health")
async def providers_health(
    provider: str | None = Query(default=None),
    registry: ProviderRegistry = Depends(get_provider_registry),
) -> dict[str, Any]:
    """Return current configured/probe state from provider objects.

    This remains distinct from `/providers/evidence`, which is backed only by
    durable observations of completed provider operations.
    """
    try:
        rows = [await registry.get(provider).health()] if provider else await registry.health()
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown provider") from exc
    return {
        "providers": [row.model_dump(mode="json") for row in rows],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/evidence")
async def providers_evidence(
    provider: str | None = Query(default=None),
    registry: ProviderRegistry = Depends(get_provider_registry),
    db: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """Return durable provider-operation evidence.

    Zero observations is `UNKNOWN`, never success. This endpoint does not turn a
    configured credential or a successful historical probe into live evidence.
    Evidence older than the deterministic freshness threshold is `STALE` even
    when its historical provider result was VERIFIED.
    """
    if provider:
        try:
            registry.get(provider)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown provider") from exc
        provider_ids = [provider]
    else:
        provider_ids = [item.provider_id for item in registry.list()]

    evidence = await latest_provider_evidence(db, provider_ids)
    return {
        "providers": evidence,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stale_after_seconds": PROVIDER_EVIDENCE_STALE_SECONDS,
        "semantics": {
            "UNKNOWN": "no durable provider-operation observation exists",
            "CONFIGURED": "latest observed result was configured but not live-verified",
            "LIVE_VERIFIED": "latest observed provider operation returned VERIFIED and remains within the freshness threshold",
            "DEGRADED": "latest observed provider operation returned partial/invalid/conflicting evidence",
            "RATE_LIMITED": "latest observed provider operation was rate-limited",
            "STALE": "latest durable provider-operation observation is older than the freshness threshold; its historical status remains available separately",
            "UNAVAILABLE": "latest observed provider operation was unavailable/unconfigured/circuit-open",
        },
    }


@router.get("/capabilities")
async def providers_capabilities(
    provider: str | None = Query(default=None),
    registry: ProviderRegistry = Depends(get_provider_registry),
) -> dict[str, Any]:
    try:
        rows = await registry.get(provider).capabilities() if provider else await registry.capabilities()
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown provider") from exc
    return {
        "capabilities": [row.model_dump(mode="json") for row in rows],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/quota")
async def providers_quota(
    provider: str | None = Query(default=None),
    registry: ProviderRegistry = Depends(get_provider_registry),
) -> dict[str, Any]:
    try:
        if provider:
            quotas = {provider: await registry.get(provider).quota()}
        else:
            quotas = await registry.quota()
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown provider") from exc
    return {
        "quota": {name: quota.model_dump(mode="json") for name, quota in quotas.items()},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
