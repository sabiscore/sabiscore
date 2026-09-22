"""Berrar rating system — Berrar et al., Machine Learning (2019).

3 features per matchup:
  home_berrar_rating, away_berrar_rating, berrar_rating_diff

Captures recency-weighted opponent-quality form. Complements pi-ratings
(different signal dimension) and Elo (higher K sensitivity to recent results).

decay=0.98 applies a per-update exponential discount so recent results
carry more weight than distant history.

⚠ CHRONOLOGICAL INVARIANT: same as PiRatingSystem — matches MUST arrive
  in ascending match_date order. Caller is responsible for pre-sorting.

Persistence mirrors elo_engine.py: parquet at settings.berrar_ratings_parquet_path.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

logger = logging.getLogger(__name__)

_DEFAULT_RATING = 1500.0


@dataclass(frozen=True)
class BerrarContext:
    home_berrar_rating: float
    away_berrar_rating: float
    berrar_rating_diff: float


class BerrarRatingSystem:
    """Elo-style rating with recency decay and K=32."""

    _COLUMNS = [
        "match_id",
        "team_id",
        "rating_pre",
        "rating_post",
        "league",
        "match_date",
    ]

    def __init__(
        self, parquet_path: Optional[Path] = None, decay: float = 0.98
    ) -> None:
        self.decay = decay
        self._parquet_path = parquet_path
        self._ratings: Dict[str, float] = defaultdict(lambda: _DEFAULT_RATING)
        self._cache: Optional[pd.DataFrame] = None
        if parquet_path and Path(parquet_path).exists():
            self._load_from_parquet(parquet_path)

    # ── Public API ────────────────────────────────────────────────────────────

    def get_context(self, home: str, away: str) -> BerrarContext:
        """Pre-match snapshot — does NOT mutate ratings."""
        rh, ra = self._ratings[home], self._ratings[away]
        return BerrarContext(
            home_berrar_rating=round(rh, 2),
            away_berrar_rating=round(ra, 2),
            berrar_rating_diff=round(rh - ra, 2),
        )

    def update(
        self,
        match_id: str,
        home: str,
        away: str,
        result: int,
        league: str,
        match_date: datetime,
    ) -> None:
        """Apply post-match update. Idempotent by match_id.

        Args:
            result: 1=home win, 0=draw, -1=away win.

        ⚠ Caller must guarantee matches arrive in chronological order.
        """
        table = self._load_table()
        if not table.empty and (table["match_id"] == match_id).any():
            logger.debug("Berrar update skipped for existing match_id=%s", match_id)
            self._replay_to_current(table)
            return

        rh_pre, ra_pre = self._ratings[home], self._ratings[away]
        exp_h = 1.0 / (1.0 + 10 ** ((ra_pre - rh_pre) / 400.0))
        score_h = 1.0 if result == 1 else 0.5 if result == 0 else 0.0
        k = 32.0

        self._ratings[home] = rh_pre + k * (score_h - exp_h) * self.decay
        self._ratings[away] = (
            ra_pre + k * ((1.0 - score_h) - (1.0 - exp_h)) * self.decay
        )

        rows = [
            {
                "match_id": match_id,
                "team_id": home,
                "rating_pre": rh_pre,
                "rating_post": self._ratings[home],
                "league": league,
                "match_date": pd.Timestamp(match_date),
            },
            {
                "match_id": match_id,
                "team_id": away,
                "rating_pre": ra_pre,
                "rating_post": self._ratings[away],
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
        if table.empty:
            return
        for _, row in table.sort_values("match_date").iterrows():
            self._ratings[row["team_id"]] = float(row["rating_post"])

    def _load_from_parquet(self, path: Path) -> None:
        try:
            table = pd.read_parquet(path)
            self._replay_to_current(table)
            self._cache = table
        except Exception:
            logger.warning(
                "Could not load berrar_ratings parquet at %s; starting fresh.", path
            )

    def _persist(self, table: pd.DataFrame) -> None:
        if not self._parquet_path:
            return
        path = Path(self._parquet_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        table.to_parquet(path, index=False)
        self._cache = table
