"""Add server_default to jobs.retry_count so raw SQL inserts get 0 instead of NULL.

This is a safe, non-destructive change — existing rows keep their current value.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260417_0002"
down_revision = "20260412_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Backfill any NULL rows first, then set the server default.
    op.execute("UPDATE jobs SET retry_count = 0 WHERE retry_count IS NULL")
    op.alter_column(
        "jobs",
        "retry_count",
        existing_type=sa.Integer(),
        server_default="0",
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "jobs",
        "retry_count",
        existing_type=sa.Integer(),
        server_default=None,
        nullable=True,
    )
