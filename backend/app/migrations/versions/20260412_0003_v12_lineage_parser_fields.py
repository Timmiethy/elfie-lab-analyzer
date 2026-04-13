"""Add v12 parser substrate fields to lineage_runs.

Adds parser_backend and parser_backend_version columns to the
lineage_runs table so the v12 parser migration metadata survives
end-to-end through Alembic schema drift for existing databases.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260412_0003"
down_revision = "20260412_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lineage_runs",
        sa.Column("parser_backend", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "lineage_runs",
        sa.Column("parser_backend_version", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("lineage_runs", "parser_backend_version")
    op.drop_column("lineage_runs", "parser_backend")
