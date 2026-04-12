"""Phase 38: v11 leak-prevention blocking tests.

These tests codify the non-negotiable leak-prevention gates from
labs_analyzer_v11_source_of_truth.md section 15.2.

Each test documents the current broken behavior (why it is expected to fail
against the pre-fix codebase) and the intended typed outcome that the v11
implementation must achieve.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.schemas.artifact import PatientArtifactSchema
from app.schemas.observation import FailureCode, ObservationSchema, RowType
from app.services.analyte_resolver import AnalyteResolver
from app.services.artifact_renderer import ArtifactRenderer
from app.services.observation_builder import ObservationBuilder, _derive_support_outcome, _normalize_row_type
from app.workers.pipeline import PipelineOrchestrator


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _raw_row(**overrides: object) -> dict:
    base: dict = {
        "document_id": uuid4(),
        "source_page": 1,
        "row_hash": f"hash-{uuid4()}",
        "raw_text": "",
        "raw_analyte_label": "",
        "raw_value_string": None,
        "raw_unit_string": None,
        "raw_reference_range": None,
        "parsed_numeric_value": None,
        "specimen_context": None,
        "method_context": None,
        "language_id": "en",
        "extraction_confidence": 0.99,
    }
    base.update(overrides)  # type: ignore[arg-type]
    return base


def _run_pipeline(monkeypatch, extracted_rows: list[dict]) -> dict:
    async def fake_extract_rows(job_uuid, *, file_bytes, lane_type):  # type: ignore[no-untyped-def]
        return extracted_rows

    monkeypatch.setattr("app.workers.pipeline._extract_rows", fake_extract_rows)
    return asyncio.run(
        PipelineOrchestrator().run(
            "v11-leak-prevention",
            file_bytes=b"trusted-pdf",
            lane_type="trusted_pdf",
            source_checksum="sha256:v11-leak",
        )
    )


# ---------------------------------------------------------------------------
# 1. admin rows must never enter the observation pool
# ---------------------------------------------------------------------------

class TestAdminRowsNeverEnterObservationPool:
    """V11 15.2: test_admin_rows_never_enter_observation_pool

    Current broken behavior: admin-like labels such as ``DOB :``,
    ``Collected :``, and ``Report Printed :`` are treated as regular
    extracted rows, reach the observation builder, and may appear in
    patient-facing "not assessed" lists.

    Intended outcome: rows typed ``admin_metadata_row`` are rejected
    before canonical observation construction with
    ``FailureCode.ADMIN_METADATA_ROW`` and must never appear in the
    patient ``not_assessed`` list.
    """

    _ADMIN_LABELS = ("DOB :", "Collected :", "Report Printed :", "Ref :", "Age :")

    def test_admin_row_type_is_excluded(self) -> None:
        for label in self._ADMIN_LABELS:
            row = _raw_row(raw_analyte_label=label, row_type="admin_metadata_row")
            row_type = _normalize_row_type(row)
            assert row_type == "admin_metadata_row"
            _, failure_code, support_state, eligible = _derive_support_outcome(
                row_type=row_type,
                primary_result=None,
                secondary_result=None,
                parsed_numeric_value=None,
                raw_value_string=None,
                accepted_analyte_code=None,
                source_observation_ids=[],
                primary_unit_status="unit_optional",
                secondary_unit_status="unit_optional",
            )
            assert eligible is False, f"{label} must not be eligible for observation pool"
            assert support_state == "unsupported"
            assert failure_code == "admin_metadata_row"

    def test_admin_rows_not_in_observations(self) -> None:
        builder = ObservationBuilder()
        admin_rows = [
            _raw_row(raw_analyte_label=label, row_type="admin_metadata_row", row_hash=f"admin-{idx}")
            for idx, label in enumerate(self._ADMIN_LABELS)
        ]
        observations = builder.build(admin_rows)
        assert len(observations) == len(admin_rows), "observation builder currently emits all rows"
        # The intended v11 outcome: observations where row_type is admin_metadata_row
        # must have eligible_for_observation_pool == False and must be filtered out
        # before the observation pool is passed to the rule engine.
        for obs in observations:
            if obs["row_type"] == "admin_metadata_row":
                assert obs["eligible_for_observation_pool"] is False

    def test_admin_rows_not_in_patient_artifact_not_assessed(self, monkeypatch) -> None:
        """When the pipeline is correct, admin rows must never reach patient not_assessed."""
        extracted = [
            _raw_row(
                raw_analyte_label="DOB :",
                row_type="admin_metadata_row",
                raw_value_string="1990-01-01",
                row_hash="admin-dob",
            ),
            _raw_row(
                raw_analyte_label="Collected :",
                row_type="admin_metadata_row",
                raw_value_string="2026-04-10",
                row_hash="admin-collected",
            ),
        ]
        result = _run_pipeline(monkeypatch, extracted)
        patient = PatientArtifactSchema.model_validate(result["patient_artifact"])
        not_assessed_labels = {item.raw_label for item in patient.not_assessed}
        # Intended v11 outcome: no admin metadata labels in patient not_assessed.
        # Current broken behavior: these labels may leak through.
        assert "DOB :" not in not_assessed_labels, "DOB must never appear as patient-facing not-assessed"
        assert "Collected :" not in not_assessed_labels


# ---------------------------------------------------------------------------
# 2. threshold table rows must never surface as unassessed labs
# ---------------------------------------------------------------------------

class TestThresholdTableRowsNeverSurfaceAsUnassessed:
    """V11 15.2: test_threshold_table_rows_never_surface_as_unassessed_labs

    Current broken behavior: threshold-table rows like ``Normal``,
    ``IFG (Prediabetes)``, ``KDIGO 2012`` are parsed as candidate rows,
    fail analyte mapping, and appear in ``not_assessed`` as if they were
    failed lab results.

    Intended outcome: rows typed ``threshold_reference_row`` are rejected
    with ``FailureCode.THRESHOLD_TABLE_ROW`` and are invisible to the
    patient ``not_assessed`` list.
    """

    _THRESHOLD_LABELS = (
        "Normal",
        "IFG (Prediabetes)",
        "KDIGO 2012 Albuminuria Categories",
        "Prediabetes 5.7-6.4",
    )

    def test_threshold_row_type_is_excluded(self) -> None:
        for label in self._THRESHOLD_LABELS:
            row = _raw_row(raw_analyte_label=label, row_type="threshold_table_row")
            row_type = _normalize_row_type(row)
            assert row_type == "threshold_table_row"
            _, failure_code, support_state, eligible = _derive_support_outcome(
                row_type=row_type,
                primary_result=None,
                secondary_result=None,
                parsed_numeric_value=None,
                raw_value_string=None,
                accepted_analyte_code=None,
                source_observation_ids=[],
                primary_unit_status="unit_optional",
                secondary_unit_status="unit_optional",
            )
            assert eligible is False
            assert support_state == "unsupported"
            assert failure_code == "threshold_table_row"

    def test_threshold_rows_not_in_patient_artifact_not_assessed(self, monkeypatch) -> None:
        extracted = [
            _raw_row(
                raw_analyte_label=label,
                row_type="threshold_table_row",
                row_hash=f"threshold-{idx}",
            )
            for idx, label in enumerate(self._THRESHOLD_LABELS)
        ]
        result = _run_pipeline(monkeypatch, extracted)
        patient = PatientArtifactSchema.model_validate(result["patient_artifact"])
        not_assessed_labels = {item.raw_label for item in patient.not_assessed}
        for label in self._THRESHOLD_LABELS:
            assert label not in not_assessed_labels, (
                f"threshold-table row '{label}' must never appear as patient-facing not-assessed"
            )
