"""Job pipeline orchestrator (blueprint section 3.1 flow).

Steps:
1. upload enters API
2. preflight classifies input lane
3. trusted PDF lane or image beta lane selected
4. extraction runs
5. extraction QA runs
6. provisional observations created
7. analyte mapping and abstention run
8. UCUM validation and canonicalization run
9. panel reconstruction runs
10. deterministic rules fire
11. deterministic severity and next-step assignment runs
12. patient artifact renders
13. clinician-share artifact renders
14. lineage and benchmark telemetry persist
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from time import perf_counter
from typing import Literal, TypedDict
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import TopLevelLifecycleStore
from app.schemas.artifact import SupportBanner, TrustStatus
from app.services.analyte_resolver import AnalyteResolver
from app.services.artifact_renderer import ArtifactRenderer
from app.services.benchmark import BenchmarkRecorder
from app.services.clinician_pdf import clinician_pdf_route, write_clinician_pdf
from app.services.comparable_history import ComparableHistoryService
from app.services.explanation import ExplanationAdapter
from app.services.extraction_qa import ExtractionQA
from app.services.input_gateway import InputGateway
from app.services.lineage import LineageLogger
from app.services.nextstep_policy import NextStepPolicyEngine
from app.services.observation_builder import ObservationBuilder
from app.services.ocr import OcrAdapter
from app.services.panel_reconstructor import PanelReconstructor
from app.services.parser import TrustedPdfParser
from app.services.proof_pack import proof_pack_route, write_proof_pack
from app.services.reference_selection import ReferenceSelectionService
from app.services.rule_engine import RuleEngine
from app.services.severity_policy import SeverityPolicyEngine
from app.services.ucum import UcumEngine
from app.terminology import get_loaded_snapshot_metadata

_JOB_RUNS: dict[str, dict] = {}
_LOGGER = logging.getLogger(__name__)
_SUPPORTED_LANES = {"trusted_pdf", "image_beta", "unsupported"}
_FAIL_CLOSED_DOCUMENT_CLASSES = {
    "unsupported",
    "unsupported_pdf",
    "structured_record",
    "interpreted_summary",
    "non_lab_medical",
    "unknown",
}

# v12 parser lineage constants
_PARSER_VERSION_TRUSTED = "pymupdf-1.27.x"
_PARSER_VERSION_IMAGE_BETA = "qwen-vl-ocr-2025-11-20"
_OCR_VERSION_IMAGE_BETA = "qwen-vl-ocr-2025-11-20"
_ADAPTER_VERSION = "family-adapter-v1"
_ROW_ASSEMBLY_VERSION = "row-assembly-v2"
_ROW_TYPE_RULE_SET_VERSION = "row-type-rules-v1"
_FORMULA_VERSION = "formula-v1"
_MAPPING_THRESHOLD_DEFAULT = {"default": 0.9}
_UNIT_ENGINE_VERSION = "ucum-v1"
_RULE_PACK_VERSION = "rules-v1"
_SEVERITY_POLICY_VERSION = "severity-v1"
_NEXTSTEP_POLICY_VERSION = "nextstep-v1"
_TEMPLATE_VERSION = "templates-v1"
_REPORT_TYPE = "truth_engine_pipeline"
_PROOF_CORPUS_ID = "seeded-launch-corpus-v1"
_UNKNOWN_RUNTIME_VALUE = "unknown"
_UNDETERMINED_LANGUAGE_ID = "und"
_COMPLETENESS_TELEMETRY_VERSION = "completeness-telemetry-v1"
_SEMANTIC_SUCCESS_SHADOW_VERSION = "semantic-success-shadow-v1"
_NORMALIZATION_TRACE_VERSION = "normalization-trace-v3"
_COMPLETENESS_NON_RESULT_ROW_TYPES = {
    "admin_metadata_row",
    "threshold_reference_row",
    "narrative_guidance_row",
    "header_footer_row",
    "test_request_row",
    "metadata_row",
    "heading_row",
    "unknown_row",
}


class PipelineStep(StrEnum):
    PREFLIGHT = "preflight"
    LANE_SELECTION = "lane_selection"
    EXTRACTION = "extraction"
    EXTRACTION_QA = "extraction_qa"
    OBSERVATION_BUILD = "observation_build"
    ANALYTE_MAPPING = "analyte_mapping"
    UCUM_CONVERSION = "ucum_conversion"
    PANEL_RECONSTRUCTION = "panel_reconstruction"
    RULE_EVALUATION = "rule_evaluation"
    SEVERITY_ASSIGNMENT = "severity_assignment"
    NEXTSTEP_ASSIGNMENT = "nextstep_assignment"
    PATIENT_ARTIFACT = "patient_artifact"
    CLINICIAN_ARTIFACT = "clinician_artifact"
    LINEAGE_PERSIST = "lineage_persist"


class ContextStatus(StrEnum):
    EXTRACTED = "extracted"
    MISSING = "missing"
    CONFLICTED = "conflicted"


class MissingContextReasonCode(StrEnum):
    AGE_MISSING = "age_missing"
    SEX_MISSING = "sex_missing"
    LANGUAGE_MISSING = "language_missing"
    REPORT_DATE_MISSING = "report_date_missing"
    PATIENT_ID_CONFLICT = "patient_id_conflict"
    AGE_CONFLICT = "age_conflict"
    SEX_CONFLICT = "sex_conflict"
    LANGUAGE_CONFLICT = "language_conflict"
    REPORT_DATE_CONFLICT = "report_date_conflict"


class PatientContextV1(TypedDict):
    patient_id: str
    age_years: int | None
    sex: Literal["female", "male", "other", "unknown"] | None
    language_id: str | None
    context_status: ContextStatus
    missing_reason_codes: list[str]
    report_date: str | None


class RuntimeMetadataV1(TypedDict):
    terminology_release: str
    build_commit: str


class RuntimeRoutingV1(TypedDict):
    requested_lane: str
    selected_lane: str
    preflight_lane: str | None
    route_document_class: str | None
    route_reason_codes: list[str]
    route_confidence: float | None
    promotion_status: str | None
    enforcement_action: str


def _normalize_language_id(value: object) -> str | None:
    rendered = str(value or "").strip().lower()
    if not rendered:
        return None
    return rendered.split("-", 1)[0]


def _normalize_sex(value: object) -> Literal["female", "male", "other", "unknown"] | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    if normalized in {"f", "female", "woman", "w"}:
        return "female"
    if normalized in {"m", "male", "man"}:
        return "male"
    if normalized in {"other", "nonbinary", "non-binary", "x"}:
        return "other"
    if normalized in {"unknown", "u"}:
        return "unknown"
    return None


def _normalize_report_date(value: object) -> str | None:
    rendered = str(value or "").strip()
    return rendered or None


def _coerce_age_years(value: object) -> int | None:
    if value is None:
        return None
    try:
        age = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
    if age < 0 or age > 130:
        return None
    return age


def _resolve_unique(values: list[str]) -> tuple[str | None, bool]:
    if not values:
        return None, False
    normalized = sorted({value for value in values if value})
    if not normalized:
        return None, False
    if len(normalized) > 1:
        return None, True
    return normalized[0], False


def _resolve_unique_int(values: list[int]) -> tuple[int | None, bool]:
    if not values:
        return None, False
    normalized = sorted(set(values))
    if len(normalized) > 1:
        return None, True
    return normalized[0], False


def _derive_patient_context(job_id: str, extracted_rows: list[dict]) -> PatientContextV1:
    patient_ids: list[str] = []
    ages: list[int] = []
    sexes: list[str] = []
    languages: list[str] = []
    report_dates: list[str] = []

    for row in extracted_rows:
        patient_id = str(row.get("patient_id") or "").strip()
        if patient_id:
            patient_ids.append(patient_id)

        age = _coerce_age_years(row.get("age_years"))
        if age is not None:
            ages.append(age)

        sex = _normalize_sex(row.get("sex"))
        if sex is not None:
            sexes.append(sex)

        language_id = _normalize_language_id(row.get("language_id"))
        if language_id is not None:
            languages.append(language_id)

        report_date = _normalize_report_date(row.get("report_date"))
        if report_date is not None:
            report_dates.append(report_date)

    resolved_patient_id, patient_conflict = _resolve_unique(patient_ids)
    resolved_age, age_conflict = _resolve_unique_int(ages)
    resolved_sex, sex_conflict = _resolve_unique(sexes)
    resolved_language, language_conflict = _resolve_unique(languages)
    resolved_report_date, report_date_conflict = _resolve_unique(report_dates)

    missing_reason_codes: list[str] = []
    if resolved_age is None:
        missing_reason_codes.append(MissingContextReasonCode.AGE_MISSING.value)
    if resolved_sex is None:
        missing_reason_codes.append(MissingContextReasonCode.SEX_MISSING.value)
    if resolved_language is None:
        missing_reason_codes.append(MissingContextReasonCode.LANGUAGE_MISSING.value)
    if resolved_report_date is None:
        missing_reason_codes.append(MissingContextReasonCode.REPORT_DATE_MISSING.value)

    if patient_conflict:
        missing_reason_codes.append(MissingContextReasonCode.PATIENT_ID_CONFLICT.value)
    if age_conflict:
        missing_reason_codes.append(MissingContextReasonCode.AGE_CONFLICT.value)
    if sex_conflict:
        missing_reason_codes.append(MissingContextReasonCode.SEX_CONFLICT.value)
    if language_conflict:
        missing_reason_codes.append(MissingContextReasonCode.LANGUAGE_CONFLICT.value)
    if report_date_conflict:
        missing_reason_codes.append(MissingContextReasonCode.REPORT_DATE_CONFLICT.value)

    if patient_conflict or age_conflict or sex_conflict or language_conflict or report_date_conflict:
        context_status = ContextStatus.CONFLICTED
    elif missing_reason_codes:
        context_status = ContextStatus.MISSING
    else:
        context_status = ContextStatus.EXTRACTED

    resolved_sex_value: Literal["female", "male", "other", "unknown"] | None = None
    if resolved_sex in {"female", "male", "other", "unknown"}:
        resolved_sex_value = resolved_sex

    return {
        "patient_id": resolved_patient_id or str(uuid5(NAMESPACE_URL, f"patient:{job_id}")),
        "age_years": resolved_age,
        "sex": resolved_sex_value,
        "language_id": resolved_language,
        "context_status": context_status,
        "missing_reason_codes": sorted(set(missing_reason_codes)),
        "report_date": resolved_report_date,
    }


def _build_runtime_metadata(snapshot_metadata: dict | None) -> RuntimeMetadataV1:
    terminology_release = (
        str(snapshot_metadata.get("release") or _UNKNOWN_RUNTIME_VALUE)
        if snapshot_metadata
        else _UNKNOWN_RUNTIME_VALUE
    )
    build_commit = str(getattr(settings, "build_commit", "") or _UNKNOWN_RUNTIME_VALUE)
    return {
        "terminology_release": terminology_release,
        "build_commit": build_commit,
    }


def _build_render_context(
    job_uuid: UUID,
    language_id: str,
    observations: list[dict],
    lane_type: str,
    findings: list[dict],
    comparable_history: dict | None,
    report_date: str | None,
) -> dict:
    return {
        "job_id": job_uuid,
        "language_id": language_id,
        "support_banner": SupportBanner(
            _support_banner_from_runtime(observations, findings, comparable_history)
        ),
        "trust_status": (
            TrustStatus.NON_TRUSTED_BETA if lane_type == "image_beta" else TrustStatus.TRUSTED
        ),
        "report_date": report_date,
        "comparable_history": comparable_history,
    }


def _build_lineage_payload(
    job_id: str,
    *,
    source_checksum: str | None,
    lane_type: str,
    terminology_release: str,
    build_commit: str,
    parser_backend: str | None = None,
    parser_backend_version: str | None = None,
    row_assembly_version: str | None = None,
    completeness_telemetry: dict | None = None,
) -> dict:
    """Build the v12 lineage payload with parser substrate metadata.

    When parser_backend and parser_backend_version are provided by the extraction
    step, they are recorded honestly in the lineage bundle. Otherwise the pipeline
    falls back to the lane-level constants for backwards compatibility.
    """
    effective_parser = parser_backend or (
        "pymupdf" if lane_type == "trusted_pdf" else "qwen_ocr"
    )
    effective_parser_version = parser_backend_version or (
        _PARSER_VERSION_TRUSTED if lane_type == "trusted_pdf" else _PARSER_VERSION_IMAGE_BETA
    )
    effective_row_assembly = row_assembly_version or _ROW_ASSEMBLY_VERSION

    return {
        "source_checksum": source_checksum or f"{_UNKNOWN_RUNTIME_VALUE}:{job_id}",
        "parser_backend": effective_parser,
        "parser_backend_version": effective_parser_version,
        "parser_version": (
            _PARSER_VERSION_TRUSTED if lane_type == "trusted_pdf" else _PARSER_VERSION_IMAGE_BETA
        ),
        "adapter_version": _ADAPTER_VERSION,
        "row_assembly_version": effective_row_assembly,
        "row_type_rule_set_version": _ROW_TYPE_RULE_SET_VERSION,
        "formula_version": _FORMULA_VERSION,
        "ocr_version": _OCR_VERSION_IMAGE_BETA if lane_type == "image_beta" else None,
        "terminology_release": terminology_release,
        "mapping_threshold_config": _MAPPING_THRESHOLD_DEFAULT,
        "unit_engine_version": _UNIT_ENGINE_VERSION,
        "rule_pack_version": _RULE_PACK_VERSION,
        "severity_policy_version": _SEVERITY_POLICY_VERSION,
        "nextstep_policy_version": _NEXTSTEP_POLICY_VERSION,
        "template_version": _TEMPLATE_VERSION,
        "model_version": None,
        "build_commit": build_commit or _UNKNOWN_RUNTIME_VALUE,
        "completeness_telemetry": completeness_telemetry,
    }


def _build_persistence_payloads(
    patient_artifact: dict,
    clinician_artifact: dict,
    lineage: dict,
    benchmark: dict,
    status: str,
) -> dict:
    return {
        "patient_artifact": {
            "language_id": patient_artifact["language_id"],
            "support_banner": patient_artifact["support_banner"],
            "content": _json_safe(patient_artifact),
            "template_version": _TEMPLATE_VERSION,
        },
        "clinician_artifact": {
            "content": _json_safe(clinician_artifact),
            "template_version": _TEMPLATE_VERSION,
        },
        "lineage_run": {
            "source_checksum": lineage["source_checksum"],
            "parser_backend": lineage.get("parser_backend"),
            "parser_backend_version": lineage.get("parser_backend_version"),
            "parser_version": lineage["parser_version"],
            "adapter_version": lineage.get("adapter_version"),
            "row_assembly_version": lineage.get("row_assembly_version"),
            "row_type_rule_set_version": lineage.get("row_type_rule_set_version"),
            "formula_version": lineage.get("formula_version"),
            "ocr_version": lineage["ocr_version"],
            "terminology_release": lineage["terminology_release"],
            "mapping_threshold_config": lineage["mapping_threshold_config"],
            "unit_engine_version": lineage["unit_engine_version"],
            "rule_pack_version": lineage["rule_pack_version"],
            "severity_policy_version": lineage["severity_policy_version"],
            "nextstep_policy_version": lineage["nextstep_policy_version"],
            "template_version": lineage["template_version"],
            "model_version": lineage["model_version"],
            "build_commit": lineage["build_commit"],
        },
        "benchmark_run": {
            "report_type": benchmark["report_type"],
            "metrics": benchmark["metrics"],
        },
        "status": status,
    }


def _assemble_result(
    job_id: str,
    lane_type: str,
    qa_result: dict,
    observations: list[dict],
    panels: list[dict],
    findings: list[dict],
    patient_artifact: dict,
    clinician_artifact: dict,
    lineage: dict,
    benchmark: dict,
) -> dict:
    return {
        "job_id": job_id,
        "status": "completed" if patient_artifact["support_banner"] == "fully_supported" else "partial",
        "step": PipelineStep.LINEAGE_PERSIST.value,
        "lane_type": lane_type,
        "qa": qa_result,
        "observations": observations,
        "panels": panels,
        "findings": findings,
        "patient_artifact": patient_artifact,
        "clinician_artifact": clinician_artifact,
        "lineage": lineage,
        "benchmark": benchmark,
    }


def _build_proof_pack(
    *,
    benchmark_recorder: BenchmarkRecorder,
    job_uuid: UUID,
    benchmark: dict,
    lineage: dict,
    lane_type: str,
    language_id: str,
) -> dict:
    return benchmark_recorder.build_proof_pack(
        benchmark=benchmark,
        lineage=lineage,
        artifact_refs={
            "patient_artifact": f"/api/artifacts/{job_uuid}/patient",
            "clinician_artifact": f"/api/artifacts/{job_uuid}/clinician",
            "clinician_pdf": clinician_pdf_route(job_uuid),
            "job_status": f"/api/jobs/{job_uuid}",
            "proof_pack": proof_pack_route(job_uuid),
        },
        report_metadata={
            "build_commit": lineage.get("build_commit") or _UNKNOWN_RUNTIME_VALUE,
            "corpus_id": _PROOF_CORPUS_ID,
            "lane_id": lane_type,
            "language_id": language_id,
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        },
    )


class PipelineOrchestrator:
    """Orchestrate the full processing pipeline for a job."""

    async def run(
        self,
        job_id: str,
        *,
        file_bytes: bytes | None = None,
        lane_type: str | None = None,
        db_session: AsyncSession | None = None,
        document_id: UUID | str | None = None,
        source_checksum: str | None = None,
        source_filename: str | None = None,
        source_mime_type: str | None = None,
        runtime_preflight: dict | None = None,
    ) -> dict:
        job_uuid = _job_uuid(job_id)
        document_uuid = (
            (document_id if isinstance(document_id, UUID) else UUID(str(document_id)))
            if document_id is not None
            else job_uuid
        )
        requested_lane = lane_type or "trusted_pdf"
        runtime_routing = _default_runtime_routing(
            requested_lane,
            action="caller_lane_without_runtime_preflight",
        )
        selected_lane = runtime_routing["selected_lane"]
        if file_bytes is not None and (runtime_preflight is not None or (source_filename and source_mime_type)):
            runtime_routing = await _resolve_runtime_routing(
                file_bytes=file_bytes,
                requested_lane=requested_lane,
                source_filename=source_filename,
                source_mime_type=source_mime_type,
                runtime_preflight=runtime_preflight,
            )
            selected_lane = runtime_routing["selected_lane"]
        _LOGGER.info(
            "pipeline_start job_id=%s requested_lane=%s selected_lane=%s action=%s",
            job_id,
            requested_lane,
            selected_lane,
            runtime_routing["enforcement_action"],
        )

        extraction_qa = ExtractionQA()
        observation_builder = ObservationBuilder()
        analyte_resolver = AnalyteResolver()
        ucum_engine = UcumEngine()
        panel_reconstructor = PanelReconstructor()
        reference_selector = ReferenceSelectionService()
        rule_engine = RuleEngine()
        severity_policy = SeverityPolicyEngine()
        nextstep_policy = NextStepPolicyEngine()
        artifact_renderer = ArtifactRenderer()
        lineage_logger = LineageLogger()
        benchmark_recorder = BenchmarkRecorder()
        comparable_history_service = ComparableHistoryService(db_session)
        processing_start = perf_counter()

        try:
            _validate_lane(selected_lane)
            extraction_start = perf_counter()
            extracted_rows = await _extract_rows(
                job_uuid,
                file_bytes=file_bytes,
                lane_type=selected_lane,
            )
            patient_context = _derive_patient_context(job_id, extracted_rows)
            extraction_ms = int((perf_counter() - extraction_start) * 1000)
            qa_result = extraction_qa.validate(extracted_rows)
            observations = observation_builder.build(qa_result["clean_rows"])
            normalized_observations = _normalize_observations(
                observations,
                analyte_resolver=analyte_resolver,
                ucum_engine=ucum_engine,
            )
            normalized_observations = _attach_derived_source_links(normalized_observations)
            normalization_trace = _build_normalization_trace(normalized_observations)
            reference_decisions = reference_selector.select_for_observations(
                normalized_observations,
                patient_context,
            )
            normalized_observations = _attach_reference_decisions(
                normalized_observations,
                reference_decisions,
            )
            completeness_telemetry = _build_completeness_telemetry(
                extracted_rows=extracted_rows,
                clean_rows=qa_result["clean_rows"],
                observations=normalized_observations,
            )
            panels = panel_reconstructor.reconstruct(normalized_observations)
            findings = rule_engine.evaluate(normalized_observations, patient_context)
            findings = severity_policy.assign(findings, patient_context)
            findings = nextstep_policy.assign(findings, patient_context)
            comparable_history = await comparable_history_service.build_for_artifact(
                job_id=job_uuid,
                observations=normalized_observations,
                report_date=patient_context.get("report_date") or _UNKNOWN_RUNTIME_VALUE,
            )
            support_banner_shadow = _support_banner_from_runtime(
                normalized_observations,
                findings,
                comparable_history,
            )
            semantic_success_shadow = _build_semantic_success_shadow(
                completeness_telemetry=completeness_telemetry,
                findings=findings,
                support_banner=support_banner_shadow,
                lane_type=selected_lane,
            )
            completeness_telemetry = {
                **completeness_telemetry,
                "semantic_success_shadow": semantic_success_shadow,
            }

            render_context = _build_render_context(
                job_uuid,
                patient_context.get("language_id") or _UNDETERMINED_LANGUAGE_ID,
                normalized_observations,
                selected_lane,
                findings,
                comparable_history,
                patient_context.get("report_date"),
            )
            patient_artifact = artifact_renderer.render_patient(
                findings,
                render_context,
                observations=normalized_observations,
            )
            explanation_payload = await ExplanationAdapter().generate(
                findings,
                patient_context.get("language_id") or _UNDETERMINED_LANGUAGE_ID,
            )
            patient_artifact["explanation"] = explanation_payload
            clinician_artifact = artifact_renderer.render_clinician(
                findings,
                render_context,
                observations=normalized_observations,
            )
            write_clinician_pdf(job_uuid, clinician_artifact)
            snapshot_metadata = get_loaded_snapshot_metadata()
            runtime_metadata = _build_runtime_metadata(snapshot_metadata)

            # v12: capture parser metadata from extraction step if available
            parser_backend = _extract_parser_backend(extracted_rows)
            parser_backend_version = _extract_parser_backend_version(extracted_rows)
            row_assembly_version = _extract_row_assembly_version(extracted_rows)

            lineage_payload = _build_lineage_payload(
                job_id,
                source_checksum=source_checksum,
                lane_type=selected_lane,
                terminology_release=runtime_metadata["terminology_release"],
                build_commit=runtime_metadata["build_commit"],
                parser_backend=parser_backend,
                parser_backend_version=parser_backend_version,
                row_assembly_version=row_assembly_version,
                completeness_telemetry=completeness_telemetry,
            )
            lineage = lineage_logger.record(str(job_uuid), lineage_payload)
            # v12: merge the logger return (persisted ids) into the deterministic payload
            # so that sparse collaborator returns do not drop v12 provenance fields.
            lineage = {**lineage_payload, **lineage}
            processing_ms = int((perf_counter() - processing_start) * 1000)

            # Compute benchmark metrics deterministically; the recorder may enrich
            # them but must not strip pipeline-computed provenance metadata.
            computed_metrics = {
                "extracted_rows": len(extracted_rows),
                "clean_rows": len(qa_result["clean_rows"]),
                "findings": len(findings),
                "panels": len(panels),
                "extraction_ms": extraction_ms,
                "processing_ms": processing_ms,
                "parser_backend": parser_backend,
                "parser_backend_version": parser_backend_version,
                "row_assembly_version": row_assembly_version,
                **_completeness_metrics(completeness_telemetry),
            }
            benchmark = benchmark_recorder.record(
                lineage_id=str(lineage["id"]),
                report_type=_REPORT_TYPE,
                metrics=computed_metrics,
            )
            # v12: merge computed metrics with the recorder return so sparse
            # collaborator dicts do not erase pipeline-computed provenance fields.
            benchmark_metrics = benchmark.get("metrics", {})
            for key, value in computed_metrics.items():
                benchmark_metrics.setdefault(key, value)
            benchmark["metrics"] = benchmark_metrics
            proof_pack = _build_proof_pack(
                benchmark_recorder=benchmark_recorder,
                job_uuid=job_uuid,
                benchmark=benchmark,
                lineage=lineage,
                lane_type=selected_lane,
                language_id=patient_context.get("language_id") or _UNDETERMINED_LANGUAGE_ID,
            )
            write_proof_pack(job_uuid, proof_pack)

            result = _assemble_result(
                job_id,
                selected_lane,
                qa_result,
                normalized_observations,
                panels,
                findings,
                patient_artifact,
                clinician_artifact,
                lineage,
                benchmark,
            )
            result["completeness_telemetry"] = completeness_telemetry
            result["semantic_success_shadow"] = semantic_success_shadow
            result["proof_pack_ref"] = proof_pack_route(job_uuid)
            result["clinician_pdf_ref"] = clinician_pdf_route(job_uuid)
            result["proof_pack"] = proof_pack
            result["patient_context"] = patient_context
            result["runtime_metadata"] = runtime_metadata
            result["reference_decisions"] = reference_decisions
            result["normalization_trace"] = normalization_trace
            result["runtime_routing"] = runtime_routing

            if db_session is not None:
                store = TopLevelLifecycleStore(db_session)
                persistence = _build_persistence_payloads(
                    patient_artifact,
                    clinician_artifact,
                    lineage,
                    benchmark,
                    result["status"],
                )
                persisted_rows = await _persist_row_level_entities(
                    store,
                    job_uuid=job_uuid,
                    document_id=document_uuid,
                    clean_rows=qa_result["clean_rows"],
                    observations=normalized_observations,
                    findings=findings,
                )
                await store.persist_top_level_bundle(
                    job_id=job_uuid,
                    status=persistence["status"],
                    patient_artifact=persistence["patient_artifact"],
                    clinician_artifact=persistence["clinician_artifact"],
                    lineage_run=persistence["lineage_run"],
                    benchmark_run=persistence["benchmark_run"],
                )
                result["row_level_persistence"] = persisted_rows

            _JOB_RUNS[str(job_uuid)] = result
            _JOB_RUNS[job_id] = result
            _LOGGER.info(
                "pipeline_complete job_id=%s lane=%s status=%s",
                job_id,
                selected_lane,
                result["status"],
            )
            return result
        except Exception as exc:
            _LOGGER.error(
                "pipeline_failed job_id=%s lane=%s error=%s",
                job_id,
                selected_lane,
                exc,
            )
            raise


def get_job_run(job_id: str) -> dict | None:
    return _JOB_RUNS.get(job_id)


def _job_uuid(job_id: str) -> UUID:
    try:
        return UUID(str(job_id))
    except ValueError:
        return uuid5(NAMESPACE_URL, f"job:{job_id}")


def _validate_lane(lane_type: str) -> None:
    if lane_type not in _SUPPORTED_LANES:
        raise ValueError(f"unsupported_lane:{lane_type}")


def _default_runtime_routing(requested_lane: str, *, action: str) -> RuntimeRoutingV1:
    return {
        "requested_lane": requested_lane,
        "selected_lane": requested_lane,
        "preflight_lane": None,
        "route_document_class": None,
        "route_reason_codes": [],
        "route_confidence": None,
        "promotion_status": None,
        "enforcement_action": action,
    }


def _coerce_route_confidence(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def _resolve_runtime_routing(
    *,
    file_bytes: bytes,
    requested_lane: str,
    source_filename: str | None,
    source_mime_type: str | None,
    runtime_preflight: dict | None,
) -> RuntimeRoutingV1:
    preflight = runtime_preflight
    if preflight is None:
        if not source_filename or not source_mime_type:
            return _default_runtime_routing(
                requested_lane,
                action="caller_lane_without_runtime_preflight",
            )
        try:
            preflight = await InputGateway().preflight(
                file_bytes,
                source_filename,
                source_mime_type,
            )
        except Exception as exc:  # noqa: BLE001 - fail closed on runtime preflight errors
            routing = _default_runtime_routing(
                requested_lane,
                action="downgraded_runtime_preflight_error",
            )
            routing["selected_lane"] = "unsupported"
            routing["route_reason_codes"] = [f"runtime_preflight_error:{exc}"]
            return routing

    preflight_lane = str(preflight.get("lane_type") or "unsupported")
    route_document_class = str(
        preflight.get("route_document_class")
        or preflight.get("document_class")
        or _UNKNOWN_RUNTIME_VALUE
    )
    route_reason_codes = [str(code) for code in (preflight.get("route_reason_codes") or [])]
    route_confidence = _coerce_route_confidence(preflight.get("route_confidence"))
    promotion_status = str(preflight.get("promotion_status") or "")

    selected_lane = preflight_lane
    enforcement_action = "preflight_lane_enforced"

    if route_document_class in _FAIL_CLOSED_DOCUMENT_CLASSES:
        selected_lane = "unsupported"
        enforcement_action = "downgraded_non_lab_or_ambiguous_class"
    elif selected_lane == "image_beta" and promotion_status != "beta_ready":
        selected_lane = "unsupported"
        enforcement_action = "downgraded_image_beta_not_ready"
        route_reason_codes.append(
            f"image_beta_not_ready:{promotion_status or _UNKNOWN_RUNTIME_VALUE}"
        )
    elif requested_lane != preflight_lane:
        enforcement_action = "lane_mismatch_preflight_enforced"

    _validate_lane(selected_lane)
    return {
        "requested_lane": requested_lane,
        "selected_lane": selected_lane,
        "preflight_lane": preflight_lane,
        "route_document_class": route_document_class,
        "route_reason_codes": route_reason_codes,
        "route_confidence": route_confidence,
        "promotion_status": promotion_status,
        "enforcement_action": enforcement_action,
    }


# ---------------------------------------------------------------------------
# v12 runtime page-limit guard (separate from parser-level truncation)
# ---------------------------------------------------------------------------

def _enforce_pdf_page_limit(file_bytes: bytes) -> None:
    """Raise ``page_count_limit_exceeded`` if the PDF exceeds ``settings.max_pdf_pages``.

    This is a runtime safety check that lives in the pipeline layer, not in the
    parser itself.  ``BornDigitalParser.parse(..., max_pages=...)`` intentionally
    truncates rather than raising; the hard failure belongs at the upload/runtime
    boundary so oversized uploads produce a persisted ``failed`` job with a clear
    ``operator_note``.
    """
    import fitz

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        page_count = doc.page_count
    except Exception:  # noqa: BLE001 - corrupt PDF is handled upstream
        return
    finally:
        try:
            doc.close()
        except Exception:  # noqa: BLE001
            pass

    limit = settings.max_pdf_pages
    if page_count > limit:
        raise ValueError(f"page_count_limit_exceeded:{page_count}>{limit}")


# ---------------------------------------------------------------------------
# v12 parser metadata extraction helpers
# ---------------------------------------------------------------------------

def _extract_parser_backend(rows: list[dict]) -> str | None:
    """Return the parser backend identifier from extraction rows, if present."""
    for row in rows:
        backend = row.get("parser_backend") or row.get("_v12_parser_backend")
        if backend:
            return str(backend)
    return None


def _extract_parser_backend_version(rows: list[dict]) -> str | None:
    """Return the parser backend version from extraction rows, if present."""
    for row in rows:
        version = row.get("parser_backend_version") or row.get("_v12_parser_backend_version")
        if version:
            return str(version)
    return None


def _extract_row_assembly_version(rows: list[dict]) -> str | None:
    """Return the row-assembly version from extraction rows, if present."""
    for row in rows:
        version = row.get("row_assembly_version") or row.get("_v12_row_assembly_version")
        if version:
            return str(version)
    return None


async def _extract_rows(
    job_uuid: UUID,
    *,
    file_bytes: bytes | None,
    lane_type: str,
) -> list[dict]:
    _validate_lane(lane_type)

    if file_bytes is None:
        if lane_type == "unsupported":
            return []
        raise ValueError("missing_file_bytes")

    if lane_type == "trusted_pdf":
        _enforce_pdf_page_limit(file_bytes)
        return await TrustedPdfParser().parse(file_bytes, max_pages=settings.max_pdf_pages)

    if lane_type == "image_beta":
        return await OcrAdapter(
            image_beta_enabled=settings.image_beta_enabled,
        ).extract(
            file_bytes,
            document_id=job_uuid,
            language_id=None,
        )

    if lane_type == "unsupported":
        return []

    raise ValueError(f"unsupported_lane:{lane_type}")


async def _persist_row_level_entities(
    store: TopLevelLifecycleStore,
    *,
    job_uuid: UUID,
    document_id: UUID,
    clean_rows: list[dict],
    observations: list[dict],
    findings: list[dict],
) -> dict[str, int]:
    extracted_row_ids_by_row_hash: dict[str, UUID] = {}
    observation_ids_by_observation_uuid: dict[UUID, UUID] = {}
    row_level_counts = {
        "extracted_rows": 0,
        "observations": 0,
        "mapping_candidates": 0,
        "rule_events": 0,
        "policy_events": 0,
    }

    for row in clean_rows:
        persisted_row = await store.create_extracted_row(
            document_id=document_id,
            job_id=job_uuid,
            source_page=int(row["source_page"]),
            row_hash=str(row["row_hash"]),
            raw_text=str(row["raw_text"]),
            raw_analyte_label=row.get("raw_analyte_label"),
            raw_value_string=row.get("raw_value_string"),
            raw_unit_string=row.get("raw_unit_string"),
            raw_reference_range=row.get("raw_reference_range"),
            source_block_id=row.get("block_id"),
            source_row_id=str((row.get("candidate_trace") or {}).get("segment_index"))
            if isinstance(row.get("candidate_trace"), dict) and (row.get("candidate_trace") or {}).get("segment_index") is not None
            else row.get("source_row_id"),
            row_type=row.get("row_type"),
            block_type=row.get("page_class"),
            family_adapter_id=row.get("family_adapter_id"),
            failure_code=row.get("failure_code"),
            extraction_confidence=row.get("extraction_confidence"),
        )
        extracted_row_ids_by_row_hash[str(row["row_hash"])] = persisted_row.id
        row_level_counts["extracted_rows"] += 1

    for observation in observations:
        observation_id = observation.get("id")
        if observation_id is None:
            raise ValueError("observation_missing_id")
        if not isinstance(observation_id, UUID):
            observation_id = UUID(str(observation_id))

        extracted_row_id = extracted_row_ids_by_row_hash.get(str(observation["row_hash"]))
        if extracted_row_id is None:
            raise LookupError(f"missing_extracted_row_for_observation:{observation['row_hash']}")

        persisted_observation = await store.create_observation(
            document_id=document_id,
            job_id=job_uuid,
            extracted_row_id=extracted_row_id,
            source_page=int(observation["source_page"]),
            row_hash=str(observation["row_hash"]),
            raw_analyte_label=str(observation["raw_analyte_label"]),
            raw_value_string=observation.get("raw_value_string"),
            raw_unit_string=observation.get("raw_unit_string"),
            parsed_numeric_value=observation.get("parsed_numeric_value"),
            source_block_id=observation.get("source_block_id") or observation.get("block_id"),
            source_row_id=observation.get("source_row_id"),
            row_type=observation.get("row_type"),
            measurement_kind=observation.get("measurement_kind"),
            support_code=observation.get("support_code"),
            failure_code=observation.get("failure_code"),
            family_adapter_id=observation.get("family_adapter_id"),
            parsed_locale=_compact_parsed_locale(observation.get("parsed_locale")),
            parsed_comparator=observation.get("parsed_comparator"),
            primary_result=observation.get("primary_result"),
            secondary_result=observation.get("secondary_result"),
            candidate_trace=observation.get("candidate_trace"),
            derived_formula_id=observation.get("derived_formula_id"),
            source_observation_ids=observation.get("source_observation_ids"),
            accepted_analyte_code=observation.get("accepted_analyte_code"),
            accepted_analyte_display=observation.get("accepted_analyte_display"),
            specimen_context=observation.get("specimen_context"),
            method_context=observation.get("method_context"),
            raw_reference_range=observation.get("raw_reference_range"),
            canonical_unit=observation.get("canonical_unit"),
            canonical_value=observation.get("canonical_value"),
            language_id=observation.get("language_id"),
            support_state=_enum_value(observation.get("support_state")),
            suppression_reasons=observation.get("suppression_reasons") or None,
        )
        observation_ids_by_observation_uuid[observation_id] = persisted_observation.id
        row_level_counts["observations"] += 1

        for candidate in observation.get("candidates", []):
            await store.create_mapping_candidate(
                observation_id=persisted_observation.id,
                candidate_code=str(candidate["candidate_code"]),
                candidate_display=str(candidate["candidate_display"]),
                score=float(candidate["score"]),
                threshold_used=float(candidate["threshold_used"]),
                accepted=bool(candidate["accepted"]),
                rejection_reason=candidate.get("rejection_reason"),
            )
            row_level_counts["mapping_candidates"] += 1

    for finding in findings:
        observation_ids = [
            observation_ids_by_observation_uuid[uuid]
            for uuid in finding.get("observation_ids", [])
            if uuid in observation_ids_by_observation_uuid
        ]
        if not observation_ids:
            continue

        persisted_rule_event = await store.create_rule_event(
            job_id=job_uuid,
            observation_id=observation_ids[0],
            rule_id=str(finding["rule_id"]),
            finding_id=_stable_identifier(str(finding["finding_id"])),
            threshold_source=str(finding["threshold_source"]),
            supporting_observation_ids=observation_ids,
            suppression_conditions=finding.get("suppression_conditions"),
            severity_class_candidate=_enum_value(finding.get("severity_class_candidate")),
            nextstep_class_candidate=_enum_value(finding.get("nextstep_class_candidate")),
        )
        row_level_counts["rule_events"] += 1

        await store.create_policy_event(
            job_id=job_uuid,
            rule_event_id=persisted_rule_event.id,
            severity_class=_enum_value(finding.get("severity_class")),
            nextstep_class=_enum_value(finding.get("nextstep_class")),
            severity_policy_version=_SEVERITY_POLICY_VERSION,
            nextstep_policy_version=_NEXTSTEP_POLICY_VERSION,
            suppression_active=bool(finding.get("suppression_active", False)),
            suppression_reason=finding.get("suppression_reason"),
        )
        row_level_counts["policy_events"] += 1

    return row_level_counts


def _enum_value(value: object) -> object:
    if hasattr(value, "value"):
        return value.value
    return value


def _compact_parsed_locale(value: object) -> str | None:
    if isinstance(value, dict):
        decimal_separator = str(value.get("decimal_separator") or "").strip()
        thousands_separator = str(value.get("thousands_separator") or "").strip()
        normalized = bool(value.get("normalized"))
        parts: list[str] = []
        if decimal_separator == ",":
            parts.append("decimal_comma")
        elif decimal_separator == ".":
            parts.append("decimal_dot")
        if thousands_separator == ",":
            parts.append("thousands_comma")
        elif thousands_separator == ".":
            parts.append("thousands_dot")
        if normalized:
            parts.append("normalized")
        return "+".join(parts) or None
    if value is None:
        return None
    rendered = str(value).strip()
    return rendered or None


def _stable_identifier(value: str, *, max_length: int = 64) -> str:
    if len(value) <= max_length:
        return value
    digest = sha256(value.encode("utf-8")).hexdigest()[:32]
    prefix = value.split("::", 1)[0] if "::" in value else "id"
    return f"{prefix}::{digest}"


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _normalize_page(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_normalization_trace(observations: list[dict]) -> dict:
    numeric = 0
    qualitative = 0
    dual_unit = 0
    derived = 0
    partial = 0
    unsupported = 0

    for observation in observations:
        raw_value = str(observation.get("raw_value_string") or "").strip().lower()
        support_state = str(observation.get("support_state") or "").strip().lower()
        secondary_result = observation.get("secondary_result")
        measurement_kind = str(observation.get("measurement_kind") or "").strip().lower()

        if observation.get("parsed_numeric_value") is not None:
            numeric += 1
        elif raw_value in {
            "positive",
            "negative",
            "detected",
            "not detected",
            "present",
            "absent",
            "trace",
            "dnr",
            "ldnr",
            "oor",
        }:
            qualitative += 1

        if secondary_result not in (None, {}):
            dual_unit += 1

        if measurement_kind == "derived":
            derived += 1

        if support_state == "partial":
            partial += 1
        if support_state == "unsupported":
            unsupported += 1

    return {
        "contract_version": _NORMALIZATION_TRACE_VERSION,
        "counts": {
            "observations": len(observations),
            "numeric": numeric,
            "qualitative": qualitative,
            "dual_unit": dual_unit,
            "derived": derived,
            "partial": partial,
            "unsupported": unsupported,
        },
    }


def _build_completeness_telemetry(
    *,
    extracted_rows: list[dict],
    clean_rows: list[dict],
    observations: list[dict],
) -> dict:
    extracted_pages = {
        page for row in extracted_rows if (page := _normalize_page(row.get("source_page"))) is not None
    }
    clean_pages = {
        page for row in clean_rows if (page := _normalize_page(row.get("source_page"))) is not None
    }

    result_observations = [
        observation
        for observation in observations
        if str(observation.get("row_type") or "").strip().lower()
        not in _COMPLETENESS_NON_RESULT_ROW_TYPES
    ]

    supported_count = sum(
        1
        for observation in result_observations
        if str(observation.get("support_state") or "").strip().lower() == "supported"
    )
    partial_count = sum(
        1
        for observation in result_observations
        if str(observation.get("support_state") or "").strip().lower() == "partial"
    )
    unsupported_count = sum(
        1
        for observation in result_observations
        if str(observation.get("support_state") or "").strip().lower() == "unsupported"
    )
    reference_bound_count = sum(
        1
        for observation in result_observations
        if str(observation.get("raw_reference_range") or "").strip()
    )

    extracted_count = len(extracted_rows)
    clean_count = len(clean_rows)
    result_observation_count = len(result_observations)

    structural_ratio = _safe_ratio(clean_count, extracted_count)
    page_coverage_ratio = _safe_ratio(len(clean_pages), len(extracted_pages))
    supported_ratio = _safe_ratio(supported_count, result_observation_count)
    reference_coverage_ratio = _safe_ratio(reference_bound_count, result_observation_count)

    if extracted_count == 0 or clean_count == 0:
        structural_state = "absent"
    elif structural_ratio >= 0.8 and page_coverage_ratio >= 0.8:
        structural_state = "complete"
    elif structural_ratio >= 0.5:
        structural_state = "partial"
    else:
        structural_state = "sparse"

    if result_observation_count == 0:
        observation_state = "absent"
    elif supported_count == result_observation_count:
        observation_state = "complete"
    elif supported_count > 0:
        observation_state = "partial"
    else:
        observation_state = "sparse"

    if result_observation_count == 0:
        reference_state = "unavailable"
    elif reference_coverage_ratio >= 0.8:
        reference_state = "complete"
    elif reference_bound_count > 0:
        reference_state = "partial"
    else:
        reference_state = "missing"

    return {
        "contract_version": _COMPLETENESS_TELEMETRY_VERSION,
        "counts": {
            "extracted_rows": extracted_count,
            "clean_rows": clean_count,
            "extracted_pages": len(extracted_pages),
            "clean_pages": len(clean_pages),
            "result_observations": result_observation_count,
            "supported_observations": supported_count,
            "partial_observations": partial_count,
            "unsupported_observations": unsupported_count,
            "reference_bound_observations": reference_bound_count,
        },
        "ratios": {
            "structural_clean_row_ratio": structural_ratio,
            "structural_page_coverage_ratio": page_coverage_ratio,
            "observation_supported_ratio": supported_ratio,
            "reference_coverage_ratio": reference_coverage_ratio,
        },
        "states": {
            "structural": structural_state,
            "observation": observation_state,
            "reference": reference_state,
        },
    }


def _build_semantic_success_shadow(
    *,
    completeness_telemetry: dict,
    findings: list[dict],
    support_banner: str,
    lane_type: str,
) -> dict:
    counts = dict(completeness_telemetry.get("counts") or {})
    ratios = dict(completeness_telemetry.get("ratios") or {})
    states = dict(completeness_telemetry.get("states") or {})

    result_observation_count = int(counts.get("result_observations") or 0)
    supported_ratio = float(ratios.get("observation_supported_ratio") or 0.0)
    structural_state = str(states.get("structural") or "absent")
    observation_state = str(states.get("observation") or "absent")
    reference_state = str(states.get("reference") or "unavailable")

    actionable_finding_count = sum(
        1
        for finding in findings
        if not bool(finding.get("suppression_active"))
        and str(finding.get("severity_class") or "") not in {"S0", "SX"}
    )
    suppressed_finding_count = sum(1 for finding in findings if bool(finding.get("suppression_active")))
    threshold_conflict_count = sum(
        1
        for finding in findings
        if str(finding.get("suppression_reason") or "") == "threshold_conflict"
    )

    structural_gate_pass = structural_state == "complete"
    observation_gate_pass = (
        result_observation_count > 0
        and observation_state in {"complete", "partial"}
        and supported_ratio >= 0.5
    )
    reference_gate_pass = reference_state in {"complete", "partial"}

    gate_pass_count = (
        int(structural_gate_pass)
        + int(observation_gate_pass)
        + int(reference_gate_pass)
    )
    confidence = round(gate_pass_count / 3.0, 4)
    if support_banner == "could_not_assess":
        confidence = min(confidence, 0.33)
    if lane_type == "unsupported":
        confidence = min(confidence, 0.25)

    limiting_factors: list[str] = []
    if not structural_gate_pass:
        limiting_factors.append("structural_incomplete")
    if not observation_gate_pass:
        limiting_factors.append("observation_incomplete")
    if not reference_gate_pass:
        limiting_factors.append("reference_incomplete")
    if threshold_conflict_count > 0:
        limiting_factors.append("threshold_conflict_present")
    if support_banner == "could_not_assess":
        limiting_factors.append("support_banner_could_not_assess")
    if lane_type == "unsupported":
        limiting_factors.append("unsupported_lane")

    if (
        lane_type != "unsupported"
        and support_banner == "fully_supported"
        and structural_gate_pass
        and observation_gate_pass
        and reference_gate_pass
        and actionable_finding_count == 0
    ):
        semantic_state = "shadow_fully_recoverable"
    elif lane_type != "unsupported" and support_banner in {"fully_supported", "partially_supported"} and observation_gate_pass:
        semantic_state = "shadow_partially_recoverable"
    else:
        semantic_state = "shadow_not_recoverable"

    return {
        "contract_version": _SEMANTIC_SUCCESS_SHADOW_VERSION,
        "semantic_state": semantic_state,
        "confidence": confidence,
        "support_banner": support_banner,
        "lane_type": lane_type,
        "structural_gate_pass": structural_gate_pass,
        "observation_gate_pass": observation_gate_pass,
        "reference_gate_pass": reference_gate_pass,
        "finding_counts": {
            "total": len(findings),
            "actionable": actionable_finding_count,
            "suppressed": suppressed_finding_count,
            "threshold_conflicts": threshold_conflict_count,
        },
        "limiting_factors": limiting_factors,
    }


def _completeness_metrics(completeness_telemetry: dict) -> dict:
    ratios = dict(completeness_telemetry.get("ratios") or {})
    states = dict(completeness_telemetry.get("states") or {})
    semantic_shadow = dict(completeness_telemetry.get("semantic_success_shadow") or {})
    finding_counts = dict(semantic_shadow.get("finding_counts") or {})

    return {
        "completeness_structural_ratio": float(ratios.get("structural_clean_row_ratio") or 0.0),
        "completeness_page_coverage_ratio": float(
            ratios.get("structural_page_coverage_ratio") or 0.0
        ),
        "completeness_supported_ratio": float(ratios.get("observation_supported_ratio") or 0.0),
        "completeness_reference_coverage_ratio": float(
            ratios.get("reference_coverage_ratio") or 0.0
        ),
        "completeness_structural_state": str(states.get("structural") or "absent"),
        "completeness_observation_state": str(states.get("observation") or "absent"),
        "completeness_reference_state": str(states.get("reference") or "unavailable"),
        "semantic_shadow_state": str(semantic_shadow.get("semantic_state") or "unavailable"),
        "semantic_shadow_confidence": float(semantic_shadow.get("confidence") or 0.0),
        "semantic_shadow_support_banner": str(semantic_shadow.get("support_banner") or "unknown"),
        "semantic_shadow_structural_gate_pass": int(bool(semantic_shadow.get("structural_gate_pass"))),
        "semantic_shadow_observation_gate_pass": int(
            bool(semantic_shadow.get("observation_gate_pass"))
        ),
        "semantic_shadow_reference_gate_pass": int(bool(semantic_shadow.get("reference_gate_pass"))),
        "semantic_shadow_actionable_findings": int(finding_counts.get("actionable") or 0),
        "semantic_shadow_threshold_conflicts": int(
            finding_counts.get("threshold_conflicts") or 0
        ),
    }


def _json_safe(value: object) -> object:
    if isinstance(value, UUID):
        return str(value)
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


def _normalize_observations(
    observations: list[dict],
    *,
    analyte_resolver: AnalyteResolver,
    ucum_engine: UcumEngine,
) -> list[dict]:
    normalized_observations: list[dict] = []

    for observation in observations:
        updated = dict(observation)
        resolver_result = analyte_resolver.resolve(
            raw_label=updated["raw_analyte_label"],
            context={
                "row_type": updated.get("row_type"),
                "measurement_kind": updated.get("measurement_kind"),
                "family_adapter_id": updated.get("family_adapter_id"),
                "specimen_context": updated.get("specimen_context"),
                "language_id": updated.get("language_id"),
                "raw_unit_string": updated.get("raw_unit_string"),
                "primary_result": updated.get("primary_result"),
                "source_observation_ids": updated.get("source_observation_ids"),
                "derived_formula_id": updated.get("derived_formula_id"),
            },
        )
        updated["candidates"] = resolver_result["candidates"]
        updated["support_state"] = resolver_result["support_state"]
        if "support_code" in resolver_result:
            updated["support_code"] = resolver_result.get("support_code")
        if "failure_code" in resolver_result:
            updated["failure_code"] = resolver_result.get("failure_code")
        updated["candidate_trace"] = resolver_result.get("candidate_trace") or updated.get(
            "candidate_trace"
        )

        accepted_candidate = resolver_result.get("accepted_candidate")
        if accepted_candidate is not None:
            updated["accepted_analyte_code"] = accepted_candidate["candidate_code"]
            updated["accepted_analyte_display"] = accepted_candidate["candidate_display"]

        primary_result = (
            dict(updated["primary_result"])
            if isinstance(updated.get("primary_result"), dict)
            else None
        )
        secondary_result = (
            dict(updated["secondary_result"])
            if isinstance(updated.get("secondary_result"), dict)
            else None
        )

        if primary_result is not None:
            # Keep noisy innoquest unsupported-family rows from degrading
            # support_banner via unit parse errors, but preserve partial
            # behavior for generic unmapped rows (e.g. MysteryMarker).
            if accepted_candidate is None:
                failure_code = str(updated.get("failure_code") or "").lower()
                family_adapter_id = str(updated.get("family_adapter_id") or "").lower()
                if (
                    failure_code == "unsupported_family"
                    and family_adapter_id == "innoquest_bilingual_general"
                ):
                    normalized_observations.append(updated)
                    continue
            try:
                normalized_channels = ucum_engine.normalize_dual_unit_channels(
                    primary_result,
                    secondary_result,
                )
                updated["primary_result"] = normalized_channels["primary_result"]
                updated["secondary_result"] = normalized_channels["secondary_result"]
                updated["canonical_value"] = normalized_channels["canonical_value"]
                updated["canonical_unit"] = normalized_channels["canonical_unit"]
                updated["parsed_numeric_value"] = normalized_channels["primary_result"].get(
                    "normalized_numeric_value"
                )
                updated["parsed_locale"] = _compact_parsed_locale(
                    normalized_channels["primary_result"].get("parse_locale")
                )
                updated["parsed_comparator"] = normalized_channels["primary_result"].get(
                    "normalized_comparator"
                )
                if normalized_channels.get("failure_code") is not None:
                    updated["support_state"] = "partial"
                    updated["support_code"] = normalized_channels.get("support_code")
                    updated["failure_code"] = normalized_channels.get("failure_code")
            except ValueError as exc:
                updated["support_state"] = "partial"
                updated["support_code"] = "partial_result"
                updated["failure_code"] = "unit_parse_fail"
                updated["suppression_reasons"] = sorted(
                    {*(updated.get("suppression_reasons") or []), str(exc)}
                )

        normalized_observations.append(updated)

    return normalized_observations


def _attach_derived_source_links(observations: list[dict]) -> list[dict]:
    observations_by_display: dict[str, list[dict]] = {}
    for observation in observations:
        display = str(observation.get("accepted_analyte_display") or "").strip().lower()
        if display:
            observations_by_display.setdefault(display, []).append(observation)

    def _source_ids(*candidate_labels: str) -> list[UUID]:
        source_ids: list[UUID] = []
        for label in candidate_labels:
            for source_observation in observations_by_display.get(label, []):
                source_id = source_observation.get("id")
                if source_id is None:
                    continue
                if not isinstance(source_id, UUID):
                    source_id = UUID(str(source_id))
                if source_id not in source_ids:
                    source_ids.append(source_id)
        return source_ids

    for observation in observations:
        display = str(observation.get("accepted_analyte_display") or "").strip().lower()
        if display == "egfr":
            source_ids = _source_ids("creatinine")
            if source_ids:
                observation["measurement_kind"] = "derived"
                observation["derived_formula_id"] = (
                    observation.get("derived_formula_id") or "reported_egfr_creatinine_link_v1"
                )
                observation["source_observation_ids"] = source_ids
                observation["candidate_trace"] = [
                    *(observation.get("candidate_trace") or []),
                    {
                        "stage": "derived_source_link",
                        "status": "bound",
                        "detail": "creatinine",
                    },
                ]
        if display == "acr":
            source_ids = _source_ids("urine albumin", "urine creatinine")
            if source_ids:
                observation["measurement_kind"] = "derived"
                observation["derived_formula_id"] = (
                    observation.get("derived_formula_id") or "reported_acr_ratio_link_v1"
                )
                observation["source_observation_ids"] = source_ids
                observation["candidate_trace"] = [
                    *(observation.get("candidate_trace") or []),
                    {
                        "stage": "derived_source_link",
                        "status": "bound",
                        "detail": "urine_albumin+urine_creatinine",
                    },
                ]

    return observations


def _attach_reference_decisions(
    observations: list[dict],
    reference_decisions: dict[str, dict],
) -> list[dict]:
    for observation in observations:
        observation_id = str(observation.get("id") or observation.get("row_hash") or "")
        if not observation_id:
            continue
        decision = reference_decisions.get(observation_id)
        if decision is None:
            continue
        observation["reference_decision"] = decision
    return observations


def _support_banner(observations: list[dict]) -> str:
    def _normalized_state(observation: dict) -> str:
        return str(observation.get("support_state") or "").lower()

    def _ignorable_for_banner(observation: dict) -> bool:
        state = _normalized_state(observation)
        failure_code = str(observation.get("failure_code") or "").lower()
        if state == "unsupported" and failure_code == "derived_observation_unbound":
            return True
        return False

    support_states = {
        _normalized_state(observation)
        for observation in observations
        if not _ignorable_for_banner(observation)
    }
    support_states.discard("")

    if not support_states:
        return "could_not_assess"

    if support_states == {"supported"}:
        return "fully_supported"
    if "supported" in support_states:
        return "partially_supported"
    return "could_not_assess"


def _support_banner_from_runtime(
    observations: list[dict],
    findings: list[dict],
    comparable_history: dict | None,
) -> str:
    baseline = _support_banner(observations)
    threshold_conflicts = [
        finding
        for finding in findings
        if str(finding.get("suppression_reason") or "") == "threshold_conflict"
    ]
    if threshold_conflicts:
        actionable_findings = [
            finding
            for finding in findings
            if not finding.get("suppression_active")
            and str(finding.get("severity_class") or "") not in {"S0", "SX"}
        ]
        if actionable_findings:
            baseline = "partially_supported"
        else:
            baseline = "could_not_assess"

    return baseline


def _is_launch_scope_kidney_unit(raw_unit_string: object) -> bool:
    normalized = " ".join(str(raw_unit_string or "").strip().lower().split())
    return normalized in {
        "ml/min/1.73 m2",
        "ml/min/1.73 m^2",
        "ml/min/1.73 m²",
    }


