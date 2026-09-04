"""Persist the canonical frozen parameter document for each run.

Revision ID: 20260830_003
Revises: 20260830_002
Create Date: 2026-08-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260830_003"
down_revision = "20260830_002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add an immutable-at-API-level canonical parameter document."""

    op.add_column(
        "runs",
        sa.Column(
            "parameters_document",
            postgresql.JSONB(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove the supplementary parameter document on explicit downgrade."""

    op.drop_column("runs", "parameters_document")
