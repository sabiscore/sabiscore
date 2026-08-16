"""StatsBomb Open Data loader for offline event-level xG research.

This module is intentionally optional and *never* runs during request-time
inference unless a caller explicitly imports and invokes it.  It provides a
clean interface to the open StatsBomb JSON exports and, when ``kloppy`` is
installed, allows event serialisation via the kloppy standard object model.

This is distinct from ``settings.statsbomb_cache_path`` (the Phase 8
``statsbomb_features_cache.parquet`` artifact consumed by the canonical Phase 8
model). That artifact is produced offline by the existing Phase 8 pipeline;
this loader is a research/ablation tool for *additional* StatsBomb open-data
matches and does not write to or read from that production cache path.

StatsBomb open-data repository:
https://github.com/statsbomb/open-data
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .base import SourceMeta

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StatsBombOpenDataSource:
    """Loader for a local StatsBomb open-data JSON export.

    Parameters
    ----------
    root:
        Local directory containing the StatsBomb open-data structure
        (``events/``, ``lineups/``, ``matches/``, etc.).  Clone with::

            git clone https://github.com/statsbomb/open-data
    """

    root: Path

    # ------------------------------------------------------------------
    # Raw event loading
    # ------------------------------------------------------------------

    def load_events_json(
        self, match_id: str | int
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Parse a StatsBomb events JSON file into a flat DataFrame.

        Returns
        -------
        (DataFrame, meta_dict)
            DataFrame columns include: event_id, match_id, minute, second,
            team, player, type, x, y, shot_xg, shot_outcome, body_part,
            under_pressure, play_pattern.
        """
        path = self.root / "events" / f"{match_id}.json"
        if not path.exists():
            raise FileNotFoundError(
                f"StatsBomb events file not found: {path}"
            )
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(
                f"StatsBomb event payload must be a list at: {path}"
            )

        rows: list[dict[str, Any]] = []
        for event in payload:
            if not isinstance(event, dict):
                continue
            shot = event.get("shot") or {}
            location = event.get("location") or [None, None]
            rows.append(
                {
                    "event_id": event.get("id"),
                    "match_id": match_id,
                    "minute": event.get("minute"),
                    "second": event.get("second"),
                    "period": event.get("period"),
                    "team": (event.get("team") or {}).get("name"),
                    "player": (event.get("player") or {}).get("name"),
                    "type": (event.get("type") or {}).get("name"),
                    "x": location[0] if len(location) > 0 else None,
                    "y": location[1] if len(location) > 1 else None,
                    "shot_xg": shot.get("statsbomb_xg"),
                    "shot_outcome": (shot.get("outcome") or {}).get("name"),
                    "body_part": (shot.get("body_part") or {}).get("name"),
                    "under_pressure": bool(event.get("under_pressure", False)),
                    "play_pattern": (event.get("play_pattern") or {}).get("name"),
                }
            )

        frame = pd.DataFrame(rows)
        meta = SourceMeta(source="statsbomb-open-data").as_dict() | {
            "match_id": str(match_id),
            "row_count": int(len(frame)),
        }
        return frame, meta

    # ------------------------------------------------------------------
    # Shot-level feature extraction
    # ------------------------------------------------------------------

    def shot_features(self, events: pd.DataFrame) -> pd.DataFrame:
        """Filter events to shots and enrich with goal flag."""
        if events.empty:
            return pd.DataFrame()
        shots = events[events["type"].eq("Shot")].copy()
        if shots.empty:
            return shots
        shots["shot_xg"] = pd.to_numeric(shots["shot_xg"], errors="coerce")
        shots["is_goal"] = shots["shot_outcome"].eq("Goal").astype(int)
        return shots

    def xg_summary_by_team(
        self, events: pd.DataFrame
    ) -> pd.DataFrame:
        """Aggregate xG and goal counts by team from an events DataFrame.

        Returns a DataFrame indexed by ``team`` with columns:
        ``shots``, ``xg_total``, ``goals``, ``xg_per_shot``.
        """
        shots = self.shot_features(events)
        if shots.empty:
            return pd.DataFrame(
                columns=["team", "shots", "xg_total", "goals", "xg_per_shot"]
            )
        grp = shots.groupby("team", as_index=False).agg(
            shots=("shot_xg", "count"),
            xg_total=("shot_xg", "sum"),
            goals=("is_goal", "sum"),
        )
        grp["xg_per_shot"] = grp["xg_total"] / grp["shots"].replace(0, float("nan"))
        return grp

    # ------------------------------------------------------------------
    # Optional kloppy integration
    # ------------------------------------------------------------------

    def load_events_kloppy(self, match_id: str | int) -> Any:
        """Parse events via kloppy (optional, richer object model).

        Requires: ``pip install kloppy``
        Returns a ``kloppy.EventDataset`` if kloppy is installed.
        """
        try:
            from kloppy import statsbomb  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "Install kloppy for the richer event model: pip install kloppy"
            ) from exc

        events_file = str(self.root / "events" / f"{match_id}.json")
        lineup_file = str(self.root / "lineups" / f"{match_id}.json")
        return statsbomb.load(
            event_data=events_file,
            lineup_data=lineup_file,
        )
