"""Phase 7-A StatsBomb aggregation with cache-first feature extraction."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from ...core.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StatsBombFeatureResult:
    features: Dict[str, float]
    data_gaps: List[str]
    # None when nothing was measured (unreadable or empty cache, no dated rows).
    # 0 would read as "measured just now" and render as Fresh.
    staleness_seconds: Optional[int]


class StatsBombAggregator:
    """Read and aggregate tactical event features from a cached parquet store.

    The cache format is match-level with one row per team per match and these columns:
    match_id, team_id, league, match_date, ppda_ratio, progressive_carry_diff,
    shot_quality_diff, key_passes_under_pressure_diff, set_piece_xg_diff
    """

    FEATURE_COLUMNS: Tuple[str, ...] = (
        "ppda_ratio",
        "progressive_carry_diff",
        "shot_quality_diff",
        "key_passes_under_pressure_diff",
        "set_piece_xg_diff",
    )

    def __init__(self, cache_path: Optional[Path] = None) -> None:
        self.cache_path = Path(cache_path or settings.statsbomb_cache_path)

    def get_team_features(
        self,
        team_id: str,
        league: str,
        match_date: datetime,
        window: int = 5,
    ) -> StatsBombFeatureResult:
        table = self._load_cache()
        if table.empty:
            return StatsBombFeatureResult(
                features=self._default_features(),
                data_gaps=list(self.FEATURE_COLUMNS),
                staleness_seconds=None,
            )

        league_rows = table[table["league"].astype(str).str.lower() == league.lower()]
        team_rows = league_rows[
            (league_rows["team_id"].astype(str) == str(team_id))
            & (pd.to_datetime(league_rows["match_date"]) < pd.Timestamp(match_date))
        ].sort_values("match_date")

        if team_rows.empty:
            return StatsBombFeatureResult(
                features=self._default_features(),
                data_gaps=list(self.FEATURE_COLUMNS),
                staleness_seconds=self._staleness_seconds(league_rows),
            )

        recent = team_rows.tail(window)
        features: Dict[str, float] = {}
        data_gaps: List[str] = []

        staleness = self._staleness_seconds(recent)
        max_staleness = settings.statsbomb_staleness_max_days * 86_400
        # B13: if cache data exceeds the staleness window, treat ALL features as DATA_GAP
        # rather than surfacing stale values as if they were live.
        if staleness is not None and staleness > max_staleness > 0:
            logger.info(
                "StatsBomb cache stale (%ds > limit %ds) for team %s — marking all features as DATA_GAP",
                staleness,
                max_staleness,
                team_id,
            )
            return StatsBombFeatureResult(
                features=self._default_features(),
                data_gaps=list(self.FEATURE_COLUMNS),
                staleness_seconds=staleness,
            )

        for column in self.FEATURE_COLUMNS:
            if column not in recent.columns:
                features[column] = 0.0
                data_gaps.append(column)
                continue
            value = pd.to_numeric(recent[column], errors="coerce").mean()
            if pd.isna(value):
                features[column] = 0.0
                data_gaps.append(column)
            else:
                features[column] = float(value)

        return StatsBombFeatureResult(
            features=features,
            data_gaps=data_gaps,
            staleness_seconds=self._staleness_seconds(recent),
        )

    # Whether this process has already reported an unreadable cache. The failure
    # is a property of the runtime (a missing parquet engine), not of the
    # request, so it is the same on every call -- production emitted this
    # five-line traceback twice per /full-analysis request on 2026-09-22.
    # Class-level so it stays quiet across aggregator instances too.
    _cache_failure_reported: bool = False

    def _load_cache(self) -> pd.DataFrame:
        # Directive v9 R1: nothing reads these features unless enrichment is on,
        # and the five tactical columns are ALWAYS_DATA_GAP anyway (coverage
        # 23.58% < 85%). Reading the parquet would need pyarrow (~RSS we don't
        # have on a 512 MB instance) to buy nothing; skip it. An empty table
        # yields the same five gaps and a None age.
        if not settings.enable_statsbomb_enrichment or not self.cache_path.exists():
            return pd.DataFrame()
        try:
            return pd.read_parquet(self.cache_path)
        except Exception as exc:
            if not StatsBombAggregator._cache_failure_reported:
                StatsBombAggregator._cache_failure_reported = True
                logger.warning(
                    "Unable to read StatsBomb cache %s (reported once per process): %s",
                    self.cache_path,
                    exc,
                )
            return pd.DataFrame()

    def _staleness_seconds(self, rows: pd.DataFrame) -> Optional[int]:
        if rows.empty or "match_date" not in rows.columns:
            return None
        latest = pd.to_datetime(rows["match_date"], errors="coerce").max()
        if pd.isna(latest):
            return None
        now = datetime.now(timezone.utc)
        latest_ts = latest.to_pydatetime()
        if latest_ts.tzinfo is None:
            latest_ts = latest_ts.replace(tzinfo=timezone.utc)
        return max(0, int((now - latest_ts).total_seconds()))

    def _default_features(self) -> Dict[str, float]:
        return {
            "ppda_ratio": 1.0,
            "progressive_carry_diff": 0.0,
            "shot_quality_diff": 0.0,
            "key_passes_under_pressure_diff": 0.0,
            "set_piece_xg_diff": 0.0,
        }
