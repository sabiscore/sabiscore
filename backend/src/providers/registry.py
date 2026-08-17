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


def _annotation_contains_provider_result(annotation: Any) -> bool:
    """Return whether a resolved annotation contains ProviderResult."""
    if annotation is ProviderResult:
        return True
    return any(_annotation_contains_provider_result(arg) for arg in get_args(annotation))


def _returns_provider_result(method: Any) -> bool:
    """Recognize ProviderResult operations using resolved type hints.

    Provider modules use postponed annotations, so inspecting the raw signature
    can yield strings instead of runtime types. ``get_type_hints`` resolves those
    annotations against the declaring module and lets instrumentation fail closed
    when a method cannot be resolved.
    """
    try:
        annotation = get_type_hints(method).get("return")
    except (NameError, TypeError):
        return False
    return _annotation_contains_provider_result(annotation)


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

        # Preserve useful diagnostics without functools.wraps' ParamSpec typing
        # fighting this intentionally dynamic instance-level instrumentation.
        observed.__name__ = getattr(attribute, "__name__", name)
        observed.__doc__ = getattr(attribute, "__doc__", None)
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

    return ProviderRegistry(
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


def get_provider_registry(request: Request) -> ProviderRegistry:
    """FastAPI dependency returning the lifespan-owned registry from app.state.

    Use via `Depends(get_provider_registry)` in endpoints instead of calling
    `build_provider_registry()` directly, so requests share the one pooled
    httpx client created at startup.
    """
    return request.app.state.provider_registry
