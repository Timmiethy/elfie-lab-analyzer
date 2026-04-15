"""v12 pipeline runtime integration tests.

Covers:
- v12 lineage payload includes parser_backend, parser_backend_version, row_assembly_version
- Pipeline seeds carry v12 parser metadata on extraction rows
- Benchmark metrics include parser_backend metadata
- Persistence payloads include parser_backend fields
- The normalization-first contracts remain stable (no changes to deterministic policy logic)
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workers.pipeline import (
    PipelineOrchestrator,
    _build_completeness_telemetry,
    _build_lineage_payload,
    _build_runtime_metadata,
    _build_semantic_success_shadow,
    _resolve_runtime_routing,
    _derive_patient_context,
    _build_persistence_payloads,
    _extract_rows,
    _extract_parser_backend,
    _extract_parser_backend_version,
    _extract_row_assembly_version,
)


class TestV12LineagePayload:
    """Tests for v12 lineage payload construction."""

    def test_lineage_payload_includes_parser_backend_fields(self):
        payload = _build_lineage_payload(
            "test-job-001",
            source_checksum="abc123",
            lane_type="trusted_pdf",
            terminology_release="seeded-demo-2026-04-10",
            build_commit="unknown",
            parser_backend="pymupdf",
            parser_backend_version="pymupdf-1.27.x",
            row_assembly_version="row-assembly-v2",
        )
        assert payload["parser_backend"] == "pymupdf"
        assert payload["parser_backend_version"] == "pymupdf-1.27.x"
        assert payload["row_assembly_version"] == "row-assembly-v2"
        # Backwards-compat fields remain
        assert payload["parser_version"] is not None
        assert payload["adapter_version"] is not None

    def test_lineage_payload_defaults_when_parser_metadata_absent(self):
        payload = _build_lineage_payload(
            "test-job-002",
            source_checksum="abc123",
            lane_type="trusted_pdf",
            terminology_release="seeded-demo-2026-04-10",
            build_commit="unknown",
        )
        assert payload["parser_backend"] == "pymupdf"
        assert payload["parser_backend_version"] == "pymupdf-1.27.x"
        assert payload["row_assembly_version"] == "row-assembly-v2"

    def test_lineage_payload_image_beta_defaults(self):
        payload = _build_lineage_payload(
            "test-job-003",
            source_checksum="abc123",
            lane_type="image_beta",
            terminology_release="seeded-demo-2026-04-10",
            build_commit="unknown",
        )
        assert payload["parser_backend"] == "qwen_ocr"
        assert payload["parser_backend_version"] == "qwen-vl-ocr-2025-11-20"
        assert payload["ocr_version"] == "qwen-vl-ocr-2025-11-20"

    def test_lineage_payload_preserves_v11_fields(self):
        payload = _build_lineage_payload(
            "test-job-004",
            source_checksum="abc123",
            lane_type="trusted_pdf",
            terminology_release="seeded-demo-2026-04-10",
            build_commit="unknown",
        )
        v11_keys = {
            "source_checksum", "parser_version", "adapter_version",
            "row_assembly_version", "row_type_rule_set_version",
            "formula_version", "ocr_version", "terminology_release",
            "mapping_threshold_config", "unit_engine_version",
            "rule_pack_version", "severity_policy_version",
            "nextstep_policy_version", "template_version",
            "model_version", "build_commit",
        }
        assert v11_keys.issubset(set(payload.keys()))

    def test_lineage_payload_can_carry_completeness_telemetry(self):
        payload = _build_lineage_payload(
            "test-job-005",
            source_checksum="abc123",
            lane_type="trusted_pdf",
            terminology_release="seeded-demo-2026-04-10",
            build_commit="unknown",
            completeness_telemetry={"contract_version": "completeness-telemetry-v1"},
        )
        assert payload["completeness_telemetry"] == {
            "contract_version": "completeness-telemetry-v1"
        }


class TestV12CompletenessTelemetry:
    def test_completeness_telemetry_computes_ratios_and_states(self):
        telemetry = _build_completeness_telemetry(
            extracted_rows=[
                {"source_page": 1},
                {"source_page": 2},
                {"source_page": 2},
            ],
            clean_rows=[
                {"source_page": 1},
                {"source_page": 2},
            ],
            observations=[
                {
                    "row_type": "measured_analyte_row",
                    "support_state": "supported",
                    "raw_reference_range": "70-99",
                },
                {
                    "row_type": "measured_analyte_row",
                    "support_state": "partial",
                    "raw_reference_range": None,
                },
                {
                    "row_type": "admin_metadata_row",
                    "support_state": "unsupported",
                    "raw_reference_range": None,
                },
            ],
        )

        assert telemetry["contract_version"] == "completeness-telemetry-v1"
        assert telemetry["counts"]["extracted_rows"] == 3
        assert telemetry["counts"]["clean_rows"] == 2
        assert telemetry["counts"]["result_observations"] == 2
        assert telemetry["counts"]["reference_bound_observations"] == 1
        assert telemetry["ratios"]["structural_clean_row_ratio"] == 0.6667
        assert telemetry["ratios"]["structural_page_coverage_ratio"] == 1.0
        assert telemetry["states"]["structural"] == "partial"
        assert telemetry["states"]["observation"] == "partial"
        assert telemetry["states"]["reference"] == "partial"

    def test_semantic_shadow_is_additive_and_deterministic(self):
        telemetry = _build_completeness_telemetry(
            extracted_rows=[{"source_page": 1}, {"source_page": 2}],
            clean_rows=[{"source_page": 1}, {"source_page": 2}],
            observations=[
                {
                    "row_type": "measured_analyte_row",
                    "support_state": "supported",
                    "raw_reference_range": "70-99",
                },
                {
                    "row_type": "measured_analyte_row",
                    "support_state": "partial",
                    "raw_reference_range": None,
                },
            ],
        )
        shadow = _build_semantic_success_shadow(
            completeness_telemetry=telemetry,
            findings=[
                {
                    "severity_class": "S2",
                    "suppression_active": False,
                    "suppression_reason": None,
                },
            ],
            support_banner="partially_supported",
            lane_type="trusted_pdf",
        )

        assert shadow["contract_version"] == "semantic-success-shadow-v1"
        assert shadow["semantic_state"] == "shadow_partially_recoverable"
        assert shadow["structural_gate_pass"] is True
        assert shadow["observation_gate_pass"] is True
        assert shadow["reference_gate_pass"] is True
        assert shadow["finding_counts"]["actionable"] == 1


class TestV12PersistencePayloads:
    """Tests for v12 persistence payload construction."""

    def test_persistence_payload_includes_parser_backend_fields(self):
        lineage = {
            "source_checksum": "abc123",
            "parser_version": "pymupdf-1.27.x",
            "parser_backend": "pymupdf",
            "parser_backend_version": "pymupdf-1.27.x",
            "adapter_version": "family-adapter-v1",
            "row_assembly_version": "row-assembly-v2",
            "row_type_rule_set_version": "row-type-rules-v1",
            "formula_version": "formula-v1",
            "ocr_version": None,
            "terminology_release": "seeded-demo-2026-04-10",
            "mapping_threshold_config": {"default": 0.9},
            "unit_engine_version": "ucum-v1",
            "rule_pack_version": "rules-v1",
            "severity_policy_version": "severity-v1",
            "nextstep_policy_version": "nextstep-v1",
            "template_version": "templates-v1",
            "model_version": None,
            "build_commit": "local-dev",
        }
        patient_artifact = {
            "language_id": "en",
            "support_banner": "fully_supported",
        }
        clinician_artifact = {"content": "clinician-data"}
        benchmark = {"report_type": "test", "metrics": {}}

        payloads = _build_persistence_payloads(
            patient_artifact, clinician_artifact, lineage, benchmark, "completed"
        )
        lr = payloads["lineage_run"]
        assert lr["parser_backend"] == "pymupdf"
        assert lr["parser_backend_version"] == "pymupdf-1.27.x"
        assert lr["row_assembly_version"] == "row-assembly-v2"
        assert lr["parser_version"] == "pymupdf-1.27.x"


class TestV12ParserMetadataExtraction:
    """Tests for parser metadata extraction from extraction rows."""

    def test_extract_parser_backend_from_rows(self):
        rows = [{"parser_backend": "pymupdf"}, {"parser_backend": "pymupdf"}]
        assert _extract_parser_backend(rows) == "pymupdf"

    def test_extract_parser_backend_returns_none_when_absent(self):
        rows = [{"some_key": "value"}]
        assert _extract_parser_backend(rows) is None

    def test_extract_parser_backend_version_from_rows(self):
        rows = [{"parser_backend_version": "pymupdf-1.27.x"}]
        assert _extract_parser_backend_version(rows) == "pymupdf-1.27.x"

    def test_extract_row_assembly_version_from_rows(self):
        rows = [{"row_assembly_version": "row-assembly-v2"}]
        assert _extract_row_assembly_version(rows) == "row-assembly-v2"

    def test_extract_parser_backend_fallback_keys(self):
        rows = [{"_v12_parser_backend": "pymupdf"}]
        assert _extract_parser_backend(rows) == "pymupdf"

    def test_extract_parser_backend_version_fallback_keys(self):
        rows = [{"_v12_parser_backend_version": "pymupdf-1.27.x"}]
        assert _extract_parser_backend_version(rows) == "pymupdf-1.27.x"


class TestV12RuntimeGuardrails:
    """Tests for runtime truth constraints."""

    def test_patient_context_stays_missing_when_rows_lack_demographics(self):
        context = _derive_patient_context(
            "phase-1-context",
            extracted_rows=[
                {
                    "raw_analyte_label": "Glucose",
                    "raw_value_string": "180",
                    "language_id": None,
                }
            ],
        )

        assert context["age_years"] is None
        assert context["sex"] is None
        assert context["report_date"] is None
        assert context["context_status"] == "missing"
        assert "age_missing" in context["missing_reason_codes"]
        assert "sex_missing" in context["missing_reason_codes"]
        assert "report_date_missing" in context["missing_reason_codes"]

    def test_runtime_metadata_uses_unknown_without_seeded_defaults(self):
        metadata = _build_runtime_metadata(snapshot_metadata=None)
        assert metadata["terminology_release"] == "unknown"
        assert metadata["build_commit"] == "unknown"

    @pytest.mark.asyncio
    async def test_extract_rows_requires_file_bytes_for_runtime_lanes(self):
        with pytest.raises(ValueError, match="missing_file_bytes"):
            await _extract_rows(
                uuid.uuid4(),
                file_bytes=None,
                lane_type="trusted_pdf",
            )

        with pytest.raises(ValueError, match="missing_file_bytes"):
            await _extract_rows(
                uuid.uuid4(),
                file_bytes=None,
                lane_type="image_beta",
            )

    @pytest.mark.asyncio
    async def test_extract_rows_allows_unsupported_lane_without_file_bytes(self):
        rows = await _extract_rows(
            uuid.uuid4(),
            file_bytes=None,
            lane_type="unsupported",
        )
        assert rows == []

    @pytest.mark.asyncio
    async def test_runtime_routing_enforces_preflight_lane_on_mismatch(self):
        decision = await _resolve_runtime_routing(
            file_bytes=b"%PDF-1.4 fake",
            requested_lane="trusted_pdf",
            source_filename="seed.png",
            source_mime_type="image/png",
            runtime_preflight={
                "lane_type": "image_beta",
                "route_document_class": "image_pdf_lab",
                "route_reason_codes": ["image_file_route"],
                "promotion_status": "beta_ready",
                "route_confidence": 0.95,
            },
        )

        assert decision["selected_lane"] == "image_beta"
        assert decision["preflight_lane"] == "image_beta"
        assert decision["enforcement_action"] == "lane_mismatch_preflight_enforced"

    @pytest.mark.asyncio
    async def test_runtime_routing_downgrades_non_lab_document_class(self):
        decision = await _resolve_runtime_routing(
            file_bytes=b"%PDF-1.4 fake",
            requested_lane="trusted_pdf",
            source_filename="seed.pdf",
            source_mime_type="application/pdf",
            runtime_preflight={
                "lane_type": "trusted_pdf",
                "route_document_class": "non_lab_medical",
                "route_reason_codes": ["non_lab_medical_keywords"],
                "promotion_status": "ready_unsupported",
                "route_confidence": 0.97,
            },
        )

        assert decision["selected_lane"] == "unsupported"
        assert decision["enforcement_action"] == "downgraded_non_lab_or_ambiguous_class"

    @pytest.mark.asyncio
    async def test_runtime_routing_downgrades_when_preflight_context_is_missing(self):
        decision = await _resolve_runtime_routing(
            file_bytes=b"%PDF-1.4 fake",
            requested_lane="trusted_pdf",
            source_filename=None,
            source_mime_type=None,
            runtime_preflight=None,
        )

        assert decision["selected_lane"] == "unsupported"
        assert decision["enforcement_action"] == "downgraded_missing_runtime_preflight_context"


class TestV12PipelineRuntimeIntegration:
    """Integration tests for the pipeline with v12 lineage metadata."""

    @pytest.mark.asyncio
    async def test_pipeline_run_records_v12_lineage_metadata(self):
        orchestrator = PipelineOrchestrator()

        mock_extracted_rows = [
            {
                "document_id": uuid.uuid4(),
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
                "parser_backend": "pymupdf",
                "parser_backend_version": "pymupdf-1.27.x",
                "row_assembly_version": "row-assembly-v2",
            },
        ]

        with patch("app.workers.pipeline._extract_rows", new_callable=AsyncMock) as mock_extract:
            mock_extract.return_value = mock_extracted_rows
            # Mock services
            with patch("app.workers.pipeline.ExtractionQA") as mock_qa, \
                 patch("app.workers.pipeline.ObservationBuilder") as mock_obs, \
                 patch("app.workers.pipeline.AnalyteResolver") as mock_resolver, \
                 patch("app.workers.pipeline.UcumEngine") as mock_ucum, \
                 patch("app.workers.pipeline.PanelReconstructor") as mock_panel, \
                 patch("app.workers.pipeline.RuleEngine") as mock_rules, \
                 patch("app.workers.pipeline.SeverityPolicyEngine") as mock_severity, \
                 patch("app.workers.pipeline.NextStepPolicyEngine") as mock_nextstep, \
                 patch("app.workers.pipeline.ArtifactRenderer") as mock_renderer, \
                 patch("app.workers.pipeline.LineageLogger") as mock_lineage, \
                 patch("app.workers.pipeline.BenchmarkRecorder") as mock_benchmark, \
                 patch("app.workers.pipeline.ComparableHistoryService") as mock_history, \
                 patch("app.workers.pipeline.ExplanationAdapter") as mock_explanation, \
                 patch("app.workers.pipeline.write_clinician_pdf"), \
                 patch("app.workers.pipeline.write_proof_pack"), \
                 patch("app.workers.pipeline.get_loaded_snapshot_metadata", return_value={"release": "seeded-demo-2026-04-10"}):

                mock_qa.return_value.validate.return_value = {"clean_rows": mock_extracted_rows}
                mock_obs.return_value.build.return_value = []
                mock_resolver.return_value.resolve.return_value = {
                    "candidates": [],
                    "support_state": "supported",
                }
                mock_ucum.return_value.normalize_dual_unit_channels.return_value = {
                    "primary_result": {"normalized_numeric_value": 180.0, "parse_locale": {}, "normalized_comparator": None},
                    "secondary_result": None,
                    "canonical_value": 180.0,
                    "canonical_unit": "mg/dL",
                }
                mock_panel.return_value.reconstruct.return_value = []
                mock_rules.return_value.evaluate.return_value = []
                mock_severity.return_value.assign.return_value = []
                mock_nextstep.return_value.assign.return_value = []
                mock_history.return_value.build_for_artifact = AsyncMock(return_value=None)
                mock_renderer.return_value.render_patient.return_value = {"language_id": "en", "support_banner": "fully_supported"}
                mock_renderer.return_value.render_clinician.return_value = {}
                mock_explanation.return_value.generate = AsyncMock(return_value={})
                mock_lineage.return_value.record.return_value = {"id": uuid.uuid4()}
                mock_benchmark.return_value.record.return_value = {"report_type": "test", "metrics": {}}
                mock_benchmark.return_value.build_proof_pack.return_value = {}

                result = await orchestrator.run(
                    "test-job-v12-001",
                    file_bytes=None,
                    lane_type="trusted_pdf",
                )

                # Verify v12 lineage metadata is present
                lineage = result["lineage"]
                assert lineage["parser_backend"] == "pymupdf"
                assert lineage["parser_backend_version"] == "pymupdf-1.27.x"
                assert lineage["row_assembly_version"] == "row-assembly-v2"
                assert lineage["completeness_telemetry"]["contract_version"] == "completeness-telemetry-v1"
                assert lineage["completeness_telemetry"]["semantic_success_shadow"]["contract_version"] == "semantic-success-shadow-v1"

                # Runtime behavior remains unchanged while semantic scoring is shadow-only.
                assert result["status"] == "completed"
                assert result["patient_artifact"]["support_banner"] == "fully_supported"
                assert result["semantic_success_shadow"]["contract_version"] == "semantic-success-shadow-v1"

                # Verify benchmark metrics include v12 metadata
                benchmark = result["benchmark"]
                assert "parser_backend" in benchmark["metrics"]
                assert "parser_backend_version" in benchmark["metrics"]
                assert "row_assembly_version" in benchmark["metrics"]
                assert "completeness_structural_ratio" in benchmark["metrics"]
                assert "completeness_page_coverage_ratio" in benchmark["metrics"]
                assert "completeness_supported_ratio" in benchmark["metrics"]
                assert "completeness_reference_coverage_ratio" in benchmark["metrics"]
                assert "completeness_structural_state" in benchmark["metrics"]
                assert "completeness_observation_state" in benchmark["metrics"]
                assert "completeness_reference_state" in benchmark["metrics"]
                assert "semantic_shadow_state" in benchmark["metrics"]
                assert "semantic_shadow_confidence" in benchmark["metrics"]
                assert "semantic_shadow_support_banner" in benchmark["metrics"]
                assert "semantic_shadow_structural_gate_pass" in benchmark["metrics"]
                assert "semantic_shadow_observation_gate_pass" in benchmark["metrics"]
                assert "semantic_shadow_reference_gate_pass" in benchmark["metrics"]
                assert "semantic_shadow_actionable_findings" in benchmark["metrics"]
                assert "semantic_shadow_threshold_conflicts" in benchmark["metrics"]

    def test_v12_does_not_alter_deterministic_policy_logic(self):
        """Verify that v12 lineage additions don't change deterministic support state logic."""
        from app.schemas.observation import SupportState
        # Verify the SupportState enum remains stable
        assert hasattr(SupportState, "SUPPORTED")
        assert hasattr(SupportState, "PARTIAL")
        assert hasattr(SupportState, "UNSUPPORTED")
        # Verify v11 contract version is unchanged
        from app.schemas.observation import CONTRACT_VERSION
        assert CONTRACT_VERSION.startswith("observation-contract-v2")
