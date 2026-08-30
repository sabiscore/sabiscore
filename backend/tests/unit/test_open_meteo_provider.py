"""Contract tests for the Open-Meteo adapter.

No live calls: every response is a stub. The point is the fail-closed
behaviour, since an invented weather reading is indistinguishable from a
measured one once it reaches a feature vector.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.providers.open_meteo import (
    FORECAST_HORIZON_DAYS,
    OpenMeteoProvider,
    _parse_hourly,
)


def _hourly(stamp: str = "2026-08-16T15:00") -> dict:
    return {
        "hourly": {
            "time": ["2026-08-16T14:00", stamp, "2026-08-16T16:00"],
            "temperature_2m": [17.1, 18.4, 18.0],
            "precipitation": [0.0, 0.3, 0.1],
            "wind_speed_10m": [11.0, 12.5, 13.0],
            "relative_humidity_2m": [70.0, 72.0, 74.0],
        }
    }


KICKOFF = datetime(2026, 8, 16, 15, 0, tzinfo=timezone.utc)


class _StubProvider(OpenMeteoProvider):
    """Captures the request instead of issuing it."""

    def __init__(self, payload):
        super().__init__(enabled=True)
        self._payload = payload
        self.last_url: str | None = None
        self.last_params: dict | None = None

    async def _get_json(self, url, *, headers=None, params=None):  # type: ignore[override]
        self.last_url = url
        self.last_params = dict(params or {})
        return self._payload, {}


def test_parses_the_exact_kickoff_hour() -> None:
    reading = _parse_hourly(
        _hourly(), kickoff_utc=KICKOFF, latitude=53.4, longitude=-2.9, source="archive"
    )
    assert reading is not None
    assert reading.temperature_c == 18.4
    assert reading.precipitation_mm == 0.3
    assert reading.wind_speed_kmh == 12.5
    assert reading.source == "archive"
    assert reading.observed_for_utc == KICKOFF


def test_a_missing_kickoff_hour_is_absent_not_nearest_neighbour() -> None:
    """A gap in the series must stay a gap; the 14:00 reading is not 15:00's."""
    payload = _hourly()
    payload["hourly"]["time"] = ["2026-08-16T14:00", "2026-08-16T16:00"]
    assert _parse_hourly(
        payload, kickoff_utc=KICKOFF, latitude=0.0, longitude=0.0, source="archive"
    ) is None


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda p: p["hourly"].pop("precipitation"), id="variable-missing"),
        pytest.param(lambda p: p["hourly"].update({"temperature_2m": [1.0, None, 2.0]}), id="null-value"),
        pytest.param(lambda p: p["hourly"].update({"temperature_2m": [1.0, float("nan"), 2.0]}), id="nan-value"),
        pytest.param(lambda p: p["hourly"].update({"wind_speed_10m": [1.0, float("inf"), 2.0]}), id="inf-value"),
        pytest.param(lambda p: p["hourly"].update({"precipitation": [0.0, True, 0.1]}), id="bool-not-a-reading"),
        pytest.param(lambda p: p["hourly"].update({"wind_speed_10m": [1.0]}), id="short-series"),
        pytest.param(lambda p: p.update({"hourly": []}), id="hourly-not-an-object"),
    ],
)
def test_partial_or_malformed_responses_yield_nothing(mutate) -> None:
    """Never a partially populated reading — that would look like a measurement."""
    payload = _hourly()
    mutate(payload)
    assert _parse_hourly(
        payload, kickoff_utc=KICKOFF, latitude=0.0, longitude=0.0, source="archive"
    ) is None


@pytest.mark.asyncio
async def test_a_past_kickoff_reads_the_archive() -> None:
    provider = _StubProvider(_hourly())
    reading = await provider.weather_at_kickoff(
        latitude=53.4, longitude=-2.9, kickoff_utc=KICKOFF
    )
    assert reading is not None and reading.source == "archive"
    assert "archive-api" in (provider.last_url or "")
    assert provider.last_params["start_date"] == "2026-08-16"


@pytest.mark.asyncio
async def test_a_future_kickoff_reads_the_forecast() -> None:
    soon = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(days=2)
    stamp = soon.strftime("%Y-%m-%dT%H:00")
    payload = {
        "hourly": {
            "time": [stamp],
            "temperature_2m": [15.0],
            "precipitation": [0.0],
            "wind_speed_10m": [9.0],
            "relative_humidity_2m": [65.0],
        }
    }
    provider = _StubProvider(payload)
    reading = await provider.weather_at_kickoff(latitude=53.4, longitude=-2.9, kickoff_utc=soon)
    assert reading is not None and reading.source == "forecast"
    assert "archive" not in (provider.last_url or "")


@pytest.mark.asyncio
async def test_beyond_the_forecast_horizon_is_absent_never_extrapolated() -> None:
    far = datetime.now(timezone.utc) + timedelta(days=FORECAST_HORIZON_DAYS + 5)
    provider = _StubProvider(_hourly())
    assert await provider.weather_at_kickoff(
        latitude=53.4, longitude=-2.9, kickoff_utc=far
    ) is None
    assert provider.last_url is None, "no request should be issued past the horizon"


@pytest.mark.asyncio
async def test_geocode_country_mismatch_returns_none_rather_than_another_country() -> None:
    """`Valencia` exists in both ES and VE. A filtered miss must not fall through."""
    provider = _StubProvider({
        "results": [
            {"name": "Valencia", "country_code": "VE", "latitude": 10.2, "longitude": -67.9},
        ]
    })
    assert await provider.geocode("Valencia", country_code="ES") is None


@pytest.mark.asyncio
async def test_geocode_filters_to_the_requested_country() -> None:
    provider = _StubProvider({
        "results": [
            {"name": "Valencia", "country_code": "VE", "latitude": 10.2, "longitude": -67.9},
            {"name": "Valencia", "country_code": "ES", "latitude": 39.47, "longitude": -0.38},
        ]
    })
    point = await provider.geocode("Valencia", country_code="ES")
    assert point is not None and point.country_code == "ES"
    assert point.latitude == pytest.approx(39.47)


@pytest.mark.asyncio
async def test_geocode_rejects_an_empty_name_without_calling_upstream() -> None:
    provider = _StubProvider({"results": []})
    assert await provider.geocode("   ") is None
    assert provider.last_url is None


def test_provider_is_keyless() -> None:
    """Like ESPN. A key variable for this provider would be a defect."""
    assert OpenMeteoProvider.requires_key is False


@pytest.mark.asyncio
async def test_egress_is_denied_for_any_host_outside_the_allowlist() -> None:
    """The adapter must not be usable as a general-purpose fetcher."""
    provider = OpenMeteoProvider(enabled=True)
    for url in (
        "https://evil.example.com/v1/forecast",
        "http://api.open-meteo.com/v1/forecast",  # correct host, plaintext
    ):
        with pytest.raises(ValueError, match="egress denied"):
            await provider._get_json(url)
