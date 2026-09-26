"""An unmeasured StatsBomb cache must report no age, not age zero.

`staleness_seconds` feeds the match page's freshness pill and the
edge-quality freshness term. Production cannot read the parquet (no pyarrow),
and the aggregator returned 0 for that case, so every fixture rendered "Fresh"
and earned full freshness credit for a measurement that never happened.
"""

from datetime import datetime
from types import SimpleNamespace

import pandas as pd

from src.core.config import settings
from src.data.enrichment.statsbomb_aggregator import StatsBombAggregator
from src.services.upcoming_match_feature_service import _enrichment_staleness


def test_missing_cache_reports_unknown_age(tmp_path) -> None:
    result = StatsBombAggregator(tmp_path / "absent.parquet").get_team_features(
        "t1", "EPL", datetime(2026, 9, 25)
    )
    assert result.staleness_seconds is None
    assert set(result.data_gaps) == set(StatsBombAggregator.FEATURE_COLUMNS)


def test_unreadable_cache_reports_unknown_age(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "enable_statsbomb_enrichment", True)
    corrupt = tmp_path / "cache.parquet"
    corrupt.write_bytes(b"not a parquet file")
    result = StatsBombAggregator(corrupt).get_team_features("t1", "EPL", datetime(2026, 9, 25))
    assert result.staleness_seconds is None


def test_match_staleness_is_the_oldest_measured_side() -> None:
    side = lambda age: SimpleNamespace(staleness_seconds=age)  # noqa: E731
    assert _enrichment_staleness(side(None), side(None)) is None
    assert _enrichment_staleness(side(None), side(120)) == 120
    assert _enrichment_staleness(side(60), side(120)) == 120


def test_cache_is_not_read_while_enrichment_is_off(tmp_path, monkeypatch) -> None:
    """Directive v9 R1: no parquet engine is needed to serve the default path."""
    monkeypatch.setattr(settings, "enable_statsbomb_enrichment", False)
    cache = tmp_path / "cache.parquet"
    cache.write_bytes(b"present, but must not be opened")

    # Record, don't raise: _load_cache swallows every exception, so a raising
    # stub would pass against the unguarded code too.
    reads: list[object] = []
    monkeypatch.setattr(pd, "read_parquet", lambda *a, **k: reads.append(a) or pd.DataFrame())
    result = StatsBombAggregator(cache).get_team_features(
        "t1", "EPL", datetime(2026, 9, 25)
    )
    assert reads == []
    assert result.staleness_seconds is None
    assert set(result.data_gaps) == set(StatsBombAggregator.FEATURE_COLUMNS)
