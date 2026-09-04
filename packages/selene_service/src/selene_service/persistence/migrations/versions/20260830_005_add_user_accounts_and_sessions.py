"""Add operator user accounts and server-side sessions.

Revision ID: 20260830_005
Revises: 20260830_004
Create Date: 2026-08-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260830_005"
down_revision = "20260830_004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create user_accounts (1:1 with subjects) and user_sessions."""

    op.create_table(
        "user_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by_user_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("failed_login_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["created_by_user_account_id"], ["user_accounts.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_accounts"),
        sa.UniqueConstraint("subject_id", name="uq_user_accounts_subject_id"),
        sa.UniqueConstraint("username", name="uq_user_accounts_username"),
        sa.CheckConstraint(
            "role IN ('analyst', 'reviewer', 'admin')", name="ck_user_accounts_role"
        ),
    )
    op.create_index(
        "ix_user_accounts_created_by_user_account_id",
        "user_accounts",
        ["created_by_user_account_id"],
        unique=False,
    )

    op.create_table(
        "user_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_account_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_user_sessions"),
    )
    op.create_index(
        "ix_user_sessions_user_account_id", "user_sessions", ["user_account_id"], unique=False
    )
    op.create_index("ix_user_sessions_expires_at", "user_sessions", ["expires_at"], unique=False)


def downgrade() -> None:
    """Drop sessions before accounts to respect the foreign key."""

    op.drop_table("user_sessions")
    op.drop_table("user_accounts")
