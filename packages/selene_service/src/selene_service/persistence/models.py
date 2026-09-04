"""Typed ORM mapping for the service's durable PostgreSQL/PostGIS state.

The mapping deliberately represents service coordination and provenance only.
It neither stores image bytes nor reimplements a scientific pipeline.  Schema
changes are made exclusively through the Alembic revisions in this package.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKBElement
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, validates

from selene_service.persistence.validation import validate_sha256


class Base(DeclarativeBase):
    """Base metadata for Alembic and the service persistence mapping."""


class Subject(Base):
    """A minimal service identity that can own products and API credentials."""

    __tablename__ = "subjects"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    __table_args__ = (UniqueConstraint("subject_name", name="uq_subjects_subject_name"),)

    subject_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class ApiKey(Base):
    """A scoped credential represented exclusively by its one-way digest."""

    __tablename__ = "api_keys"
    __table_args__ = (
        CheckConstraint("char_length(key_digest) >= 32", name="ck_api_keys_digest_length"),
        Index("ix_api_keys_subject_id", "subject_id"),
        UniqueConstraint("key_digest", name="uq_api_keys_key_digest"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    subject_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False
    )
    # Never add a plaintext-token column here.  Credential verification compares
    # a supplied token's digest with this value.
    key_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    label: Mapped[str | None] = mapped_column(String(255))
    scopes: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class UserAccount(Base):
    """A human operator's login, 1:1-linked to its own durable subject."""

    __tablename__ = "user_accounts"
    __table_args__ = (
        CheckConstraint("role IN ('analyst', 'reviewer', 'admin')", name="ck_user_accounts_role"),
        UniqueConstraint("subject_id", name="uq_user_accounts_subject_id"),
        UniqueConstraint("username", name="uq_user_accounts_username"),
        Index("ix_user_accounts_created_by_user_account_id", "created_by_user_account_id"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    subject_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False
    )
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    # Argon2id encoded hash string (algorithm, params, salt, and digest all
    # inline). Never a plaintext password or a separate salt column.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        nullable=False, default=True, server_default=text("true")
    )
    created_by_user_account_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="SET NULL")
    )
    failed_login_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    @validates("username")
    def _normalize_username(self, _key: str, value: str) -> str:
        normalized = value.strip().casefold()
        if not normalized:
            raise ValueError("username must not be blank")
        return normalized


class UserSession(Base):
    """An opaque, server-side, revocable operator session."""

    __tablename__ = "user_sessions"
    __table_args__ = (
        Index("ix_user_sessions_user_account_id", "user_account_id"),
        Index("ix_user_sessions_expires_at", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_account_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Product(Base):
    """Validated product metadata; imagery itself remains outside PostgreSQL."""

    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint(
            "manifest_sha256 ~ '^[0-9a-f]{64}$'", name="ck_products_manifest_sha256_format"
        ),
        UniqueConstraint("owner_subject_id", "product_identity", name="uq_products_owner_identity"),
        Index("ix_products_footprint", "footprint", postgresql_using="gist"),
        Index("ix_products_manifest_sha256", "manifest_sha256"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_subject_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False
    )
    product_identity: Mapped[str] = mapped_column(String(512), nullable=False)
    payload_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    validation_state: Mapped[str] = mapped_column(String(32), nullable=False)
    validation_details: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    quarantine_reason: Mapped[str | None] = mapped_column(Text)
    # SRID -1 deliberately avoids claiming an Earth CRS.  The accompanying
    # WKT/PROJJSON string documents the actual lunar CRS (or an explicit
    # unknown state) for every stored footprint.
    footprint: Mapped[WKBElement | None] = mapped_column(
        Geometry(geometry_type="POLYGON", srid=-1, spatial_index=False)
    )
    footprint_crs: Mapped[str | None] = mapped_column(Text)
    footprint_srid: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    @validates("manifest_sha256")
    def _validate_manifest_sha256(self, key: str, value: str) -> str:
        return validate_sha256(value, field_name=key)


class Run(Base):
    """Frozen run definition and independent execution/scientific decisions."""

    __tablename__ = "runs"
    __table_args__ = (
        CheckConstraint(
            "execution_state IN ('created', 'queued', 'running', 'cancelling', "
            "'cancelled', 'succeeded', 'failed')",
            name="ck_runs_execution_state",
        ),
        CheckConstraint("state_version >= 0", name="ck_runs_state_version_nonnegative"),
        CheckConstraint("event_sequence >= 0", name="ck_runs_event_sequence_nonnegative"),
        CheckConstraint(
            "parameters_sha256 ~ '^[0-9a-f]{64}$'", name="ck_runs_parameters_sha256_format"
        ),
        Index("ix_runs_owner_created_at", "owner_subject_id", "created_at"),
        Index("ix_runs_execution_state", "execution_state"),
        Index("ix_runs_effective_disposition", "effective_disposition"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_subject_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False
    )
    source_product_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    reference_product_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    # The canonical document is frozen with the digest at creation time.  It
    # gives a future runner the exact requested parameters without treating a
    # mutable configuration file or a server-local path as state authority.
    #
    # ``NULL`` is meaningful for rows created before this supplementary field
    # existed: a historic digest alone cannot reconstruct the lost document.
    # New API writes always supply a non-empty canonical document.
    parameters_document: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    parameters_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm_versions: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    model_versions: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    execution_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default="created", server_default="created"
    )
    state_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    event_sequence: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    # These remain distinct: lifecycle does not manufacture scientific truth,
    # and a review does not rewrite the computed verdict.
    computed_verdict: Mapped[str | None] = mapped_column(String(32))
    effective_disposition: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default="pending"
    )
    code_revision: Mapped[str] = mapped_column(String(128), nullable=False)
    environment_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    @validates("parameters_sha256")
    def _validate_parameters_sha256(self, key: str, value: str) -> str:
        return validate_sha256(value, field_name=key)


class RunStage(Base):
    """An ordered, retry-aware record of one run's scientific stage."""

    __tablename__ = "run_stages"
    __table_args__ = (
        CheckConstraint(
            "input_sha256 IS NULL OR input_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_run_stages_input_sha256_format",
        ),
        CheckConstraint(
            "output_sha256 IS NULL OR output_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_run_stages_output_sha256_format",
        ),
        UniqueConstraint("run_id", "stage_name", "attempt", name="uq_run_stages_attempt"),
        Index("ix_run_stages_run_ordinal", "run_id", "stage_ordinal"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("runs.id", ondelete="RESTRICT"), nullable=False
    )
    stage_name: Mapped[str] = mapped_column(String(128), nullable=False)
    stage_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    execution_state: Mapped[str] = mapped_column(String(32), nullable=False)
    input_sha256: Mapped[str | None] = mapped_column(String(64))
    output_sha256: Mapped[str | None] = mapped_column(String(64))
    lease_holder: Mapped[str | None] = mapped_column(String(255))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    warning_document: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    failure_document: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    atomic_completion_marker: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    @validates("input_sha256", "output_sha256")
    def _validate_optional_sha256(self, key: str, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_sha256(value, field_name=key)


class Artifact(Base):
    """Metadata for a validated, atomically published external object."""

    __tablename__ = "artifacts"
    __table_args__ = (
        CheckConstraint("publication_state = 'published'", name="ck_artifacts_published_only"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_artifacts_sha256_format"),
        UniqueConstraint("run_id", "storage_uri", name="uq_artifacts_run_storage_uri"),
        Index("ix_artifacts_run_kind", "run_id", "kind"),
        Index("ix_artifacts_checksum", "sha256"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("runs.id", ondelete="RESTRICT"), nullable=False
    )
    run_stage_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("run_stages.id", ondelete="RESTRICT")
    )
    kind: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_uri: Mapped[str | None] = mapped_column(Text)
    crs_metadata: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    validation_document: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    publication_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default="published", server_default="published"
    )
    validated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    @validates("sha256")
    def _validate_sha256(self, key: str, value: str) -> str:
        return validate_sha256(value, field_name=key)


class Metric(Base):
    """A versioned metric report plus narrow fields for database filtering."""

    __tablename__ = "metrics"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "report_kind", "report_version", name="uq_metrics_report_version"
        ),
        Index("ix_metrics_run_kind", "run_id", "report_kind"),
        Index("ix_metrics_computed_verdict", "computed_verdict"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("runs.id", ondelete="RESTRICT"), nullable=False
    )
    report_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    report_version: Mapped[str] = mapped_column(String(128), nullable=False)
    report_document: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    indexed_fields: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    computed_verdict: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class Review(Base):
    """Immutable human review/override history for a run."""

    __tablename__ = "reviews"
    __table_args__ = (Index("ix_reviews_run_recorded_at", "run_id", "recorded_at"),)

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("runs.id", ondelete="RESTRICT"), nullable=False
    )
    actor_subject_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    source_computed_verdict: Mapped[str | None] = mapped_column(String(32))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class IdempotencyRecord(Base):
    """Idempotent command result retained per subject, operation, and key."""

    __tablename__ = "idempotency_records"
    __table_args__ = (
        CheckConstraint(
            "request_digest ~ '^[0-9a-f]{64}$'", name="ck_idempotency_request_digest_format"
        ),
        UniqueConstraint(
            "subject_id", "operation", "idempotency_key", name="uq_idempotency_subject_op_key"
        ),
        Index("ix_idempotency_records_expires_at", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    subject_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False
    )
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    result_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    response_document: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    @validates("request_digest")
    def _validate_request_digest(self, key: str, value: str) -> str:
        return validate_sha256(value, field_name=key)


class KnowledgeEntity(Base):
    """A durable semantic entity; no rows are seeded or inferred by the service."""

    __tablename__ = "knowledge_entities"
    __table_args__ = (
        UniqueConstraint(
            "entity_type",
            "external_id",
            name="uq_knowledge_entities_type_external_id",
        ),
        Index("ix_knowledge_entities_type_created_at", "entity_type", "created_at"),
        Index("ix_knowledge_entities_external_id", "external_id"),
        Index("ix_knowledge_entities_location", "location", postgresql_using="gist"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    created_by_subject_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(512))
    label: Mapped[str] = mapped_column(String(512), nullable=False)
    properties: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # As with product footprints, SRID -1 prevents accidentally claiming that
    # semantic lunar locations use an Earth reference system.
    location: Mapped[WKBElement | None] = mapped_column(
        Geometry(geometry_type="POINT", srid=-1, spatial_index=False)
    )
    location_crs: Mapped[str | None] = mapped_column(Text)
    location_srid: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class KnowledgeEdge(Base):
    """A directed semantic relationship between two persisted knowledge entities."""

    __tablename__ = "knowledge_edges"
    __table_args__ = (
        Index("ix_knowledge_edges_source_relation", "source_entity_id", "relation_type"),
        Index("ix_knowledge_edges_target_relation", "target_entity_id", "relation_type"),
        Index("ix_knowledge_edges_relation_created_at", "relation_type", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    created_by_subject_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False
    )
    source_entity_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("knowledge_entities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    target_entity_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("knowledge_entities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    relation_type: Mapped[str] = mapped_column(String(128), nullable=False)
    properties: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    weight: Mapped[float | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class RunEvent(Base):
    """Append-only service history; database triggers prevent mutation."""

    __tablename__ = "run_events"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_run_events_run_sequence"),
        CheckConstraint("sequence >= 1", name="ck_run_events_sequence_positive"),
        Index("ix_run_events_run_recorded_at", "run_id", "recorded_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("runs.id", ondelete="RESTRICT"), nullable=False
    )
    actor_subject_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("subjects.id", ondelete="RESTRICT")
    )
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    execution_state: Mapped[str | None] = mapped_column(String(32))
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_document: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
