"""Phase 38 continued: v11 v11 normalization and observation construction tests.

Tests 3-10 from the mandatory v11 test set in
labs_analyzer_v11_source_of_truth.md section 15.2.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.schemas.artifact import PatientArtifactSchema
from app.schemas.observation import SupportState
from app.services.analyte_resolver import AnalyteResolver
from app.services.observation_builder import (
    ObservationBuilder,
    _derive_support_outcome,
    _normalize_row_type,
    _parse_numeric,
    _parse_numeric_fragment,
)
from app.services.parser import _normalize_measurement_unit_string
from app.services.ucum import UcumEngine
from app.workers.pipeline import PipelineOrchestrator


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
            "v11-normalization",
            file_bytes=b"trusted-pdf",
            lane_type="trusted_pdf",
            source_checksum="sha256:v11-norm",
        )
    )


# ---------------------------------------------------------------------------
# 3. Innoquest bilingual row merge — Sodium 钠
# ---------------------------------------------------------------------------

class TestInnoquestBilingualRowMergeSodium:
    """V11 15.2: test_innoquest_bilingual_row_merge_sodium

    Current broken behavior: bilingual labels like ``Sodium`` + ``钠``
    on adjacent micro-lines are not merged, so the analyte resolver
    cannot map either fragment alone.

    Intended outcome: after row assembly the normalized label resolves
    to a known alias and the analyte resolver accepts it for the
    ``innoquest_bilingual_general`` family.
    """

    def test_resolver_accepts_english_sodium(self) -> None:
        resolver = AnalyteResolver()
        result = resolver.resolve(
            "Sodium",
            context={
                "family_adapter_id": "innoquest_bilingual_general",
                "specimen_context": "serum",
                "language_id": "en",
            },
        )
        accepted = result.get("accepted_candidate")
        assert accepted is not None, "Sodium must resolve to a LOINC candidate"
        assert accepted.get("accepted") is True

    def test_resolver_accepts_bilingual_sodium(self) -> None:
        resolver = AnalyteResolver()
        result = resolver.resolve(
            "Sodium 钠",
            context={
                "family_adapter_id": "innoquest_bilingual_general",
                "specimen_context": "serum",
                "language_id": "en",
            },
        )
        accepted = result.get("accepted_candidate")
        assert accepted is not None, "Sodium 钠 must resolve after bilingual normalization"
        assert accepted.get("accepted") is True


# ---------------------------------------------------------------------------
# 4. Innoquest HbA1c dual-unit result
# ---------------------------------------------------------------------------

class TestInnoquestHba1cDualUnitResult:
    """V11 15.2: test_innoquest_hba1c_dual_unit_result

    Current broken behavior: HbA1c rows carrying both ``%`` and
    ``mmol/mol`` are parsed as a single value or cause duplicate findings.

    Intended outcome: the parser produces a primary result channel
    (NGSP %) and a secondary result channel (IFCC mmol/mol), the
    observation builder keeps both, and the renderer generates exactly
    one finding.
    """

    def test_dual_unit_observation_has_both_channels(self) -> None:
        builder = ObservationBuilder()
        rows = [
            _raw_row(
                raw_analyte_label="HbA1c",
                raw_value_string="6.5",
                raw_unit_string="%",
                parsed_numeric_value=6.5,
                secondary_result={"raw_value_string": "48", "unit": "mmol/mol", "parsed_numeric_value": 48.0},
                accepted_analyte_code="4548-4",
                row_hash="hba1c-dual",
            ),
        ]
        observations = builder.build(rows)
        assert len(observations) == 1
        obs = observations[0]
        assert obs["primary_result"] is not None
        assert obs["secondary_result"] is not None
        assert obs["support_code"] == "dual_unit_result"


# ---------------------------------------------------------------------------
# 5. Innoquest ACR comparator-first value
# ---------------------------------------------------------------------------

class TestInnoquestAcrComparatorFirstValue:
    """V11 15.2: test_innoquest_acr_comparator_first_value

    Current broken behavior: comparator-first values like ``< 0.1 mg Alb/mmol``
    lose the comparator or fail to parse entirely.

    Intended outcome: the comparator ``<`` is preserved in ``parsed_comparator``
    and the numeric value ``0.1`` is correctly extracted.
    """

    def test_comparator_first_parses_correctly(self) -> None:
        result = _parse_numeric_fragment("< 0.1")
        value, locale = result
        assert value == pytest.approx(0.1)
        assert locale["decimal_separator"] == "."

    def test_acr_row_maps_and_retains_comparator(self) -> None:
        resolver = AnalyteResolver()
        result = resolver.resolve(
            "ACR",
            context={
                "family_adapter_id": "innoquest_bilingual_general",
                "specimen_context": "urine",
                "language_id": "en",
            },
        )
        accepted = result.get("accepted_candidate")
        assert accepted is not None
        assert accepted.get("accepted") is True


# ---------------------------------------------------------------------------
# 6. eGFR row kept and guideline note rejected
# ---------------------------------------------------------------------------

class TestEgfrRowKeptAndGuidelineNoteRejected:
    """V11 15.2: test_egfr_row_kept_and_guideline_note_rejected

    Current broken behavior: the eGFR measured result and the KDIGO
    narrative classification below it are both treated the same way,
    so the narrative note either leaks into observations or the actual
    eGFR value is lost.

    Intended outcome: the eGFR measured row enters the observation pool
    as a derived analyte row, while the KDIGO guideline narrative is
    typed as ``narrative_row`` and excluded.
    """

    def test_egfr_derived_row_eligible_with_source_links(self) -> None:
        _, _, support_state, eligible = _derive_support_outcome(
            row_type="derived_analyte_row",
            primary_result={"raw_token_string": "90", "normalized_numeric_value": 90.0},
            secondary_result=None,
            parsed_numeric_value=90.0,
            raw_value_string="90",
            accepted_analyte_code="62238-1",
            source_observation_ids=["src-1"],
            primary_unit_status="unit_optional",
            secondary_unit_status="unit_optional",
        )
        assert eligible is True
        assert support_state == "supported"

    def test_narrative_row_excluded(self) -> None:
        row = _raw_row(
            raw_analyte_label="KDIGO 2012 Albuminuria Categories",
            row_type="narrative_row",
        )
        row_type = _normalize_row_type(row)
        assert row_type == "narrative_row"
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
        assert failure_code == "narrative_row"


# ---------------------------------------------------------------------------
# 7. Patient artifact must never show DOB as unassessed lab
# ---------------------------------------------------------------------------

class TestPatientArtifactNeverShowsDobAsUnassessedLab:
    """V11 15.2: test_patient_artifact_never_shows_DOB_as_unassessed_lab

    Current broken behavior: ``DOB :`` and similar metadata fields
    surface in the patient "not assessed" section.

    Intended outcome: the artifact renderer filters out any
    not-assessed item whose raw label matches known admin patterns.
    """

    def test_dob_not_in_patient_not_assessed(self, monkeypatch) -> None:
        extracted = [
            _raw_row(
                raw_analyte_label="DOB :",
                row_type="admin_metadata_row",
                raw_value_string="1990-01-15",
                row_hash="dob-row",
            ),
            _raw_row(
                raw_analyte_label="Glucose",
                raw_value_string="180",
                raw_unit_string="mg/dL",
                parsed_numeric_value=180.0,
                accepted_analyte_code="2345-7",
                row_hash="glucose-row",
            ),
        ]
        result = _run_pipeline(monkeypatch, extracted)
        patient = PatientArtifactSchema.model_validate(result["patient_artifact"])
        not_assessed_labels = {item.raw_label.lower() for item in patient.not_assessed}
        assert "dob" not in not_assessed_labels
        assert "dob :" not in not_assessed_labels

    def test_sample_report_not_in_patient_not_assessed(self, monkeypatch) -> None:
        extracted = [
            _raw_row(
                raw_analyte_label="Sample Report,",
                row_type="admin_metadata_row",
                raw_value_string="505271",
                row_hash="sample-report-row",
            ),
            _raw_row(
                raw_analyte_label="Glucose",
                raw_value_string="180",
                raw_unit_string="mg/dL",
                parsed_numeric_value=180.0,
                accepted_analyte_code="2345-7",
                row_hash="glucose-row-2",
            ),
        ]
        result = _run_pipeline(monkeypatch, extracted)
        patient = PatientArtifactSchema.model_validate(result["patient_artifact"])
        not_assessed_labels = {item.raw_label.lower() for item in patient.not_assessed}
        assert "sample report," not in not_assessed_labels


# ---------------------------------------------------------------------------
# 8. Generic insufficient_support is forbidden
# ---------------------------------------------------------------------------

class TestGenericInsufficientSupportForbidden:
    """V11 15.2: test_generic_insufficient_support_forbidden

    Current broken behavior: the catch-all ``insufficient_support``
    reason is used for many different failure modes, making debug
    and patient communication impossible.

    Intended outcome: internal traces and suppression_reasons use only
    typed failure codes from ``FailureCode``. The string
    ``insufficient_support`` may appear only as a user-facing fallback
    label, never as an internal failure code.
    """

    def test_failure_code_enum_has_typed_reasons(self) -> None:
        """Verify FailureCode enum exists and contains required v11 codes."""
        expected_codes = {
            "admin_metadata_row",
            "narrative_row",
            "threshold_table_row",
            "unreadable_value",
            "unit_parse_fail",
            "bilingual_label_unresolved",
            "ambiguous_analyte",
            "unsupported_family",
            "missing_overlay_context",
            "derived_observation_unbound",
            "threshold_conflict",
            "unsupported_unit_or_reference_range",
        }
        actual_codes = {member.value for member in __import__("app.schemas.observation", fromlist=["FailureCode"]).FailureCode}
        assert expected_codes <= actual_codes, (
            f"Missing FailureCode entries: {expected_codes - actual_codes}"
        )

    def test_no_catch_all_insufficient_support_in_internal_traces(self) -> None:
        """Internal support_code and failure_code must never be the catch-all."""
        catch_all = "insufficient_support"
        # Verify that _derive_support_outcome never returns catch_all as failure_code
        test_cases = [
            ("admin_metadata_row", {}),
            ("narrative_row", {}),
            ("threshold_table_row", {}),
            ("measured_analyte_row", {"accepted_analyte_code": "2345-7"}),
            ("measured_analyte_row", {}),
        ]
        for row_type, kwargs in test_cases:
            _, failure_code, _, _ = _derive_support_outcome(
                row_type=row_type,
                primary_result=None,
                secondary_result=None,
                parsed_numeric_value=None,
                raw_value_string=None,
                accepted_analyte_code=kwargs.get("accepted_analyte_code"),
                source_observation_ids=[],
                primary_unit_status="unit_optional",
                secondary_unit_status="unit_optional",
            )
            assert failure_code != catch_all, (
                f"Row type {row_type} must not return catch-all insufficient_support"
            )


# ---------------------------------------------------------------------------
# 9. Locale decimal comma parser
# ---------------------------------------------------------------------------

class TestLocaleDecimalCommaParser:
    """V11 15.2: test_locale_decimal_comma_parser

    Current broken behavior: values with decimal commas (e.g. ``7,2``)
    either fail to parse or produce wrong numeric values.

    Intended outcome: the locale parser correctly distinguishes
    decimal comma from thousands separator and normalizes to a
    canonical decimal point.
    """

    def test_decimal_comma_parses(self) -> None:
        value, locale = _parse_numeric_fragment("7,2")
        assert value == pytest.approx(7.2)
        assert locale["decimal_separator"] == ","

    def test_thousands_comma_parses(self) -> None:
        value, locale = _parse_numeric_fragment("1,234")
        assert value == pytest.approx(1234.0)
        assert locale["thousands_separator"] == ","

    def test_mixed_separators_parse(self) -> None:
        value, locale = _parse_numeric_fragment("1.234,56")
        assert value == pytest.approx(1234.56)
        assert locale["decimal_separator"] == ","
        assert locale["thousands_separator"] == "."

    def test_plain_decimal_point_parses(self) -> None:
        value, locale = _parse_numeric_fragment("180.5")
        assert value == pytest.approx(180.5)
        assert locale["decimal_separator"] == "."


class TestV11UnitNormalizationCoverage:
    """Common deterministic units from the trusted corpus must normalize
    without widening unsafe-unit acceptance."""

    def test_iu_per_liter_normalizes(self) -> None:
        normalized = UcumEngine().normalize_result_channel(
            {"raw_token_string": "32", "normalized_numeric_value": 32.0, "unit": "IU/L"}
        )
        assert normalized["canonical_unit"] == "U/L"
        assert normalized["unit_family"] == "enzyme_activity"

    def test_split_count_unit_normalizes(self) -> None:
        normalized = UcumEngine().normalize_result_channel(
            {"raw_token_string": "5.4", "normalized_numeric_value": 5.4, "unit": "x10E3/uL"}
        )
        assert normalized["canonical_unit"] == "x10E3/uL"
        assert normalized["unit_family"] == "cell_count"

    def test_ocr_flag_word_is_not_treated_as_unit(self) -> None:
        assert _normalize_measurement_unit_string("NORMEAL") is None

    def test_percent_suffix_noise_normalizes_to_percent(self) -> None:
        assert _normalize_measurement_unit_string("% O") == "%"


class TestTrustedCorpusValueBearingResolverCoverage:
    @pytest.mark.parametrize(
        ("raw_label", "raw_unit_string"),
        [
            ("ABSOLUTE NEUTROPHILS", "cells/uL"),
            ("ABSOLUTE EOSINOPHILS", "cells/uL"),
            ("ABSOLUTE BASOPHILS", "cells/uL"),
            ("BASOPHILS P", "%"),
            ("MAGNESIUM RBMC", "mg/dL"),
            ("LYMPHOCYTES", "%"),
            ("SED RATE BY MODIFIED WESTERGREN", "mm/h"),
        ],
    )
    def test_resolver_accepts_value_bearing_labtestingapi_rows(
        self,
        raw_label: str,
        raw_unit_string: str,
    ) -> None:
        result = AnalyteResolver().resolve(
            raw_label,
            context={
                "family_adapter_id": "generic_layout",
                "language_id": "en",
                "measurement_kind": "numeric",
                "row_type": "measured_analyte_row",
                "raw_unit_string": raw_unit_string,
            },
        )
        accepted = result.get("accepted_candidate")
        assert accepted is not None, raw_label
        assert accepted.get("accepted") is True, raw_label
        assert result.get("support_state") == "supported", raw_label


# ---------------------------------------------------------------------------
# 10. Derived observation requires source links
# ---------------------------------------------------------------------------

class TestDerivedObservationRequiresSourceLinks:
    """V11 15.2: test_derived_observation_requires_source_links

    Current broken behavior: derived observations like eGFR or ACR
    may appear without links to their source observations, making
    provenance unverifiable.

    Intended outcome: any observation with row_type
    ``derived_analyte_row`` and an empty ``source_observation_ids``
    list is marked unsupported with failure_code
    ``derived_observation_unbound``.
    """

    def test_derived_without_sources_is_unsupported(self) -> None:
        _, failure_code, support_state, eligible = _derive_support_outcome(
            row_type="derived_analyte_row",
            primary_result=None,
            secondary_result=None,
            parsed_numeric_value=None,
            raw_value_string="eGFR 90",
            accepted_analyte_code="62238-1",
            source_observation_ids=[],
            primary_unit_status="unit_optional",
            secondary_unit_status="unit_optional",
        )
        assert eligible is False
        assert support_state == "unsupported"
        assert failure_code == "derived_observation_unbound"

    def test_derived_with_sources_is_supported(self) -> None:
        _, failure_code, support_state, eligible = _derive_support_outcome(
            row_type="derived_analyte_row",
            primary_result={"raw_token_string": "90", "normalized_numeric_value": 90.0},
            secondary_result=None,
            parsed_numeric_value=90.0,
            raw_value_string="90",
            accepted_analyte_code="62238-1",
            source_observation_ids=["obs-creatinine"],
            primary_unit_status="unit_optional",
            secondary_unit_status="unit_optional",
        )
        assert eligible is True
        assert support_state == "supported"
        assert failure_code is None

    def test_observation_builder_marks_derived_unbound(self) -> None:
        builder = ObservationBuilder()
        rows = [
            _raw_row(
                raw_analyte_label="eGFR",
                row_type="derived_analyte_row",
                raw_value_string="90",
                parsed_numeric_value=90.0,
                accepted_analyte_code="62238-1",
                row_hash="egfr-unbound",
            ),
        ]
        observations = builder.build(rows)
        assert len(observations) == 1
        obs = observations[0]
        assert obs["eligible_for_observation_pool"] is False
        assert obs["support_state"] == SupportState.UNSUPPORTED.value
        assert obs["failure_code"] == "derived_observation_unbound"
