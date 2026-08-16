"""Regression tests for caught DB failures and session finalization."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_get_db_session_rolls_back_partial_transaction_instead_of_committing() -> None:
    from src.db import session as session_module

    class FakeSession:
        is_active = False

        def __init__(self) -> None:
            self.commit = AsyncMock()
            self.rollback = AsyncMock()
            self.close = AsyncMock()

        def in_transaction(self) -> bool:
            return True

    fake = FakeSession()

    with patch.object(session_module, "AsyncSessionLocal", new=lambda: fake):
        async with session_module.get_db_session() as yielded:
            assert yielded is fake

    fake.rollback.assert_awaited_once()
    fake.commit.assert_not_awaited()
    fake.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_db_session_commits_healthy_transaction() -> None:
    from src.db import session as session_module

    class FakeSession:
        is_active = True

        def __init__(self) -> None:
            self.commit = AsyncMock()
            self.rollback = AsyncMock()
            self.close = AsyncMock()

        def in_transaction(self) -> bool:
            return True

    fake = FakeSession()

    with patch.object(session_module, "AsyncSessionLocal", new=lambda: fake):
        async with session_module.get_db_session():
            pass

    fake.commit.assert_awaited_once()
    fake.rollback.assert_not_awaited()
    fake.close.assert_awaited_once()
