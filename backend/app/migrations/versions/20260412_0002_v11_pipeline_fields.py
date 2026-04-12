"""Add v11 typed pipeline persistence fields.

This keeps the migration explicit and reviewable while the v11 parser and
normalization contracts are still settling.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260412_0002"
down_revision = "20260410_0001"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.add_column("documents", sa.Column("document_class", sa.String(length=64), nullable=True))
    op.add_column("documents", sa.Column("preflight_failure_code", sa.String(length=64), nullable=True))
    op.add_column("documents", sa.Column("duplicate_state", sa.String(length=32), nullable=True))
    op.add_column("documents", sa.Column("promotion_status", sa.String(length=32), nullable=True))
    op.add_column("documents", sa.Column("text_extractability", sa.String(length=32), nullable=True))
    op.add_column("documents", sa.Column("image_density", sa.String(length=32), nullable=True))

    op.add_column("extracted_rows", sa.Column("source_block_id", sa.String(length=128), nullable=True))
    op.add_column("extracted_rows", sa.Column("source_row_id", sa.String(length=128), nullable=True))
    op.add_column("extracted_rows", sa.Column("row_type", sa.String(length=64), nullable=True))
    op.add_column("extracted_rows", sa.Column("block_type", sa.String(length=64), nullable=True))
    op.add_column("extracted_rows", sa.Column("family_adapter_id", sa.String(length=64), nullable=True))
    op.add_column("extracted_rows", sa.Column("failure_code", sa.String(length=64), nullable=True))

    op.add_column("observations", sa.Column("source_block_id", sa.String(length=128), nullable=True))
    op.add_column("observations", sa.Column("source_row_id", sa.String(length=128), nullable=True))
    op.add_column("observations", sa.Column("row_type", sa.String(length=64), nullable=True))
    op.add_column("observations", sa.Column("measurement_kind", sa.String(length=64), nullable=True))
    op.add_column("observations", sa.Column("support_code", sa.String(length=64), nullable=True))
    op.add_column("observations", sa.Column("failure_code", sa.String(length=64), nullable=True))
    op.add_column("observations", sa.Column("family_adapter_id", sa.String(length=64), nullable=True))
    op.add_column("observations", sa.Column("parsed_locale", sa.String(length=32), nullable=True))
    op.add_column("observations", sa.Column("parsed_comparator", sa.String(length=16), nullable=True))
    op.add_column("observations", sa.Column("primary_result", postgresql.JSON(astext_type=sa.Text()), nullable=True))
    op.add_column("observations", sa.Column("secondary_result", postgresql.JSON(astext_type=sa.Text()), nullable=True))
    op.add_column("observations", sa.Column("candidate_trace", postgresql.JSON(astext_type=sa.Text()), nullable=True))
    op.add_column("observations", sa.Column("derived_formula_id", sa.String(length=64), nullable=True))
    op.add_column("observations", sa.Column("source_observation_ids", postgresql.ARRAY(UUID), nullable=True))

    op.add_column("lineage_runs", sa.Column("adapter_version", sa.String(length=32), nullable=True))
    op.add_column("lineage_runs", sa.Column("row_assembly_version", sa.String(length=32), nullable=True))
    op.add_column("lineage_runs", sa.Column("row_type_rule_set_version", sa.String(length=32), nullable=True))
    op.add_column("lineage_runs", sa.Column("formula_version", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("lineage_runs", "formula_version")
    op.drop_column("lineage_runs", "row_type_rule_set_version")
    op.drop_column("lineage_runs", "row_assembly_version")
    op.drop_column("lineage_runs", "adapter_version")

    op.drop_column("observations", "source_observation_ids")
    op.drop_column("observations", "derived_formula_id")
    op.drop_column("observations", "candidate_trace")
    op.drop_column("observations", "secondary_result")
    op.drop_column("observations", "primary_result")
    op.drop_column("observations", "parsed_comparator")
    op.drop_column("observations", "parsed_locale")
    op.drop_column("observations", "family_adapter_id")
    op.drop_column("observations", "failure_code")
    op.drop_column("observations", "support_code")
    op.drop_column("observations", "measurement_kind")
    op.drop_column("observations", "row_type")
    op.drop_column("observations", "source_row_id")
    op.drop_column("observations", "source_block_id")

    op.drop_column("extracted_rows", "failure_code")
    op.drop_column("extracted_rows", "family_adapter_id")
    op.drop_column("extracted_rows", "block_type")
    op.drop_column("extracted_rows", "row_type")
    op.drop_column("extracted_rows", "source_row_id")
    op.drop_column("extracted_rows", "source_block_id")

    op.drop_column("documents", "image_density")
    op.drop_column("documents", "text_extractability")
    op.drop_column("documents", "promotion_status")
    op.drop_column("documents", "duplicate_state")
    op.drop_column("documents", "preflight_failure_code")
    op.drop_column("documents", "document_class")
