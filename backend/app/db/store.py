"""Top-level lifecycle persistence helpers.

This store only owns the durable lifecycle records that the main agent will
wire later: documents, jobs, rendered artifacts, lineage bundles, and
benchmark runs. It intentionally does not persist row-level extraction or
policy tables yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import (
    BenchmarkRun,
    ClinicianArtifact,
    Document,
    ExtractedRow,
    MappingCandidate,
    Job,
    Observation,
    LineageRun,
    PatientArtifact,
    PolicyEvent,
    RuleEvent,
    ShareEvent,
)


def _coerce_uuid(value: UUID | str) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


@dataclass(slots=True)
class TopLevelLifecycleBundle:
    """Convenience view for the six top-level lifecycle records."""

    document: Document | None = None
    job: Job | None = None
    patient_artifact: PatientArtifact | None = None
    clinician_artifact: ClinicianArtifact | None = None
    lineage_run: LineageRun | None = None
    benchmark_run: BenchmarkRun | None = None


class TopLevelLifecycleStore:
    """Async persistence helper for top-level lifecycle records only."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_document(
        self,
        *,
        checksum: str,
        filename: str,
        mime_type: str,
        file_size_bytes: int,
        lane_type: str,
        storage_path: str,
        page_count: int | None = None,
        language_id: str | None = None,
        region: str | None = None,
    ) -> Document:
        document = Document(
            checksum=checksum,
            filename=filename,
            mime_type=mime_type,
            file_size_bytes=file_size_bytes,
            page_count=page_count,
            lane_type=lane_type,
            language_id=language_id,
            region=region,
            storage_path=storage_path,
        )
        self.session.add(document)
        await self.session.flush()
        return document

    async def create_job(
        self,
        *,
        document_id: UUID | str,
        idempotency_key: str,
        input_checksum: str,
        lane_type: str,
        status: str = "pending",
        retry_count: int = 0,
        dead_letter: bool = False,
        operator_note: str | None = None,
        region: str | None = None,
    ) -> Job:
        job = Job(
            document_id=_coerce_uuid(document_id),
            idempotency_key=idempotency_key,
            input_checksum=input_checksum,
            lane_type=lane_type,
            status=status,
            retry_count=retry_count,
            dead_letter=dead_letter,
            operator_note=operator_note,
            region=region,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def get_job_by_idempotency_key(self, idempotency_key: str) -> Job | None:
        result = await self.session.execute(
            select(Job)
            .where(Job.idempotency_key == idempotency_key)
            .order_by(Job.created_at.desc(), Job.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_job_by_input_checksum(self, input_checksum: str) -> Job | None:
        result = await self.session.execute(
            select(Job)
            .where(Job.input_checksum == input_checksum)
            .order_by(Job.created_at.desc(), Job.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def update_job_status(
        self,
        job_id: UUID | str,
        *,
        status: str,
        retry_count: int | None = None,
        dead_letter: bool | None = None,
        operator_note: str | None = None,
    ) -> Job:
        job = await self.get_job(job_id)
        if job is None:
            raise LookupError("job_not_found")

        job.status = status
        job.updated_at = datetime.utcnow()
        if retry_count is not None:
            job.retry_count = retry_count
        if dead_letter is not None:
            job.dead_letter = dead_letter
        if operator_note is not None:
            job.operator_note = operator_note

        await self.session.flush()
        return job

    async def create_patient_artifact(
        self,
        *,
        job_id: UUID | str,
        language_id: str,
        support_banner: str,
        content: Mapping[str, Any],
        template_version: str,
    ) -> PatientArtifact:
        artifact = PatientArtifact(
            job_id=_coerce_uuid(job_id),
            language_id=language_id,
            support_banner=support_banner,
            content=dict(content),
            template_version=template_version,
        )
        self.session.add(artifact)
        await self.session.flush()
        return artifact

    async def create_clinician_artifact(
        self,
        *,
        job_id: UUID | str,
        content: Mapping[str, Any],
        template_version: str,
    ) -> ClinicianArtifact:
        artifact = ClinicianArtifact(
            job_id=_coerce_uuid(job_id),
            content=dict(content),
            template_version=template_version,
        )
        self.session.add(artifact)
        await self.session.flush()
        return artifact

    async def create_lineage_run(
        self,
        *,
        job_id: UUID | str,
        source_checksum: str,
        parser_version: str,
        terminology_release: str,
        mapping_threshold_config: Mapping[str, Any],
        unit_engine_version: str,
        rule_pack_version: str,
        severity_policy_version: str,
        nextstep_policy_version: str,
        template_version: str,
        ocr_version: str | None = None,
        model_version: str | None = None,
        build_commit: str | None = None,
    ) -> LineageRun:
        lineage_run = LineageRun(
            job_id=_coerce_uuid(job_id),
            source_checksum=source_checksum,
            parser_version=parser_version,
            ocr_version=ocr_version,
            terminology_release=terminology_release,
            mapping_threshold_config=dict(mapping_threshold_config),
            unit_engine_version=unit_engine_version,
            rule_pack_version=rule_pack_version,
            severity_policy_version=severity_policy_version,
            nextstep_policy_version=nextstep_policy_version,
            template_version=template_version,
            model_version=model_version,
            build_commit=build_commit,
        )
        self.session.add(lineage_run)
        await self.session.flush()
        return lineage_run

    async def create_benchmark_run(
        self,
        *,
        lineage_id: UUID | str,
        report_type: str,
        metrics: Mapping[str, Any],
    ) -> BenchmarkRun:
        benchmark_run = BenchmarkRun(
            lineage_id=_coerce_uuid(lineage_id),
            report_type=report_type,
            metrics=dict(metrics),
        )
        self.session.add(benchmark_run)
        await self.session.flush()
        return benchmark_run

    async def create_extracted_row(
        self,
        *,
        document_id: UUID | str,
        job_id: UUID | str,
        source_page: int,
        row_hash: str,
        raw_text: str,
        raw_analyte_label: str | None = None,
        raw_value_string: str | None = None,
        raw_unit_string: str | None = None,
        raw_reference_range: str | None = None,
        extraction_confidence: float | None = None,
        id: UUID | str | None = None,
    ) -> ExtractedRow:
        extracted_row = ExtractedRow(
            id=_coerce_uuid(id) if id is not None else None,
            document_id=_coerce_uuid(document_id),
            job_id=_coerce_uuid(job_id),
            source_page=source_page,
            row_hash=row_hash,
            raw_text=raw_text,
            raw_analyte_label=raw_analyte_label,
            raw_value_string=raw_value_string,
            raw_unit_string=raw_unit_string,
            raw_reference_range=raw_reference_range,
            extraction_confidence=extraction_confidence,
        )
        self.session.add(extracted_row)
        await self.session.flush()
        return extracted_row

    async def create_observation(
        self,
        *,
        document_id: UUID | str,
        job_id: UUID | str,
        extracted_row_id: UUID | str,
        source_page: int,
        row_hash: str,
        raw_analyte_label: str,
        raw_value_string: str | None = None,
        raw_unit_string: str | None = None,
        parsed_numeric_value: float | None = None,
        accepted_analyte_code: str | None = None,
        accepted_analyte_display: str | None = None,
        specimen_context: str | None = None,
        method_context: str | None = None,
        raw_reference_range: str | None = None,
        canonical_unit: str | None = None,
        canonical_value: float | None = None,
        language_id: str | None = None,
        support_state: str,
        suppression_reasons: list[str] | None = None,
        lineage_id: UUID | str | None = None,
        id: UUID | str | None = None,
    ) -> Observation:
        observation = Observation(
            id=_coerce_uuid(id) if id is not None else None,
            document_id=_coerce_uuid(document_id),
            job_id=_coerce_uuid(job_id),
            extracted_row_id=_coerce_uuid(extracted_row_id),
            source_page=source_page,
            row_hash=row_hash,
            raw_analyte_label=raw_analyte_label,
            raw_value_string=raw_value_string,
            raw_unit_string=raw_unit_string,
            parsed_numeric_value=parsed_numeric_value,
            accepted_analyte_code=accepted_analyte_code,
            accepted_analyte_display=accepted_analyte_display,
            specimen_context=specimen_context,
            method_context=method_context,
            raw_reference_range=raw_reference_range,
            canonical_unit=canonical_unit,
            canonical_value=canonical_value,
            language_id=language_id,
            support_state=support_state,
            suppression_reasons=list(suppression_reasons) if suppression_reasons is not None else None,
            lineage_id=_coerce_uuid(lineage_id) if lineage_id is not None else None,
        )
        self.session.add(observation)
        await self.session.flush()
        return observation

    async def create_mapping_candidate(
        self,
        *,
        observation_id: UUID | str,
        candidate_code: str,
        candidate_display: str,
        score: float,
        threshold_used: float,
        accepted: bool = False,
        rejection_reason: str | None = None,
        id: UUID | str | None = None,
    ) -> MappingCandidate:
        mapping_candidate = MappingCandidate(
            id=_coerce_uuid(id) if id is not None else None,
            observation_id=_coerce_uuid(observation_id),
            candidate_code=candidate_code,
            candidate_display=candidate_display,
            score=score,
            threshold_used=threshold_used,
            accepted=accepted,
            rejection_reason=rejection_reason,
        )
        self.session.add(mapping_candidate)
        await self.session.flush()
        return mapping_candidate

    async def create_rule_event(
        self,
        *,
        job_id: UUID | str,
        observation_id: UUID | str,
        rule_id: str,
        finding_id: str,
        threshold_source: str,
        supporting_observation_ids: list[UUID | str] | None = None,
        suppression_conditions: dict[str, Any] | None = None,
        severity_class_candidate: str | None = None,
        nextstep_class_candidate: str | None = None,
        id: UUID | str | None = None,
    ) -> RuleEvent:
        rule_event = RuleEvent(
            id=_coerce_uuid(id) if id is not None else None,
            job_id=_coerce_uuid(job_id),
            observation_id=_coerce_uuid(observation_id),
            rule_id=rule_id,
            finding_id=finding_id,
            threshold_source=threshold_source,
            supporting_observation_ids=[
                _coerce_uuid(value) for value in supporting_observation_ids
            ]
            if supporting_observation_ids is not None
            else None,
            suppression_conditions=dict(suppression_conditions) if suppression_conditions is not None else None,
            severity_class_candidate=severity_class_candidate,
            nextstep_class_candidate=nextstep_class_candidate,
        )
        self.session.add(rule_event)
        await self.session.flush()
        return rule_event

    async def create_policy_event(
        self,
        *,
        job_id: UUID | str,
        rule_event_id: UUID | str,
        severity_class: str,
        nextstep_class: str,
        severity_policy_version: str,
        nextstep_policy_version: str,
        suppression_active: bool = False,
        suppression_reason: str | None = None,
        id: UUID | str | None = None,
    ) -> PolicyEvent:
        policy_event = PolicyEvent(
            id=_coerce_uuid(id) if id is not None else None,
            job_id=_coerce_uuid(job_id),
            rule_event_id=_coerce_uuid(rule_event_id),
            severity_class=severity_class,
            nextstep_class=nextstep_class,
            severity_policy_version=severity_policy_version,
            nextstep_policy_version=nextstep_policy_version,
            suppression_active=suppression_active,
            suppression_reason=suppression_reason,
        )
        self.session.add(policy_event)
        await self.session.flush()
        return policy_event

    async def create_share_event(
        self,
        *,
        job_id: UUID | str,
        artifact_type: str,
        share_method: str,
    ) -> ShareEvent:
        share_event = ShareEvent(
            job_id=_coerce_uuid(job_id),
            artifact_type=artifact_type,
            share_method=share_method,
        )
        self.session.add(share_event)
        await self.session.flush()
        return share_event

    async def persist_top_level_bundle(
        self,
        *,
        job_id: UUID | str,
        status: str | None = None,
        patient_artifact: Mapping[str, Any] | None = None,
        clinician_artifact: Mapping[str, Any] | None = None,
        lineage_run: Mapping[str, Any] | None = None,
        benchmark_run: Mapping[str, Any] | None = None,
    ) -> TopLevelLifecycleBundle:
        """Persist the final top-level outputs for a job.

        The caller controls transaction boundaries. This method only writes the
        durable lifecycle rows that are safe to expose to routes later.
        """

        job_uuid = _coerce_uuid(job_id)
        persisted_job: Job | None = None
        persisted_lineage: LineageRun | None = None
        persisted_benchmark: BenchmarkRun | None = None
        persisted_patient: PatientArtifact | None = None
        persisted_clinician: ClinicianArtifact | None = None

        if status is not None:
            persisted_job = await self.update_job_status(job_uuid, status=status)
        else:
            persisted_job = await self.get_job(job_uuid)
            if persisted_job is None:
                raise LookupError("job_not_found")

        if lineage_run is not None:
            persisted_lineage = await self.create_lineage_run(job_id=job_uuid, **lineage_run)
        if benchmark_run is not None:
            if persisted_lineage is None:
                persisted_lineage = await self.get_latest_lineage_run(job_uuid)
            if persisted_lineage is None:
                raise LookupError("lineage_run_required_for_benchmark")
            persisted_benchmark = await self.create_benchmark_run(
                lineage_id=persisted_lineage.id,
                **benchmark_run,
            )
        if patient_artifact is not None:
            persisted_patient = await self.create_patient_artifact(job_id=job_uuid, **patient_artifact)
        if clinician_artifact is not None:
            persisted_clinician = await self.create_clinician_artifact(
                job_id=job_uuid,
                **clinician_artifact,
            )

        return TopLevelLifecycleBundle(
            job=persisted_job,
            patient_artifact=persisted_patient,
            clinician_artifact=persisted_clinician,
            lineage_run=persisted_lineage,
            benchmark_run=persisted_benchmark,
        )

    async def get_job(self, job_id: UUID | str) -> Job | None:
        return await self.session.get(Job, _coerce_uuid(job_id))

    async def get_document(self, document_id: UUID | str) -> Document | None:
        return await self.session.get(Document, _coerce_uuid(document_id))

    async def get_patient_artifact(self, job_id: UUID | str) -> PatientArtifact | None:
        result = await self.session.execute(
            select(PatientArtifact)
            .where(PatientArtifact.job_id == _coerce_uuid(job_id))
            .order_by(PatientArtifact.created_at.desc(), PatientArtifact.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_clinician_artifact(self, job_id: UUID | str) -> ClinicianArtifact | None:
        result = await self.session.execute(
            select(ClinicianArtifact)
            .where(ClinicianArtifact.job_id == _coerce_uuid(job_id))
            .order_by(ClinicianArtifact.created_at.desc(), ClinicianArtifact.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_latest_lineage_run(self, job_id: UUID | str) -> LineageRun | None:
        result = await self.session.execute(
            select(LineageRun)
            .where(LineageRun.job_id == _coerce_uuid(job_id))
            .order_by(LineageRun.created_at.desc(), LineageRun.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def count_lineage_runs(self, job_id: UUID | str) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(LineageRun)
            .where(LineageRun.job_id == _coerce_uuid(job_id))
        )
        return int(result.scalar_one())

    async def get_latest_benchmark_run(self, lineage_id: UUID | str) -> BenchmarkRun | None:
        result = await self.session.execute(
            select(BenchmarkRun)
            .where(BenchmarkRun.lineage_id == _coerce_uuid(lineage_id))
            .order_by(BenchmarkRun.created_at.desc(), BenchmarkRun.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
