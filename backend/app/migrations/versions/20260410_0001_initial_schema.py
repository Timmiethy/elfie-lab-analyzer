"""Initial schema baseline for the current SQLAlchemy model set.

This revision is intentionally explicit so the repo has a readable, stable
starting point even without Alembic autogeneration.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260410_0001"
down_revision = None
branch_labels = None
depends_on = None


UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", UUID, primary_key=True, nullable=False),
        sa.Column("checksum", sa.String(length=128), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=64), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("lane_type", sa.String(length=32), nullable=False),
        sa.Column("language_id", sa.String(length=8), nullable=True),
        sa.Column("region", sa.String(length=8), nullable=True),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "jobs",
        sa.Column("id", UUID, primary_key=True, nullable=False),
        sa.Column("document_id", UUID, sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("input_checksum", sa.String(length=128), nullable=False),
        sa.Column("lane_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("dead_letter", sa.Boolean(), nullable=False),
        sa.Column("operator_note", sa.Text(), nullable=True),
        sa.Column("region", sa.String(length=8), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_jobs_idempotency_key"),
    )

    op.create_table(
        "lineage_runs",
        sa.Column("id", UUID, primary_key=True, nullable=False),
        sa.Column("job_id", UUID, sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("source_checksum", sa.String(length=128), nullable=False),
        sa.Column("parser_version", sa.String(length=32), nullable=False),
        sa.Column("ocr_version", sa.String(length=32), nullable=True),
        sa.Column("terminology_release", sa.String(length=32), nullable=False),
        sa.Column("mapping_threshold_config", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("unit_engine_version", sa.String(length=32), nullable=False),
        sa.Column("rule_pack_version", sa.String(length=32), nullable=False),
        sa.Column("severity_policy_version", sa.String(length=32), nullable=False),
        sa.Column("nextstep_policy_version", sa.String(length=32), nullable=False),
        sa.Column("template_version", sa.String(length=32), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=True),
        sa.Column("build_commit", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "extracted_rows",
        sa.Column("id", UUID, primary_key=True, nullable=False),
        sa.Column("document_id", UUID, sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("job_id", UUID, sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("source_page", sa.Integer(), nullable=False),
        sa.Column("row_hash", sa.String(length=128), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("raw_analyte_label", sa.Text(), nullable=True),
        sa.Column("raw_value_string", sa.String(length=64), nullable=True),
        sa.Column("raw_unit_string", sa.String(length=64), nullable=True),
        sa.Column("raw_reference_range", sa.String(length=128), nullable=True),
        sa.Column("extraction_confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "observations",
        sa.Column("id", UUID, primary_key=True, nullable=False),
        sa.Column("document_id", UUID, sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("job_id", UUID, sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("extracted_row_id", UUID, sa.ForeignKey("extracted_rows.id"), nullable=False),
        sa.Column("source_page", sa.Integer(), nullable=False),
        sa.Column("row_hash", sa.String(length=128), nullable=False),
        sa.Column("raw_analyte_label", sa.Text(), nullable=False),
        sa.Column("raw_value_string", sa.String(length=64), nullable=True),
        sa.Column("raw_unit_string", sa.String(length=64), nullable=True),
        sa.Column("parsed_numeric_value", sa.Float(), nullable=True),
        sa.Column("accepted_analyte_code", sa.String(length=32), nullable=True),
        sa.Column("accepted_analyte_display", sa.String(length=256), nullable=True),
        sa.Column("specimen_context", sa.String(length=128), nullable=True),
        sa.Column("method_context", sa.String(length=128), nullable=True),
        sa.Column("raw_reference_range", sa.String(length=128), nullable=True),
        sa.Column("canonical_unit", sa.String(length=32), nullable=True),
        sa.Column("canonical_value", sa.Float(), nullable=True),
        sa.Column("language_id", sa.String(length=8), nullable=True),
        sa.Column("support_state", sa.String(length=32), nullable=False),
        sa.Column("suppression_reasons", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("lineage_id", UUID, sa.ForeignKey("lineage_runs.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "mapping_candidates",
        sa.Column("id", UUID, primary_key=True, nullable=False),
        sa.Column("observation_id", UUID, sa.ForeignKey("observations.id"), nullable=False),
        sa.Column("candidate_code", sa.String(length=32), nullable=False),
        sa.Column("candidate_display", sa.String(length=256), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("threshold_used", sa.Float(), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
    )

    op.create_table(
        "rule_events",
        sa.Column("id", UUID, primary_key=True, nullable=False),
        sa.Column("job_id", UUID, sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("observation_id", UUID, sa.ForeignKey("observations.id"), nullable=False),
        sa.Column("rule_id", sa.String(length=64), nullable=False),
        sa.Column("finding_id", sa.String(length=64), nullable=False),
        sa.Column("threshold_source", sa.String(length=128), nullable=False),
        sa.Column(
            "supporting_observation_ids",
            postgresql.ARRAY(UUID),
            nullable=True,
        ),
        sa.Column("suppression_conditions", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("severity_class_candidate", sa.String(length=4), nullable=True),
        sa.Column("nextstep_class_candidate", sa.String(length=4), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "policy_events",
        sa.Column("id", UUID, primary_key=True, nullable=False),
        sa.Column("job_id", UUID, sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("rule_event_id", UUID, sa.ForeignKey("rule_events.id"), nullable=False),
        sa.Column("severity_class", sa.String(length=4), nullable=False),
        sa.Column("nextstep_class", sa.String(length=4), nullable=False),
        sa.Column("severity_policy_version", sa.String(length=16), nullable=False),
        sa.Column("nextstep_policy_version", sa.String(length=16), nullable=False),
        sa.Column("suppression_active", sa.Boolean(), nullable=False),
        sa.Column("suppression_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "patient_artifacts",
        sa.Column("id", UUID, primary_key=True, nullable=False),
        sa.Column("job_id", UUID, sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("language_id", sa.String(length=8), nullable=False),
        sa.Column("support_banner", sa.String(length=32), nullable=False),
        sa.Column("content", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("template_version", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "clinician_artifacts",
        sa.Column("id", UUID, primary_key=True, nullable=False),
        sa.Column("job_id", UUID, sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("content", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("template_version", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "benchmark_runs",
        sa.Column("id", UUID, primary_key=True, nullable=False),
        sa.Column("lineage_id", UUID, sa.ForeignKey("lineage_runs.id"), nullable=False),
        sa.Column("report_type", sa.String(length=64), nullable=False),
        sa.Column("metrics", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "share_events",
        sa.Column("id", UUID, primary_key=True, nullable=False),
        sa.Column("job_id", UUID, sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("artifact_type", sa.String(length=32), nullable=False),
        sa.Column("share_method", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("share_events")
    op.drop_table("benchmark_runs")
    op.drop_table("clinician_artifacts")
    op.drop_table("patient_artifacts")
    op.drop_table("policy_events")
    op.drop_table("rule_events")
    op.drop_table("mapping_candidates")
    op.drop_table("observations")
    op.drop_table("extracted_rows")
    op.drop_table("lineage_runs")
    op.drop_table("jobs")
    op.drop_table("documents")
