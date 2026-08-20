"""Provider identity bridge to the Elo-bearing application Team domain.

Canonical identity and legacy/application team identity are deliberately
separate domains in SabiScore. ``ProviderTeamMapping`` anchors provider IDs to
``canonical_teams``; durable Elo, fixtures and serving features are keyed by
``core.database.Team``. This model supplies the missing explicit bridge without
reinterpreting the canonical mapping table.

Rows are created only when the target Team has real durable Elo history in the
same competition. Genuinely new/history-free clubs therefore remain unbridged
instead of being treated as resolved through a neutral/default rating.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base


class ProviderEloTeamMapping(Base):
    __tablename__ = "provider_elo_team_mappings"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_team_id",
            "competition",
            name="uq_provider_elo_team_identity",
        ),
        Index("ix_provider_elo_team_provider_id", "provider", "provider_team_id"),
        Index("ix_provider_elo_team_team_id", "team_id"),
        {"extend_existing": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    provider_team_id: Mapped[str] = mapped_column(String, nullable=False)
    provider_team_name: Mapped[str] = mapped_column(String, nullable=False)
    competition: Mapped[str] = mapped_column(String, nullable=False)
    team_id: Mapped[str] = mapped_column(String, ForeignKey("teams.id"), nullable=False)
    reconciliation_status: Mapped[str] = mapped_column(String, nullable=False)
    reconciliation_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


__all__ = ["ProviderEloTeamMapping"]
