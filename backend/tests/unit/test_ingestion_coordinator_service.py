"""Unit tests for multi-provider ingestion coordinator service and quota budgeting."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
import pytest

from src.providers.orchestrator import EvidenceProfile
from src.services.ingestion_coordinator import IngestionCoordinatorService


def test_ingestion_coordinator_quota_budgeting() -> None:
    service = IngestionCoordinatorService()

    # Initial state: can dispatch
    assert service.can_dispatch_provider("football-data.org") is True

    # Record usage
    service.record_provider_usage("football-data.org", cost=100)
    assert service.budgets["football-data.org"].used_today == 100
    assert service.can_dispatch_provider("football-data.org") is True

    # Exhaust budget
    service.record_provider_usage("football-data.org", cost=950)
    assert service.can_dispatch_provider("football-data.org") is False


def test_ingestion_coordinator_priority_scheduling() -> None:
    service = IngestionCoordinatorService()
    now = datetime.now(timezone.utc)

    # Fixture in 1 hour (urgent, priority 100)
    task1 = service.schedule_fixture_enrichment(
        match_id="m1",
        kickoff_utc=now + timedelta(hours=1),
        profile=EvidenceProfile.PREMATCH_STANDARD,
    )
    assert task1.priority == 100

    # Fixture in 12 hours (upcoming, priority 20)
    task2 = service.schedule_fixture_enrichment(
        match_id="m2",
        kickoff_utc=now + timedelta(hours=12),
        profile=EvidenceProfile.PREMATCH_STANDARD,
    )
    assert task2.priority == 20

    # Fixture in 3 days (future, priority 5)
    task3 = service.schedule_fixture_enrichment(
        match_id="m3",
        kickoff_utc=now + timedelta(days=3),
        profile=EvidenceProfile.DISCOVERY,
    )
    assert task3.priority == 5

    # Enqueued tasks are sorted with highest priority first
    assert service.queue[0].match_id == "m1"
    assert service.queue[1].match_id == "m2"
    assert service.queue[2].match_id == "m3"


@pytest.mark.asyncio
async def test_orchestrate_enrichment_delegation() -> None:
    mock_orchestrator = AsyncMock()
    mock_orchestrator.gather_evidence.return_value = {"status": "VERIFIED"}

    service = IngestionCoordinatorService(
        providers={"football-data.org": MagicMock()},
        orchestrator=mock_orchestrator,
    )

    db = AsyncMock()
    result = await service.orchestrate_enrichment(
        match_id="fd-1234",
        profile=EvidenceProfile.PREMATCH_STANDARD,
        session=db,
    )

    assert result["status"] == "COMPLETED"
    assert result["evidence_status"] == "VERIFIED"
    mock_orchestrator.gather_evidence.assert_awaited_once_with(
        match_id="fd-1234",
        profile=EvidenceProfile.PREMATCH_STANDARD,
        session=db,
    )
