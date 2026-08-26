"""Concurrency regressions for shared provider transport evidence."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx

from src.providers.base import BaseProvider, ProviderResult, ProviderStatus, TrustTier
from src.providers.registry import ProviderRegistry


class _ConcurrentHTTPProvider(BaseProvider):
    provider_id = "concurrent_http_dummy"
    trust_tier = TrustTier.OFFICIAL_OPEN

    async def fetch(self, name: str) -> ProviderResult:
        payload, _headers = await self._get_json(f"https://provider.test/{name}")
        return ProviderResult(
            provider=self.provider_id,
            operation="fetch",
            status=ProviderStatus.VERIFIED,
            trust_tier=self.trust_tier,
            records=[{"provider_event_id": payload["id"], "coherent": True}],
        )


async def test_shared_provider_keeps_success_status_task_local() -> None:
    """Concurrent calls must not cross-attribute HTTP status observations."""

    async def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        if name == "slow":
            await asyncio.sleep(0.02)
            status_code = 200
        else:
            await asyncio.sleep(0)
            status_code = 201
        return httpx.Response(status_code, json={"id": name}, request=request)

    sink = SimpleNamespace(
        record_result=AsyncMock(return_value=True),
        record_exception=AsyncMock(return_value=True),
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = _ConcurrentHTTPProvider(enabled=True, http_client=client, observation_sink=sink)
    registry = ProviderRegistry([provider])
    assert registry.get("concurrent_http_dummy") is provider

    try:
        slow, fast = await asyncio.gather(provider.fetch("slow"), provider.fetch("fast"))
    finally:
        await client.aclose()

    assert slow.records[0]["provider_event_id"] == "slow"
    assert slow.http_status_code == 200
    assert slow.http_status_category == "SUCCESS"
    assert fast.records[0]["provider_event_id"] == "fast"
    assert fast.http_status_code == 201
    assert fast.http_status_category == "SUCCESS"

    observed = {
        call.args[0].records[0]["provider_event_id"]: call.args[0].http_status_code
        for call in sink.record_result.await_args_list
    }
    assert observed == {"slow": 200, "fast": 201}
    sink.record_exception.assert_not_awaited()
