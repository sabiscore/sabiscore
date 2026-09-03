"""Understat team xG ingestion with graceful optional-dependency handling.

Understat has no official public API. Use this connector only when enabled
and ensure the site's robots.txt / ToS policy is acceptable for your use-case.
The preferred interface is the maintained ``soccerdata`` library; if unavailable
the connector raises a clear ``ImportError`` so production keeps running.

This connector is offline/batch-only (see ``source_registry.py`` —
``request_time_safe=False``). It is invoked from
``backend/scripts/backfill_v4_data_sources.py``, never from the live
request path.

Team-name resolution
--------------------
Football databases use inconsistent team names (e.g. "Man City" vs
"Manchester City" vs "Manchester City FC"). This connector uses ``rapidfuzz``
(WRatio scorer, 80-point threshold) for fuzzy resolution when available.
Install with ``pip install rapidfuzz`` — it has no other dependencies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .base import SourceMeta

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SabiScore league slug → soccerdata league ID
# ---------------------------------------------------------------------------
# ⚠️ These values are ``soccerdata``'s OWN standardized league IDs, NOT
# Understat's website slugs. The two look interchangeable and are not:
# understat.com serves ``/league/EPL``, but ``sd.Understat(leagues="EPL")``
# raises ``ValueError`` — ``_selected_leagues`` validates every id against
# ``LEAGUE_DICT`` and rejects unknown ones outright.
#
# This map held the website slugs until 2026-09-03. Nothing caught it because
# ``_reader``/``team_match_xg`` have no test coverage (the suite exercises only
# ``_resolve_team_name`` and the pure ``rolling_xg_features``) and the one
# caller, ``scripts/backfill_v4_data_sources.py``, wraps the fetch in a broad
# ``except Exception`` that would have recorded the failure as an opaque
# "Understat error" warning for every league of every season.
#
# Verify against ``sd.Understat.available_leagues()`` before adding a league.
LEAGUE_TO_UNDERSTAT: dict[str, str] = {
    "epl": "ENG-Premier League",
    "premier_league": "ENG-Premier League",
    "la_liga": "ESP-La Liga",
    "laliga": "ESP-La Liga",
    "serie_a": "ITA-Serie A",
    "bundesliga": "GER-Bundesliga",
    "ligue_1": "FRA-Ligue 1",
    "ligue1": "FRA-Ligue 1",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_team_name(team: str, available_teams: list[str]) -> str | None:
    """Return the best-matching team name from ``available_teams``.

    Uses ``rapidfuzz.process.extractOne`` (WRatio scorer) with a score cutoff
    of 80 when the library is installed.  Falls back to exact match otherwise.
    """
    if not available_teams:
        return None
    if team in available_teams:
        return team
    try:
        from rapidfuzz import fuzz, process  # type: ignore

        result = process.extractOne(
            team, available_teams, scorer=fuzz.WRatio, score_cutoff=80
        )
        if result:
            logger.debug(
                "rapidfuzz resolved %r -> %r (score=%.1f)", team, result[0], result[1]
            )
            return result[0]
    except ImportError:
        pass
    # Case-insensitive exact fallback.
    lower = team.casefold()
    for candidate in available_teams:
        if candidate.casefold() == lower:
            return candidate
    return None


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UnderstatTeamXGSource:
    """Offline/batch xG ingestion from Understat via the ``soccerdata`` wrapper.

    Parameters
    ----------
    cache_dir:
        Local directory for ``soccerdata``'s on-disk cache.  Recommended to
        keep separate from the main data artefacts directory.
    """

    cache_dir: str | Path | None = None

    def _reader_kwargs(self, league: str, season: int) -> dict[str, Any]:
        """Build the ``sd.Understat(**kwargs)`` arguments.

        Kept pure and free of the ``soccerdata`` import so it stays testable in
        an environment without the optional dependency — which is every
        environment except the offline research venv.
        """
        # Validate the argument before the caller imports the optional heavy
        # dependency: a bad league is a caller error and should say so
        # regardless of whether soccerdata happens to be installed. Failing
        # closed here also keeps the message nameable — passing the raw slug
        # through would surface as soccerdata's generic ValueError inside the
        # caller's broad `except Exception`, which is how the wrong-ID bug
        # above stayed invisible.
        league_name = LEAGUE_TO_UNDERSTAT.get(league.lower())
        if league_name is None:
            raise ValueError(
                f"No soccerdata league ID mapped for {league!r}. "
                f"Known: {sorted(LEAGUE_TO_UNDERSTAT)}"
            )

        kwargs: dict[str, Any] = {"leagues": league_name, "seasons": season}
        if self.cache_dir is not None:
            # ⚠️ soccerdata calls ``data_dir.mkdir()``, so this must be a Path.
            # The one caller (backfill_v4_data_sources.py) passes a str, which
            # raised `'str' object has no attribute 'mkdir'` inside that
            # script's broad `except Exception`. Coerced here rather than at the
            # call site so every caller is covered.
            kwargs["data_dir"] = Path(self.cache_dir)
        return kwargs

    def _reader(self, league: str, season: int) -> Any:
        kwargs = self._reader_kwargs(league, season)

        try:
            import soccerdata as sd  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "Install soccerdata to enable Understat ingestion: "
                "pip install soccerdata"
            ) from exc

        return sd.Understat(**kwargs)

    def team_match_xg(
        self, *, league: str, season: int
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Return a per-match xG DataFrame and source metadata.

        Columns guaranteed in output
        ----------------------------
        ``home_team``, ``away_team``, ``home_xg``, ``away_xg``.

        Additional columns (``date``, ``home_goals``, etc.) are passed through
        if present in the raw ``soccerdata`` schedule frame.
        """
        reader = self._reader(league, season)
        schedule = reader.read_schedule()
        if not isinstance(schedule, pd.DataFrame):
            schedule = pd.DataFrame(schedule)

        frame = schedule.reset_index()

        # Normalise column names — soccerdata may use different casing/naming
        # across versions.
        rename_map: dict[str, str] = {}
        col_lower = {c.lower(): c for c in frame.columns}
        for target, candidates in (
            ("home_team", ["home_team", "home", "hometeam"]),
            ("away_team", ["away_team", "away", "awayteam"]),
            ("home_xg", ["home_xg", "xg_home", "xgh"]),
            ("away_xg", ["away_xg", "xg_away", "xga"]),
        ):
            if target in frame.columns:
                continue
            for candidate in candidates:
                if candidate in col_lower:
                    rename_map[col_lower[candidate]] = target
                    break

        if rename_map:
            frame = frame.rename(columns=rename_map)

        for col in ("home_xg", "away_xg"):
            if col in frame.columns:
                frame[col] = pd.to_numeric(frame[col], errors="coerce")

        meta: dict[str, Any] = SourceMeta(
            source="understat/soccerdata",
            fetched_at=datetime.now(UTC),
            notes=(
                "Unofficial scraping wrapper - keep disabled unless "
                "ToS/robots policy is acceptable.",
            ),
        ).as_dict() | {
            "league": league,
            "season": season,
            "row_count": int(len(frame)),
        }
        return frame, meta

    @staticmethod
    def rolling_xg_features(
        matches: pd.DataFrame,
        *,
        window: int = 5,
        date_col: str = "date",
    ) -> pd.DataFrame:
        """Compute rolling per-team xG features from a match-level DataFrame.

        Returns a long-form DataFrame indexed by (team, match_order) with:

        - ``rolling_xg_for``     — rolling mean xG scored (shift-1, min 2)
        - ``rolling_xg_against`` — rolling mean xG conceded (shift-1, min 2)
        - ``rolling_xg_diff``    — for minus against (team quality proxy)
        - ``match_order``        — integer sequence per team for later sorting

        The ``match_order`` column is critical for ``_latest_team_row`` in
        the feature builder and allows correct temporal ordering when joining
        to the main prediction frame.

        Shift-1 enforces strictly pre-match knowledge — there is no
        look-ahead leakage into walk-forward training splits **provided the
        input is in chronological order**. To make that guarantee robust this
        method sorts by ``date_col`` first when that column is present (a
        stable sort, so same-day fixtures keep their input order); if the
        column is absent it falls back to the input row order and assumes the
        caller has already sorted chronologically.
        """
        required = {"home_team", "away_team", "home_xg", "away_xg"}
        missing = required - set(matches.columns)
        if missing:
            raise ValueError(
                f"Understat matches DataFrame is missing columns: {sorted(missing)}"
            )

        # Enforce chronological order so shift-1 truly excludes future games.
        if date_col in matches.columns:
            ordered = matches.sort_values(
                date_col, kind="stable", na_position="last"
            ).reset_index(drop=True)
        else:
            ordered = matches.reset_index(drop=True)

        long_rows: list[dict[str, Any]] = []
        for _, row in ordered.iterrows():
            long_rows.append(
                {
                    "team": row["home_team"],
                    "xg_for": float(row["home_xg"]) if pd.notna(row["home_xg"]) else None,
                    "xg_against": float(row["away_xg"]) if pd.notna(row["away_xg"]) else None,
                }
            )
            long_rows.append(
                {
                    "team": row["away_team"],
                    "xg_for": float(row["away_xg"]) if pd.notna(row["away_xg"]) else None,
                    "xg_against": float(row["home_xg"]) if pd.notna(row["home_xg"]) else None,
                }
            )

        long = pd.DataFrame(long_rows)

        # Assign monotonic match_order within each team group for temporal
        # sorting downstream — cumcount is 0-indexed so add 1.
        long["match_order"] = long.groupby("team").cumcount() + 1

        # Shift-1 to enforce strictly pre-match knowledge.
        long["rolling_xg_for"] = long.groupby("team")["xg_for"].transform(
            lambda s: s.shift(1).rolling(window, min_periods=2).mean()
        )
        long["rolling_xg_against"] = long.groupby("team")["xg_against"].transform(
            lambda s: s.shift(1).rolling(window, min_periods=2).mean()
        )
        long["rolling_xg_diff"] = long["rolling_xg_for"] - long["rolling_xg_against"]

        return long

    def resolve_team_in_rollups(
        self,
        team: str,
        rollups: pd.DataFrame,
    ) -> str | None:
        """Return the best-matching team name present in ``rollups``.

        Uses fuzzy matching if ``rapidfuzz`` is installed.
        """
        if "team" not in rollups.columns:
            return None
        available = rollups["team"].dropna().unique().tolist()
        return _resolve_team_name(team, available)
