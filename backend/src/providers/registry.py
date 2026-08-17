"""Provider registration and aggregate gateway operations."""

from __future__ import annotations

import asyncio
import builtins
import inspect
import time
from typing import Any, Iterable, get_args, get_type_hints

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

_RUNTIME_PROVIDER_REGISTRY: "ProviderRegistry | None" = None


def _annotation_contains_provider_result(annotation: Any) -> bool:
    """Return whether a resolved annotation contains ProviderResult."""
    if annotation is ProviderResult:
        return True
    return any(_annotation_contains_provider_result(arg) for arg in get_args(annotation))


def _returns_provider_result(method: Any) -> bool:
    """Recognize ProviderResult operations using resolved type hints."""
    try:
        annotation = get_type_hints(method).get("return")
    except (NameError, TypeError):
        return False
    return _annotation_contains_provider_result(annotation)


def _instrument_provider(provider: BaseProvider) -> BaseProvider:
    """Wrap public ProviderResult operations in-place, preserving object identity."""
    if bool(getattr(provider, "_provider_evidence_instrumented", False)):
        return provider

    for name in dir(provider):
        if name.startswith("_"):
            continue
        attribute = getattr(provider, name)
        if not inspect.iscoroutinefunction(attribute) or not _returns_provider_result(attribute):
            continue

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

        observed.__name__ = getattr(attribute, "__name__", name)
        observed.__doc__ = getattr(attribute, "__doc__", None)
        setattr(provider, name, observed)

    setattr(provider, "_provider_evidence_instrumented", True)
    return provider


class ProviderRegistry:
    def __init__(self, providers: Iterable[BaseProvider]) -> None:
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

    When a shared ``http_client`` is supplied, this is the application-lifespan
    registry. Keep its identity available to background jobs that are not FastAPI
    request handlers; they must never open an independent provider transport.
    """
    global _RUNTIME_PROVIDER_REGISTRY

    if observation_sink is None:
        from ..services.provider_evidence_service import ProviderEvidenceRecorder

        observation_sink = ProviderEvidenceRecorder()

    registry = ProviderRegistry(
        [
            ESPNProvider(
                enabled=settings.enable_espn_provider,
                live_tests=settings.provider_live_tests,
                http_client=http_client,
                observation_sink=observation_sink,
            ),
            FootballDataOrgProvider(
                api_key=settings.football_data_api_key,
                enabled=settings.enable_football_data_provider,
                live_tests=settings.provider_live_tests,
                http_client=http_client,
                observation_sink=observation_sink,
            ),
            APIFootballProvider(
                api_key=settings.api_football_key,
                enabled=settings.enable_api_football_provider,
                live_tests=settings.provider_live_tests,
                http_client=http_client,
                observation_sink=observation_sink,
            ),
            SportmonksProvider(
                api_key=settings.sportmonks_api_key,
                enabled=settings.enable_sportmonks_provider,
                live_tests=settings.provider_live_tests,
                http_client=http_client,
                observation_sink=observation_sink,
            ),
            TheOddsAPIProvider(
                api_key=settings.the_odds_api_key,
                enabled=settings.enable_the_odds_api_provider,
                live_tests=settings.provider_live_tests,
                http_client=http_client,
                observation_sink=observation_sink,
            ),
        ]
    )
    if http_client is not None:
        _RUNTIME_PROVIDER_REGISTRY = registry
    return registry


def get_runtime_provider(provider_id: str) -> BaseProvider:
    """Return the provider owned by the active application lifespan.

    Background workers run outside a request context, so they cannot use the
    FastAPI dependency. Failing closed here prevents an accidental fallback to a
    second HTTP client if lifespan initialization has not established the gateway.
    """
    registry = _RUNTIME_PROVIDER_REGISTRY
    if registry is None:
        raise RuntimeError("lifespan provider registry is not initialized")
    return registry.get(provider_id)


def get_provider_registry(request: Request) -> ProviderRegistry:
    """FastAPI dependency returning the lifespan-owned registry from app.state."""
    return request.app.state.provider_registry
