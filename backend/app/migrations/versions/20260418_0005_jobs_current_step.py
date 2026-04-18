"""Add jobs.current_step column for per-stage progress tracking.

Nullable, no default — populated by PipelineOrchestrator between stages so
the polling endpoint can surface fine-grained progress to the frontend.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260418_0005"
down_revision = "20260415_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("current_step", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("jobs", "current_step")
