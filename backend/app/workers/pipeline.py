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
12. structured patient artifact renders
13. clinician-share artifact renders
14. lineage and benchmark telemetry persist
"""

from __future__ import annotations

import logging
from time import perf_counter
from hashlib import sha256
from enum import Enum
from uuid import UUID, NAMESPACE_URL, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import TopLevelLifecycleStore
from app.schemas.artifact import SupportBanner, TrustStatus
from app.services.analyte_resolver import AnalyteResolver
from app.services.artifact_renderer import ArtifactRenderer
from app.services.benchmark import BenchmarkRecorder
from app.services.extraction_qa import ExtractionQA
from app.services.lineage import LineageLogger
from app.services.nextstep_policy import NextStepPolicyEngine
from app.services.observation_builder import ObservationBuilder
from app.services.ocr import OcrAdapter
from app.services.panel_reconstructor import PanelReconstructor
from app.services.parser import TrustedPdfParser
from app.services.rule_engine import RuleEngine
from app.services.severity_policy import SeverityPolicyEngine
from app.services.ucum import UcumEngine


_JOB_RUNS: dict[str, dict] = {}
_LOGGER = logging.getLogger(__name__)
_SUPPORTED_LANES = {"trusted_pdf", "image_beta"}


class PipelineStep(str, Enum):
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
    ) -> dict:
        job_uuid = _job_uuid(job_id)
        document_uuid = (
            document_id if isinstance(document_id, UUID) else UUID(str(document_id))
        ) if document_id is not None else job_uuid
        selected_lane = lane_type or "trusted_pdf"
        _LOGGER.info(
            "pipeline_start job_id=%s lane=%s",
            job_id,
            selected_lane,
        )
        patient_context = {
            "patient_id": str(uuid5(NAMESPACE_URL, f"patient:{job_id}")),
            "age_years": 42,
            "sex": "female",
            "language_id": "en",
        }

        extraction_qa = ExtractionQA()
        observation_builder = ObservationBuilder()
        analyte_resolver = AnalyteResolver()
        ucum_engine = UcumEngine()
        panel_reconstructor = PanelReconstructor()
        rule_engine = RuleEngine()
        severity_policy = SeverityPolicyEngine()
        nextstep_policy = NextStepPolicyEngine()
        artifact_renderer = ArtifactRenderer()
        lineage_logger = LineageLogger()
        benchmark_recorder = BenchmarkRecorder()
        processing_start = perf_counter()

        try:
            _validate_lane(selected_lane)
            extraction_start = perf_counter()
            extracted_rows = await _extract_rows(
                job_uuid,
                file_bytes=file_bytes,
                lane_type=selected_lane,
            )
            extraction_ms = int((perf_counter() - extraction_start) * 1000)
            qa_result = extraction_qa.validate(extracted_rows)
            observations = observation_builder.build(qa_result["clean_rows"])
            normalized_observations = _normalize_observations(
                observations,
                analyte_resolver=analyte_resolver,
                ucum_engine=ucum_engine,
            )
            panels = panel_reconstructor.reconstruct(normalized_observations)
            findings = rule_engine.evaluate(normalized_observations, patient_context)
            findings = severity_policy.assign(findings, patient_context)
            findings = nextstep_policy.assign(findings, patient_context)

            render_context = {
                "job_id": job_uuid,
                "language_id": patient_context["language_id"],
                "support_banner": SupportBanner(_support_banner(normalized_observations)),
                "trust_status": (
                    TrustStatus.NON_TRUSTED_BETA
                    if selected_lane == "image_beta"
                    else TrustStatus.TRUSTED
                ),
                "report_date": "2026-04-10",
            }
            patient_artifact = artifact_renderer.render_patient(findings, render_context)
            clinician_artifact = artifact_renderer.render_clinician(findings, render_context)
            lineage = lineage_logger.record(
                str(job_uuid),
                {
                    "source_checksum": source_checksum or f"source:{job_id}",
                    "parser_version": "trusted-pdf-v1" if selected_lane == "trusted_pdf" else "image-beta-bypass",
                    "ocr_version": "beta-adapter-v1" if selected_lane == "image_beta" else None,
                    "terminology_release": "seeded-demo-2026-04-10",
                    "mapping_threshold_config": {"default": 0.9},
                    "unit_engine_version": "ucum-v1",
                    "rule_pack_version": "rules-v1",
                    "severity_policy_version": "severity-v1",
                    "nextstep_policy_version": "nextstep-v1",
                    "template_version": "templates-v1",
                    "model_version": None,
                    "build_commit": "local-dev",
                },
            )
            processing_ms = int((perf_counter() - processing_start) * 1000)
            benchmark = benchmark_recorder.record(
                lineage_id=str(lineage["id"]),
                report_type="truth_engine_seeded_pipeline",
                metrics={
                    "extracted_rows": len(extracted_rows),
                    "clean_rows": len(qa_result["clean_rows"]),
                    "findings": len(findings),
                    "panels": len(panels),
                    "extraction_ms": extraction_ms,
                    "processing_ms": processing_ms,
                },
            )

            result = {
                "job_id": job_id,
                "status": (
                    "completed"
                    if qa_result["passed"] and _support_banner(normalized_observations) == "fully_supported"
                    else "partial"
                ),
                "lane_type": selected_lane,
                "qa": qa_result,
                "observations": normalized_observations,
                "panels": panels,
                "findings": findings,
                "patient_artifact": patient_artifact,
                "clinician_artifact": clinician_artifact,
                "lineage": lineage,
                "benchmark": benchmark,
            }

            if db_session is not None:
                store = TopLevelLifecycleStore(db_session)
                persisted_patient_artifact = _json_safe(patient_artifact)
                persisted_clinician_artifact = _json_safe(clinician_artifact)
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
                    status=result["status"],
                    patient_artifact={
                        "language_id": patient_artifact["language_id"],
                        "support_banner": patient_artifact["support_banner"],
                        "content": persisted_patient_artifact,
                        "template_version": "templates-v1",
                    },
                    clinician_artifact={
                        "content": persisted_clinician_artifact,
                        "template_version": "templates-v1",
                    },
                    lineage_run={
                        "source_checksum": lineage["source_checksum"],
                        "parser_version": lineage["parser_version"],
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
                    benchmark_run={
                        "report_type": benchmark["report_type"],
                        "metrics": benchmark["metrics"],
                    },
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


def _seed_extracted_rows(document_id: UUID) -> list[dict]:
    return [
        {
            "document_id": document_id,
            "source_page": 1,
            "row_hash": "row-glucose",
            "raw_text": "Glucose 180 mg/dL",
            "raw_analyte_label": "Glucose",
            "raw_value_string": "180",
            "raw_unit_string": "mg/dL",
            "raw_reference_range": "70-99",
            "parsed_numeric_value": 180.0,
            "specimen_context": "serum",
            "language_id": "en",
            "extraction_confidence": 0.99,
        },
        {
            "document_id": document_id,
            "source_page": 1,
            "row_hash": "row-hba1c",
            "raw_text": "HbA1c 6.8 %",
            "raw_analyte_label": "HbA1c",
            "raw_value_string": "6.8",
            "raw_unit_string": "%",
            "raw_reference_range": "<5.7",
            "parsed_numeric_value": 6.8,
            "specimen_context": "blood",
            "language_id": "en",
            "extraction_confidence": 0.98,
        },
    ]


async def _extract_rows(
    job_uuid: UUID,
    *,
    file_bytes: bytes | None,
    lane_type: str,
) -> list[dict]:
    if file_bytes is None:
        _validate_lane(lane_type)
        return _seed_extracted_rows(job_uuid)

    if lane_type == "trusted_pdf":
        return await TrustedPdfParser().parse(file_bytes, max_pages=settings.max_pdf_pages)

    if lane_type == "image_beta":
        return await OcrAdapter(
            image_beta_enabled=settings.image_beta_enabled,
        ).extract(
            file_bytes,
            document_id=job_uuid,
            language_id="en",
        )

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
            severity_policy_version="severity-v1",
            nextstep_policy_version="nextstep-v1",
            suppression_active=bool(finding.get("suppression_active", False)),
            suppression_reason=finding.get("suppression_reason"),
        )
        row_level_counts["policy_events"] += 1

    return row_level_counts


def _enum_value(value: object) -> object:
    if hasattr(value, "value"):
        return value.value
    return value


def _stable_identifier(value: str, *, max_length: int = 64) -> str:
    if len(value) <= max_length:
        return value
    digest = sha256(value.encode("utf-8")).hexdigest()[:32]
    prefix = value.split("::", 1)[0] if "::" in value else "id"
    return f"{prefix}::{digest}"


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
                "specimen_context": updated.get("specimen_context"),
                "language_id": updated.get("language_id"),
            },
        )
        updated["candidates"] = resolver_result["candidates"]
        updated["support_state"] = resolver_result["support_state"]

        accepted_candidate = resolver_result.get("accepted_candidate")
        if accepted_candidate is not None:
            updated["accepted_analyte_code"] = accepted_candidate["candidate_code"]
            updated["accepted_analyte_display"] = accepted_candidate["candidate_display"]

        parsed_numeric_value = updated.get("parsed_numeric_value")
        raw_value_string = updated.get("raw_value_string")
        numeric_value = parsed_numeric_value
        if numeric_value is None and raw_value_string not in (None, ""):
            numeric_value = float(str(raw_value_string))
            updated["parsed_numeric_value"] = numeric_value

        raw_unit_string = updated.get("raw_unit_string")
        if numeric_value is not None and raw_unit_string:
            if _is_launch_scope_kidney_unit(raw_unit_string):
                updated["canonical_value"] = float(numeric_value)
                updated["canonical_unit"] = str(raw_unit_string)
            else:
                try:
                    conversion = ucum_engine.validate_and_convert(
                        float(numeric_value),
                        str(raw_unit_string),
                        str(raw_unit_string),
                    )
                    updated["canonical_value"] = conversion["canonical_value"]
                    updated["canonical_unit"] = conversion["canonical_unit"]
                except ValueError as exc:
                    updated["support_state"] = "partial"
                    updated["suppression_reasons"] = sorted(
                        {*(updated.get("suppression_reasons") or []), str(exc)}
                    )

        normalized_observations.append(updated)

    return normalized_observations


def _support_banner(observations: list[dict]) -> str:
    support_states = {str(observation.get("support_state") or "").lower() for observation in observations}
    if support_states == {"supported"}:
        return "fully_supported"
    if "supported" in support_states:
        return "partially_supported"
    return "could_not_assess"


def _is_launch_scope_kidney_unit(raw_unit_string: object) -> bool:
    normalized = " ".join(str(raw_unit_string or "").strip().lower().split())
    return normalized in {
        "ml/min/1.73 m2",
        "ml/min/1.73 m^2",
        "ml/min/1.73 m²",
    }
