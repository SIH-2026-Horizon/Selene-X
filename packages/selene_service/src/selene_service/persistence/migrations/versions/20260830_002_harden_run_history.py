"""Harden run transitions, event ordering, and digest validation.

Revision ID: 20260830_002
Revises: 20260830_001
Create Date: 2026-08-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260830_002"
down_revision = "20260830_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add forward-only concurrency and integrity protections to existing state."""

    # Existing databases can contain rows already.  Add nullable/defaulted
    # fields first, backfill every event deterministically, then make the final
    # guarantees mandatory.  UUID is the stable tie-breaker for equal timestamps.
    op.add_column(
        "runs",
        sa.Column("state_version", sa.Integer(), server_default=sa.text("0"), nullable=True),
    )
    op.add_column(
        "runs",
        sa.Column("event_sequence", sa.Integer(), server_default=sa.text("0"), nullable=True),
    )
    op.add_column("run_events", sa.Column("sequence", sa.Integer(), nullable=True))

    # Revision 001 intentionally protects history from every update.  This
    # migration is the sole schema-authorised exception: disable the trigger
    # only for the deterministic ordinal backfill, then restore it before any
    # application transaction can observe the final revision.
    op.execute("ALTER TABLE run_events DISABLE TRIGGER trg_run_events_immutable")
    op.execute(
        """
        WITH ordered_events AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY run_id
                    ORDER BY recorded_at ASC, id ASC
                )::integer AS assigned_sequence
            FROM run_events
        )
        UPDATE run_events AS event
        SET sequence = ordered_events.assigned_sequence
        FROM ordered_events
        WHERE event.id = ordered_events.id
        """
    )
    op.execute("ALTER TABLE run_events ENABLE TRIGGER trg_run_events_immutable")
    op.execute(
        """
        UPDATE runs AS run
        SET
            state_version = COALESCE(run.state_version, 0),
            event_sequence = COALESCE(
                (
                    SELECT MAX(event.sequence)
                    FROM run_events AS event
                    WHERE event.run_id = run.id
                ),
                0
            )
        """
    )

    op.alter_column(
        "runs",
        "state_version",
        existing_type=sa.Integer(),
        nullable=False,
        server_default=sa.text("0"),
    )
    op.alter_column(
        "runs",
        "event_sequence",
        existing_type=sa.Integer(),
        nullable=False,
        server_default=sa.text("1"),
    )
    op.alter_column("run_events", "sequence", existing_type=sa.Integer(), nullable=False)

    op.create_check_constraint("ck_runs_state_version_nonnegative", "runs", "state_version >= 0")
    op.create_check_constraint("ck_runs_event_sequence_nonnegative", "runs", "event_sequence >= 0")
    op.create_check_constraint("ck_run_events_sequence_positive", "run_events", "sequence >= 1")
    op.create_unique_constraint("uq_run_events_run_sequence", "run_events", ["run_id", "sequence"])

    # ``NOT VALID`` preserves a safe upgrade path for pre-existing historical
    # records while enforcing canonical digests for every later insert/update.
    op.execute(
        """
        ALTER TABLE products
        ADD CONSTRAINT ck_products_manifest_sha256_format
        CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$') NOT VALID
        """
    )
    op.execute(
        """
        ALTER TABLE runs
        ADD CONSTRAINT ck_runs_parameters_sha256_format
        CHECK (parameters_sha256 ~ '^[0-9a-f]{64}$') NOT VALID
        """
    )
    op.execute(
        """
        ALTER TABLE run_stages
        ADD CONSTRAINT ck_run_stages_input_sha256_format
        CHECK (input_sha256 IS NULL OR input_sha256 ~ '^[0-9a-f]{64}$') NOT VALID
        """
    )
    op.execute(
        """
        ALTER TABLE run_stages
        ADD CONSTRAINT ck_run_stages_output_sha256_format
        CHECK (output_sha256 IS NULL OR output_sha256 ~ '^[0-9a-f]{64}$') NOT VALID
        """
    )
    op.execute(
        """
        ALTER TABLE artifacts
        ADD CONSTRAINT ck_artifacts_sha256_format
        CHECK (sha256 ~ '^[0-9a-f]{64}$') NOT VALID
        """
    )
    op.execute(
        """
        ALTER TABLE idempotency_records
        ADD CONSTRAINT ck_idempotency_request_digest_format
        CHECK (request_digest ~ '^[0-9a-f]{64}$') NOT VALID
        """
    )


def downgrade() -> None:
    """Return to the original revision's schema without rewriting history."""

    op.drop_constraint("ck_idempotency_request_digest_format", "idempotency_records", type_="check")
    op.drop_constraint("ck_artifacts_sha256_format", "artifacts", type_="check")
    op.drop_constraint("ck_run_stages_output_sha256_format", "run_stages", type_="check")
    op.drop_constraint("ck_run_stages_input_sha256_format", "run_stages", type_="check")
    op.drop_constraint("ck_runs_parameters_sha256_format", "runs", type_="check")
    op.drop_constraint("ck_products_manifest_sha256_format", "products", type_="check")
    op.drop_constraint("uq_run_events_run_sequence", "run_events", type_="unique")
    op.drop_constraint("ck_run_events_sequence_positive", "run_events", type_="check")
    op.drop_constraint("ck_runs_event_sequence_nonnegative", "runs", type_="check")
    op.drop_constraint("ck_runs_state_version_nonnegative", "runs", type_="check")
    op.drop_column("run_events", "sequence")
    op.drop_column("runs", "event_sequence")
    op.drop_column("runs", "state_version")
