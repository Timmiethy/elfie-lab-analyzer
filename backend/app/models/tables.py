"""SQLAlchemy models for the 12 core tables (blueprint section 11.1)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSON, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Document(Base):
    """Uploaded lab report document."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer)
    lane_type: Mapped[str] = mapped_column(String(32), nullable=False)  # trusted_pdf | image_beta | structured
    language_id: Mapped[str | None] = mapped_column(String(8))
    region: Mapped[str | None] = mapped_column(String(8))
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Job(Base):
    """Processing job for a document."""

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    input_checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    lane_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    dead_letter: Mapped[bool] = mapped_column(default=False)
    operator_note: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ExtractedRow(Base):
    """Raw row extracted from a document page."""

    __tablename__ = "extracted_rows"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), nullable=False)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"), nullable=False)
    source_page: Mapped[int] = mapped_column(Integer, nullable=False)
    row_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    raw_analyte_label: Mapped[str | None] = mapped_column(Text)
    raw_value_string: Mapped[str | None] = mapped_column(String(64))
    raw_unit_string: Mapped[str | None] = mapped_column(String(64))
    raw_reference_range: Mapped[str | None] = mapped_column(String(128))
    extraction_confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Observation(Base):
    """Canonical observation after mapping and normalization (blueprint section 3.5)."""

    __tablename__ = "observations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), nullable=False)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"), nullable=False)
    extracted_row_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("extracted_rows.id"), nullable=False)
    source_page: Mapped[int] = mapped_column(Integer, nullable=False)
    row_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    raw_analyte_label: Mapped[str] = mapped_column(Text, nullable=False)
    raw_value_string: Mapped[str | None] = mapped_column(String(64))
    raw_unit_string: Mapped[str | None] = mapped_column(String(64))
    parsed_numeric_value: Mapped[float | None] = mapped_column(Float)
    accepted_analyte_code: Mapped[str | None] = mapped_column(String(32))
    accepted_analyte_display: Mapped[str | None] = mapped_column(String(256))
    specimen_context: Mapped[str | None] = mapped_column(String(128))
    method_context: Mapped[str | None] = mapped_column(String(128))
    raw_reference_range: Mapped[str | None] = mapped_column(String(128))
    canonical_unit: Mapped[str | None] = mapped_column(String(32))
    canonical_value: Mapped[float | None] = mapped_column(Float)
    language_id: Mapped[str | None] = mapped_column(String(8))
    support_state: Mapped[str] = mapped_column(String(32), nullable=False)  # supported | unsupported | partial
    suppression_reasons: Mapped[list | None] = mapped_column(ARRAY(Text))
    lineage_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("lineage_runs.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MappingCandidate(Base):
    """Analyte mapping candidates with scores."""

    __tablename__ = "mapping_candidates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    observation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("observations.id"), nullable=False)
    candidate_code: Mapped[str] = mapped_column(String(32), nullable=False)
    candidate_display: Mapped[str] = mapped_column(String(256), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    threshold_used: Mapped[float] = mapped_column(Float, nullable=False)
    accepted: Mapped[bool] = mapped_column(default=False)
    rejection_reason: Mapped[str | None] = mapped_column(Text)


class RuleEvent(Base):
    """Deterministic rule firing event."""

    __tablename__ = "rule_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"), nullable=False)
    observation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("observations.id"), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(64), nullable=False)
    finding_id: Mapped[str] = mapped_column(String(64), nullable=False)
    threshold_source: Mapped[str] = mapped_column(String(128), nullable=False)
    supporting_observation_ids: Mapped[list | None] = mapped_column(ARRAY(UUID(as_uuid=True)))
    suppression_conditions: Mapped[dict | None] = mapped_column(JSON)
    severity_class_candidate: Mapped[str | None] = mapped_column(String(4))  # S0-S4, SX
    nextstep_class_candidate: Mapped[str | None] = mapped_column(String(4))  # A0-A4, AX
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PolicyEvent(Base):
    """Final severity and next-step policy assignment."""

    __tablename__ = "policy_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"), nullable=False)
    rule_event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rule_events.id"), nullable=False)
    severity_class: Mapped[str] = mapped_column(String(4), nullable=False)
    nextstep_class: Mapped[str] = mapped_column(String(4), nullable=False)
    severity_policy_version: Mapped[str] = mapped_column(String(16), nullable=False)
    nextstep_policy_version: Mapped[str] = mapped_column(String(16), nullable=False)
    suppression_active: Mapped[bool] = mapped_column(default=False)
    suppression_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PatientArtifact(Base):
    """Rendered patient-facing artifact."""

    __tablename__ = "patient_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"), nullable=False)
    language_id: Mapped[str] = mapped_column(String(8), nullable=False)
    support_banner: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    template_version: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ClinicianArtifact(Base):
    """Rendered clinician-share artifact."""

    __tablename__ = "clinician_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"), nullable=False)
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    template_version: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LineageRun(Base):
    """Lineage bundle for reproducibility (blueprint section 0.2.6)."""

    __tablename__ = "lineage_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"), nullable=False)
    source_checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(32), nullable=False)
    ocr_version: Mapped[str | None] = mapped_column(String(32))
    terminology_release: Mapped[str] = mapped_column(String(32), nullable=False)
    mapping_threshold_config: Mapped[dict] = mapped_column(JSON, nullable=False)
    unit_engine_version: Mapped[str] = mapped_column(String(32), nullable=False)
    rule_pack_version: Mapped[str] = mapped_column(String(32), nullable=False)
    severity_policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    nextstep_policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    template_version: Mapped[str] = mapped_column(String(32), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(64))
    build_commit: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BenchmarkRun(Base):
    """Benchmark run results."""

    __tablename__ = "benchmark_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lineage_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lineage_runs.id"), nullable=False)
    report_type: Mapped[str] = mapped_column(String(64), nullable=False)
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ShareEvent(Base):
    """Audit log for share/export events."""

    __tablename__ = "share_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(32), nullable=False)  # patient | clinician
    share_method: Mapped[str] = mapped_column(String(32), nullable=False)  # export | share | link
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
