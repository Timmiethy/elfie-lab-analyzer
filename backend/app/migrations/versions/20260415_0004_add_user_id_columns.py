"""Add user_id columns to documents and jobs for multi-tenant auth.

Revision ID: 20260415_0004
Revises: 20260412_0003
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "20260415_0004"
down_revision = "20260417_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_documents_user_id", "documents", ["user_id"])
    op.create_index("ix_jobs_user_id", "jobs", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_jobs_user_id", table_name="jobs")
    op.drop_index("ix_documents_user_id", table_name="documents")
    op.drop_column("jobs", "user_id")
    op.drop_column("documents", "user_id")
