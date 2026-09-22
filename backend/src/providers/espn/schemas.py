"""ESPN response schemas and the normalized SabiScore envelope.

Two layers live here:

1. **Wire schemas** (``Espn*``) validate the *shape* of ESPN's untrusted JSON.
   They are deliberately strict: ``extra="ignore"`` so ESPN can add fields, but
   required fields must be present and correctly typed. A drift in a required
   field raises ``EspnSchemaError`` and the provider fails closed.

2. **Normalized contracts** (``NormalizedFixture``, ``ProviderEnvelope``) are the
   only thing the rest of SabiScore consumes. They preserve provider IDs,
   separate ``kickoff_utc`` from ``provider_timestamp``, and stamp acquisition
   time + a snapshot hash for audit.

ESPN is UNOFFICIAL_PUBLIC / SUPPLEMENTARY_ONLY / KEYLESS. Nothing here may be
treated as critical odds, lineup, injury, probability, or execution evidence.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class EspnSchemaError(ValueError):
    """ESPN response failed contract validation. The provider must fail closed."""


# --------------------------------------------------------------------------- #
# Trust + status semantics (canonical authority: production certificate §6.1)
# --------------------------------------------------------------------------- #


class TrustTier(str, Enum):
    UNOFFICIAL_PUBLIC = "UNOFFICIAL_PUBLIC"
    OFFICIAL_AUTHENTICATED = "OFFICIAL_AUTHENTICATED"


class ProviderStatus(str, Enum):
    """A health response may claim HEALTHY only after a successful probe."""

    DISABLED = "DISABLED"
    CONFIGURED = "CONFIGURED"  # enabled, not yet probed
    HEALTHY = "HEALTHY"  # successful probe within validity window
    DEGRADED = "DEGRADED"
    RATE_LIMITED = "RATE_LIMITED"
    SCHEMA_INVALID = "SCHEMA_INVALID"
    UNAVAILABLE = "UNAVAILABLE"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"


# --------------------------------------------------------------------------- #
# ESPN wire schemas (untrusted input — validate strictly, fail closed)
# --------------------------------------------------------------------------- #


class _Wire(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class EspnTeamRef(_Wire):
    id: str
    display_name: str = Field(alias="displayName")
    abbreviation: str | None = None


class EspnCompetitor(_Wire):
    home_away: str = Field(alias="homeAway")
    team: EspnTeamRef

    @field_validator("home_away")
    @classmethod
    def _known_side(cls, v: str) -> str:
        if v not in {"home", "away"}:
            raise ValueError(f"unexpected homeAway value {v!r}")
        return v


class EspnStatusType(_Wire):
    name: str
    completed: bool | None = None


class EspnStatus(_Wire):
    type: EspnStatusType


class EspnCompetition(_Wire):
    competitors: list[EspnCompetitor]

    @field_validator("competitors")
    @classmethod
    def _exactly_two(cls, v: list[EspnCompetitor]) -> list[EspnCompetitor]:
        if len(v) != 2:
            raise ValueError(f"expected 2 competitors, got {len(v)}")
        sides = {c.home_away for c in v}
        if sides != {"home", "away"}:
            raise ValueError(f"competitors must be one home + one away, got {sides}")
        return v


class EspnEvent(_Wire):
    id: str
    date: str  # ISO-8601 kickoff in UTC (e.g. 2026-06-26T18:00Z)
    status: EspnStatus
    competitions: list[EspnCompetition]

    @field_validator("competitions")
    @classmethod
    def _at_least_one(cls, v: list[EspnCompetition]) -> list[EspnCompetition]:
        if not v:
            raise ValueError("event has no competitions")
        return v


class EspnScoreboard(_Wire):
    events: list[EspnEvent] = Field(default_factory=list)


def parse_scoreboard(raw: dict[str, Any]) -> EspnScoreboard:
    """Validate a raw ESPN scoreboard payload. Raises EspnSchemaError on drift."""
    try:
        return EspnScoreboard.model_validate(raw)
    except ValidationError as exc:
        raise EspnSchemaError(
            f"ESPN scoreboard failed contract validation: {exc.error_count()} errors"
        ) from exc


# --------------------------------------------------------------------------- #
# Normalized SabiScore contracts (the only thing downstream consumes)
# --------------------------------------------------------------------------- #


class NormalizedFixture(BaseModel):
    """A single ESPN fixture, normalized and audit-stamped.

    ``provider_*_id`` are preserved for canonical reconciliation; they are NOT
    user-facing names. ``kickoff_utc`` is the match start; ``provider_timestamp``
    is ESPN's content timestamp (or None — ESPN scoreboards rarely carry one),
    and ``acquired_at`` is when SabiScore fetched it.
    """

    model_config = ConfigDict(frozen=True)

    provider: str = "espn"
    provider_event_id: str
    competition: str
    kickoff_utc: datetime
    status: str
    provider_home_team_id: str
    provider_away_team_id: str
    provider_home_team_name: str
    provider_away_team_name: str
    provider_timestamp: datetime | None
    acquired_at: datetime


class ProviderEnvelope(BaseModel):
    """Standard redacted provider envelope returned to the gateway.

    Mirrors the documented envelope: trust tier, status, quota, warnings,
    snapshot hash, acquired timestamp. ESPN is keyless so ``quota`` is null.
    """

    model_config = ConfigDict(frozen=True)

    provider: str = "espn"
    trust_tier: TrustTier = TrustTier.UNOFFICIAL_PUBLIC
    status: ProviderStatus
    competition: str | None = None
    fixtures: tuple[NormalizedFixture, ...] = ()
    quota: dict[str, Any] | None = None  # ESPN is keyless → no quota headers
    warnings: tuple[str, ...] = ()
    snapshot_hash: str | None = None
    acquired_at: datetime
    correlation_id: str | None = None


def snapshot_hash(raw: dict[str, Any]) -> str:
    """Deterministic content hash of a raw provider payload for audit/dedup."""
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def utcnow() -> datetime:
    """Timezone-aware UTC now. Injected acquisition timestamp source."""
    return datetime.now(timezone.utc)
