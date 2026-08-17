"""Provider registration and aggregate gateway operations."""

from __future__ import annotations

import asyncio
import builtins
import inspect
import time
from functools import wraps
from typing import Any, Iterable

import httpx
from fastapi import Request

from ..core.config import settings
from .api_football import APIFootballProvider
from .base import (
    BaseProvider,
    ProviderCapability,
    ProviderHealth,
    ProviderObservationSink,
    ProviderQuota,
    ProviderResult,
)
from .espn import ESPNProvider
from .football_data_org import FootballDataOrgProvider
from .sportmonks import SportmonksProvider
from .the_odds_api import TheOddsAPIProvider


def _returns_provider_result(method: Any) -> bool:
    """Recognize provider operations without a hard-coded method-name list."""
    try:
        annotation = inspect.signature(method).return_annotation
    except (TypeError, ValueError):
        return False
    return "ProviderResult" in str(annotation)


def _instrument_provider(provider: BaseProvider) -> BaseProvider:
    """Wrap public ProviderResult operations in-place, preserving object identity.

    Several call sites and tests legitimately rely on concrete provider type and
    helper attributes, so registry observability must not replace providers with
    proxy objects. Only public async methods whose declared return type is a
    ProviderResult are wrapped; health/capabilities/quota/doctor remain separate
    configuration/diagnostic operations and are not recorded as provider data
    evidence.
    """
    if bool(getattr(provider, "_provider_evidence_instrumented", False)):
        return provider

    for name in dir(provider):
        if name.startswith("_"):
            continue
        attribute = getattr(provider, name)
        if not inspect.iscoroutinefunction(attribute) or not _returns_provider_result(attribute):
            continue

        @wraps(attribute)
        async def observed(
            *args: Any,
            __method: Any = attribute,
            __operation: str = name,
            **kwargs: Any,
        ) -> Any:
            started = time.perf_counter()
            try:
                result = await __method(*args, **kwargs)
            except Exception as exc:
                await provider._observe_exception(
                    __operation,
                    exc,
                    (time.perf_counter() - started) * 1000,
                )
                raise

            if isinstance(result, ProviderResult):
                await provider._observe_result(
                    result,
                    (time.perf_counter() - started) * 1000,
                )
            return result

        setattr(provider, name, observed)

    setattr(provider, "_provider_evidence_instrumented", True)
    return provider


class ProviderRegistry:
    def __init__(self, providers: Iterable[BaseProvider]) -> None:
        # Instrument the actual provider objects instead of introducing a proxy;
        # this preserves isinstance()/identity expectations and all existing
        # provider helper/property access.
        self.providers = [_instrument_provider(provider) for provider in providers]

    def list(self) -> builtins.list[BaseProvider]:
        return list(self.providers)

    def get(self, provider_id: str) -> BaseProvider:
        for provider in self.providers:
            if getattr(provider, "provider_id", None) == provider_id:
                return provider
        raise KeyError(provider_id)

    async def health(self) -> builtins.list[ProviderHealth]:
        return list(await asyncio.gather(*(provider.health() for provider in self.providers)))

    async def capabilities(self) -> builtins.list[ProviderCapability]:
        nested = await asyncio.gather(*(provider.capabilities() for provider in self.providers))
        return [item for group in nested for item in group]

    async def quota(self) -> dict[str, ProviderQuota]:
        values = await asyncio.gather(*(provider.quota() for provider in self.providers))
        return {provider.provider_id: quota for provider, quota in zip(self.providers, values)}

    async def doctor(self, provider_id: str | None = None) -> dict:
        providers = [self.get(provider_id)] if provider_id else self.providers
        reports = await asyncio.gather(*(provider.doctor() for provider in providers))
        return {"providers": reports}


def build_provider_registry(
    http_client: httpx.AsyncClient | None = None,
    observation_sink: ProviderObservationSink | None = None,
) -> ProviderRegistry:
    """Build the canonical provider set.

    `http_client` should be the single application-lifespan client (see
    `app.state.http_client` in `api/main.py`) so providers share one pooled
    connection instead of opening a new client per request. Left optional so
    tests and CLI tools can construct a registry without a running app.

    Provider observation persistence is also injected at this boundary. The
    recorder is stateless and lazily acquires the async DB session only when a
    provider operation finishes, so registry construction can still happen
    before `init_db()` during application lifespan startup.
    """
    if observation_sink is None:
        from ..services.provider_evidence_service import ProviderEvidenceRecorder

        observation_sink = ProviderEvidenceRecorder()

    common = {
        "live_tests": settings.provider_live_tests,
        "http_client": http_client,
        "observation_sink": observation_sink,
    }
    return ProviderRegistry(
        [
            ESPNProvider(
                enabled=settings.enable_espn_provider,
                **common,
            ),
            FootballDataOrgProvider(
                api_key=settings.football_data_api_key,
                enabled=settings.enable_football_data_provider,
                **common,
            ),
            APIFootballProvider(
                api_key=settings.api_football_key,
                enabled=settings.enable_api_football_provider,
                **common,
            ),
            SportmonksProvider(
                api_key=settings.sportmonks_api_key,
                enabled=settings.enable_sportmonks_provider,
                **common,
            ),
            TheOddsAPIProvider(
                api_key=settings.the_odds_api_key,
                enabled=settings.enable_the_odds_api_provider,
                **common,
            ),
        ]
    )


def get_provider_registry(request: Request) -> ProviderRegistry:
    """FastAPI dependency returning the lifespan-owned registry from app.state.

    Use via `Depends(get_provider_registry)` in endpoints instead of calling
    `build_provider_registry()` directly, so requests share the one pooled
    httpx client created at startup.
    """
    return request.app.state.provider_registry
