"""Top-level lifecycle persistence helpers.

This store only owns the durable lifecycle records that the main agent will
wire later: documents, jobs, rendered artifacts, lineage bundles, and
benchmark runs. It intentionally does not persist row-level extraction or
policy tables yet.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar
from uuid import UUID, uuid4

from sqlalchemy import func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import (
    BenchmarkRun,
    ClinicianArtifact,
    Document,
    ExtractedRow,
    Job,
    LineageRun,
    MappingCandidate,
    Observation,
    PatientArtifact,
    PolicyEvent,
    RuleEvent,
    ShareEvent,
    utc_now,
)

T = TypeVar("T")


def _coerce_uuid(value: UUID | str) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _normalize_storage_path(raw_path: str) -> Path:
    # Stored paths can move between Windows host and Linux container runtimes.
    return Path(raw_path.replace("\\", "/"))


def _clip(value: str | None, max_len: int) -> str | None:
    if value is None:
        return None
    return value if len(value) <= max_len else value[:max_len]


async def _add_and_flush(session: AsyncSession, entity: T) -> T:
    """Add an entity to the session, flush, and return it."""
    session.add(entity)
    await session.flush()
    return entity


async def _latest_by_job(
    session: AsyncSession,
    model: type[T],
    job_id: UUID,
) -> T | None:
    """Return the most recent record for a job, ordered by created_at then id."""
    result = await session.execute(
        select(model)
        .where(model.job_id == job_id)
        .order_by(model.created_at.desc(), model.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _latest_by_lineage(
    session: AsyncSession,
    model: type[T],
    lineage_id: UUID,
) -> T | None:
    """Return the most recent record for a lineage, ordered by created_at then id."""
    result = await session.execute(
        select(model)
        .where(model.lineage_id == lineage_id)
        .order_by(model.created_at.desc(), model.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


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
        user_id: UUID | None = None,
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
            user_id=user_id,
        )
        return await _add_and_flush(self.session, document)

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
        user_id: UUID | None = None,
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
            user_id=user_id,
        )
        return await _add_and_flush(self.session, job)

    async def create_job_on_conflict_do_nothing(
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
        user_id: UUID | None = None,
    ) -> Job | None:
        stmt = (
            pg_insert(Job)
            .values(
                document_id=_coerce_uuid(document_id),
                idempotency_key=idempotency_key,
                input_checksum=input_checksum,
                lane_type=lane_type,
                status=status,
                retry_count=retry_count,
                dead_letter=dead_letter,
                operator_note=operator_note,
                region=region,
                user_id=user_id,
            )
            .on_conflict_do_nothing(index_elements=[Job.idempotency_key])
            .returning(Job.id)
        )
        result = await self.session.execute(stmt)
        created_job_id = result.scalar_one_or_none()
        if created_job_id is None:
            return None
        job = await self.get_job(created_job_id, user_id=user_id)
        if job is None:
            raise LookupError("job_not_found_after_insert")
        return job

    async def get_job_by_idempotency_key(
        self, idempotency_key: str, *, user_id: UUID | None = None
    ) -> Job | None:
        stmt = (
            select(Job)
            .where(Job.idempotency_key == idempotency_key)
            .order_by(Job.created_at.desc(), Job.id.desc())
            .limit(1)
        )
        if user_id is not None:
            stmt = stmt.where(Job.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_job_by_input_checksum(
        self, input_checksum: str, *, user_id: UUID | None = None
    ) -> Job | None:
        stmt = (
            select(Job)
            .where(Job.input_checksum == input_checksum)
            .order_by(Job.created_at.desc(), Job.id.desc())
            .limit(1)
        )
        if user_id is not None:
            stmt = stmt.where(Job.user_id == user_id)
        result = await self.session.execute(stmt)
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
        job.updated_at = utc_now()
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
        return await _add_and_flush(self.session, artifact)

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
        return await _add_and_flush(self.session, artifact)

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
        return await _add_and_flush(self.session, lineage_run)

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
        return await _add_and_flush(self.session, benchmark_run)

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
            raw_value_string=_clip(raw_value_string, 64),
            raw_unit_string=_clip(raw_unit_string, 64),
            raw_reference_range=_clip(raw_reference_range, 128),
            extraction_confidence=extraction_confidence,
        )
        return await _add_and_flush(self.session, extracted_row)

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
            raw_value_string=_clip(raw_value_string, 64),
            raw_unit_string=_clip(raw_unit_string, 64),
            parsed_numeric_value=parsed_numeric_value,
            accepted_analyte_code=accepted_analyte_code,
            accepted_analyte_display=accepted_analyte_display,
            specimen_context=specimen_context,
            method_context=method_context,
            raw_reference_range=_clip(raw_reference_range, 128),
            canonical_unit=canonical_unit,
            canonical_value=canonical_value,
            language_id=language_id,
            support_state=support_state,
            suppression_reasons=list(suppression_reasons)
            if suppression_reasons is not None
            else None,
            lineage_id=_coerce_uuid(lineage_id) if lineage_id is not None else None,
        )
        return await _add_and_flush(self.session, observation)

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
        return await _add_and_flush(self.session, mapping_candidate)

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
            supporting_observation_ids=[_coerce_uuid(value) for value in supporting_observation_ids]
            if supporting_observation_ids is not None
            else None,
            suppression_conditions=dict(suppression_conditions)
            if suppression_conditions is not None
            else None,
            severity_class_candidate=severity_class_candidate,
            nextstep_class_candidate=nextstep_class_candidate,
        )
        return await _add_and_flush(self.session, rule_event)

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
        return await _add_and_flush(self.session, policy_event)

    async def bulk_create_extracted_rows(
        self,
        *,
        rows: list[Mapping[str, Any]],
    ) -> dict[str, UUID]:
        if not rows:
            return {}

        payloads: list[dict[str, Any]] = []
        for row in rows:
            payloads.append(
                {
                    "id": _coerce_uuid(row.get("id")) if row.get("id") is not None else uuid4(),
                    "document_id": _coerce_uuid(row["document_id"]),
                    "job_id": _coerce_uuid(row["job_id"]),
                    "source_page": int(row["source_page"]),
                    "row_hash": str(row["row_hash"]),
                    "raw_text": str(row["raw_text"]),
                    "raw_analyte_label": row.get("raw_analyte_label"),
                    "raw_value_string": _clip(row.get("raw_value_string"), 64),
                    "raw_unit_string": _clip(row.get("raw_unit_string"), 64),
                    "raw_reference_range": _clip(row.get("raw_reference_range"), 128),
                    "extraction_confidence": row.get("extraction_confidence"),
                }
            )

        stmt = insert(ExtractedRow).returning(ExtractedRow.id, ExtractedRow.row_hash)
        result = await self.session.execute(stmt, payloads)
        return {str(row_hash): row_id for row_id, row_hash in result.all()}

    async def bulk_create_observations(
        self,
        *,
        rows: list[Mapping[str, Any]],
    ) -> dict[UUID, UUID]:
        if not rows:
            return {}

        payloads: list[dict[str, Any]] = []
        for row in rows:
            observation_uuid = _coerce_uuid(row.get("observation_uuid") or row.get("id") or uuid4())
            payloads.append(
                {
                    "id": observation_uuid,
                    "document_id": _coerce_uuid(row["document_id"]),
                    "job_id": _coerce_uuid(row["job_id"]),
                    "extracted_row_id": _coerce_uuid(row["extracted_row_id"]),
                    "source_page": int(row["source_page"]),
                    "row_hash": str(row["row_hash"]),
                    "raw_analyte_label": str(row["raw_analyte_label"]),
                    "raw_value_string": _clip(row.get("raw_value_string"), 64),
                    "raw_unit_string": _clip(row.get("raw_unit_string"), 64),
                    "parsed_numeric_value": row.get("parsed_numeric_value"),
                    "accepted_analyte_code": row.get("accepted_analyte_code"),
                    "accepted_analyte_display": row.get("accepted_analyte_display"),
                    "specimen_context": row.get("specimen_context"),
                    "method_context": row.get("method_context"),
                    "raw_reference_range": _clip(row.get("raw_reference_range"), 128),
                    "canonical_unit": row.get("canonical_unit"),
                    "canonical_value": row.get("canonical_value"),
                    "language_id": row.get("language_id"),
                    "support_state": str(row["support_state"]),
                    "suppression_reasons": list(row["suppression_reasons"])
                    if row.get("suppression_reasons") is not None
                    else None,
                    "lineage_id": _coerce_uuid(row["lineage_id"])
                    if row.get("lineage_id") is not None
                    else None,
                }
            )

        stmt = insert(Observation).returning(Observation.id)
        result = await self.session.execute(stmt, payloads)
        persisted_ids = [row_id for (row_id,) in result.all()]
        return {observation_id: observation_id for observation_id in persisted_ids}

    async def bulk_create_mapping_candidates(
        self,
        *,
        rows: list[Mapping[str, Any]],
    ) -> None:
        if not rows:
            return

        payloads: list[dict[str, Any]] = []
        for row in rows:
            payloads.append(
                {
                    "id": _coerce_uuid(row.get("id")) if row.get("id") is not None else uuid4(),
                    "observation_id": _coerce_uuid(row["observation_id"]),
                    "candidate_code": str(row["candidate_code"]),
                    "candidate_display": str(row["candidate_display"]),
                    "score": float(row.get("score", 0.0)),
                    "threshold_used": float(row.get("threshold_used", 0.9)),
                    "accepted": bool(row.get("accepted", False)),
                    "rejection_reason": row.get("rejection_reason"),
                }
            )

        await self.session.execute(insert(MappingCandidate), payloads)

    async def bulk_create_rule_events(
        self,
        *,
        rows: list[Mapping[str, Any]],
    ) -> dict[UUID, UUID]:
        if not rows:
            return {}

        payloads: list[dict[str, Any]] = []
        for row in rows:
            rule_event_id = _coerce_uuid(row.get("id") or uuid4())
            payloads.append(
                {
                    "id": rule_event_id,
                    "job_id": _coerce_uuid(row["job_id"]),
                    "observation_id": _coerce_uuid(row["observation_id"]),
                    "rule_id": str(row["rule_id"]),
                    "finding_id": str(row["finding_id"]),
                    "threshold_source": str(row["threshold_source"]),
                    "supporting_observation_ids": [
                        _coerce_uuid(value)
                        for value in row.get("supporting_observation_ids", [])
                    ]
                    or None,
                    "suppression_conditions": dict(row["suppression_conditions"])
                    if row.get("suppression_conditions") is not None
                    else None,
                    "severity_class_candidate": row.get("severity_class_candidate"),
                    "nextstep_class_candidate": row.get("nextstep_class_candidate"),
                }
            )

        stmt = insert(RuleEvent).returning(RuleEvent.id)
        result = await self.session.execute(stmt, payloads)
        persisted_ids = [row_id for (row_id,) in result.all()]
        return {rule_event_id: rule_event_id for rule_event_id in persisted_ids}

    async def bulk_create_policy_events(
        self,
        *,
        rows: list[Mapping[str, Any]],
    ) -> None:
        if not rows:
            return

        payloads: list[dict[str, Any]] = []
        for row in rows:
            payloads.append(
                {
                    "id": _coerce_uuid(row.get("id")) if row.get("id") is not None else uuid4(),
                    "job_id": _coerce_uuid(row["job_id"]),
                    "rule_event_id": _coerce_uuid(row["rule_event_id"]),
                    "severity_class": str(row["severity_class"]),
                    "nextstep_class": str(row["nextstep_class"]),
                    "severity_policy_version": str(row["severity_policy_version"]),
                    "nextstep_policy_version": str(row["nextstep_policy_version"]),
                    "suppression_active": bool(row.get("suppression_active", False)),
                    "suppression_reason": row.get("suppression_reason"),
                }
            )

        await self.session.execute(insert(PolicyEvent), payloads)

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
        return await _add_and_flush(self.session, share_event)

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
            persisted_patient = await self.create_patient_artifact(
                job_id=job_uuid, **patient_artifact
            )
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

    async def get_job(self, job_id: UUID | str, *, user_id: UUID | None = None) -> Job | None:
        job = await self.session.get(Job, _coerce_uuid(job_id))
        if job is not None and user_id is not None and job.user_id != user_id:
            return None
        return job

    async def get_job_for_update(self, job_id: UUID | str) -> Job | None:
        """Fetch a job row with a row-level lock to prevent concurrent retry races."""
        result = await self.session.execute(
            select(Job).where(Job.id == _coerce_uuid(job_id)).with_for_update()
        )
        return result.scalar_one_or_none()

    async def increment_retry_count_if_below(
        self,
        job_id: UUID | str,
        *,
        max_retry_count: int,
    ) -> int | None:
        stmt = (
            update(Job)
            .where(
                Job.id == _coerce_uuid(job_id),
                Job.dead_letter.is_(False),
                Job.retry_count < max_retry_count,
            )
            .values(
                retry_count=Job.retry_count + 1,
                updated_at=utc_now(),
            )
            .returning(Job.retry_count)
        )
        result = await self.session.execute(stmt)
        retry_count = result.scalar_one_or_none()
        if retry_count is None:
            return None
        return int(retry_count)

    async def get_document(self, document_id: UUID | str) -> Document | None:
        return await self.session.get(Document, _coerce_uuid(document_id))

    async def get_patient_artifact(self, job_id: UUID | str) -> PatientArtifact | None:
        return await _latest_by_job(self.session, PatientArtifact, _coerce_uuid(job_id))

    async def get_clinician_artifact(self, job_id: UUID | str) -> ClinicianArtifact | None:
        return await _latest_by_job(self.session, ClinicianArtifact, _coerce_uuid(job_id))

    async def get_latest_lineage_run(self, job_id: UUID | str) -> LineageRun | None:
        return await _latest_by_job(self.session, LineageRun, _coerce_uuid(job_id))

    async def count_lineage_runs(self, job_id: UUID | str) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(LineageRun)
            .where(LineageRun.job_id == _coerce_uuid(job_id))
        )
        return int(result.scalar_one())

    async def list_recent_jobs(
        self, limit: int = 20, *, user_id: UUID | None = None
    ) -> list[dict[str, Any]]:
        patient_artifact_exists = (
            select(PatientArtifact.id).where(PatientArtifact.job_id == Job.id).exists()
        )
        clinician_artifact_exists = (
            select(ClinicianArtifact.id).where(ClinicianArtifact.job_id == Job.id).exists()
        )

        stmt = (
            select(
                Job,
                patient_artifact_exists.label("has_patient_artifact"),
                clinician_artifact_exists.label("has_clinician_artifact"),
            )
            .order_by(Job.updated_at.desc(), Job.created_at.desc(), Job.id.desc())
            .limit(limit)
        )
        if user_id is not None:
            stmt = stmt.where(Job.user_id == user_id)

        result = await self.session.execute(stmt)

        jobs: list[dict[str, Any]] = []
        for job, has_patient_artifact, has_clinician_artifact in result.all():
            jobs.append(
                {
                    "job_id": str(job.id),
                    "status": job.status,
                    "lane_type": job.lane_type,
                    "retry_count": int(job.retry_count or 0),
                    "dead_letter": bool(job.dead_letter),
                    "created_at": job.created_at.isoformat()
                    if job.created_at is not None
                    else None,
                    "updated_at": job.updated_at.isoformat()
                    if job.updated_at is not None
                    else None,
                    "operator_note": job.operator_note,
                    "has_patient_artifact": bool(has_patient_artifact),
                    "has_clinician_artifact": bool(has_clinician_artifact),
                }
            )
        return jobs

    async def get_job_audit_data(
        self, job_id: UUID | str, *, user_id: UUID | None = None
    ) -> dict[str, Any]:
        job = await self.get_job(job_id, user_id=user_id)
        if job is None:
            raise LookupError("job_not_found")

        lineage_runs_count = await self.count_lineage_runs(job_id)
        latest_lineage = await self.get_latest_lineage_run(job_id)
        latest_benchmark = None
        if latest_lineage is not None:
            benchmark = await self.get_latest_benchmark_run(latest_lineage.id)
            if benchmark is not None:
                latest_benchmark = {
                    "id": str(benchmark.id),
                    "lineage_id": str(benchmark.lineage_id),
                    "report_type": benchmark.report_type,
                    "metrics": dict(benchmark.metrics),
                    "created_at": benchmark.created_at.isoformat()
                    if benchmark.created_at is not None
                    else None,
                }

        share_events_result = await self.session.execute(
            select(ShareEvent)
            .where(ShareEvent.job_id == _coerce_uuid(job_id))
            .order_by(ShareEvent.created_at.desc(), ShareEvent.id.desc())
        )
        share_events = [
            {
                "id": str(event.id),
                "job_id": str(event.job_id),
                "artifact_type": event.artifact_type,
                "share_method": event.share_method,
                "created_at": event.created_at.isoformat()
                if event.created_at is not None
                else None,
            }
            for event in share_events_result.scalars().all()
        ]

        return {
            "job_id": str(job.id),
            "status": job.status,
            "lane_type": job.lane_type,
            "retry_count": int(job.retry_count or 0),
            "dead_letter": bool(job.dead_letter),
            "operator_note": job.operator_note,
            "lineage_runs_count": lineage_runs_count,
            "latest_lineage_run": None
            if latest_lineage is None
            else {"id": str(latest_lineage.id)},
            "latest_benchmark": latest_benchmark,
            "share_events": share_events,
        }

    async def get_retry_preview_data(
        self,
        job_id: UUID | str,
        *,
        max_retry_count: int,
        user_id: UUID | None = None,
    ) -> dict[str, Any]:
        job = await self.get_job(job_id, user_id=user_id)
        if job is None:
            raise LookupError("job_not_found")

        document = await self.get_document(job.document_id)
        document_present = (
            document is not None and _normalize_storage_path(document.storage_path).is_file()
        )
        dead_letter = bool(job.dead_letter)
        retry_count = int(job.retry_count or 0)
        retry_block_reason: str | None = None
        retry_allowed = True

        if not document_present:
            retry_allowed = False
            retry_block_reason = "document_missing"
        elif dead_letter:
            retry_allowed = False
            retry_block_reason = "dead_lettered"
        elif retry_count >= max_retry_count:
            retry_allowed = False
            retry_block_reason = "retry_limit_reached"

        return {
            "job_id": str(job.id),
            "status": job.status,
            "lane_type": job.lane_type,
            "document_present": document_present,
            "dead_letter": dead_letter,
            "retry_count": retry_count,
            "max_job_retries": max_retry_count,
            "retry_allowed": retry_allowed,
            "retry_block_reason": retry_block_reason,
            "would_dead_letter_on_retry": retry_count + 1 >= max_retry_count,
            "operator_note": job.operator_note,
        }

    async def get_latest_benchmark_run(self, lineage_id: UUID | str) -> BenchmarkRun | None:
        return await _latest_by_lineage(self.session, BenchmarkRun, _coerce_uuid(lineage_id))
