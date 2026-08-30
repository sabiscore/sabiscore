"""Advanced Insights Service (R4 of v5 directive).

Composes tactical metrics (PPDA, PSxG, xT), contextual data (referee, weather, fatigue),
market intelligence with complete provenance, and certification invariants into a unified
analytical read layer.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..core.cache import cache_manager
from ..db.models import Match, MatchContext, Odds, RefereeProfile
from ..models.active_generation import (
    active_feature_schema_version,
    active_generation_is_certified,
    active_model_version,
)
from ..schemas.advanced_insights import (
    AdvancedMetricsPayload,
    AdvancedInsightsResponse,
    DecisionStatePayload,
    MatchContextPayload,
    ModelIdentityPayload,
    RefereeInsightPayload,
)
from .advanced_metrics import MetricStatus, evaluate_xt
from .market_intel import build_market_intelligence
from .odds_service import OddsService

logger = logging.getLogger(__name__)

_INSIGHTS_CACHE_TTL = 60  # seconds


class AdvancedInsightsService:
    """Service orchestrating advanced metrics, market intelligence, and match context."""

    def __init__(self, odds_service: Optional[OddsService] = None) -> None:
        self.odds_service = odds_service

    async def get_advanced_insights(
        self,
        match_id: str,
        db: AsyncSession,
    ) -> Optional[AdvancedInsightsResponse]:
        """Aggregate all analytical signals for a match into an AdvancedInsightsResponse."""
        cache_key = f"advanced_insights:{match_id}"
        cached = cache_manager.get(cache_key)
        if cached:
            if isinstance(cached, dict):
                return AdvancedInsightsResponse(**cached)
            return cached

        # 1. Fetch match record
        stmt = (
            select(Match)
            .where(Match.id == match_id)
            .options(selectinload(Match.home_team), selectinload(Match.away_team))
        )
        result = await db.execute(stmt)
        match_row = result.scalar_one_or_none()

        if match_row is None:
            return None

        now = datetime.now(timezone.utc)
        kickoff = match_row.match_date
        if kickoff and kickoff.tzinfo is None:
            kickoff = kickoff.replace(tzinfo=timezone.utc)

        # 2. Fetch match context if persisted
        ctx_stmt = select(MatchContext).where(MatchContext.match_id == match_id)
        ctx_res = await db.execute(ctx_stmt)
        match_ctx = ctx_res.scalar_one_or_none()

        # 3. Fetch referee profile if available
        referee_payload: Optional[RefereeInsightPayload] = None
        if match_row.referee:
            ref_stmt = select(RefereeProfile).where(RefereeProfile.name == match_row.referee)
            ref_res = await db.execute(ref_stmt)
            ref_row = ref_res.scalar_one_or_none()
            if ref_row:
                referee_payload = RefereeInsightPayload(
                    name=ref_row.name,
                    avg_yellow_cards=ref_row.avg_yellow_cards,
                    avg_red_cards=ref_row.avg_red_cards,
                    penalties_awarded=ref_row.penalties_awarded,
                    strictness_index=ref_row.strictness_index,
                    sample_size=ref_row.sample_size,
                    source=ref_row.source,
                )
            else:
                referee_payload = RefereeInsightPayload(name=match_row.referee)

        # 4. Compute / assemble Advanced Metrics
        ppda_h = match_ctx.ppda_home if match_ctx else None
        ppda_a = match_ctx.ppda_away if match_ctx else None
        ppda_status = MetricStatus.AVAILABLE.value if (ppda_h is not None or ppda_a is not None) else MetricStatus.ADVISORY_REQUIRES_CORPUS.value

        psxg_h = match_ctx.psxg_home if match_ctx else None
        psxg_a = match_ctx.psxg_away if match_ctx else None
        psxg_status = MetricStatus.AVAILABLE.value if (psxg_h is not None or psxg_a is not None) else MetricStatus.UNAVAILABLE.value

        xt_res = evaluate_xt(event_corpus_available=False, event_count=0)

        advanced_metrics = AdvancedMetricsPayload(
            ppda_home=ppda_h,
            ppda_away=ppda_a,
            ppda_status=ppda_status,
            psxg_home_delta=psxg_h,
            psxg_away_delta=psxg_a,
            psxg_status=psxg_status,
            xt_status=xt_res.status.value,
            xt_home=None,
            xt_away=None,
            xt_reason=xt_res.reason,
        )

        # 5. Assemble Context
        context_payload = MatchContextPayload(
            weather_condition=match_ctx.weather_condition if match_ctx else None,
            weather_source=match_ctx.weather_source if match_ctx else None,
            weather_observed_at=match_ctx.weather_observed_at.isoformat() if match_ctx and match_ctx.weather_observed_at else None,
            fatigue_index_home=match_ctx.fatigue_index_home if match_ctx else None,
            fatigue_index_away=match_ctx.fatigue_index_away if match_ctx else None,
            referee=referee_payload,
        )

        # 6. Model identity & certification state
        try:
            m_ver = active_model_version()
        except Exception:
            m_ver = "v5_phase7"
        try:
            f_schema = active_feature_schema_version()
        except Exception:
            f_schema = "phase7_68"
        try:
            is_cert = active_generation_is_certified()
        except Exception:
            is_cert = False

        cert_state = "CERTIFIED" if is_cert else "UNVERIFIED"

        model_identity = ModelIdentityPayload(
            version=m_ver,
            feature_schema_version=f_schema,
            certification_state=cert_state,
        )

        # 7. Market Intelligence
        market_intel_summary = None
        odds_stmt = (
            select(Odds)
            .where(Odds.match_id == match_id)
            .order_by(Odds.timestamp.desc())
            .limit(1)
        )
        odds_res = await db.execute(odds_stmt)
        odds_row = odds_res.scalars().first()

        if odds_row and odds_row.home_win and odds_row.draw and odds_row.away_win:
            odds_dict = {
                "home_win": float(odds_row.home_win),
                "draw": float(odds_row.draw),
                "away_win": float(odds_row.away_win),
            }
            market_intel_summary = build_market_intelligence(
                odds=odds_dict,
                # ponytail: no model probabilities are linked on this read path, so
                # edge/EV stay None rather than being computed from an invented prior.
                # Wire a real prediction here before trusting any edge from this route.
                model_probabilities=None,
                provider="odds_service",
                bookmaker=getattr(odds_row, "bookmaker", "consensus") or "consensus",
                captured_at=odds_row.timestamp or now,
                is_suspended=False,
                pre_kickoff=bool(kickoff and kickoff > now),
                uncertainty_available=False,
            )

        # 8. Decision State
        decision_state = DecisionStatePayload(
            research_only=not is_cert,
            stake_permitted=False if not is_cert else (market_intel_summary.stake_permitted if market_intel_summary else False),
            verdict="RESEARCH_ONLY" if not is_cert else (market_intel_summary.decision.value if market_intel_summary else "HOLD"),
        )

        response = AdvancedInsightsResponse(
            match_id=match_id,
            home_team=getattr(match_row.home_team, "name", str(match_row.home_team_id or "Home")),
            away_team=getattr(match_row.away_team, "name", str(match_row.away_team_id or "Away")),
            league=match_row.league_id or "unknown",
            kickoff_utc=kickoff.isoformat() if kickoff else None,
            advanced_metrics=advanced_metrics,
            match_context=context_payload,
            market_intelligence=market_intel_summary,
            decision_state=decision_state,
            model_identity=model_identity,
            generated_at=now.isoformat(),
            staleness_seconds=None,
        )

        cache_manager.set(cache_key, response.model_dump(), _INSIGHTS_CACHE_TTL)
        return response
