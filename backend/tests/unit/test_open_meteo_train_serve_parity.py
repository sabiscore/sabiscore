"""DEBT 155: the adapter must read what the research dataset reads.

The F3/F3b dataset (`scripts/ingest_openmeteo_weather.py`) is the archived
forecast valid at kickoff - 2 h, from 2022-03-01 on. The adapter used to read
ERA5 reanalysis (`archive-api`) at the kickoff hour for any past kickoff: the
weather that actually happened. A training backfill through it would leak, and
serving would read a different hour than training. No network: stubbed payloads.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from src.providers.open_meteo import OpenMeteoProvider

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import ingest_openmeteo_weather as ingest  # noqa: E402

# Kickoff at 19:00; the 17:00 row is the one both paths must read.
_PAYLOAD = {
    "hourly": {
        "time": ["2024-03-01T17:00", "2024-03-01T18:00", "2024-03-01T19:00"],
        "temperature_2m": [9.0, 10.0, 11.0],
        "precipitation": [0.5, 0.0, 3.0],
        "wind_speed_10m": [20.0, 21.0, 40.0],
        "wind_gusts_10m": [35.0, 36.0, 70.0],
        "relative_humidity_2m": [80.0, 81.0, 90.0],
    }
}
_KICKOFF = datetime(2024, 3, 1, 19, 0, tzinfo=timezone.utc)


class _Stub(OpenMeteoProvider):
    def __init__(self, payload):
        super().__init__(enabled=True)
        self._payload = payload
        self.urls: list[str] = []

    async def _get_json(self, url, *, headers=None, params=None):  # type: ignore[override]
        self.urls.append(url)
        return self._payload, {}


@pytest.mark.asyncio
async def test_a_past_kickoff_never_reads_reanalysis() -> None:
    provider = _Stub(_PAYLOAD)
    await provider.weather_at_kickoff(latitude=52.0, longitude=5.0, kickoff_utc=_KICKOFF)
    hosts = {urlsplit(u).hostname for u in provider.urls}
    assert hosts == {"historical-forecast-api.open-meteo.com"}


@pytest.mark.asyncio
async def test_a_kickoff_before_the_forecast_archive_is_absent() -> None:
    provider = _Stub(_PAYLOAD)
    reading = await provider.weather_at_kickoff(
        latitude=53.41, longitude=-2.98, kickoff_utc=datetime(2021, 8, 14, 15, 0, tzinfo=timezone.utc)
    )
    assert reading is None
    assert provider.urls == [], "no request: only reanalysis exists this early"


@pytest.mark.asyncio
async def test_adapter_and_research_ingest_read_the_same_hour(monkeypatch) -> None:
    provider = _Stub(_PAYLOAD)
    served = await provider.weather_at_kickoff(latitude=52.0, longitude=5.0, kickoff_utc=_KICKOFF)

    monkeypatch.setattr(ingest, "fetch_venue_window", lambda *a, **k: _PAYLOAD)
    monkeypatch.setattr(ingest.time, "sleep", lambda _s: None)
    fixture = {
        "league": "EREDIVISIE",
        "season": "2023/2024",
        "season_code": "2324",
        "kickoff_date": date(2024, 3, 1),
        "kickoff_clock": (19, 0),
        "home_team": "AZ Alkmaar",
        "away_team": "Feyenoord",
    }
    rows, gaps = ingest.build_rows([fixture], {"AZ Alkmaar": (52.0, 5.0)})

    assert gaps == {} and len(rows) == 1
    assert served is not None
    assert served.temperature_c == rows[0]["temperature_2m_c"] == 9.0
    assert served.precipitation_mm == rows[0]["precipitation_mm"] == 0.5
