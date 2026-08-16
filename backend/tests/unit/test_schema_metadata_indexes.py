"""Schema metadata must retain every migration-owned production index."""
from __future__ import annotations

from src.core.database import Base
from src.db import models as _db_models  # noqa: F401


EXPECTED_MIGRATION_INDEXES = {
    "provider_request_summaries": {
        "ix_provider_request_provider_time",
        "ix_provider_request_status",
    },
    "provider_capabilities": {"ix_provider_capability_provider_comp"},
    "provider_quota_observations": {"ix_provider_quota_provider_time"},
    "canonical_teams": {"ix_canonical_teams_competition_name"},
    "canonical_fixtures": {"ix_canonical_fixtures_comp_kickoff"},
    "provider_event_mappings": {
        "ix_provider_event_provider_id",
        "ix_provider_event_fixture",
    },
    "market_snapshots": {
        "ix_market_snapshots_fixture_time",
        "ix_market_snapshots_bookmaker",
        "ix_market_snapshots_match_id",
    },
}


def test_migration_owned_indexes_are_present_in_sqlalchemy_metadata() -> None:
    """Prevent Alembic autogenerate from proposing destructive index removals."""

    for table_name, expected_indexes in EXPECTED_MIGRATION_INDEXES.items():
        table = Base.metadata.tables[table_name]
        actual_indexes = {index.name for index in table.indexes}
        assert expected_indexes <= actual_indexes, (
            f"{table_name} missing migration-owned indexes: "
            f"{sorted(expected_indexes - actual_indexes)}"
        )
