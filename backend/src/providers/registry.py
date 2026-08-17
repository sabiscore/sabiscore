"""Provider registration and aggregate gateway operations."""

from __future__ import annotations

import asyncio
import builtins
from typing import Iterable

import httpx
from fastapi import Request

from ..core.config import settings
from .api_football import APIFootballProvider
from .base import BaseProvider, ProviderCapability, ProviderHealth, ProviderObservationSink, ProviderQuota
from .espn import ESPNProvider
from .football_data_org import FootballDataOrgProvider
from .sportmonks import SportmonksProvider
from .the_odds_api import TheOddsAPIProvider


class ProviderRegistry:
    def __init__(self, providers: Iterable[BaseProvider]) -> None:
        self.providers = list(providers)

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
