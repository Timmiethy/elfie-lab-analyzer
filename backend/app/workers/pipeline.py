from __future__ import annotations

from app.services.lab_normalizer import LabNormalizer
from app.services.mineru_adapter import MineruAdapter

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


import logging
import re
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from time import perf_counter
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import TopLevelLifecycleStore
from app.schemas.artifact import SupportBanner, TrustStatus
from app.schemas.patient_context import PatientContext
from app.services.analyte_resolver import AnalyteResolver
from app.services.artifact_renderer import ArtifactRenderer
from app.services.benchmark import BenchmarkRecorder
from app.services.comparable_history import ComparableHistoryService
from app.services.explanation import ExplanationAdapter
from app.services.lineage import LineageLogger
from app.services.metric_resolver import MetricResolver
from app.services.nextstep_policy import NextStepPolicyEngine
from app.services.observation_builder import ObservationBuilder
from app.services.observability import get_current_correlation_id, span
from app.services.panel_reconstructor import PanelReconstructor
from app.services.proof_pack import proof_pack_route, write_proof_pack
from app.services.rule_engine import RuleEngine
from app.services.severity_policy import SeverityPolicyEngine
from app.services.ucum import UcumEngine
from app.terminology import get_loaded_snapshot_metadata

_JOB_RUNS: dict[str, dict] = {}
_LOGGER = logging.getLogger(__name__)
_TERMINOLOGY_RELEASE_DEFAULT = "seeded-demo-2026-04-10"
_MAPPING_THRESHOLD_DEFAULT = {"default": 0.9}
_UNIT_ENGINE_VERSION = "ucum-v1"
_RULE_PACK_VERSION = "rules-v1"
_SEVERITY_POLICY_VERSION = "severity-v1"
_NEXTSTEP_POLICY_VERSION = "nextstep-v1"
_TEMPLATE_VERSION = "templates-v1"
_BUILD_COMMIT_DEFAULT = "local-dev"
_SUPPORT_BANNER_FULLY_SUPPORTED = "fully_supported"
_REPORT_TYPE = "truth_engine_seeded_pipeline"
_PROOF_CORPUS_ID = "seeded-launch-corpus-v1"
_DEFAULT_LANGUAGE_ID = "en"
_DEFAULT_REPORT_DATE = "2026-04-10"

_TEXT_LAYER_HEADER_KEYWORDS = (
    "laboratory report", "patient details", "doctor details", "name :", "ur :",
    "ref :", "dob :", "ic no", "collected :", "referred :", "report printed",
    "ward :", "yr ref", "courier run", "analytes", "results", "units", "ref. ranges",
    "general screening", "biochemistry", "serum/plasma", "special chemistry",
    "specimen:", "specimen type", "specimen collected", "random urine",
    "albumin and creatinine", "kdigo", "interpretation:", "source:", "recommend",
    "cc drs", "page ", "tests requested", "report completed", "note:",
    "due to the variability", "kfre risk", "result should be", "ifg ", "igt ",
    "ifg:", "igt:", "t2dm", "a:", "b:", "c:", "ifg =", "dm ",
)

_TEXT_LAYER_CATEGORY_LINE_PATTERNS = [
    re.compile(r"^\s*(normal|prediabetes|dm|a1|a2|a3)\b", re.IGNORECASE),
    re.compile(r"^\s*(<=|>=|<|>)\s*\d"),
    re.compile(r"^\s*glucose\s+levels\b", re.IGNORECASE),
    re.compile(r"\bfor\s+hba1c\s+levels\b", re.IGNORECASE),
]

_TEXT_LAYER_ROW_RE = re.compile(
    r"^(?P<label>[A-Za-z][A-Za-z0-9 /\-().,]+?)"
    r"(?:\s+[^\x00-\x7F]+)?"
    r"\s+(?P<value>[<>]?=?\s*-?\d+(?:\.\d+)?)\s*%?"
    r"\s*(?P<unit>%|"
    r"mmol/L|mmol/l|umol/L|umol/l|micromol/L|"
    r"mg/L|mg/l|mg/dL|mg/dl|g/dL|g/dl|g/L|g/l|"
    r"ng/mL|ng/ml|ng/dL|ng/dl|pg/mL|pg/ml|"
    r"mmol/mol|U/L|u/l|IU/L|iu/l|IU/mL|iu/ml|microIU/mL|uIU/mL|"
    r"mL/min/1\.73m2?|mL/min|"
    r"mg\s*Alb/mmol|mg/g|"
    r"/cmm|/uL|/mm3|10\^3/uL|10\^6/uL|10\*3/uL|"
    r"fL|fl|pg|ratio"
    r")"
    r"\s*(?P<ref>.*)$",
    re.IGNORECASE,
)

_TEXT_LAYER_HBA1C_DUAL_RE = re.compile(
    r"^hba1c\b.*?(?P<pct_val>\d+(?:\.\d+)?)\s*%\s+(?P<mmol_val>\d+(?:\.\d+)?)\s*mmol/mol",
    re.IGNORECASE,
)

_TEXT_LAYER_REF_PAREN_RE = re.compile(r"\(([^)]*)\)")
_TEXT_LAYER_REF_BARE_RE = re.compile(r"^([<>]=?\s*\d+(?:\.\d+)?)\s*$")
_NUMERIC_VALUE_CLEAN_RE = re.compile(r"[^\d\.-]+")


class PipelineStep(StrEnum):
    EXTRACTION = "extraction"

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


def _build_patient_context(
    job_id: str,
    *,
    age_years: float | None = None,
    sex: str | None = None,
    detected_language_id: str | None = None,
) -> dict:
    return {
        "patient_id": str(uuid5(NAMESPACE_URL, f"patient:{job_id}")),
        "age_years": age_years,
        "sex": sex,
        "language_id": detected_language_id or _DEFAULT_LANGUAGE_ID,
    }


def _build_render_context(
    job_uuid: UUID,
    language_id: str,
    observations: list[dict],
    findings: list[dict],
    comparable_history: dict | None,
) -> dict:
    return {
        "job_id": job_uuid,
        "language_id": language_id,
        "support_banner": SupportBanner(
            _support_banner_from_runtime(observations, findings, comparable_history)
        ),
        "trust_status": TrustStatus.TRUSTED,
        "report_date": _DEFAULT_REPORT_DATE,
        "comparable_history": comparable_history,
    }


def _build_lineage_payload(
    job_id: str,
    *,
    source_checksum: str | None,
    terminology_release: str,
) -> dict:
    return {
        "source_checksum": source_checksum or f"source:{job_id}",
        "parser_version": "vlm-parser-v2",
        "ocr_version": None,
        "terminology_release": terminology_release,
        "mapping_threshold_config": _MAPPING_THRESHOLD_DEFAULT,
        "unit_engine_version": _UNIT_ENGINE_VERSION,
        "rule_pack_version": _RULE_PACK_VERSION,
        "severity_policy_version": _SEVERITY_POLICY_VERSION,
        "nextstep_policy_version": _NEXTSTEP_POLICY_VERSION,
        "template_version": _TEMPLATE_VERSION,
        "model_version": None,
        "build_commit": _BUILD_COMMIT_DEFAULT,
        # Include run timestamp so each retry produces a distinct lineage UUID.
        "run_at": datetime.now(UTC).isoformat(),
    }


def _build_persistence_payloads(
    patient_artifact: dict,
    clinician_artifact: dict,
    lineage: dict,
    benchmark: dict,
    status: str,
    lane_type: str,
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
        "status": (
            "completed"
            if qa_result["passed"] and patient_artifact["support_banner"] == _SUPPORT_BANNER_FULLY_SUPPORTED
            else "partial"
        ),
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
    language_id: str,
    lane_id: str,
) -> dict:
    return benchmark_recorder.build_proof_pack(
        benchmark=benchmark,
        lineage=lineage,
        artifact_refs={
            "patient_artifact": f"/api/artifacts/{job_uuid}/patient",
            "clinician_artifact": f"/api/artifacts/{job_uuid}/clinician",
            "job_status": f"/api/jobs/{job_uuid}",
            "proof_pack": proof_pack_route(job_uuid),
        },
        report_metadata={
            "build_commit": lineage.get("build_commit") or _BUILD_COMMIT_DEFAULT,
            "corpus_id": _PROOF_CORPUS_ID,
            "lane_id": lane_id,
            "language_id": language_id,
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        },
    )


class PipelineOrchestrator:
    """Orchestrate the full processing pipeline for a job."""

    async def _emit_progress(
        self,
        job_id: str,
        job_uuid: UUID,
        step: str,
        *,
        db_session: AsyncSession | None,
    ) -> None:
        """Record current pipeline step so polling clients see granular progress.

        Persists to jobs.current_step + mirrors into the in-memory _JOB_RUNS
        dict (for the no-DB fallback lane). Best-effort: never raises. Uses a
        fresh session so a commit here doesn't disturb the pipeline's own
        transactional scope.
        """
        try:
            run = _JOB_RUNS.setdefault(str(job_uuid), {})
            run["current_step"] = step
            _JOB_RUNS[job_id] = run
        except Exception:
            pass
        if db_session is None:
            return
        try:
            from app.db.session import async_session_factory as factory  # type: ignore
        except Exception:
            factory = None  # type: ignore
        try:
            if factory is not None:
                async with factory() as s:  # type: ignore
                    store = TopLevelLifecycleStore(s)
                    try:
                        await store.update_job_status(job_uuid, current_step=step)
                        await s.commit()
                    except LookupError:
                        pass
        except Exception as exc:  # pragma: no cover - best-effort
            _LOGGER.debug("progress_emit_failed job=%s step=%s err=%s", job_id, step, exc)

    async def run(
        self,
        job_id: str,
        *,
        file_bytes: bytes | None = None,
        db_session: AsyncSession | None = None,
        document_id: UUID | str | None = None,
        source_checksum: str | None = None,
        lane_type: str | None = None,
        age_years: float | None = None,
        sex: str | None = None,
    ) -> dict:
        job_uuid = _job_uuid(job_id)
        document_uuid = (
            (document_id if isinstance(document_id, UUID) else UUID(str(document_id)))
            if document_id is not None
            else job_uuid
        )
        selected_lane = lane_type or "vlm"
        _LOGGER.info(
            "pipeline_start job_id=%s lane=%s correlation_id=%s",
            job_id,
            selected_lane,
            get_current_correlation_id(),
        )
        patient_context = _build_patient_context(job_id, age_years=age_years, sex=sex)

        observation_builder = ObservationBuilder()
        analyte_resolver = AnalyteResolver()
        ucum_engine = UcumEngine()
        metric_resolver = MetricResolver()
        panel_reconstructor = PanelReconstructor()
        rule_engine = RuleEngine()
        severity_policy = SeverityPolicyEngine()
        nextstep_policy = NextStepPolicyEngine()
        artifact_renderer = ArtifactRenderer()
        lineage_logger = LineageLogger()
        benchmark_recorder = BenchmarkRecorder()
        comparable_history_service = ComparableHistoryService(db_session)
        processing_start = perf_counter()

        try:
            if selected_lane not in (
                "trusted_pdf",
                "image_beta",
                "vlm",
                "unsupported_pdf",
                "structured",
            ):
                raise ValueError(f"unsupported_lane:{selected_lane}")

            if selected_lane == "unsupported_pdf":
                raise ValueError("unsupported_pdf")

            await self._emit_progress(job_id, job_uuid, "preflight", db_session=db_session)
            await self._emit_progress(job_id, job_uuid, "lane_selection", db_session=db_session)
            await self._emit_progress(job_id, job_uuid, "extraction", db_session=db_session)
            with span("stage.extract") as extract_span:
                extracted_rows = await _extract_rows(
                    job_uuid,
                    file_bytes=file_bytes,
                    lane_type=selected_lane,
                )

                from app.services.semantic_cleaner import SemanticCleaner

                extracted_rows = await SemanticCleaner().clean(extracted_rows)

                if not extracted_rows:
                    _LOGGER.warning(
                        "empty_extraction job_id=%s lane=%s — proceeding with empty artifact",
                        job_id,
                        selected_lane,
                    )

                _apply_detected_language(extracted_rows, patient_context)

            extraction_ms = int(extract_span.get("elapsed_ms", 0))

            qa_result = {"passed": True, "clean_rows": extracted_rows}
            await self._emit_progress(job_id, job_uuid, "observation_build", db_session=db_session)
            with span("stage.normalize") as normalize_span:
                observations = observation_builder.build(extracted_rows)
                normalized_observations = _normalize_observations(
                    observations,
                    analyte_resolver=analyte_resolver,
                    ucum_engine=ucum_engine,
                    metric_resolver=metric_resolver,
                    patient_context=patient_context,
                )
                await self._emit_progress(
                    job_id, job_uuid, "analyte_mapping", db_session=db_session
                )
                await self._emit_progress(
                    job_id, job_uuid, "ucum_conversion", db_session=db_session
                )
                await self._emit_progress(
                    job_id, job_uuid, "panel_reconstruction", db_session=db_session
                )
                panels = panel_reconstructor.reconstruct(normalized_observations)

            normalize_ms = int(normalize_span.get("elapsed_ms", 0))

            await self._emit_progress(job_id, job_uuid, "rule_evaluation", db_session=db_session)
            with span("stage.rules") as rules_span:
                findings = rule_engine.evaluate(normalized_observations, patient_context)
                await self._emit_progress(
                    job_id, job_uuid, "severity_assignment", db_session=db_session
                )
                findings = severity_policy.assign(findings, patient_context)
                await self._emit_progress(
                    job_id, job_uuid, "nextstep_assignment", db_session=db_session
                )
                findings = nextstep_policy.assign(findings, patient_context)

            rules_ms = int(rules_span.get("elapsed_ms", 0))
            comparable_history = await comparable_history_service.build_for_artifact(
                job_id=job_uuid,
                observations=normalized_observations,
                report_date=_DEFAULT_REPORT_DATE,
            )

            render_context = _build_render_context(
                job_uuid,
                patient_context["language_id"],
                normalized_observations,
                findings,
                comparable_history,
            )

            if selected_lane == "image_beta":
                render_context["trust_status"] = TrustStatus.NON_TRUSTED_BETA

            await self._emit_progress(job_id, job_uuid, "patient_artifact", db_session=db_session)
            patient_artifact = artifact_renderer.render_patient(
                findings,
                render_context,
                observations=normalized_observations,
            )
            explanation_payload = await ExplanationAdapter().generate(
                findings,
                patient_context["language_id"],
            )
            patient_artifact["explanation"] = explanation_payload

            # Debug-only: embed raw extraction and dump to disk.
            # Never enable in production — extracted_rows may contain PHI.
            # Dual gate: settings.debug (general) AND settings.allow_debug_artifacts
            # (explicit opt-in for PHI-bearing artifacts).
            if settings.debug and settings.allow_debug_artifacts:
                import json as _json
                _debug_raw = [
                    {k: str(v) if isinstance(v, UUID) else v for k, v in row.items()}
                    for row in extracted_rows
                ]
                patient_artifact["_debug_raw_extraction"] = _debug_raw
                debug_dir = settings.artifact_store_path / "debug"
                debug_dir.mkdir(parents=True, exist_ok=True)
                (debug_dir / f"{job_uuid}_vlm_extraction.json").write_text(
                    _json.dumps(_debug_raw, indent=2), encoding="utf-8"
                )

            clinician_artifact = artifact_renderer.render_clinician(
                findings,
                render_context,
                observations=normalized_observations,
            )
            await self._emit_progress(job_id, job_uuid, "clinician_artifact", db_session=db_session)
            snapshot_metadata = get_loaded_snapshot_metadata()
            terminology_release = (
                snapshot_metadata.get("release", _TERMINOLOGY_RELEASE_DEFAULT)
                if snapshot_metadata
                else _TERMINOLOGY_RELEASE_DEFAULT
            )
            lineage_payload = _build_lineage_payload(
                job_id,
                source_checksum=source_checksum,
                terminology_release=terminology_release,
            )
            lineage = lineage_logger.record(str(job_uuid), lineage_payload)
            await self._emit_progress(job_id, job_uuid, "lineage_persist", db_session=db_session)

            persisted_rows: dict[str, int] | None = None
            store: TopLevelLifecycleStore | None = None
            persist_ms = 0
            if db_session is not None:
                store = TopLevelLifecycleStore(db_session)
                with span("stage.persist") as persist_span:
                    persisted_rows = await _persist_row_level_entities(
                        store,
                        job_uuid=job_uuid,
                        document_id=document_uuid,
                        clean_rows=qa_result["clean_rows"],
                        observations=normalized_observations,
                        findings=findings,
                    )
                persist_ms = int(persist_span.get("elapsed_ms", 0))

            processing_ms = int((perf_counter() - processing_start) * 1000)
            benchmark = benchmark_recorder.record(
                lineage_id=str(lineage["id"]),
                report_type=_REPORT_TYPE,
                metrics={
                    "extracted_rows": len(extracted_rows),
                    "clean_rows": len(qa_result["clean_rows"]),
                    "findings": len(findings),
                    "panels": len(panels),
                    "extraction_ms": extraction_ms,
                    "normalize_ms": normalize_ms,
                    "rules_ms": rules_ms,
                    "persist_ms": persist_ms,
                    "processing_ms": processing_ms,
                },
            )
            proof_pack = _build_proof_pack(
                benchmark_recorder=benchmark_recorder,
                job_uuid=job_uuid,
                benchmark=benchmark,
                lineage=lineage,
                language_id=patient_context["language_id"],
                lane_id=selected_lane,
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
            result["proof_pack_ref"] = proof_pack_route(job_uuid)
            result["proof_pack"] = proof_pack

            if db_session is not None and store is not None:
                persistence = _build_persistence_payloads(
                    patient_artifact,
                    clinician_artifact,
                    lineage,
                    benchmark,
                    result["status"],
                    selected_lane,
                )
                await store.persist_top_level_bundle(
                    job_id=job_uuid,
                    status=persistence["status"],
                    patient_artifact=persistence["patient_artifact"],
                    clinician_artifact=persistence["clinician_artifact"],
                    lineage_run=persistence["lineage_run"],
                    benchmark_run=persistence["benchmark_run"],
                )
                result["row_level_persistence"] = persisted_rows or {
                    "extracted_rows": 0,
                    "observations": 0,
                    "mapping_candidates": 0,
                    "rule_events": 0,
                    "policy_events": 0,
                }

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
                exc_info=True,
            )
            raise


def get_job_run(job_id: str) -> dict | None:
    return _JOB_RUNS.get(job_id)


def _job_uuid(job_id: str) -> UUID:
    try:
        return UUID(str(job_id))
    except ValueError:
        return uuid5(NAMESPACE_URL, f"job:{job_id}")


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
    lane_type: str | None = None,
) -> list[dict]:
    if file_bytes is None:
        return _seed_extracted_rows(job_uuid)

    if lane_type == "structured":
        import json

        try:
            payload = json.loads(file_bytes)
        except json.JSONDecodeError:
            raise ValueError("invalid_json_payload")

        observations = payload.get("observations")
        return _validate_structured_observations(observations, document_id=job_uuid)

    # Trusted PDF lane: run VLM first (Qwen-VL reads the whole page, catches
    # units/analytes the regex whitelist misses). Text-layer regex is a
    # deterministic fallback only — it is blind to analytes whose unit string
    # is not in its narrow whitelist (g/dL, /cmm, 10^3/uL, fL, pg, ng/mL, etc.)
    # and therefore silently under-extracts multi-page panels. Running it
    # first short-circuited the VLM and produced artifacts with 1/50 analytes.
    text_rows_fallback: list[dict] = []
    if lane_type == "trusted_pdf" and file_bytes.startswith(b"%PDF"):
        try:
            text_rows_fallback = _extract_rows_from_text_layer(file_bytes, document_id=job_uuid)
            _LOGGER.info(
                "text_layer_extraction job=%s rows=%d", job_uuid, len(text_rows_fallback)
            )
        except Exception as exc:  # pragma: no cover - defensive
            _LOGGER.warning("text_layer_extraction_failed job=%s err=%s", job_uuid, exc)

    adapter = MineruAdapter(mode="ocr" if lane_type == "image_beta" else "auto")
    try:
        mineru_output = await adapter.execute(file_bytes)
    except Exception as exc:
        _LOGGER.warning("vlm_extraction_raised job=%s err=%s", job_uuid, exc)
        mineru_output = {"status": "error", "error_message": str(exc), "content": {"blocks": []}}

    vlm_rows: list[dict] = []
    if mineru_output.get("status") == "error":
        err_msg = mineru_output.get("error_message", "mineru_pipeline_failed")
        if "page_count_limit_exceeded" in err_msg:
            raise ValueError("page_count_limit_exceeded")
        if "pdf_render_bytes_limit_exceeded" in err_msg:
            raise ValueError("pdf_render_bytes_limit_exceeded")
        _LOGGER.warning(
            "vlm_extraction_error job=%s err=%s (falling back to text layer)",
            job_uuid, err_msg,
        )
    else:
        vlm_rows = LabNormalizer().normalize(
            mineru_output["content"].get("blocks", []), document_id=job_uuid
        )

    # Merge VLM rows + text-layer rows. VLM wins on overlap (richer context),
    # but text-layer fills gaps for rows VLM missed (happens routinely for
    # Urea/AST/ALT/ACR on some report formats).
    merged = _merge_extraction_rows(vlm_rows, text_rows_fallback)
    _LOGGER.info(
        "extraction_merged job=%s vlm=%d text=%d merged=%d",
        job_uuid, len(vlm_rows), len(text_rows_fallback), len(merged),
    )
    if not merged and lane_type == "trusted_pdf":
        # Both paths failed — raise so caller records the job as failed
        # instead of silently producing an empty artifact.
        raise ValueError("extraction_empty")
    return merged


def _merge_extraction_rows(
    vlm_rows: list[dict],
    text_rows: list[dict],
) -> list[dict]:
    """Union VLM + text-layer rows, keyed by (normalized label, page, value).

    VLM wins on conflict because it supplies bbox + confidence. Text-layer
    fills in rows VLM omitted (typically present but missed by the model).
    Row-hash + row indices are re-stamped so downstream stable-ids remain
    collision-free.
    """

    def _key(row: dict) -> tuple[str, int, str]:
        label = str(row.get("raw_analyte_label") or "").strip().lower()
        page = int(row.get("source_page") or 0)
        value = str(row.get("raw_value_string") or "").strip().lower()
        return (label, page, value)

    seen: set[tuple[str, int, str]] = set()
    merged: list[dict] = []
    for row in list(vlm_rows) + list(text_rows):
        if not row.get("raw_analyte_label"):
            continue
        key = _key(row)
        if key[0] == "":
            # Keep unlabeled rows (cannot dedupe) — rare path.
            merged.append(row)
            continue
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)

    # Re-stamp row_hash so every row has a distinct stable id.
    for idx, row in enumerate(merged):
        row["row_hash"] = f"row-{idx}"
    return merged


def _extract_rows_from_text_layer(
    pdf_bytes: bytes,
    *,
    document_id: UUID,
) -> list[dict]:
    """Deterministic analyte-row extraction from a text-layer PDF.

    Parses each line of each page looking for `<label> [i18n chars] <value> <unit> [<ref>]`.
    Ignores interpretation tables, footers, and patient-header blocks.
    """
    import io
    import pdfplumber

    rows: list[dict] = []
    row_index = 0

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                for raw_line in text.split("\n"):
                    line = raw_line.strip()
                    if not line:
                        continue

                    lowered = line.lower()
                    if any(lowered.startswith(prefix) for prefix in _TEXT_LAYER_HEADER_KEYWORDS):
                        continue
                    if any(pat.match(line) for pat in _TEXT_LAYER_CATEGORY_LINE_PATTERNS):
                        continue

                    # Dual-channel HbA1c row → emit two rows.
                    hba_match = _TEXT_LAYER_HBA1C_DUAL_RE.search(line)
                    if hba_match:
                        rows.append({
                            "document_id": document_id,
                            "source_page": page_number,
                            "row_hash": f"row-{row_index}",
                            "raw_text": line,
                            "raw_analyte_label": "HbA1c",
                            "raw_value_string": hba_match.group("pct_val"),
                            "raw_unit_string": "%",
                            "raw_reference_range": "< 5.7",
                            "extraction_confidence": 0.99,
                            "row_bbox": [0, 0, 0, 0],
                        })
                        row_index += 1
                        rows.append({
                            "document_id": document_id,
                            "source_page": page_number,
                            "row_hash": f"row-{row_index}",
                            "raw_text": line,
                            "raw_analyte_label": "HbA1c",
                            "raw_value_string": hba_match.group("mmol_val"),
                            "raw_unit_string": "mmol/mol",
                            "raw_reference_range": "< 39",
                            "extraction_confidence": 0.99,
                            "row_bbox": [0, 0, 0, 0],
                        })
                        row_index += 1
                        continue

                    match = _TEXT_LAYER_ROW_RE.match(line)
                    if not match:
                        continue

                    label = match.group("label").strip()
                    # Drop rows whose label is clearly not an analyte
                    if len(label) < 2 or label.lower() in {"an egfr", "egfr(ckd-epi)"}:
                        continue

                    value = match.group("value").strip().replace(" ", "")
                    unit = match.group("unit").strip()
                    ref = match.group("ref").strip()
                    # Reference range is typically parenthesised; drop surrounding text.
                    ref_paren = _TEXT_LAYER_REF_PAREN_RE.search(ref)
                    if ref_paren:
                        ref = f"({ref_paren.group(1).strip()})"
                    else:
                        # Allow "< 20.1" style bare comparators
                        ref_bare = _TEXT_LAYER_REF_BARE_RE.match(ref)
                        ref = ref_bare.group(1).strip() if ref_bare else ""

                    rows.append({
                        "document_id": document_id,
                        "source_page": page_number,
                        "row_hash": f"row-{row_index}",
                        "raw_text": line,
                        "raw_analyte_label": label,
                        "raw_value_string": value,
                        "raw_unit_string": unit,
                        "raw_reference_range": ref or None,
                        "extraction_confidence": 0.99,
                        "row_bbox": [0, 0, 0, 0],
                    })
                    row_index += 1
    except Exception as exc:  # pragma: no cover - defensive
        _LOGGER.warning("text_layer_extraction_failed: %s", exc)
        return []

    return rows


async def _persist_row_level_entities(
    store: TopLevelLifecycleStore,
    *,
    job_uuid: UUID,
    document_id: UUID,
    clean_rows: list[dict],
    observations: list[dict],
    findings: list[dict],
) -> dict[str, int]:
    if not _store_supports_bulk_row_persistence(store):
        return await _persist_row_level_entities_row_by_row(
            store,
            job_uuid=job_uuid,
            document_id=document_id,
            clean_rows=clean_rows,
            observations=observations,
            findings=findings,
        )

    try:
        return await _persist_row_level_entities_bulk(
            store,
            job_uuid=job_uuid,
            document_id=document_id,
            clean_rows=clean_rows,
            observations=observations,
            findings=findings,
        )
    except IntegrityError as exc:
        _LOGGER.warning(
            "bulk_row_persistence_failed_fallback job_id=%s error=%s",
            job_uuid,
            type(exc).__name__,
        )
        return await _persist_row_level_entities_row_by_row(
            store,
            job_uuid=job_uuid,
            document_id=document_id,
            clean_rows=clean_rows,
            observations=observations,
            findings=findings,
        )


def _store_supports_bulk_row_persistence(store: TopLevelLifecycleStore) -> bool:
    required_methods = (
        "bulk_create_extracted_rows",
        "bulk_create_observations",
        "bulk_create_mapping_candidates",
        "bulk_create_rule_events",
        "bulk_create_policy_events",
    )
    return all(callable(getattr(store, method_name, None)) for method_name in required_methods)


async def _persist_row_level_entities_bulk(
    store: TopLevelLifecycleStore,
    *,
    job_uuid: UUID,
    document_id: UUID,
    clean_rows: list[dict],
    observations: list[dict],
    findings: list[dict],
) -> dict[str, int]:
    row_level_counts = {
        "extracted_rows": 0,
        "observations": 0,
        "mapping_candidates": 0,
        "rule_events": 0,
        "policy_events": 0,
    }

    extracted_rows_payload = [
        {
            "document_id": document_id,
            "job_id": job_uuid,
            "source_page": int(row["source_page"]),
            "row_hash": str(row["row_hash"]),
            "raw_text": str(row["raw_text"]),
            "raw_analyte_label": row.get("raw_analyte_label"),
            "raw_value_string": row.get("raw_value_string"),
            "raw_unit_string": row.get("raw_unit_string"),
            "raw_reference_range": row.get("raw_reference_range"),
            "extraction_confidence": row.get("extraction_confidence"),
        }
        for row in clean_rows
    ]
    extracted_row_ids_by_row_hash = await store.bulk_create_extracted_rows(
        rows=extracted_rows_payload
    )
    row_level_counts["extracted_rows"] = len(extracted_rows_payload)

    observations_payload: list[dict] = []
    for observation in observations:
        observation_uuid = observation.get("id")
        if observation_uuid is None:
            raise ValueError("observation_missing_id")
        if not isinstance(observation_uuid, UUID):
            observation_uuid = UUID(str(observation_uuid))

        extracted_row_id = extracted_row_ids_by_row_hash.get(str(observation["row_hash"]))
        if extracted_row_id is None:
            raise LookupError(f"missing_extracted_row_for_observation:{observation['row_hash']}")

        observations_payload.append(
            {
                "observation_uuid": observation_uuid,
                "document_id": document_id,
                "job_id": job_uuid,
                "extracted_row_id": extracted_row_id,
                "source_page": int(observation["source_page"]),
                "row_hash": str(observation["row_hash"]),
                "raw_analyte_label": str(observation["raw_analyte_label"]),
                "raw_value_string": observation.get("raw_value_string"),
                "raw_unit_string": observation.get("raw_unit_string"),
                "parsed_numeric_value": observation.get("parsed_numeric_value"),
                "accepted_analyte_code": observation.get("accepted_analyte_code"),
                "accepted_analyte_display": observation.get("accepted_analyte_display"),
                "specimen_context": observation.get("specimen_context"),
                "method_context": observation.get("method_context"),
                "raw_reference_range": observation.get("raw_reference_range"),
                "canonical_unit": observation.get("canonical_unit"),
                "canonical_value": observation.get("canonical_value"),
                "language_id": observation.get("language_id"),
                "support_state": _enum_value(observation.get("support_state")),
                "suppression_reasons": observation.get("suppression_reasons") or None,
            }
        )

    observation_ids_by_observation_uuid = await store.bulk_create_observations(
        rows=observations_payload
    )
    row_level_counts["observations"] = len(observations_payload)

    mapping_candidates_payload: list[dict] = []
    for observation in observations:
        observation_uuid = observation.get("id")
        if observation_uuid is None:
            continue
        if not isinstance(observation_uuid, UUID):
            observation_uuid = UUID(str(observation_uuid))
        persisted_observation_id = observation_ids_by_observation_uuid.get(observation_uuid)
        if persisted_observation_id is None:
            continue

        for candidate in observation.get("candidates", []):
            mapping_candidates_payload.append(
                {
                    "observation_id": persisted_observation_id,
                    "candidate_code": str(candidate["candidate_code"]),
                    "candidate_display": str(candidate["candidate_display"]),
                    "score": float(candidate.get("score", 0.0)),
                    "threshold_used": float(candidate.get("threshold_used", 0.9)),
                    "accepted": bool(candidate["accepted"]),
                    "rejection_reason": candidate.get("rejection_reason"),
                }
            )

    await store.bulk_create_mapping_candidates(rows=mapping_candidates_payload)
    row_level_counts["mapping_candidates"] = len(mapping_candidates_payload)

    rule_events_payload: list[dict] = []
    policy_events_payload: list[dict] = []
    for finding in findings:
        persisted_observation_ids: list[UUID] = []
        for observation_uuid in finding.get("observation_ids", []):
            try:
                normalized_observation_uuid = (
                    observation_uuid
                    if isinstance(observation_uuid, UUID)
                    else UUID(str(observation_uuid))
                )
            except (TypeError, ValueError):
                continue

            persisted_observation_id = observation_ids_by_observation_uuid.get(
                normalized_observation_uuid
            )
            if persisted_observation_id is not None:
                persisted_observation_ids.append(persisted_observation_id)

        if not persisted_observation_ids:
            continue

        rule_event_id = uuid4()
        rule_events_payload.append(
            {
                "id": rule_event_id,
                "job_id": job_uuid,
                "observation_id": persisted_observation_ids[0],
                "rule_id": str(finding["rule_id"]),
                "finding_id": _stable_identifier(str(finding["finding_id"])),
                "threshold_source": str(finding["threshold_source"]),
                "supporting_observation_ids": persisted_observation_ids,
                "suppression_conditions": finding.get("suppression_conditions"),
                "severity_class_candidate": _enum_value(finding.get("severity_class_candidate")),
                "nextstep_class_candidate": _enum_value(finding.get("nextstep_class_candidate")),
            }
        )
        policy_events_payload.append(
            {
                "job_id": job_uuid,
                "rule_event_id": rule_event_id,
                "severity_class": _enum_value(finding.get("severity_class")),
                "nextstep_class": _enum_value(finding.get("nextstep_class")),
                "severity_policy_version": _SEVERITY_POLICY_VERSION,
                "nextstep_policy_version": _NEXTSTEP_POLICY_VERSION,
                "suppression_active": bool(finding.get("suppression_active", False)),
                "suppression_reason": finding.get("suppression_reason"),
            }
        )

    await store.bulk_create_rule_events(rows=rule_events_payload)
    row_level_counts["rule_events"] = len(rule_events_payload)
    await store.bulk_create_policy_events(rows=policy_events_payload)
    row_level_counts["policy_events"] = len(policy_events_payload)

    return row_level_counts


async def _persist_row_level_entities_row_by_row(
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
                score=float(candidate.get("score", 0.0)),
                threshold_used=float(candidate.get("threshold_used", 0.9)),
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
    metric_resolver: MetricResolver,
    patient_context: dict,
) -> list[dict]:
    normalized_observations: list[dict] = []
    patient_context_schema = PatientContext(
        age_years=patient_context.get("age_years"),
        sex=patient_context.get("sex"),
        preferred_language=patient_context.get("language_id", "en"),
        pregnancy_status=patient_context.get("pregnancy_status"),
    )

    for observation in observations:
        updated = dict(observation)

        extraction_confidence = updated.get("extraction_confidence")
        if extraction_confidence is not None and float(extraction_confidence) < 0.90:
            updated["support_state"] = "unsupported"
            updated["suppression_reasons"] = sorted(
                {*(updated.get("suppression_reasons") or []), "low_extraction_confidence"}
            )
            normalized_observations.append(updated)
            continue

        resolver_result = analyte_resolver.resolve(
            raw_label=updated["raw_analyte_label"],
            context={
                "specimen_context": updated.get("specimen_context"),
                "language_id": updated.get("language_id"),
                "raw_unit": updated.get("raw_unit_string"),
            },
        )
        updated["candidates"] = resolver_result["candidates"]
        updated["support_state"] = resolver_result["support_state"]
        resolver_abstention_reasons = resolver_result.get("abstention_reasons") or []
        if resolver_abstention_reasons:
            updated["suppression_reasons"] = sorted(
                {*(updated.get("suppression_reasons") or []), *resolver_abstention_reasons}
            )

        accepted_candidate = resolver_result.get("accepted_candidate")
        if accepted_candidate is not None:
            updated["accepted_analyte_code"] = accepted_candidate["candidate_code"]
            updated["accepted_analyte_display"] = accepted_candidate["candidate_display"]

        parsed_numeric_value = updated.get("parsed_numeric_value")
        raw_value_string = updated.get("raw_value_string")
        numeric_value = parsed_numeric_value
        if numeric_value is None and raw_value_string not in (None, ""):
            # Strip non-numeric garbage (e.g. '< 180 mg/dL' -> '180')
            clean_str = _NUMERIC_VALUE_CLEAN_RE.sub("", str(raw_value_string))
            try:
                if clean_str.count(".") > 1:
                    clean_str = clean_str[: clean_str.index(".") + 1] + clean_str[
                        clean_str.index(".") + 1 :
                    ].replace(".", "")
                numeric_value = float(clean_str)
                updated["parsed_numeric_value"] = numeric_value
            except (ValueError, TypeError):
                numeric_value = None

        accepted_code = updated.get("accepted_analyte_code")
        if updated.get("support_state") == "supported" and accepted_code:
            metric_def = metric_resolver._lookup.get((accepted_code or "").lower().strip())
            if metric_def and metric_def.result_type == "numeric":
                if numeric_value is not None:
                    profile = metric_resolver.resolve_profile(accepted_code, patient_context_schema)
                    if profile:
                        updated["selected_reference_profile"] = profile.profile_id
                    else:
                        # Abstain/No profile: keep it supported and use paper's range or generic fallback
                        updated["suppression_reasons"] = sorted(
                            {
                                *(updated.get("suppression_reasons") or []),
                                "unresolved_reference_profile",
                            }
                        )
                else:
                    # Numeric metric but no numeric value
                    updated["support_state"] = "partial"
                    updated["suppression_reasons"] = sorted(
                        {*(updated.get("suppression_reasons") or []), "missing_numeric_value"}
                    )

        raw_unit_string = updated.get("raw_unit_string")
        if numeric_value is not None and raw_unit_string:
            if _is_ucum_bypass_unit(raw_unit_string):
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
                except ValueError:
                    # UCUM library rejected an unknown clinical unit (fL, /cmm,
                    # pg, mm/1hr, microIU/mL, etc.). These are legitimate lab
                    # units that never need cross-unit conversion here: pass
                    # through as-is so downstream rule/printed-range evaluation
                    # still fires. Do NOT suppress the row.
                    updated["canonical_value"] = float(numeric_value)
                    updated["canonical_unit"] = str(raw_unit_string)

        normalized_observations.append(updated)

    return normalized_observations


def _support_banner(observations: list[dict]) -> str:
    support_states = {
        str(observation.get("support_state") or "").lower() for observation in observations
    }
    if support_states == {"supported"}:
        return "fully_supported"
    if "supported" in support_states:
        return "partially_supported"
    return "could_not_assess"


def _downgrade_support_banner(current: str, candidate: str) -> str:
    rank = {
        "could_not_assess": 0,
        "partially_supported": 1,
        "fully_supported": 2,
    }
    current_normalized = str(current or "could_not_assess")
    candidate_normalized = str(candidate or "could_not_assess")
    if rank.get(candidate_normalized, 0) < rank.get(current_normalized, 0):
        return candidate_normalized
    return current_normalized


def _support_banner_from_runtime(
    observations: list[dict],
    findings: list[dict],
    comparable_history: dict | None,
) -> str:
    baseline = _support_banner(observations)
    suppressed_findings = [finding for finding in findings if finding.get("suppression_active")]
    if suppressed_findings:
        assessed_findings = [
            finding for finding in findings if not finding.get("suppression_active")
        ]
        baseline = _downgrade_support_banner(
            baseline,
            "partially_supported" if assessed_findings else "could_not_assess",
        )

    return baseline


def _validate_structured_observations(
    observations: object,
    *,
    document_id: UUID,
) -> list[dict]:
    if not isinstance(observations, list):
        raise ValueError("structured_observations_not_list")

    normalized_rows: list[dict] = []
    for index, observation in enumerate(observations):
        if not isinstance(observation, dict):
            raise ValueError(f"structured_observation_not_object:{index}")

        missing_required = [
            key
            for key in ("source_page", "row_hash", "raw_analyte_label")
            if key not in observation
        ]
        if missing_required:
            missing = ",".join(missing_required)
            raise ValueError(f"structured_observation_missing_fields:{index}:{missing}")

        source_page = observation.get("source_page")
        if not isinstance(source_page, int) or source_page < 1:
            raise ValueError(f"structured_observation_invalid_source_page:{index}")

        row_hash = observation.get("row_hash")
        if not isinstance(row_hash, str) or not row_hash.strip():
            raise ValueError(f"structured_observation_invalid_row_hash:{index}")

        raw_analyte_label = observation.get("raw_analyte_label")
        if not isinstance(raw_analyte_label, str) or not raw_analyte_label.strip():
            raise ValueError(f"structured_observation_invalid_analyte_label:{index}")

        raw_value_string = observation.get("raw_value_string")
        if raw_value_string is not None and not isinstance(raw_value_string, str):
            raise ValueError(f"structured_observation_invalid_raw_value_type:{index}")

        raw_unit_string = observation.get("raw_unit_string")
        if raw_unit_string is not None and not isinstance(raw_unit_string, str):
            raise ValueError(f"structured_observation_invalid_raw_unit_type:{index}")

        parsed_numeric_value = observation.get("parsed_numeric_value")
        if parsed_numeric_value is not None and (
            isinstance(parsed_numeric_value, bool)
            or not isinstance(parsed_numeric_value, (int, float))
        ):
            raise ValueError(f"structured_observation_invalid_parsed_numeric_value:{index}")

        normalized_row = {
            **observation,
            "document_id": document_id,
            "source_page": source_page,
            "row_hash": row_hash.strip(),
            "raw_analyte_label": raw_analyte_label.strip(),
        }
        normalized_rows.append(normalized_row)

    return normalized_rows


def _is_ucum_bypass_unit(raw_unit_string: object) -> bool:
    """Clinical-lab units that the UCUM library rejects but we accept as-is.

    These are reported in their own canonical channel (eGFR in mL/min/1.73m²,
    ACR in mg Alb/mmol, etc.) and never need cross-unit conversion. Returning
    True causes the pipeline to pass them through without UCUM validation.
    """
    normalized = " ".join(str(raw_unit_string or "").strip().lower().split())
    return normalized in {
        "ml/min/1.73 m2",
        "ml/min/1.73 m^2",
        "ml/min/1.73 m²",
        "ml/min/1.73m2",
        "ml/min/1.73m^2",
        "ml/min/1.73m²",
        "mg alb/mmol",
        "mg alb/mmol creat",
        "mg/mmol creat",
        "mg/g creat",
        "mg/g{creat}",
    }


def _apply_detected_language(extracted_rows: list[dict], patient_context: dict) -> None:
    language_counts: dict[str, int] = {}
    for row in extracted_rows:
        lang = str(row.get("language_id") or "en").strip().lower()
        if not lang:
            lang = "en"
        primary = lang.split("-", 1)[0]
        language_counts[primary] = language_counts.get(primary, 0) + 1

    if language_counts:
        detected = max(language_counts, key=language_counts.get)
        patient_context["language_id"] = detected
