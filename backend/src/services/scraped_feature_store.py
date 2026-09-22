"""Read-only bridge from validated Node scraper artifacts to model features."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_ROOT = _REPO_ROOT / "data" / "processed" / "node-scraper"


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _parse_date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            parsed = datetime.strptime(raw, fmt)
            return (
                parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
            )
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except ValueError:
        return None


@dataclass(frozen=True)
class ScrapedTeamForm:
    team: str
    matches_sampled: int
    ppg: float
    wins: int
    draws: int
    losses: int
    goals_for_avg: float
    goals_against_avg: float
    goal_difference_avg: float
    latest_match_date: datetime | None
    source_file: Path

    def to_projection_stats(self, is_home: bool = True) -> dict[str, float]:
        """is_home controls only the home_/away_ prefix on the 5 side-specific
        keys below — matches data/team_database.py:get_team_stats()'s is_home
        convention (WP-18/D8b). The 7 side-agnostic keys (wins_5/draws_5/
        losses_5/etc.) are unprefixed by design, matching _get_team_stats()'s
        own real-count keys."""
        prefix = "home" if is_home else "away"
        return {
            "ppg_5": self.ppg,
            "wins_5": float(self.wins),
            "draws_5": float(self.draws),
            "losses_5": float(self.losses),
            "goals_for_avg_5": self.goals_for_avg,
            "goals_against_avg_5": self.goals_against_avg,
            "gd_avg_5": self.goal_difference_avg,
            f"{prefix}_form_5": self.ppg / 3.0,
            f"{prefix}_win_rate_5": self.wins / max(self.matches_sampled, 1),
            f"{prefix}_goals_per_match_5": self.goals_for_avg,
            f"{prefix}_goals_conceded_per_match_5": self.goals_against_avg,
            f"{prefix}_gd_avg_5": self.goal_difference_avg,
        }


class ScrapedTeamFormStore:
    def __init__(self, root: str | Path | None = None) -> None:
        configured = root or os.getenv("SCRAPER_PROCESSED_ROOT")
        self.root = (
            Path(configured).expanduser().resolve()
            if configured
            else _DEFAULT_ROOT.resolve()
        )

    def get_team_form(
        self, *, competition: str, team: str, information_cutoff: datetime | None = None
    ) -> ScrapedTeamForm | None:
        if not self.root.exists():
            return None
        files = sorted(
            self.root.glob(f"team-form-{competition.upper()}-*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        target = _norm(team)
        cutoff = information_cutoff
        if cutoff is not None and cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=timezone.utc)
        for path in files:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, list):
                continue
            for item in payload:
                if (
                    not isinstance(item, dict)
                    or _norm(str(item.get("team") or "")) != target
                ):
                    continue
                record = self._parse_record(item, path)
                if record is None:
                    continue
                if (
                    cutoff
                    and record.latest_match_date
                    and record.latest_match_date >= cutoff
                ):
                    continue
                return record
        return None

    @staticmethod
    def _parse_record(item: dict[str, Any], path: Path) -> ScrapedTeamForm | None:
        numeric_fields = (
            "matches_sampled",
            "ppg",
            "wins",
            "draws",
            "losses",
            "goals_for_avg",
            "goals_against_avg",
            "goal_difference_avg",
        )
        if any(
            not isinstance(item.get(field), (int, float)) for field in numeric_fields
        ):
            return None
        matches = int(item["matches_sampled"])
        if (
            matches <= 0
            or int(item["wins"]) + int(item["draws"]) + int(item["losses"]) != matches
        ):
            return None
        return ScrapedTeamForm(
            team=str(item.get("team") or ""),
            matches_sampled=matches,
            ppg=float(item["ppg"]),
            wins=int(item["wins"]),
            draws=int(item["draws"]),
            losses=int(item["losses"]),
            goals_for_avg=float(item["goals_for_avg"]),
            goals_against_avg=float(item["goals_against_avg"]),
            goal_difference_avg=float(item["goal_difference_avg"]),
            latest_match_date=_parse_date(item.get("latest_match_date")),
            source_file=path,
        )
