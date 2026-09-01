"""Multi-provider ingestion coordinator service with quota budgeting and schedule-aware priority."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ..providers.base import BaseProvider
from ..providers.orchestrator import EvidenceOrchestrator, EvidenceProfile

logger = logging.getLogger(__name__)


@dataclass
class ProviderQuotaBudget:
    provider: str
    daily_limit: int
    minute_limit: int
    used_today: int = 0
    used_this_minute: int = 0
    last_reset_minute: float = 0.0
    is_exhausted: bool = False


@dataclass
class EnrichmentTask:
    match_id: str
    kickoff_utc: datetime
    profile: EvidenceProfile
    priority: int = 0  # higher = more urgent
    status: str = "PENDING"
    attempt_count: int = 0


class IngestionCoordinatorService:
    """Coordinates enrichment tasks across provider adapters while respecting rate/quota budgets."""

    DEFAULT_BUDGETS = {
        "football-data.org": ProviderQuotaBudget("football-data.org", daily_limit=1000, minute_limit=10),
        "the_odds_api": ProviderQuotaBudget("the_odds_api", daily_limit=500, minute_limit=30),
        "sportmonks": ProviderQuotaBudget("sportmonks", daily_limit=2000, minute_limit=60),
        "api-football": ProviderQuotaBudget("api-football", daily_limit=100, minute_limit=10),
        "espn": ProviderQuotaBudget("espn", daily_limit=10000, minute_limit=120),
    }

    def __init__(
        self,
        providers: Optional[Dict[str, BaseProvider]] = None,
        orchestrator: Optional[EvidenceOrchestrator] = None,
    ) -> None:
        self.providers = providers or {}
        self.orchestrator = orchestrator
        self.budgets: Dict[str, ProviderQuotaBudget] = dict(self.DEFAULT_BUDGETS)
        self.queue: List[EnrichmentTask] = []

    def can_dispatch_provider(self, provider_name: str) -> bool:
        """Check whether a provider has sufficient quota budget."""
        budget = self.budgets.get(provider_name)
        if not budget:
            return True
        if budget.is_exhausted or budget.used_today >= budget.daily_limit:
            return False
        return True

    def record_provider_usage(self, provider_name: str, cost: int = 1) -> None:
        budget = self.budgets.get(provider_name)
        if budget:
            budget.used_today += cost
            budget.used_this_minute += cost
            if budget.used_today >= budget.daily_limit:
                budget.is_exhausted = True

    def schedule_fixture_enrichment(
        self, match_id: str, kickoff_utc: datetime, profile: EvidenceProfile
    ) -> EnrichmentTask:
        """Calculate urgency priority based on kickoff proximity and enqueue task."""
        now = datetime.now(timezone.utc)
        if kickoff_utc.tzinfo is None:
            kickoff_aware = kickoff_utc.replace(tzinfo=timezone.utc)
        else:
            kickoff_aware = kickoff_utc

        seconds_until_kickoff = (kickoff_aware - now).total_seconds()
        # Urgent (< 2 hours): priority 100
        # Soon (< 6 hours): priority 50
        # Upcoming (< 24 hours): priority 20
        # Future: priority 5
        if seconds_until_kickoff <= 7200:
            priority = 100
        elif seconds_until_kickoff <= 21600:
            priority = 50
        elif seconds_until_kickoff <= 86400:
            priority = 20
        else:
            priority = 5

        task = EnrichmentTask(
            match_id=match_id,
            kickoff_utc=kickoff_aware,
            profile=profile,
            priority=priority,
        )
        self.queue.append(task)
        self.queue.sort(key=lambda t: t.priority, reverse=True)
        return task

    async def orchestrate_enrichment(
        self,
        match_id: str,
        profile: EvidenceProfile,
        session: AsyncSession,
    ) -> Dict[str, Any]:
        """Execute coordinated enrichment for a fixture within quota boundaries."""
        if not self.orchestrator:
            return {
                "match_id": match_id,
                "status": "SKIPPED",
                "reason": "orchestrator_unavailable",
                "profile": profile.value,
            }

        # Check provider availability
        available_providers = [
            p_name for p_name in self.providers if self.can_dispatch_provider(p_name)
        ]

        logger.info(
            "IngestionCoordinator orchestrating match %s (profile=%s, providers=%s)",
            match_id,
            profile.value,
            available_providers,
        )

        try:
            # Delegate to orchestrator
            evidence = await self.orchestrator.gather_evidence(
                match_id=match_id,
                profile=profile,
                session=session,
            )
            return {
                "match_id": match_id,
                "status": "COMPLETED",
                "profile": profile.value,
                "evidence_status": evidence.get("status", "OK"),
                "providers_consulted": available_providers,
            }
        except Exception as exc:
            logger.warning("IngestionCoordinator error for match %s: %s", match_id, exc)
            return {
                "match_id": match_id,
                "status": "FAILED",
                "error": str(exc),
                "profile": profile.value,
            }
