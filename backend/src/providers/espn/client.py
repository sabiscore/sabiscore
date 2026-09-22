"""ESPN provider client — canonical SabiScore provider gateway adapter.

Placement: ``backend/src/providers/espn/`` (not scraper or legacy API app code).

This client is the operational ESPN integration. It is keyless, supplementary,
and discovery/readiness-only. It does NOT compute probabilities, verdicts, EV,
Kelly stakes, or model features — those are the strict engine's exclusive
authority. It supplies fixture discovery and event status to the evidence
orchestrator, where ESPN sits at the lowest precedence and can never alone
establish critical odds, lineup, injury, or probability evidence.

Integration seams (dependency-injected by the gateway lifespan):
  * ``http`` — a shared ``httpx.AsyncClient`` (connection pooling, lifespan-owned)
  * ``breaker`` — a ``CircuitBreaker`` implementing the documented failure
    taxonomy; ESPN reuses the gateway's persistent circuit state
  * ``clock`` — injected UTC source for deterministic acquisition timestamps

The client never logs raw URLs with query strings, never logs response bodies
at info level, and emits structured, redacted records only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Protocol

import httpx

from .mappings import (
    Competition,
    UnsupportedCompetitionError,
    espn_slug,
    supported_competitions,
)
from .schemas import (
    EspnEvent,
    EspnSchemaError,
    NormalizedFixture,
    ProviderEnvelope,
    ProviderStatus,
    TrustTier,
    parse_scoreboard,
    snapshot_hash,
    utcnow,
)

logger = logging.getLogger("sabiscore.providers.espn")

_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
_DEFAULT_TIMEOUT = httpx.Timeout(connect=3.0, read=8.0, write=3.0, pool=3.0)
_ALLOWED_HOST = "site.api.espn.com"


# --------------------------------------------------------------------------- #
# Circuit breaker contract (implemented by the gateway; ESPN only consumes it)
# --------------------------------------------------------------------------- #


class CircuitOpenError(RuntimeError):
    """Raised by the breaker when the circuit is open for ESPN."""


class CircuitBreaker(Protocol):
    """Minimal contract the ESPN client relies on.

    The concrete breaker must distinguish network / rate-limit / auth / client /
    server / schema failures, honor Retry-After, and use half-open recovery.
    """

    def is_open(self) -> bool: ...

    async def call(
        self, fn: Callable[[], Awaitable[httpx.Response]]
    ) -> httpx.Response: ...

    def record_schema_failure(self) -> None: ...


# --------------------------------------------------------------------------- #
# ESPN provider client
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class EspnProvider:
    """Keyless supplementary discovery provider for SabiScore."""

    http: httpx.AsyncClient
    breaker: CircuitBreaker
    enabled: bool = True
    clock: Callable[[], datetime] = field(default=utcnow)

    trust_tier: TrustTier = TrustTier.UNOFFICIAL_PUBLIC
    name: str = "espn"

    # ----------------------------- public API ----------------------------- #

    async def discover_fixtures(
        self,
        competition: Competition | str,
        *,
        correlation_id: str | None = None,
    ) -> ProviderEnvelope:
        """Fetch + normalize the ESPN scoreboard for one competition.

        Returns a redacted ProviderEnvelope. Never raises for expected operational
        states (disabled, circuit-open, schema drift, transport error) — those are
        encoded as status + warnings so the orchestrator can fail closed cleanly.
        """
        acquired_at = self.clock()

        if not self.enabled:
            return self._envelope(
                ProviderStatus.DISABLED,
                competition,
                acquired_at,
                correlation_id,
                warnings=("ESPN provider disabled",),
            )

        if self.breaker.is_open():
            self._log("circuit_open", competition, correlation_id)
            return self._envelope(
                ProviderStatus.CIRCUIT_OPEN,
                competition,
                acquired_at,
                correlation_id,
                warnings=("ESPN circuit open",),
            )

        try:
            slug = espn_slug(competition)
        except UnsupportedCompetitionError as exc:
            return self._envelope(
                ProviderStatus.UNAVAILABLE,
                competition,
                acquired_at,
                correlation_id,
                warnings=(str(exc),),
            )

        try:
            raw = await self._get_scoreboard(slug, correlation_id)
        except EspnSchemaError as exc:
            # Egress-allowlist / URL guard rejected the request. Fail closed.
            self._log("egress_blocked", competition, correlation_id)
            return self._envelope(
                ProviderStatus.UNAVAILABLE,
                competition,
                acquired_at,
                correlation_id,
                warnings=(str(exc),),
            )
        except CircuitOpenError:
            return self._envelope(
                ProviderStatus.CIRCUIT_OPEN,
                competition,
                acquired_at,
                correlation_id,
                warnings=("ESPN circuit opened during call",),
            )
        except httpx.HTTPStatusError as exc:
            status = (
                ProviderStatus.RATE_LIMITED
                if exc.response.status_code == 429
                else ProviderStatus.UNAVAILABLE
            )
            self._log(
                "http_error",
                competition,
                correlation_id,
                status_code=exc.response.status_code,
            )
            return self._envelope(
                status,
                competition,
                acquired_at,
                correlation_id,
                warnings=(f"ESPN HTTP {exc.response.status_code}",),
            )
        except httpx.HTTPError as exc:
            self._log(
                "transport_error", competition, correlation_id, error=type(exc).__name__
            )
            return self._envelope(
                ProviderStatus.UNAVAILABLE,
                competition,
                acquired_at,
                correlation_id,
                warnings=("ESPN transport error",),
            )

        # Validate the untrusted payload. Fail closed on drift.
        try:
            scoreboard = parse_scoreboard(raw)
        except EspnSchemaError as exc:
            self.breaker.record_schema_failure()
            self._log("schema_invalid", competition, correlation_id)
            return self._envelope(
                ProviderStatus.SCHEMA_INVALID,
                competition,
                acquired_at,
                correlation_id,
                warnings=(str(exc),),
            )

        fixtures: list[NormalizedFixture] = []
        warnings: list[str] = []
        comp = (
            Competition(competition)
            if not isinstance(competition, Competition)
            else competition
        )

        for event in scoreboard.events:
            try:
                fixtures.append(self._normalize(event, comp, acquired_at))
            except EspnSchemaError as exc:
                # Skip the single malformed event; keep the rest. Record a warning.
                warnings.append(f"skipped event {event.id}: {exc}")

        return self._envelope(
            ProviderStatus.HEALTHY,
            competition,
            acquired_at,
            correlation_id,
            fixtures=tuple(fixtures),
            warnings=tuple(warnings),
            snapshot=raw,
        )

    async def probe(self, *, correlation_id: str | None = None) -> ProviderStatus:
        """Cheapest valid liveness probe. Used by `providers doctor`.

        Uses the first supported competition's scoreboard. Returns a status —
        HEALTHY only on a successful, schema-valid response.
        """
        first = supported_competitions()[0]
        env = await self.discover_fixtures(first, correlation_id=correlation_id)
        return env.status

    # ----------------------------- internals ------------------------------ #

    async def _get_scoreboard(
        self, slug: str, correlation_id: str | None
    ) -> dict[str, Any]:
        url = f"{_BASE}/{slug}/scoreboard"
        self._assert_allowed(url)

        async def _do() -> httpx.Response:
            resp = await self.http.get(
                url,
                timeout=_DEFAULT_TIMEOUT,
                headers=self._headers(correlation_id),
            )
            resp.raise_for_status()
            return resp

        resp = await self.breaker.call(_do)
        return resp.json()

    def _normalize(
        self, event: EspnEvent, competition: Competition, acquired_at: datetime
    ) -> NormalizedFixture:
        competitionrec = event.competitions[0]
        by_side = {c.home_away: c for c in competitionrec.competitors}
        home = by_side["home"]
        away = by_side["away"]

        try:
            kickoff = datetime.fromisoformat(event.date.replace("Z", "+00:00"))
        except ValueError as exc:
            raise EspnSchemaError(f"unparseable kickoff {event.date!r}") from exc

        return NormalizedFixture(
            provider_event_id=event.id,
            competition=competition.value,
            kickoff_utc=kickoff,
            status=event.status.type.name,
            provider_home_team_id=home.team.id,
            provider_away_team_id=away.team.id,
            provider_home_team_name=home.team.display_name,
            provider_away_team_name=away.team.display_name,
            # ESPN scoreboards expose no content-update timestamp; use None and
            # rely on acquired_at. We do NOT pretend kickoff is provider_timestamp.
            provider_timestamp=None,
            acquired_at=acquired_at,
        )

    def _envelope(
        self,
        status: ProviderStatus,
        competition: Competition | str | None,
        acquired_at: datetime,
        correlation_id: str | None,
        *,
        fixtures: tuple[NormalizedFixture, ...] = (),
        warnings: tuple[str, ...] = (),
        snapshot: dict[str, Any] | None = None,
    ) -> ProviderEnvelope:
        comp_value = (
            competition.value
            if isinstance(competition, Competition)
            else (str(competition) if competition is not None else None)
        )
        return ProviderEnvelope(
            trust_tier=self.trust_tier,
            status=status,
            competition=comp_value,
            fixtures=fixtures,
            quota=None,
            warnings=warnings,
            snapshot_hash=snapshot_hash(snapshot) if snapshot is not None else None,
            acquired_at=acquired_at,
            correlation_id=correlation_id,
        )

    @staticmethod
    def _headers(correlation_id: str | None) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "SabiScore/1.0 (+https://sabiscore; provider=espn)",
        }
        if correlation_id:
            headers["X-Correlation-ID"] = correlation_id
        return headers

    @staticmethod
    def _assert_allowed(url: str) -> None:
        """Egress allowlist: ESPN may only ever talk to its public host over HTTPS."""
        parsed = httpx.URL(url)
        if parsed.scheme != "https" or parsed.host != _ALLOWED_HOST:
            raise EspnSchemaError(f"egress to {parsed.host!r} blocked by allowlist")

    @staticmethod
    def _log(
        event: str, competition: Any, correlation_id: str | None, **extra: Any
    ) -> None:
        """Redacted structured log. Never includes URLs, query strings, or bodies."""
        logger.info(
            "espn_provider",
            extra={
                "event": event,
                "provider": "espn",
                "competition": str(competition),
                "correlation_id": correlation_id,
                **extra,
            },
        )
