"""Rename league_id values from football-data.org codes to canonical names.

Revision ID: 0006_canonical_league_ids
Revises: 0005_clv_capture_schema
Create Date: 2026-08-08

Problem: fixture_sync_service stored fd.org competition codes ("PL", "DED",
"BL1", etc.) as league.id. Every other system (league_policy, full_analysis,
model_fetcher, capability probe) uses canonical names ("EPL", "EREDIVISIE",
"BUNDESLIGA", etc.). This meant all synced fixtures produced
LEAGUE_POLICY_UNAVAILABLE critical gaps and never produced real predictions.

Migration strategy (FK-safe, idempotent):
  1. Insert canonical League row (copy from old row if it exists)
  2. Update FK children: teams.league_id, matches.league_id, league_standings.league
  3. Delete old fd.org code League row

Safe to run on a DB that:
  - Has some fd.org rows (Eredivisie: DED) — those rows get renamed
  - Has no rows for a given code yet (EPL: PL) — steps are no-ops
  - Has already been partially fixed — NOT EXISTS guard prevents duplicate inserts
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_canonical_league_ids"
down_revision = "0005_clv_capture_schema"
branch_labels = None
depends_on = None

# fd.org code → canonical SabiScore league ID
_REMAP: list[tuple[str, str]] = [
    ("PL", "EPL"),
    ("PD", "LA_LIGA"),
    ("BL1", "BUNDESLIGA"),
    ("SA", "SERIE_A"),
    ("FL1", "LIGUE_1"),
    ("DED", "EREDIVISIE"),
    ("CL", "UCL"),
]


def upgrade() -> None:
    conn = op.get_bind()

    for old_id, new_id in _REMAP:
        # 1. Copy old league row to canonical id, skipping if canonical already exists
        #    or old row does not exist (the AND NOT EXISTS guard makes it idempotent).
        conn.execute(
            sa.text(
                "INSERT INTO leagues (id, name, country, tier, active, created_at, updated_at) "
                "SELECT :new_id, name, country, tier, active, created_at, updated_at "
                "FROM leagues WHERE id = :old_id "
                "AND NOT EXISTS (SELECT 1 FROM leagues AS l2 WHERE l2.id = :new_id2)"
            ),
            {"new_id": new_id, "old_id": old_id, "new_id2": new_id},
        )

        # 2. Update FK children to point to canonical id
        conn.execute(
            sa.text("UPDATE teams SET league_id = :new_id WHERE league_id = :old_id"),
            {"new_id": new_id, "old_id": old_id},
        )
        conn.execute(
            sa.text("UPDATE matches SET league_id = :new_id WHERE league_id = :old_id"),
            {"new_id": new_id, "old_id": old_id},
        )
        conn.execute(
            sa.text(
                "UPDATE league_standings SET league = :new_id WHERE league = :old_id"
            ),
            {"new_id": new_id, "old_id": old_id},
        )

        # 3. Remove old fd.org code row — all children now point to canonical
        conn.execute(
            sa.text("DELETE FROM leagues WHERE id = :old_id"),
            {"old_id": old_id},
        )


def downgrade() -> None:
    conn = op.get_bind()

    # Reverse: canonical → fd.org code
    for old_id, new_id in _REMAP:
        # Re-insert fd.org code row from canonical (if canonical exists and old not present)
        conn.execute(
            sa.text(
                "INSERT INTO leagues (id, name, country, tier, active, created_at, updated_at) "
                "SELECT :old_id, name, country, tier, active, created_at, updated_at "
                "FROM leagues WHERE id = :new_id "
                "AND NOT EXISTS (SELECT 1 FROM leagues AS l2 WHERE l2.id = :old_id2)"
            ),
            {"old_id": old_id, "new_id": new_id, "old_id2": old_id},
        )

        # Restore FK children
        conn.execute(
            sa.text("UPDATE teams SET league_id = :old_id WHERE league_id = :new_id"),
            {"old_id": old_id, "new_id": new_id},
        )
        conn.execute(
            sa.text("UPDATE matches SET league_id = :old_id WHERE league_id = :new_id"),
            {"old_id": old_id, "new_id": new_id},
        )
        conn.execute(
            sa.text(
                "UPDATE league_standings SET league = :old_id WHERE league = :new_id"
            ),
            {"old_id": old_id, "new_id": new_id},
        )

        # Remove canonical row
        conn.execute(
            sa.text("DELETE FROM leagues WHERE id = :new_id"),
            {"new_id": new_id},
        )
