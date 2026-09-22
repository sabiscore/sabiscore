"""normalize matches.season to YYYY/YYYY format

Revision ID: 0004_normalize_match_season
Revises: 0003_team_reconciliation
Create Date: 2026-08-03

fixture_sync_service previously wrote a bare 4-digit year ("2026") while the
feature-projection path derived "2026/2027" independently for the same
Match.season column — two incompatible formats that would silently break any
future join/filter keyed on season. Both writers now share
src.utils.season.canonical_season(); this data-only migration (no schema
change) normalizes rows written before that fix landed.

Before applying to a database that may hold real rows, size the blast radius:
    SELECT count(*) FROM matches WHERE season !~ '^[0-9]{4}/[0-9]{4}$';
The update is deterministic (recomputed from match_date) and idempotent —
already-correct rows are left untouched, and re-running is a no-op.
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "0004_normalize_match_season"
down_revision = "0003_team_reconciliation"
branch_labels = None
depends_on = None

_matches = sa.table(
    "matches",
    sa.column("id", sa.String),
    sa.column("match_date", sa.DateTime),
    sa.column("season", sa.String),
)


def _canonical_season(match_date: datetime) -> str:
    year = match_date.year
    if match_date.month >= 7:
        return f"{year}/{year + 1}"
    return f"{year - 1}/{year}"


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(_matches.c.id, _matches.c.match_date, _matches.c.season)
    ).fetchall()
    for row in rows:
        if row.match_date is None:
            continue
        expected = _canonical_season(row.match_date)
        if row.season != expected:
            bind.execute(
                _matches.update().where(_matches.c.id == row.id).values(season=expected)
            )


def downgrade() -> None:
    # ponytail: pre-migration values were already inconsistent (bare year in some
    # rows, YYYY/YYYY in others) — there is no single prior value to restore, and
    # the canonical format is a strict correctness improvement. Downgrade is a
    # deliberate no-op; re-running upgrade() after a downgrade is still safe.
    pass
