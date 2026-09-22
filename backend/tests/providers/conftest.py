"""Shared httpx.MockTransport fixture for provider adapter tests.

Each new provider test injects a mocked AsyncClient via BaseProvider's
existing `http_client` constructor param — no monkeypatching needed.
"""

from __future__ import annotations

from typing import Callable

import httpx
import pytest


def make_mock_client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture
def mock_client_factory() -> Callable[
    [Callable[[httpx.Request], httpx.Response]], httpx.AsyncClient
]:
    return make_mock_client
