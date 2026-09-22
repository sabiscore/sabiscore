"""Pi-rating system — Constantinou & Fenton (2013).

6 features per matchup:
  home_pi_attack, home_pi_defense,
  away_pi_attack, away_pi_defense,
  pi_attack_diff, pi_defense_diff

⚠ CHRONOLOGICAL INVARIANT: matches MUST be fed to `update()` in ascending
  match_date order. Non-chronological updates introduce look-ahead bias that
  inflates accuracy by ~3–5pp. Callers are responsible for pre-sorting.

Persistence mirrors elo_engine.py: parquet at settings.pi_ratings_parquet_path.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_DEFAULT_RATING = 0.0


@dataclass(frozen=True)
class PiContext:
    home_pi_attack: float
    home_pi_defense: float
    away_pi_attack: float
    away_pi_defense: float
    pi_attack_diff: float
    pi_defense_diff: float


class PiRatingSystem:
    """Pi-rating with separate attack/defense per team.

    Uses goal-share (home_goals / total_goals) as the actual signal, which
    normalises across high/low-scoring leagues. lr=0.030 follows Constantinou
    & Fenton (2013). Ratings start at 0.0 (neutral) — differences are what matter.
    """

    _COLUMNS = [
        "match_id",
        "team_id",
        "pi_attack_pre",
        "pi_defense_pre",
        "pi_attack_post",
        "pi_defense_post",
        "league",
        "match_date",
    ]

    def __init__(self, parquet_path: Optional[Path] = None, lr: float = 0.030) -> None:
        self.lr = lr
        self._parquet_path = parquet_path
        self._attack: Dict[str, float] = defaultdict(float)
        self._defense: Dict[str, float] = defaultdict(float)
        self._cache: Optional[pd.DataFrame] = None
        if parquet_path and Path(parquet_path).exists():
            self._load_from_parquet(parquet_path)

    # ── Public API ────────────────────────────────────────────────────────────

    def get_context(self, home: str, away: str) -> PiContext:
        """Pre-match snapshot — does NOT mutate ratings."""
        ha, hd = self._attack[home], self._defense[home]
        aa, ad = self._attack[away], self._defense[away]
        return PiContext(
            home_pi_attack=round(ha, 4),
            home_pi_defense=round(hd, 4),
            away_pi_attack=round(aa, 4),
            away_pi_defense=round(ad, 4),
            pi_attack_diff=round(ha - aa, 4),
            pi_defense_diff=round(ad - hd, 4),
        )

    def update(
        self,
        match_id: str,
        home: str,
        away: str,
        home_goals: int,
        away_goals: int,
        league: str,
        match_date: datetime,
    ) -> None:
        """Apply post-match update. Idempotent by match_id.

        ⚠ Caller must guarantee matches arrive in chronological order.
        """
        table = self._load_table()
        if not table.empty and (table["match_id"] == match_id).any():
            logger.debug("Pi-rating update skipped for existing match_id=%s", match_id)
            self._replay_to_current(table)
            return

        total = home_goals + away_goals
        # Pre-match snapshot for persistence
        ha_pre, hd_pre = self._attack[home], self._defense[home]
        aa_pre, ad_pre = self._attack[away], self._defense[away]

        if total > 0:
            actual_home = home_goals / total
            exp_home = 1.0 / (1.0 + np.exp(-(self._attack[home] - self._defense[away])))
            exp_away = 1.0 / (1.0 + np.exp(-(self._attack[away] - self._defense[home])))

            self._attack[home] += self.lr * (actual_home - exp_home)
            self._defense[away] += self.lr * (exp_away - (away_goals / total))
            self._attack[away] += self.lr * ((away_goals / total) - exp_away)
            self._defense[home] += self.lr * (exp_home - actual_home)

        rows = [
            {
                "match_id": match_id,
                "team_id": home,
                "pi_attack_pre": ha_pre,
                "pi_defense_pre": hd_pre,
                "pi_attack_post": self._attack[home],
                "pi_defense_post": self._defense[home],
                "league": league,
                "match_date": pd.Timestamp(match_date),
            },
            {
                "match_id": match_id,
                "team_id": away,
                "pi_attack_pre": aa_pre,
                "pi_defense_pre": ad_pre,
                "pi_attack_post": self._attack[away],
                "pi_defense_post": self._defense[away],
                "league": league,
                "match_date": pd.Timestamp(match_date),
            },
        ]
        updated = pd.concat([table, pd.DataFrame(rows)], ignore_index=True)
        self._persist(updated[self._COLUMNS])

    # ── Internal ──────────────────────────────────────────────────────────────

    def _load_table(self) -> pd.DataFrame:
        if self._cache is not None:
            return self._cache
        if self._parquet_path and Path(self._parquet_path).exists():
            self._cache = pd.read_parquet(self._parquet_path)
            return self._cache
        return pd.DataFrame(columns=self._COLUMNS)

    def _replay_to_current(self, table: pd.DataFrame) -> None:
        """Rebuild in-memory ratings from persisted history (after cache miss)."""
        if table.empty:
            return
        for _, row in table.sort_values("match_date").iterrows():
            self._attack[row["team_id"]] = float(row["pi_attack_post"])
            self._defense[row["team_id"]] = float(row["pi_defense_post"])

    def _load_from_parquet(self, path: Path) -> None:
        try:
            table = pd.read_parquet(path)
            self._replay_to_current(table)
            self._cache = table
        except Exception:
            logger.warning(
                "Could not load pi_ratings parquet at %s; starting fresh.", path
            )

    def _persist(self, table: pd.DataFrame) -> None:
        if not self._parquet_path:
            return
        path = Path(self._parquet_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        table.to_parquet(path, index=False)
        self._cache = table
