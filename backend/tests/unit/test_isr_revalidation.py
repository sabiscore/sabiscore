import logging

import pytest

from src.api import websocket


@pytest.mark.asyncio
async def test_isr_revalidation_skips_http_without_shared_secret(monkeypatch, caplog):
    def unexpected_client_session():
        raise AssertionError("ISR must not open an HTTP session without a shared secret")

    monkeypatch.setattr(websocket.settings, "revalidate_secret", None)
    monkeypatch.setattr(websocket.aiohttp, "ClientSession", unexpected_client_session)

    with caplog.at_level(logging.WARNING):
        await websocket.trigger_isr_revalidation("fixture-123")

    assert "REVALIDATE_SECRET is not configured" in caplog.text