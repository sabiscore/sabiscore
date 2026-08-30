"""Open-Meteo weather provider — keyless, and the same shape for train and serve.

Why this provider and not the alternatives
------------------------------------------
Match weather is only usable as a model input if it can be resolved BOTH for
every historical match in the training corpus AND for a fixture that has not
kicked off yet. A source that offers only one half teaches the model to lean on
a signal serving can never supply — the train/serve skew that forced the vΩ.46
retrain. Open-Meteo is the only free option that satisfies both:

* ``archive-api.open-meteo.com/v1/archive`` — reanalysis back to 1940, for the
  12,765-match corpus in ``backend/data/cache``.
* ``api.open-meteo.com/v1/forecast`` — up to 16 days ahead, for an upcoming
  fixture.

Both return an identical ``hourly`` block, so ONE parser serves both paths and
the two cannot drift. Neither needs an API key.

Rejected: Visual Crossing requires a key and caps the free tier at 1,000
records/day, which does not cover a 12,765-match backfill. NOAA/NWS is
US-only and every supported competition is European.

Venue resolution
----------------
``Match.venue`` is NULL in production and ``Team.stadium`` is free text, so
there are no coordinates to query with. Rather than hand-entering ~130 stadium
positions — inventing reference data is precisely what the zero-fabrication
contract forbids — this resolves a location name through Open-Meteo's own
keyless geocoding endpoint. City-level resolution is adequate: the weather
model's grid cell is coarser than the distance from a city centre to its
stadium, and the API snaps any request to that cell regardless.

Scope
-----
This ships ACQUISITION ONLY, deliberately. Nothing here feeds a feature vector:
adding weather to the model means a new ``feature_schema_version``, a retrain
and a promotion decision, which is a separate, gated change. The same staging
ADR-0004 used for CLV capture, which shipped capture before computation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import urlsplit

from .base import BaseProvider, ProviderStatus, TrustTier

# Both hosts must be present in the egress allowlist. They are distinct
# services on distinct hosts, exactly like ESPN's two bases.
_ARCHIVE_BASE = "https://archive-api.open-meteo.com/v1/archive"
_FORECAST_BASE = "https://api.open-meteo.com/v1/forecast"
_GEOCODING_BASE = "https://geocoding-api.open-meteo.com/v1/search"

# Egress allowlist, matching ESPN's per-provider `_ALLOWED_HOST` convention:
# this adapter may reach these three hosts over HTTPS and nothing else.
_ALLOWED_HOSTS = frozenset({
    "archive-api.open-meteo.com",
    "api.open-meteo.com",
    "geocoding-api.open-meteo.com",
})

# The forecast horizon the upstream free tier serves. A kickoff beyond this
# has no forecast yet; that is an absence to report, never one to interpolate.
FORECAST_HORIZON_DAYS = 16

# Kept deliberately small. Every variable added here becomes a column that a
# future feature schema must resolve for all 12,765 historical matches AND for
# an unplayed fixture, so the set is the intersection of "plausibly affects a
# football result" and "the archive and forecast endpoints both return it".
_HOURLY_VARIABLES = (
    "temperature_2m",
    "precipitation",
    "wind_speed_10m",
    "relative_humidity_2m",
)


@dataclass(frozen=True)
class GeoPoint:
    """A resolved location. ``name``/``country_code`` are echoed for auditing."""

    latitude: float
    longitude: float
    name: str
    country_code: Optional[str]


@dataclass(frozen=True)
class MatchWeather:
    """Weather at one kickoff hour.

    ``source`` records which endpoint answered, so a stored observation always
    says whether it is a reanalysis or a forecast — they are not equivalent
    evidence and must never be silently interchanged.
    """

    latitude: float
    longitude: float
    observed_for_utc: datetime
    temperature_c: float
    precipitation_mm: float
    wind_speed_kmh: float
    relative_humidity_pct: float
    source: str  # "archive" | "forecast"
    acquired_at: datetime


class OpenMeteoProvider(BaseProvider):
    provider_id = "open_meteo"
    display_name = "Open-Meteo"
    # Open, documented, non-commercial-tier public data. Not an official
    # football source, so it can never establish fixture, market or lineup
    # evidence — a missing reading is advisory, never critical.
    trust_tier = TrustTier.OPEN_DATA
    requires_key = False

    async def _get_json(self, url: str, *, headers=None, params=None):  # type: ignore[override]
        """Enforce HTTPS + the host allowlist before any request leaves."""
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_HOSTS:
            raise ValueError(f"open_meteo: egress denied for {parsed.scheme}://{parsed.hostname}")
        return await super()._get_json(url, headers=headers, params=params)

    async def probe(self) -> ProviderStatus:
        """Cheapest real call that proves the upstream contract still holds."""
        try:
            payload, _ = await self._get_json(
                _GEOCODING_BASE,
                params={"name": "London", "count": 1, "format": "json"},
            )
        except Exception:
            return ProviderStatus.UNAVAILABLE
        if not isinstance(payload, dict) or "results" not in payload:
            return ProviderStatus.UNAVAILABLE
        return ProviderStatus.VERIFIED

    async def geocode(self, name: str, *, country_code: str | None = None) -> Optional[GeoPoint]:
        """Resolve a place name to coordinates, or None. Never guesses."""
        if not name or not name.strip():
            return None
        params: dict[str, Any] = {"name": name.strip(), "count": 10, "format": "json"}
        payload, _ = await self._get_json(_GEOCODING_BASE, params=params)
        results = _require_list(payload, "results") if isinstance(payload, dict) else None
        if not results:
            return None

        if country_code:
            wanted = country_code.upper()
            results = [r for r in results if str(r.get("country_code", "")).upper() == wanted]
            if not results:
                # A country filter that matches nothing is an unresolved
                # location, not a licence to fall back to another country.
                return None

        top = results[0]
        lat, lon = top.get("latitude"), top.get("longitude")
        if not _is_finite_number(lat) or not _is_finite_number(lon):
            return None
        return GeoPoint(
            latitude=float(lat),
            longitude=float(lon),
            name=str(top.get("name") or name),
            country_code=(str(top["country_code"]) if top.get("country_code") else None),
        )

    async def weather_at_kickoff(
        self,
        *,
        latitude: float,
        longitude: float,
        kickoff_utc: datetime,
    ) -> Optional[MatchWeather]:
        """Weather for the kickoff hour, from the archive or the forecast.

        Endpoint choice is by the kickoff's own position in time, not by a
        caller flag, so a historical backfill and a live request cannot end up
        reading different sources for the same match.
        """
        kickoff = _as_utc(kickoff_utc)
        now = datetime.now(timezone.utc)
        is_past = kickoff < now

        day = kickoff.date().isoformat()
        params: dict[str, Any] = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": ",".join(_HOURLY_VARIABLES),
            "timezone": "UTC",
        }
        if is_past:
            base, source = _ARCHIVE_BASE, "archive"
            params |= {"start_date": day, "end_date": day}
        else:
            if (kickoff - now).days > FORECAST_HORIZON_DAYS:
                return None  # beyond the published horizon — absent, not zero
            base, source = _FORECAST_BASE, "forecast"
            params["forecast_days"] = FORECAST_HORIZON_DAYS

        payload, _ = await self._get_json(base, params=params)
        return _parse_hourly(
            payload,
            kickoff_utc=kickoff,
            latitude=latitude,
            longitude=longitude,
            source=source,
        )


# ── parsing ───────────────────────────────────────────────────────────────────
# Every untrusted response is validated before use. A shape we do not recognise
# yields None (an absence the caller reports as a gap) rather than a partially
# populated reading, which would be indistinguishable from a real measurement.


def _parse_hourly(
    payload: Any,
    *,
    kickoff_utc: datetime,
    latitude: float,
    longitude: float,
    source: str,
) -> Optional[MatchWeather]:
    if not isinstance(payload, dict):
        return None
    hourly = payload.get("hourly")
    if not isinstance(hourly, dict):
        return None

    times = _require_list(hourly, "time")
    if not times:
        return None

    # The API returns whole hours; match the kickoff hour exactly rather than
    # picking a nearest neighbour, so a gap in the series stays a gap.
    target = kickoff_utc.replace(minute=0, second=0, microsecond=0)
    stamp = target.strftime("%Y-%m-%dT%H:00")
    try:
        idx = times.index(stamp)
    except ValueError:
        return None

    values: dict[str, float] = {}
    for variable in _HOURLY_VARIABLES:
        series = _require_list(hourly, variable)
        if series is None or idx >= len(series) or not _is_finite_number(series[idx]):
            return None
        values[variable] = float(series[idx])

    return MatchWeather(
        latitude=latitude,
        longitude=longitude,
        observed_for_utc=target,
        temperature_c=values["temperature_2m"],
        precipitation_mm=values["precipitation"],
        wind_speed_kmh=values["wind_speed_10m"],
        relative_humidity_pct=values["relative_humidity_2m"],
        source=source,
        acquired_at=datetime.now(timezone.utc),
    )


def _require_list(container: Mapping[str, Any], key: str) -> Optional[list]:
    value = container.get(key)
    return list(value) if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else None


def _is_finite_number(value: Any) -> bool:
    """Reject None, bools, strings, NaN and +/-inf in one predicate.

    ``math.isfinite`` covers NaN and both infinities; the explicit bool guard is
    separate because ``bool`` is an ``int`` subclass and ``True`` would otherwise
    pass as the temperature 1.
    """
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _as_utc(value: datetime) -> datetime:
    """Repo convention: DB timestamps are naive UTC, provider input is aware."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
