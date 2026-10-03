"""Understat ML Tensor Formatter.

Extracts Understat telemetry from PostgreSQL, parses JSONB shot distributions,
computes directional xG and xA metrics along with 5-match rolling xG averages,
and returns memory-contiguous numpy.float32 arrays shaped for XGBoost and LightGBM
batch inference under strict memory overhead constraints (<= 512MB).
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any, Mapping, Sequence

import asyncpg  # type: ignore[import-untyped]
import numpy as np

logger = logging.getLogger(__name__)

# Maximum allowable memory overhead for feature matrix transformation (512MB)
MAX_MEMORY_BYTES: int = 512 * 1024 * 1024

# Feature column names produced by the formatter
UNDERSTAT_FEATURE_NAMES: list[str] = [
    "home_xg",
    "away_xg",
    "delta_xg",
    "total_xg",
    "home_xa",
    "away_xa",
    "delta_xa",
    "total_xa",
    "home_rolling_xg_5",
    "away_rolling_xg_5",
    "delta_rolling_xg_5",
]


class UnderstatTensorFormatter:
    """Production-grade ML feature tensor formatter for Understat match telemetry."""

    FEATURE_NAMES: list[str] = UNDERSTAT_FEATURE_NAMES

    @classmethod
    def get_feature_names(cls) -> list[str]:
        """Return canonical feature column names."""
        return list(cls.FEATURE_NAMES)

    @staticmethod
    def extract_xa_from_shot_telemetry(shot_telemetry: Any) -> tuple[float, float]:
        """Extract aggregated Expected Assists (xA) from JSONB shot telemetry.

        In Understat's schema, a shot with `player_assisted` represents an assist
        opportunity whose xA equals the shot's xG value.

        Args:
            shot_telemetry: Parsed dict or raw JSON string of shot telemetry.

        Returns:
            Tuple of (home_xa, away_xa).
        """
        if not shot_telemetry:
            return 0.0, 0.0

        data = shot_telemetry
        if isinstance(data, (str, bytes)):
            try:
                data = json.loads(data)
            except Exception as e:
                logger.warning("Failed to parse shot_telemetry JSON: %s", e)
                return 0.0, 0.0

        if not isinstance(data, dict):
            return 0.0, 0.0

        home_shots = data.get("h", []) or []
        away_shots = data.get("a", []) or []

        def _sum_assisted_xg(shots: list[dict[str, Any]]) -> float:
            total_xa = 0.0
            for shot in shots:
                if not isinstance(shot, dict):
                    continue
                # player_assisted present and not None indicates an assisted shot event
                if shot.get("player_assisted"):
                    try:
                        total_xa += float(shot.get("xG", 0.0))
                    except (ValueError, TypeError):
                        pass
            return total_xa

        home_xa = _sum_assisted_xg(home_shots)
        away_xa = _sum_assisted_xg(away_shots)
        return float(home_xa), float(away_xa)

    @staticmethod
    def _row_chronology_key(row: Mapping[str, Any]) -> Any:
        """Return the row's kickoff/date value used for chronological validation."""
        for key in ("kickoff_utc", "match_date", "date"):
            value = row.get(key)
            if value is not None:
                return value
        return None

    @classmethod
    def compute_rolling_averages(
        cls,
        records: Sequence[Mapping[str, Any]],
        window: int = 5,
        historical_team_xg: Mapping[str, Sequence[float]] | None = None,
        min_history: int | None = None,
    ) -> list[tuple[float | None, float | None]]:
        """Compute point-in-time rolling xG averages for home and away teams.

        For each record the value is the mean of that team's xG over its previous
        ``window`` completed matches *strictly before* the record. The record's
        own xG and every later record are never used.

        Missing observations (``None``) are never counted as ``0.0``. When a team
        has fewer than ``min_history`` prior observations (default: ``window``) the
        value is ``None`` (unknown / data gap); there is no cold-start substitution.

        Args:
            records: Chronologically ordered telemetry records. If every record
                carries ``kickoff_utc``/``match_date``/``date``, the order is
                verified and a ``ValueError`` is raised on regression.
            window: Rolling window size (default: 5).
            historical_team_xg: Optional pre-existing completed-match xG series
                per team (must pre-date ``records[0]``).
            min_history: Minimum prior observations required (default: window).

        Returns:
            List of (home_rolling_xg_5, away_rolling_xg_5) per record; ``None``
            marks an unknown value.
        """
        required = window if min_history is None else min_history
        team_history: dict[str, list[float]] = defaultdict(list)
        if historical_team_xg:
            for team, values in historical_team_xg.items():
                team_history[team] = [float(v) for v in values if v is not None]

        previous_key: Any = None
        rolling_results: list[tuple[float | None, float | None]] = []

        for row in records:
            key = cls._row_chronology_key(row)
            if key is not None and previous_key is not None:
                try:
                    out_of_order = key < previous_key
                except TypeError as exc:
                    raise ValueError(
                        "Telemetry records carry non-comparable chronology keys"
                    ) from exc
                if out_of_order:
                    raise ValueError(
                        "Telemetry records must be in chronological order for "
                        "point-in-time rolling xG"
                    )
            if key is not None:
                previous_key = key

            home_team = str(row.get("home_team_slug", ""))
            away_team = str(row.get("away_team_slug", ""))
            home_prior = team_history[home_team]
            away_prior = team_history[away_team]

            home_roll: float | None = (
                float(np.mean(home_prior[-window:]))
                if len(home_prior) >= required
                else None
            )
            away_roll: float | None = (
                float(np.mean(away_prior[-window:]))
                if len(away_prior) >= required
                else None
            )
            rolling_results.append((home_roll, away_roll))

            # Only after the prediction value is fixed does this match become history.
            home_xg = row.get("home_xg")
            away_xg = row.get("away_xg")
            if home_xg is not None:
                team_history[home_team].append(float(home_xg))
            if away_xg is not None:
                team_history[away_team].append(float(away_xg))

        return rolling_results

    @classmethod
    def format_batch(
        cls,
        records: Sequence[Mapping[str, Any]],
        historical_team_xg: Mapping[str, Sequence[float]] | None = None,
    ) -> np.ndarray:
        """Transform telemetry records into a memory-contiguous float32 numpy array.

        Columns 0-7 (``home_xg`` .. ``total_xa``) describe the record's *own*
        completed match and are post-match evidence: they must never be used as
        pre-match predictors for that same fixture. Columns 8-10 are the
        point-in-time rolling features; unknown values are ``NaN``.

        Validates memory usage to strictly respect the 512MB RAM constraint,
        computes directional and aggregated metrics, and ensures C-contiguous
        memory layout suitable for direct consumption by XGBoost DMatrix or
        LightGBM Dataset.

        Args:
            records: List or sequence of records from match_telemetry.
            historical_team_xg: Optional prior xG values per team for rolling calculation.

        Returns:
            Memory-contiguous numpy.ndarray with shape (N, 11) and dtype float32.

        Raises:
            MemoryError: If the allocated tensor would exceed MAX_MEMORY_BYTES (512MB).
        """
        n_rows = len(records)
        n_features = len(cls.FEATURE_NAMES)

        if n_rows == 0:
            empty = np.empty((0, n_features), dtype=np.float32)
            return np.ascontiguousarray(empty, dtype=np.float32)

        # Strict memory footprint guard
        tensor_bytes = n_rows * n_features * np.dtype(np.float32).itemsize
        if tensor_bytes > MAX_MEMORY_BYTES:
            raise MemoryError(
                f"Batch size {n_rows} rows would allocate {tensor_bytes / (1024 * 1024):.1f} MB, "
                f"exceeding the strict {MAX_MEMORY_BYTES / (1024 * 1024)} MB limit."
            )

        # Pre-allocate contiguous array directly to eliminate allocation fragmentation
        features = np.empty((n_rows, n_features), dtype=np.float32)

        # Compute rolling xG values
        rolling_values = cls.compute_rolling_averages(
            records, window=5, historical_team_xg=historical_team_xg
        )

        for i, row in enumerate(records):
            home_xg_raw = row.get("home_xg")
            away_xg_raw = row.get("away_xg")
            home_xg = float(home_xg_raw) if home_xg_raw is not None else float("nan")
            away_xg = float(away_xg_raw) if away_xg_raw is not None else float("nan")

            # Directional metrics
            delta_xg = home_xg - away_xg
            total_xg = home_xg + away_xg

            # Extract xA from shot_telemetry if not pre-computed or if verify required
            shot_telemetry = row.get("shot_telemetry")
            # A missing stored xA is unknown (NaN), never 0.0. A 0.0 extracted from
            # present shot telemetry is a measurement and is kept.
            stored_home_xa = row.get("home_xa")
            stored_away_xa = row.get("away_xa")
            home_xa = float(stored_home_xa) if stored_home_xa is not None else float("nan")
            away_xa = float(stored_away_xa) if stored_away_xa is not None else float("nan")
            if shot_telemetry is not None:
                extracted_home_xa, extracted_away_xa = cls.extract_xa_from_shot_telemetry(shot_telemetry)
                if extracted_home_xa > 0.0 or stored_home_xa is None:
                    home_xa = extracted_home_xa
                if extracted_away_xa > 0.0 or stored_away_xa is None:
                    away_xa = extracted_away_xa

            delta_xa = home_xa - away_xa
            total_xa = home_xa + away_xa

            home_roll_5_raw, away_roll_5_raw = rolling_values[i]
            home_roll_5 = float("nan") if home_roll_5_raw is None else home_roll_5_raw
            away_roll_5 = float("nan") if away_roll_5_raw is None else away_roll_5_raw
            delta_rolling_xg_5 = home_roll_5 - away_roll_5  # NaN when either side unknown

            features[i, 0] = home_xg
            features[i, 1] = away_xg
            features[i, 2] = delta_xg
            features[i, 3] = total_xg
            features[i, 4] = home_xa
            features[i, 5] = away_xa
            features[i, 6] = delta_xa
            features[i, 7] = total_xa
            features[i, 8] = home_roll_5
            features[i, 9] = away_roll_5
            features[i, 10] = delta_rolling_xg_5

        # Guarantee contiguous memory layout
        contiguous_tensor = np.ascontiguousarray(features, dtype=np.float32)
        assert contiguous_tensor.flags["C_CONTIGUOUS"], "Output array must be C-contiguous"
        return contiguous_tensor

    @classmethod
    async def fetch_and_format(
        cls,
        conn: asyncpg.Connection,
        match_ids: Sequence[int] | None = None,
        limit: int = 1000,
    ) -> np.ndarray:
        """Fetch records from PostgreSQL match_telemetry and format into ML tensors.

        Args:
            conn: Connected asyncpg Connection.
            match_ids: Optional list of match IDs to filter.
            limit: Maximum records to retrieve.

        Returns:
            Contiguous float32 feature tensor.
        """
        if match_ids:
            query = """
            SELECT match_id, provider_id, home_team_slug, away_team_slug,
                   home_xg, away_xg, home_xa, away_xa, shot_telemetry,
                   created_at, updated_at
            FROM match_telemetry
            WHERE match_id = ANY($1::int[])
            ORDER BY created_at ASC;
            """
            rows = await conn.fetch(query, list(match_ids))
        else:
            query = """
            SELECT match_id, provider_id, home_team_slug, away_team_slug,
                   home_xg, away_xg, home_xa, away_xa, shot_telemetry,
                   created_at, updated_at
            FROM match_telemetry
            ORDER BY created_at ASC
            LIMIT $1;
            """
            rows = await conn.fetch(query, limit)

        records = [dict(row) for row in rows]
        return cls.format_batch(records)


__all__ = [
    "UnderstatTensorFormatter",
    "UNDERSTAT_FEATURE_NAMES",
    "MAX_MEMORY_BYTES",
]
