"""Guards for the Portfolio F weather cutoff and the evaluation-gate repoint.

Two things are pinned here, both of which produce a *plausible wrong answer*
rather than an error if they regress:

1. `_FORECAST_ARCHIVE_START` — Open-Meteo's Historical Forecast API returns
   ERA5 reanalysis with HTTP 200 before its archive begins (measured: identical
   to reanalysis through 2022-01-01, divergent from 2022-03-01). Dropping the
   cutoff silently trains three of seven corpus seasons on post-hoc actuals.

2. The `compare_candidate_vs_incumbent` temporal guard — docs/DEBT.md item 81.
   Scoring a model on a season it trained on looks like a strong result.

No network, no database, no model artifacts.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from compare_candidate_vs_incumbent import (  # noqa: E402
    HOLDOUT_SEASON,
    _load_incumbent_baseline,
)
from ingest_openmeteo_weather import (  # noqa: E402
    GAP_NO_ARCHIVE,
    GAP_NO_KICKOFF_TIME,
    GAP_NO_VENUE,
    _FORECAST_ARCHIVE_START,
    _parse_time,
    build_rows,
    index_hourly,
    load_verified_venues,
)
import ingest_openmeteo_weather  # noqa: E402


class TestForecastArchiveCutoff:
    def test_cutoff_sits_after_the_measured_reanalysis_fallback(self) -> None:
        """Identical to ERA5 through 2022-01-01; divergent from 2022-03-01."""
        assert _FORECAST_ARCHIVE_START > date(2022, 1, 1)
        assert _FORECAST_ARCHIVE_START <= date(2022, 3, 1)

    def test_a_pre_archive_fixture_is_refused_not_backfilled(self) -> None:
        fixtures = [{
            "league": "EPL", "season": "2019/2020", "season_code": "1920",
            "kickoff_date": date(2019, 8, 9), "kickoff_clock": (20, 0),
            "home_team": "Liverpool", "away_team": "Norwich",
        }]
        rows, gaps = build_rows(fixtures, {"Liverpool": (53.41, -2.98)})
        # No network call is made at all — the gap is decided from the clock.
        assert rows == []
        assert gaps == {GAP_NO_ARCHIVE: 1}

    def test_an_unverified_venue_is_refused_not_approximated(self) -> None:
        """Rule 5: no coordinate is invented for a club we could not locate."""
        fixtures = [{
            "league": "BUNDESLIGA", "season": "2023/2024", "season_code": "2324",
            "kickoff_date": date(2024, 3, 1), "kickoff_clock": (18, 30),
            "home_team": "Leverkusen", "away_team": "Bayern Munich",
        }]
        rows, gaps = build_rows(fixtures, {"Bayern Munich": (48.14, 11.58)})
        assert rows == []
        assert gaps == {GAP_NO_VENUE: 1}

    def test_a_missing_kickoff_clock_is_a_gap_not_a_guessed_hour(self) -> None:
        fixtures = [{
            "league": "EPL", "season": "2023/2024", "season_code": "2324",
            "kickoff_date": date(2024, 3, 1), "kickoff_clock": None,
            "home_team": "Liverpool", "away_team": "Norwich",
        }]
        rows, gaps = build_rows(fixtures, {"Liverpool": (53.41, -2.98)})
        assert rows == []
        assert gaps == {GAP_NO_KICKOFF_TIME: 1}


class TestHourlyIndexing:
    def test_cutoff_hour_is_two_hours_before_kickoff(self) -> None:
        payload = {"hourly": {
            "time": ["2024-03-01T16:00", "2024-03-01T17:00", "2024-03-01T18:00"],
            "temperature_2m": [8.0, 9.0, 10.0],
            "precipitation": [0.0, 0.5, 1.0],
        }}
        indexed = index_hourly(payload)
        # A 19:00 kickoff must read the 17:00 row, not the 19:00 one.
        assert indexed["2024-03-01T17:00"] == (9.0, 0.5)

    def test_absent_variables_do_not_raise(self) -> None:
        assert index_hourly({"hourly": {"time": ["2024-03-01T17:00"]}}) == {
            "2024-03-01T17:00": (None, None)
        }

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("20:00", (20, 0)), ("15:30", (15, 30)), ("9:05", (9, 5)),
         ("", None), ("   ", None), ("not-a-time", None)],
    )
    def test_time_parsing_is_fail_closed(self, raw: str, expected) -> None:
        assert _parse_time(raw) == expected


class TestEvaluationGateTemporalGuard:
    def _manifest(self, tmp_path: Path, holdout: str | None) -> Path:
        payload = {
            "generation": "test_gen",
            "role": "EVALUATION_BASELINE",
            "feature_schema_version": "apex_v1_68",
            "artifacts": {"epl": {"artifact": "epl_ensemble_test_gen.pkl"}},
        }
        if holdout is not None:
            payload["temporal_split"] = {"holdout_season": holdout}
        path = tmp_path / "manifest.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_matching_holdout_loads(self, tmp_path: Path) -> None:
        baseline = _load_incumbent_baseline(self._manifest(tmp_path, HOLDOUT_SEASON))
        assert baseline["holdout_season"] == HOLDOUT_SEASON
        assert baseline["suffix"] == "test_gen"

    def test_a_mismatched_holdout_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="declares holdout season"):
            _load_incumbent_baseline(self._manifest(tmp_path, "2425"))

    def test_a_manifest_declaring_no_holdout_raises(self, tmp_path: Path) -> None:
        """active_generation.json has no temporal_split — pointing at it must fail."""
        with pytest.raises(ValueError, match="docs/DEBT.md item 81"):
            _load_incumbent_baseline(self._manifest(tmp_path, None))

    def test_mixed_artifact_suffixes_raise(self, tmp_path: Path) -> None:
        path = tmp_path / "manifest.json"
        path.write_text(json.dumps({
            "generation": "mixed",
            "temporal_split": {"holdout_season": HOLDOUT_SEASON},
            "artifacts": {
                "epl": {"artifact": "epl_ensemble_a.pkl"},
                "la_liga": {"artifact": "la_liga_ensemble_b.pkl"},
            },
        }), encoding="utf-8")
        with pytest.raises(ValueError, match="artifact suffixes"):
            _load_incumbent_baseline(path)


class TestLoadVerifiedVenuesConfirmedCandidate:
    """DEBT 101: ingestion must read the candidate `classify()` confirmed.

    Sheffield United was correct in production only by accident of geocoder
    response order -- "Sheffield" (confirmed) happened to arrive before
    "United Kingdom" (unconfirmed, the country centroid from tokenising
    "united"). Reading `candidates[0]` unconditionally would silently swap in
    the wrong coordinate the moment an upstream response reordered.
    """

    def _write_manifest(self, tmp_path: Path, entries: list[dict]) -> Path:
        manifest = {
            "generated_at": "2026-01-01T00:00:00+00:00",
            "corpus": str(tmp_path),
            "roster_size": len(entries),
            "weather_cell_km": 25.0,
            "counts": {"VERIFIED": sum(1 for e in entries if e["verdict"] == "VERIFIED")},
            "coverage_verified": 1.0,
            "entries": entries,
        }
        path = tmp_path / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def test_picks_the_confirmed_candidate_not_the_first_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entries = [{
            "club": "Sheffield United",
            "country": "GB",
            "verdict": "VERIFIED",
            "candidates": [
                # Unconfirmed listed FIRST -- the exact reorder this guards against.
                {"name": "United Kingdom", "latitude": 54.7584, "longitude": -2.6953,
                 "country_code": "GB", "confirmed": False},
                {"name": "Sheffield", "latitude": 53.383, "longitude": -1.4659,
                 "country_code": "GB", "confirmed": True},
            ],
        }]
        manifest_path = self._write_manifest(tmp_path, entries)
        monkeypatch.setattr(ingest_openmeteo_weather, "_VENUE_MANIFEST", manifest_path)

        venues = load_verified_venues()

        assert venues["Sheffield United"] == (53.383, -1.4659)

    def test_falls_back_to_first_candidate_when_manifest_predates_confirmed_field(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A manifest generated before DEBT 101 has no 'confirmed' key at all.

        Must not fail closed on every venue for a schema difference alone --
        falls back to the old candidates[0] behaviour, but says so.
        """
        entries = [{
            "club": "Old Manifest FC",
            "country": "GB",
            "verdict": "VERIFIED",
            "candidates": [
                {"name": "Old Manifest", "latitude": 51.5, "longitude": -0.1, "country_code": "GB"},
            ],
        }]
        manifest_path = self._write_manifest(tmp_path, entries)
        monkeypatch.setattr(ingest_openmeteo_weather, "_VENUE_MANIFEST", manifest_path)

        with caplog.at_level("WARNING"):
            venues = load_verified_venues()

        assert venues["Old Manifest FC"] == (51.5, -0.1)
        assert any("Old Manifest FC" in r.message for r in caplog.records)
