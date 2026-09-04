"""Create initial PostgreSQL/PostGIS service-state authority.

Revision ID: 20260830_001
Revises:
Create Date: 2026-08-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260830_001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the only durable service-state schema.

    The supported local target is PostgreSQL with the PostGIS extension package
    already installed.  ``IF NOT EXISTS`` lets a migration role safely reuse an
    existing extension; that role still needs the PostGIS extension privilege.
    """

    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "subjects",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("subject_name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_subjects"),
        sa.UniqueConstraint("subject_name", name="uq_subjects_subject_name"),
    )
    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key_digest", sa.String(length=128), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column(
            "scopes", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("char_length(key_digest) >= 32", name="ck_api_keys_digest_length"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_api_keys"),
        sa.UniqueConstraint("key_digest", name="uq_api_keys_key_digest"),
    )
    op.create_index("ix_api_keys_subject_id", "api_keys", ["subject_id"], unique=False)

    op.create_table(
        "products",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_identity", sa.String(length=512), nullable=False),
        sa.Column("payload_type", sa.String(length=64), nullable=False),
        sa.Column(
            "payload_metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("validation_state", sa.String(length=32), nullable=False),
        sa.Column(
            "validation_details",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("quarantine_reason", sa.Text(), nullable=True),
        # -1 avoids fabricating an Earth SRID.  footprint_crs records a lunar
        # WKT/PROJJSON declaration before a spatial query is permitted.
        sa.Column(
            "footprint",
            Geometry(geometry_type="POLYGON", srid=-1, spatial_index=False),
            nullable=True,
        ),
        sa.Column("footprint_crs", sa.Text(), nullable=True),
        sa.Column("footprint_srid", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["owner_subject_id"], ["subjects.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_products"),
        sa.UniqueConstraint(
            "owner_subject_id", "product_identity", name="uq_products_owner_identity"
        ),
    )
    op.create_index("ix_products_manifest_sha256", "products", ["manifest_sha256"], unique=False)
    op.create_index(
        "ix_products_footprint",
        "products",
        ["footprint"],
        unique=False,
        postgresql_using="gist",
    )

    op.create_table(
        "runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reference_product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parameters_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "algorithm_versions",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "model_versions",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "execution_state", sa.String(length=32), server_default="created", nullable=False
        ),
        sa.Column("computed_verdict", sa.String(length=32), nullable=True),
        sa.Column(
            "effective_disposition", sa.String(length=32), server_default="pending", nullable=False
        ),
        sa.Column("code_revision", sa.String(length=128), nullable=False),
        sa.Column("environment_fingerprint", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "execution_state IN ('created', 'queued', 'running', 'cancelling', "
            "'cancelled', 'succeeded', 'failed')",
            name="ck_runs_execution_state",
        ),
        sa.ForeignKeyConstraint(["owner_subject_id"], ["subjects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reference_product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_runs"),
    )
    op.create_index("ix_runs_execution_state", "runs", ["execution_state"], unique=False)
    op.create_index(
        "ix_runs_effective_disposition", "runs", ["effective_disposition"], unique=False
    )
    op.create_index(
        "ix_runs_owner_created_at", "runs", ["owner_subject_id", "created_at"], unique=False
    )

    op.create_table(
        "run_stages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stage_name", sa.String(length=128), nullable=False),
        sa.Column("stage_ordinal", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), server_default="1", nullable=False),
        sa.Column("execution_state", sa.String(length=32), nullable=False),
        sa.Column("input_sha256", sa.String(length=64), nullable=True),
        sa.Column("output_sha256", sa.String(length=64), nullable=True),
        sa.Column("lease_holder", sa.String(length=255), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("warning_document", postgresql.JSONB(), nullable=True),
        sa.Column("failure_document", postgresql.JSONB(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("atomic_completion_marker", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_run_stages"),
        sa.UniqueConstraint("run_id", "stage_name", "attempt", name="uq_run_stages_attempt"),
    )
    op.create_index(
        "ix_run_stages_run_ordinal", "run_stages", ["run_id", "stage_ordinal"], unique=False
    )

    op.create_table(
        "artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_stage_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.String(length=128), nullable=False),
        sa.Column("storage_uri", sa.Text(), nullable=False),
        sa.Column("media_type", sa.String(length=255), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("schema_uri", sa.Text(), nullable=True),
        sa.Column("crs_metadata", postgresql.JSONB(), nullable=True),
        sa.Column(
            "validation_document",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "publication_state", sa.String(length=32), server_default="published", nullable=False
        ),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("publication_state = 'published'", name="ck_artifacts_published_only"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["run_stage_id"], ["run_stages.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_artifacts"),
        sa.UniqueConstraint("run_id", "storage_uri", name="uq_artifacts_run_storage_uri"),
    )
    op.create_index("ix_artifacts_checksum", "artifacts", ["sha256"], unique=False)
    op.create_index("ix_artifacts_run_kind", "artifacts", ["run_id", "kind"], unique=False)

    op.create_table(
        "metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("report_kind", sa.String(length=64), nullable=False),
        sa.Column("report_version", sa.String(length=128), nullable=False),
        sa.Column("report_document", postgresql.JSONB(), nullable=False),
        sa.Column(
            "indexed_fields",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("computed_verdict", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_metrics"),
        sa.UniqueConstraint(
            "run_id", "report_kind", "report_version", name="uq_metrics_report_version"
        ),
    )
    op.create_index("ix_metrics_computed_verdict", "metrics", ["computed_verdict"], unique=False)
    op.create_index("ix_metrics_run_kind", "metrics", ["run_id", "report_kind"], unique=False)

    op.create_table(
        "reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=128), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("source_computed_verdict", sa.String(length=32), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["actor_subject_id"], ["subjects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_reviews"),
    )
    op.create_index(
        "ix_reviews_run_recorded_at", "reviews", ["run_id", "recorded_at"], unique=False
    )

    op.create_table(
        "idempotency_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("result_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("response_document", postgresql.JSONB(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_idempotency_records"),
        sa.UniqueConstraint(
            "subject_id",
            "operation",
            "idempotency_key",
            name="uq_idempotency_subject_op_key",
        ),
    )
    op.create_index(
        "ix_idempotency_records_expires_at", "idempotency_records", ["expires_at"], unique=False
    )

    op.create_table(
        "run_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_subject_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("execution_state", sa.String(length=32), nullable=True),
        sa.Column(
            "event_document",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["actor_subject_id"], ["subjects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_run_events"),
    )
    op.create_index(
        "ix_run_events_run_recorded_at",
        "run_events",
        ["run_id", "recorded_at"],
        unique=False,
    )

    # Append-only history is enforced in PostgreSQL, including against raw SQL.
    # ORM conventions alone are insufficient for service audit evidence.
    op.execute(
        """
        CREATE FUNCTION selene_reject_history_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'SELENE-XR history rows are immutable'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_run_events_immutable
        BEFORE UPDATE OR DELETE ON run_events
        FOR EACH ROW EXECUTE FUNCTION selene_reject_history_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_reviews_immutable
        BEFORE UPDATE OR DELETE ON reviews
        FOR EACH ROW EXECUTE FUNCTION selene_reject_history_mutation()
        """
    )


def downgrade() -> None:
    """Remove the initial schema in reverse dependency order for test targets."""

    op.execute("DROP TRIGGER IF EXISTS trg_run_events_immutable ON run_events")
    op.execute("DROP TRIGGER IF EXISTS trg_reviews_immutable ON reviews")
    op.execute("DROP FUNCTION IF EXISTS selene_reject_history_mutation()")
    op.drop_index("ix_run_events_run_recorded_at", table_name="run_events")
    op.drop_table("run_events")
    op.drop_index("ix_idempotency_records_expires_at", table_name="idempotency_records")
    op.drop_table("idempotency_records")
    op.drop_index("ix_reviews_run_recorded_at", table_name="reviews")
    op.drop_table("reviews")
    op.drop_index("ix_metrics_run_kind", table_name="metrics")
    op.drop_index("ix_metrics_computed_verdict", table_name="metrics")
    op.drop_table("metrics")
    op.drop_index("ix_artifacts_run_kind", table_name="artifacts")
    op.drop_index("ix_artifacts_checksum", table_name="artifacts")
    op.drop_table("artifacts")
    op.drop_index("ix_run_stages_run_ordinal", table_name="run_stages")
    op.drop_table("run_stages")
    op.drop_index("ix_runs_owner_created_at", table_name="runs")
    op.drop_index("ix_runs_effective_disposition", table_name="runs")
    op.drop_index("ix_runs_execution_state", table_name="runs")
    op.drop_table("runs")
    op.drop_index("ix_products_footprint", table_name="products")
    op.drop_index("ix_products_manifest_sha256", table_name="products")
    op.drop_table("products")
    op.drop_index("ix_api_keys_subject_id", table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_table("subjects")
