"""Quarantine legacy market closings captured at or after kickoff.

Revision ID: 0009_quarantine_post_kickoff_closings
Revises: 0008_provider_elo_team_identity

The current market-observation writer rejects observations at kickoff or later.
This migration repairs only historical residue created before that invariant was
enforced: such rows remain auditable evidence, but they are no longer eligible
as current closing lines or CLV inputs.
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_quarantine_post_kickoff_closings"
down_revision = "0008_provider_elo_team_identity"
branch_labels = None
depends_on = None

_REMEDIATION_REVISION = revision


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE market_snapshots AS ms
            SET is_closing_line = FALSE,
                provenance = (
                    COALESCE(ms.provenance, '{}'::json)::jsonb
                    || jsonb_build_object(
                        'evidence_class', 'POST_KICKOFF_REJECTED',
                        'temporal_rejection', 'captured_at_not_before_kickoff',
                        'remediation_revision', :revision,
                        'prior_evidence_class', ms.provenance ->> 'evidence_class'
                    )
                )::json
            FROM matches AS m
            WHERE m.id = ms.match_id
              AND ms.is_closing_line IS TRUE
              AND ms.captured_at >= m.match_date
            """
        ).bindparams(revision=_REMEDIATION_REVISION)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE market_snapshots AS ms
            SET is_closing_line = TRUE,
                provenance = (
                    CASE
                        WHEN ms.provenance ->> 'prior_evidence_class' IS NULL THEN
                            ms.provenance::jsonb
                                - 'evidence_class'
                                - 'temporal_rejection'
                                - 'remediation_revision'
                                - 'prior_evidence_class'
                        ELSE
                            jsonb_set(
                                ms.provenance::jsonb
                                    - 'temporal_rejection'
                                    - 'remediation_revision'
                                    - 'prior_evidence_class',
                                '{evidence_class}',
                                to_jsonb(ms.provenance ->> 'prior_evidence_class'),
                                true
                            )
                    END
                )::json
            WHERE ms.provenance ->> 'remediation_revision' = :revision
            """
        ).bindparams(revision=_REMEDIATION_REVISION)
    )
