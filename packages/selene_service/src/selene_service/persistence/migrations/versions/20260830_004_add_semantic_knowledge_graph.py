"""Add durable generic semantic knowledge entities and relationships.

Revision ID: 20260830_004
Revises: 20260830_003
Create Date: 2026-08-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260830_004"
down_revision = "20260830_003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create unseeded semantic entities and directed relationships."""

    op.create_table(
        "knowledge_entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=512), nullable=True),
        sa.Column("label", sa.String(length=512), nullable=False),
        sa.Column(
            "properties",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "location",
            Geometry(geometry_type="POINT", srid=-1, spatial_index=False),
            nullable=True,
        ),
        sa.Column("location_crs", sa.Text(), nullable=True),
        sa.Column("location_srid", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["created_by_subject_id"], ["subjects.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_entities"),
        sa.UniqueConstraint(
            "entity_type",
            "external_id",
            name="uq_knowledge_entities_type_external_id",
        ),
    )
    op.create_index(
        "ix_knowledge_entities_type_created_at",
        "knowledge_entities",
        ["entity_type", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_entities_external_id",
        "knowledge_entities",
        ["external_id"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_entities_location",
        "knowledge_entities",
        ["location"],
        unique=False,
        postgresql_using="gist",
    )

    op.create_table(
        "knowledge_edges",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relation_type", sa.String(length=128), nullable=False),
        sa.Column(
            "properties",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("weight", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["created_by_subject_id"], ["subjects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["source_entity_id"], ["knowledge_entities.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["target_entity_id"], ["knowledge_entities.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_edges"),
    )
    op.create_index(
        "ix_knowledge_edges_source_relation",
        "knowledge_edges",
        ["source_entity_id", "relation_type"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_edges_target_relation",
        "knowledge_edges",
        ["target_entity_id", "relation_type"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_edges_relation_created_at",
        "knowledge_edges",
        ["relation_type", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Drop semantic storage only on an explicit full schema downgrade."""

    op.drop_table("knowledge_edges")
    op.drop_table("knowledge_entities")
