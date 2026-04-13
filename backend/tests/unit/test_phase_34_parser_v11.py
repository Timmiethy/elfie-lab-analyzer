"""V11 parser core: row-typing, bilingual merge, threshold rejection, admin leak prevention."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.services.extraction_qa import ExtractionQA
from app.services.parser import (
    TrustedPdfParser,
    _extract_reference_range,
    _is_admin,
    _is_derived,
    _is_location_line,
    _is_narrative,
    _is_noise_line,
    _is_threshold,
    _normalize_numeric_string,
    _normalize_text,
    classify_candidate_text,
    parse_measurement_text,
)

ROOT = Path(__file__).resolve().parents[3]
PDF_DIR = ROOT / "pdfs_by_difficulty"


def _load_pdf(relative_path: str) -> bytes:
    return (PDF_DIR / relative_path).read_bytes()


# ---------------------------------------------------------------------------
# 1. Admin / narrative / threshold / header rows are typed and excluded
# ---------------------------------------------------------------------------

class TestAdminLeakPrevention:
    """Admin metadata, narrative, threshold, and header rows must never
    reach the observation pool.  They are typed as excluded at the parser
    level so that ExtractionQA rejects them before normalization."""

    _ADMIN_LINES = [
        "DOB : 01/01/1980",
        "DOB: 01/01/1980",
        "Collected : 10/05/2025 08:30",
        "Date Collected: 10/05/2025 08:30",
        "Report Printed : 10/05/2025 14:00",
        "Ref : 12345",
        "Patient Details",
        "lab no 67890",
        "sex/age",
    ]

    _NARRATIVE_LINES = [
        "Result should be interpreted alongside clinical presentation",
        "These results should be interpreted in the context of the patient",
        "Source: KDIGO 2012",
        "Note: this test is not valid for screening purposes",
    ]

    _THRESHOLD_LINES = [
        "Normal IFG (Prediabetes) DM",
        "Normal IFG (Prediabetes) T2DM",
        "Optimal Moderate High Very High N/A",
        "biological ref. interval",
        "a-d:  reference interval table",
    ]

    _HEADER_LINES = [
        "Page 1 of 4",
        "Page 1",
        "Laboratory Report",
        "analytes results units ref. ranges",
    ]

    _NOISE_LINES = [
        "Analyte",
        "Reference range",
        "Test Result",
        "result units",
    ]

    @pytest.mark.parametrize("line", _ADMIN_LINES)
    def test_admin_lines_are_typed_admin_metadata_row(self, line: str) -> None:
        result = classify_candidate_text(
            line,
            page_class="analyte_table_page",
            family_adapter_id="innoquest_bilingual_general",
        )
        assert result["row_type"] == "admin_metadata_row", f"{line!r} -> {result['row_type']}"
        assert result["is_excluded"] is True

    @pytest.mark.parametrize("line", _NARRATIVE_LINES)
    def test_narrative_lines_are_typed_narrative_guidance_row(self, line: str) -> None:
        result = classify_candidate_text(
            line,
            page_class="analyte_table_page",
            family_adapter_id="innoquest_bilingual_general",
        )
        assert result["row_type"] == "narrative_guidance_row", f"{line!r} -> {result['row_type']}"
        assert result["is_excluded"] is True

    @pytest.mark.parametrize("line", _THRESHOLD_LINES)
    def test_threshold_lines_are_typed_threshold_reference_row(self, line: str) -> None:
        result = classify_candidate_text(
            line,
            page_class="analyte_table_page",
            family_adapter_id="innoquest_bilingual_general",
        )
        assert result["row_type"] == "threshold_reference_row", f"{line!r} -> {result['row_type']}"
        assert result["is_excluded"] is True

    @pytest.mark.parametrize("line", _HEADER_LINES)
    def test_header_lines_are_typed_header_footer_row(self, line: str) -> None:
        result = classify_candidate_text(
            line,
            page_class="analyte_table_page",
            family_adapter_id="innoquest_bilingual_general",
        )
        assert result["row_type"] == "header_footer_row", f"{line!r} -> {result['row_type']}"
        assert result["is_excluded"] is True

    @pytest.mark.parametrize("line", _NOISE_LINES)
    def test_noise_lines_are_excluded(self, line: str) -> None:
        result = classify_candidate_text(
            line,
            page_class="analyte_table_page",
            family_adapter_id="innoquest_bilingual_general",
        )
        assert result["is_excluded"] is True


# ---------------------------------------------------------------------------
# 2. Extraction QA enforces leak prevention
# ---------------------------------------------------------------------------

class TestExtractionQALeakPrevention:
    """ExtractionQA must reject non-measured rows before normalization."""

    def _make_row(self, raw_text: str, row_type: str, failure_code: str | None = None) -> dict:
        return {
            "row_hash": f"hash-{raw_text}",
            "raw_text": raw_text,
            "raw_analyte_label": raw_text.split()[0] if raw_text.split() else None,
            "raw_value_string": None,
            "raw_unit_string": None,
            "raw_reference_range": None,
            "parsed_numeric_value": None,
            "row_type": row_type,
            "failure_code": failure_code,
            "page_class": "analyte_table_page",
            "family_adapter_id": "innoquest_bilingual_general",
            "source_observation_ids": [],
        }

    def test_admin_rows_rejected_by_qa(self) -> None:
        qa = ExtractionQA()
        rows = [
            self._make_row("DOB : 01/01/1980", "admin_metadata_row", "admin_metadata_row"),
            self._make_row("Collected : 10/05/2025", "admin_metadata_row", "admin_metadata_row"),
        ]
        result = qa.validate(rows)
        assert result["passed"] is False
        assert result["metrics"]["clean_rows"] == 0
        assert result["metrics"]["rejected_rows"] == 2
        for rejection in result["rejected_rows"]:
            assert "admin" in rejection["reason"]

    def test_threshold_rows_rejected_by_qa(self) -> None:
        qa = ExtractionQA()
        rows = [
            self._make_row("Normal IFG Prediabetes DM", "threshold_reference_row", "threshold_reference_row"),
            self._make_row("KDIGO 2012 Albuminuria Categories", "threshold_reference_row", "threshold_reference_row"),
        ]
        result = qa.validate(rows)
        assert result["passed"] is False
        assert result["metrics"]["clean_rows"] == 0
        assert result["metrics"]["rejected_rows"] == 2

    def test_narrative_rows_rejected_by_qa(self) -> None:
        qa = ExtractionQA()
        rows = [
            self._make_row(
                "Result should be interpreted alongside clinical presentation",
                "narrative_guidance_row",
                "narrative_guidance_row",
            ),
        ]
        result = qa.validate(rows)
        assert result["passed"] is False
        assert result["metrics"]["clean_rows"] == 0
        assert result["metrics"]["rejected_rows"] == 1

    def test_measured_rows_pass_qa(self) -> None:
        qa = ExtractionQA()
        rows = [
            {
                "row_hash": "hash-glucose",
                "raw_text": "Glucose 180 mg/dL",
                "raw_analyte_label": "Glucose",
                "raw_value_string": "180",
                "raw_unit_string": "mg/dL",
                "raw_reference_range": "70-99",
                "parsed_numeric_value": 180.0,
                "row_type": "measured_analyte_row",
                "failure_code": None,
                "page_class": "analyte_table_page",
                "family_adapter_id": "innoquest_bilingual_general",
                "source_observation_ids": [],
            },
        ]
        result = qa.validate(rows)
        assert result["passed"] is True
        assert result["metrics"]["clean_rows"] == 1
        assert result["metrics"]["rejected_rows"] == 0


# ---------------------------------------------------------------------------
# 3. Innoquest bilingual row merge
# ---------------------------------------------------------------------------

class TestInnoquestBilingualRowMerge:
    """The innoquest_bilingual_general adapter must merge English label +
    Chinese alias + value + unit + range across small y drift."""

    def test_sodium_bilingual_row_parsed(self) -> None:
        result = parse_measurement_text(
            "Sodium 钠 141 mmol/L (135-145)",
            page_class="analyte_table_page",
            family_adapter_id="innoquest_bilingual_general",
        )
        assert result["row_type"] == "measured_analyte_row"
        assert result["raw_analyte_label"] is not None
        assert result["parsed_numeric_value"] == pytest.approx(141.0)
        assert result["raw_unit_string"] is not None
        assert "mmol" in result["raw_unit_string"].lower()

    def test_creatinine_bilingual_row_parsed(self) -> None:
        result = parse_measurement_text(
            "Creatinine 肌酸酐 95 umol/L (60-110)",
            page_class="analyte_table_page",
            family_adapter_id="innoquest_bilingual_general",
        )
        assert result["row_type"] == "measured_analyte_row"
        assert result["parsed_numeric_value"] == pytest.approx(95.0)

    def test_glucose_bilingual_row_parsed(self) -> None:
        result = parse_measurement_text(
            "Glucose 葡萄糖 5.6 mmol/L (3.9-6.1)",
            page_class="analyte_table_page",
            family_adapter_id="innoquest_bilingual_general",
        )
        assert result["row_type"] == "measured_analyte_row"
        assert result["parsed_numeric_value"] == pytest.approx(5.6)

    def test_hba1c_dual_unit_row_parsed(self) -> None:
        result = parse_measurement_text(
            "HbA1c 葡萄糖血红蛋白 6.8% 51 mmol/mol",
            page_class="analyte_table_page",
            family_adapter_id="innoquest_bilingual_general",
        )
        assert result["row_type"] == "measured_analyte_row"
        assert result["parsed_numeric_value"] == pytest.approx(6.8)
        assert result["secondary_result"] is not None

    def test_acr_comparator_first_row_parsed(self) -> None:
        result = parse_measurement_text(
            "ACR < 0.1 mg Alb/mmol < 3.5",
            page_class="analyte_table_page",
            family_adapter_id="innoquest_bilingual_general",
        )
        assert result["row_type"] == "measured_analyte_row"
        assert result["parsed_numeric_value"] == pytest.approx(0.1)
        assert result["parsed_comparator"] == "<"

    def test_egfr_row_parsed_not_narrative(self) -> None:
        result = parse_measurement_text(
            "eGFR 92 mL/min/1.73 m2",
            page_class="analyte_table_page",
            family_adapter_id="innoquest_bilingual_general",
        )
        # eGFR should be a measured or derived analyte row, NOT narrative
        assert result["row_type"] in {"measured_analyte_row", "derived_analyte_row"}
        assert result["row_type"] not in {
            "narrative_guidance_row",
            "admin_metadata_row",
            "threshold_reference_row",
            "header_footer_row",
        }


# ---------------------------------------------------------------------------
# 4. Threshold table rejection
# ---------------------------------------------------------------------------

class TestThresholdTableRejection:
    """Threshold table rows must be typed as threshold_reference_row and
    excluded before normalization."""

    def test_glucose_category_table_rejected(self) -> None:
        result = classify_candidate_text(
            "Normal IFG (Prediabetes) DM",
            page_class="analyte_table_page",
            family_adapter_id="innoquest_bilingual_general",
        )
        assert result["row_type"] == "threshold_reference_row"
        assert result["is_excluded"] is True

    def test_hba1c_category_table_rejected(self) -> None:
        result = classify_candidate_text(
            "Normal IFG (Prediabetes) T2DM",
            page_class="analyte_table_page",
            family_adapter_id="innoquest_bilingual_general",
        )
        assert result["row_type"] == "threshold_reference_row"
        assert result["is_excluded"] is True

    def test_kdigo_table_rejected(self) -> None:
        result = classify_candidate_text(
            "KDIGO 2012 Albuminuria Categories",
            page_class="analyte_table_page",
            family_adapter_id="innoquest_bilingual_general",
        )
        assert result["row_type"] in {
            "threshold_reference_row",
            "narrative_guidance_row",
            "admin_metadata_row",
        }
        assert result["is_excluded"] is True

    def test_threshold_measurement_label_rejected(self) -> None:
        result = classify_candidate_text(
            "glucose levels 6.1 - 6.9 mmol/L.",
            page_class="analyte_table_page",
            family_adapter_id="innoquest_bilingual_general",
        )
        assert result["row_type"] == "threshold_reference_row"
        assert result["is_excluded"] is True

    def test_bmi_category_threshold_row_rejected(self) -> None:
        result = classify_candidate_text(
            "Overweight >=25.0 23.0 to 27.4",
            page_class="analyte_table_page",
            family_adapter_id="innoquest_bilingual_general",
        )
        assert result["row_type"] == "threshold_reference_row"
        assert result["is_excluded"] is True

    def test_reference_interval_table_rejected(self) -> None:
        result = classify_candidate_text(
            "biological ref. interval",
            page_class="analyte_table_page",
            family_adapter_id="innoquest_bilingual_general",
        )
        assert result["is_excluded"] is True


# ---------------------------------------------------------------------------
# 5. Parser emits typed candidate rows on real PDFs
# ---------------------------------------------------------------------------

class TestParserEmitsTypedRows:
    """The parser must emit typed candidate rows (with row_type) when
    processing real PDFs."""

    def test_easy_innoquest_pdf_emits_typed_rows(self) -> None:
        parser = TrustedPdfParser()
        rows = asyncio.run(
            parser.parse(_load_pdf("easy/seed_innoquest_dbticbm.pdf"))
        )
        assert len(rows) > 0, "Expected at least one row from the easy Innoquest PDF"

        row_types = {row["row_type"] for row in rows}
        assert "measured_analyte_row" in row_types or "derived_analyte_row" in row_types, (
            f"Expected at least one measured or derived row, got: {row_types}"
        )

        # Every row must have a row_type
        for row in rows:
            assert "row_type" in row, f"Row missing row_type: {row.get('raw_text', '')}"

    def test_medium_bilingual_pdf_emits_typed_rows(self) -> None:
        parser = TrustedPdfParser()
        rows = asyncio.run(
            parser.parse(_load_pdf("medium/seed_innoquest_bilingual_2dbtica.pdf"))
        )
        assert len(rows) > 0, "Expected at least one row from the medium bilingual PDF"

        row_types = {row["row_type"] for row in rows}
        assert "measured_analyte_row" in row_types or "derived_analyte_row" in row_types, (
            f"Expected at least one measured or derived row, got: {row_types}"
        )

    def test_hard_mixed_page_order_pdf_emits_typed_rows(self) -> None:
        parser = TrustedPdfParser()
        rows = asyncio.run(
            parser.parse(
                _load_pdf("hard/var_innoquest_cardiometabolic_mixed_page_order.pdf")
            )
        )
        assert len(rows) > 0, "Expected at least one row from the hard mixed page order PDF"

        row_types = {row["row_type"] for row in rows}
        assert "measured_analyte_row" in row_types or "derived_analyte_row" in row_types, (
            f"Expected at least one measured or derived row, got: {row_types}"
        )

    def test_qa_rejects_non_measured_rows_from_real_pdf(self) -> None:
        """After parsing a real PDF, running through ExtractionQA should
        only keep measured/derived analyte rows."""
        parser = TrustedPdfParser()
        rows = asyncio.run(
            parser.parse(_load_pdf("easy/seed_innoquest_dbticbm.pdf"))
        )
        qa = ExtractionQA()
        result = qa.validate(rows)

        # The clean rows must only be measured or derived
        for row in result["clean_rows"]:
            assert row["row_type"] in {"measured_analyte_row", "derived_analyte_row"}, (
                f"Clean row should be measured or derived: {row['row_type']} "
                f"for text: {row.get('raw_text', '')}"
            )

    def test_parser_rows_have_family_adapter_id(self) -> None:
        parser = TrustedPdfParser()
        rows = asyncio.run(
            parser.parse(_load_pdf("easy/seed_innoquest_dbticbm.pdf"))
        )
        for row in rows:
            assert "family_adapter_id" in row, f"Row missing family_adapter_id: {row.get('raw_text', '')}"


# ---------------------------------------------------------------------------
# 6. Locale / numeric parsing
# ---------------------------------------------------------------------------

class TestLocaleNumericParsing:
    """The locale parser must handle decimal points, decimal commas, and
    thousands separators."""

    def test_decimal_point(self) -> None:
        value, locale = _normalize_numeric_string("5.6")
        assert value == "5.6"
        assert locale["decimal_separator"] == "."

    def test_decimal_comma(self) -> None:
        value, locale = _normalize_numeric_string("5,6")
        assert value == "5.6"
        assert locale["decimal_separator"] == ","

    def test_thousands_comma(self) -> None:
        value, locale = _normalize_numeric_string("1,234")
        assert value == "1234"
        assert locale["thousands_separator"] == ","

    def test_thousands_dot(self) -> None:
        value, locale = _normalize_numeric_string("1.234")
        assert value == "1234"
        assert locale["thousands_separator"] == "."

    def test_mixed_separator_european(self) -> None:
        value, locale = _normalize_numeric_string("1.234,56")
        assert value == "1234.56"
        assert locale["decimal_separator"] == ","
        assert locale["thousands_separator"] == "."

    def test_mixed_separator_us(self) -> None:
        value, locale = _normalize_numeric_string("1,234.56")
        assert value == "1234.56"
        assert locale["decimal_separator"] == "."
        assert locale["thousands_separator"] == ","


class TestTabularValueSelection:
    """Tabular rows must choose the measurement token near the unit/range,
    not the first incidental number in the label."""

    def test_labcorp_count_row_chooses_measurement_value(self) -> None:
        result = parse_measurement_text(
            "WBC 02 5.4 x10E3/uL 3.4-10.8",
            page_class="analyte_table_page",
            family_adapter_id="generic_layout",
        )
        assert result["raw_analyte_label"] == "WBC"
        assert result["raw_value_string"] == "5.4"
        assert result["parsed_numeric_value"] == pytest.approx(5.4)
        assert result["raw_unit_string"] == "x10E3/uL"
        assert result["raw_reference_range"] == "3.4-10.8"

    def test_flagged_result_keeps_measured_value_not_reference(self) -> None:
        result = parse_measurement_text(
            "Glucose 115 H 65-99 mg/dL",
            page_class="analyte_table_page",
            family_adapter_id="generic_layout",
        )
        assert result["raw_analyte_label"] == "Glucose"
        assert result["raw_value_string"] == "115"
        assert result["parsed_numeric_value"] == pytest.approx(115.0)
        assert result["raw_unit_string"] == "mg/dL"
        assert result["raw_reference_range"] == "65-99 mg/dL"

    def test_reference_comparator_after_value_does_not_replace_measurement(self) -> None:
        result = parse_measurement_text(
            "Triglycerides 45 <150 mg/dL",
            page_class="analyte_table_page",
            family_adapter_id="generic_layout",
        )
        assert result["raw_analyte_label"] == "Triglycerides"
        assert result["raw_value_string"] == "45"
        assert result["parsed_numeric_value"] == pytest.approx(45.0)
        assert result["raw_unit_string"] == "mg/dL"
        assert result["raw_reference_range"] == "<150 mg/dL"

    def test_or_equal_reference_phrase_keeps_primary_measurement(self) -> None:
        result = parse_measurement_text(
            "HDL Cholesterol 81 > OR = 46 mg/dL",
            page_class="analyte_table_page",
            family_adapter_id="generic_layout",
        )
        assert result["raw_analyte_label"] == "HDL Cholesterol"
        assert result["raw_value_string"] == "81"
        assert result["parsed_numeric_value"] == pytest.approx(81.0)
        assert result["raw_unit_string"] == "mg/dL"
        assert result["raw_reference_range"] == "> OR = 46 mg/dL"

    def test_a1c_label_is_not_misread_as_flagged_numeric_value(self) -> None:
        result = parse_measurement_text(
            "Hemoglobin A1c 6.1 H <5.7 % of total Hgb",
            page_class="analyte_table_page",
            family_adapter_id="generic_layout",
        )
        assert result["raw_analyte_label"] == "Hemoglobin A1c"
        assert result["raw_value_string"] == "6.1"
        assert result["parsed_numeric_value"] == pytest.approx(6.1)
        assert result["raw_unit_string"] == "%"
        assert result["raw_reference_range"] == "<5.7 % of total Hgb"
        assert result["secondary_result"] is None

    def test_note_suffix_and_footnote_do_not_create_secondary_result(self) -> None:
        result = parse_measurement_text(
            "Non-HDL Cholesterol 83 mg/dL (calc) See Note 4",
            page_class="analyte_table_page",
            family_adapter_id="generic_layout",
        )
        assert result["raw_analyte_label"] == "Non-HDL Cholesterol"
        assert result["raw_value_string"] == "83"
        assert result["parsed_numeric_value"] == pytest.approx(83.0)
        assert result["raw_unit_string"] == "mg/dL"
        assert result["secondary_result"] is None

    def test_split_reference_range_is_not_treated_as_secondary_unit(self) -> None:
        result = parse_measurement_text(
            "Fasting Plasma Glucose 6.5 mmol/L (4.1 -6.1)",
            page_class="analyte_table_page",
            family_adapter_id="innoquest_bilingual_general",
        )
        assert result["raw_analyte_label"] == "Fasting Plasma Glucose"
        assert result["raw_value_string"] == "6.5"
        assert result["raw_unit_string"] == "mmol/L"
        assert result["raw_reference_range"] == "4.1 -6.1"
        assert result["secondary_result"] is None


class TestExpandedAdminSuppression:
    """Real corpus admin lines must be rejected before observation building."""

    @pytest.mark.parametrize(
        ("line"),
        [
            "Requisition: 0046280 DOE, JANE",
            "Reported: 04/28/2014 / 17:59 EDT",
            "RECEIVED: 2019/02/14 12:55 R Room 912, 9th Floor",
            "Ordering Physician: Test Doctor",
        ],
    )
    def test_real_corpus_admin_lines_are_excluded(self, line: str) -> None:
        result = classify_candidate_text(
            line,
            page_class="mixed_page",
            family_adapter_id="generic_layout",
        )
        assert result["is_excluded"] is True
        assert result["row_type"] == "admin_metadata_row"


# ---------------------------------------------------------------------------
# 7. Derived observation requires source links
# ---------------------------------------------------------------------------

class TestDerivedObservationRequiresSourceLinks:
    """Derived analyte rows without source observation IDs must be typed
    as having a derived_observation_unbound failure code."""

    def test_derived_row_without_source_links_has_failure_code(self) -> None:
        result = classify_candidate_text(
            "eGFR",
            page_class="analyte_table_page",
            family_adapter_id="innoquest_bilingual_general",
        )
        assert result["row_type"] == "derived_analyte_row"
        assert result["failure_code"] == "derived_observation_unbound"

    def test_generic_derived_row_without_source_links_partial(self) -> None:
        result = classify_candidate_text(
            "eGFR",
            page_class="analyte_table_page",
            family_adapter_id="generic_layout",
        )
        # Generic adapter should still mark as derived but without the specific failure
        assert result["row_type"] == "derived_analyte_row"


# ---------------------------------------------------------------------------
# 8. Reference range extraction
# ---------------------------------------------------------------------------

class TestReferenceRangeExtraction:
    """Reference ranges must be correctly extracted from text."""

    def test_simple_range(self) -> None:
        assert _extract_reference_range("Glucose 180 mg/dL (70-99)") == "70-99"

    def test_range_without_parens(self) -> None:
        result = _extract_reference_range("Glucose 180 mg/dL 70-99")
        assert result == "70-99"

    def test_no_range(self) -> None:
        assert _extract_reference_range("Glucose 180 mg/dL") is None

    def test_comparator_range(self) -> None:
        result = _extract_reference_range("ACR < 0.1 mg Alb/mmol < 3.5")
        assert result is not None


# ---------------------------------------------------------------------------
# 9. Wave-4 resolver alias coverage for real-corpus row shapes
# ---------------------------------------------------------------------------

class TestWave4ResolverAliasCoverage:
    """Regression tests for the exact row shapes that caused supported text
    PDFs to stay partial in the v11 corpus report (2026-04-12)."""

    _LAUNCH_SCOPE_RESOLVABLE = [
        # Labcorp CBC / CD4/CD8 family
        ("wbc", "cbc"),
        ("white blood cell count", "cbc"),
        ("rbc", "cbc"),
        ("red blood cell count", "cbc"),
        ("hemoglobin", "cbc"),
        ("hgb", "cbc"),
        ("hematocrit", "cbc"),
        ("hct", "cbc"),
        ("platelet count", "cbc"),
        ("platelets", "cbc"),
        ("plt", "cbc"),
        ("mcv", "cbc"),
        ("mch", "cbc"),
        ("mchc", "cbc"),
        ("rdw", "cbc"),
        ("mpv", "cbc"),
        ("neutrophils", "cbc_diff"),
        ("neut", "cbc_diff"),
        ("lymphocytes", "cbc_diff"),
        ("lymph", "cbc_diff"),
        ("monocytes", "cbc_diff"),
        ("mono", "cbc_diff"),
        ("eosinophils", "cbc_diff"),
        ("eos", "cbc_diff"),
        ("basophils", "cbc_diff"),
        ("baso", "cbc_diff"),
        ("cd4", "immunology"),
        ("cd4 cells", "immunology"),
        ("cd4 count", "immunology"),
        ("cd8", "immunology"),
        ("cd8 cells", "immunology"),
        ("cd8 count", "immunology"),
        ("cd4/cd8 ratio", "immunology"),
        # Quest diabetes panel lipid variants
        ("ldl-c", "lipid"),
        ("ldl calculated", "lipid"),
        ("ldl-c calculated", "lipid"),
        ("non-hdl cholesterol", "lipid"),
        ("non-hdl-c", "lipid"),
        ("hdl-c", "lipid"),
        ("hdl", "lipid"),
        ("triglycerides", "lipid"),
        ("vldl", "lipid"),
        ("vldl cholesterol", "lipid"),
        ("total cholesterol/hdl ratio", "lipid"),
        ("chol/hdl ratio", "lipid"),
        # LabTestingAPI broad chemistry
        ("total bilirubin", "liver"),
        ("bilirubin", "liver"),
        ("alkaline phosphatase", "liver"),
        ("alp", "liver"),
        ("total protein", "chemistry"),
        ("albumin", "chemistry"),
        ("globulin", "chemistry"),
        ("a/g ratio", "chemistry"),
        ("calcium", "chemistry"),
        ("carbon dioxide", "electrolyte"),
        ("co2", "electrolyte"),
        ("bicarbonate", "electrolyte"),
    ]

    @pytest.mark.parametrize("label,expected_panel", _LAUNCH_SCOPE_RESOLVABLE)
    def test_wave4_alias_maps_to_accepted_candidate(
        self, label: str, expected_panel: str
    ) -> None:
        from app.services.analyte_resolver import AnalyteResolver

        resolver = AnalyteResolver()
        result = resolver.resolve(label, context={"family_adapter_id": "generic_layout"})
        accepted = result.get("accepted_candidate")
        assert accepted is not None, (
            f"{label!r} should resolve to an accepted candidate, "
            f"got support_state={result['support_state']}, "
            f"abstention_reasons={result['abstention_reasons']}"
        )


# ---------------------------------------------------------------------------
# 10. Mixed-row suppression: height / blood-pressure / note-threshold hybrids
# ---------------------------------------------------------------------------

class TestMixedRowSuppression:
    """Parser row-typing must exclude mixed narrative/threshold rows
    and non-lab-vitals rows from the measured-analyte pool."""

    _EXCLUDED_MIXED_ROWS = [
        ("Height 170 cm Weight 75 kg", "admin_metadata_row"),
        ("Blood pressure 120/80 mmHg", "admin_metadata_row"),
        ("BP 130/85", "admin_metadata_row"),
        ("Heart rate 72 bpm", "admin_metadata_row"),
        ("Temperature 36.8 C", "admin_metadata_row"),
        ("Note: Fasting sample required", "narrative_guidance_row"),
        ("Note 1: Sample hemolyzed", "narrative_guidance_row"),
        ("See note 2 for methodology", "narrative_guidance_row"),
        ("Normal IFG (Prediabetes) DM", "threshold_reference_row"),
        ("Optimal Moderate High Very High", "threshold_reference_row"),
        ("KDIGO 2012 Albuminuria Categories", "threshold_reference_row"),
        ("a: <10, b: 10-20, c: >20", "threshold_reference_row"),
    ]

    @pytest.mark.parametrize("text,expected_type", _EXCLUDED_MIXED_ROWS)
    def test_mixed_rows_excluded_from_observation_pool(
        self, text: str, expected_type: str
    ) -> None:
        result = classify_candidate_text(
            text,
            page_class="mixed_page",
            family_adapter_id="generic_layout",
        )
        assert result["is_excluded"] is True, (
            f"{text!r} should be excluded, got row_type={result['row_type']}"
        )
        assert result["row_type"] == expected_type, (
            f"{text!r} expected {expected_type}, got {result['row_type']}"
        )


class TestWave5RealCorpusSuppression:
    def test_room_and_floor_fragment_is_typed_admin_metadata(self) -> None:
        result = classify_candidate_text(
            "R Room 912, 9th Floor",
            page_class="mixed_page",
            family_adapter_id="generic_layout",
        )
        assert result["row_type"] == "admin_metadata_row"
        assert result["is_excluded"] is True

    def test_reference_range_prefix_is_typed_threshold_reference(self) -> None:
        result = classify_candidate_text(
            "Reference range: <100",
            page_class="mixed_page",
            family_adapter_id="generic_layout",
        )
        assert result["row_type"] == "threshold_reference_row"
        assert result["is_excluded"] is True

    def test_footer_rights_reserved_line_is_not_a_measurement(self) -> None:
        result = classify_candidate_text(
            "All Rights Reserved - Enterprise Report Version 2.00 If you have received this document in error please call",
            page_class="mixed_page",
            family_adapter_id="generic_layout",
        )
        assert result["row_type"] == "header_footer_row"
        assert result["is_excluded"] is True

    def test_labcorp_fragmented_cd_label_is_not_parsed_as_measurement(self) -> None:
        result = classify_candidate_text(
            "Absolute CD 4 Helper",
            page_class="analyte_table_page",
            family_adapter_id="generic_layout",
        )
        assert result["row_type"] == "unparsed_row"
        assert result["is_excluded"] is True

    def test_vitals_hybrid_line_is_excluded(self) -> None:
        result = classify_candidate_text(
            "HEIGHT FEET 5 ft SYSTOLIC BLOOD PRESSURE 106 mmHg",
            page_class="mixed_page",
            family_adapter_id="generic_layout",
        )
        assert result["row_type"] == "admin_metadata_row"
        assert result["is_excluded"] is True

    def test_note_threshold_hybrid_is_excluded(self) -> None:
        result = classify_candidate_text(
            "Note 4 Target for non-HDL cholesterol is 30 mg/dL higher than",
            page_class="mixed_page",
            family_adapter_id="generic_layout",
        )
        assert result["row_type"] == "narrative_guidance_row"
        assert result["is_excluded"] is True

    def test_wave21_innoquest_address_line_not_typed_as_measurement(self) -> None:
        """Wave-21: Innoquest address lines like GRIBBLES IT DEPARTMENT with
        jalan/floor fragments must NOT classify as measured_analyte_row.

        Root cause: `_LOCATION_HINTS` missed floor abbreviations (`flr`) and
        Malaysian street tokens (`jalan`), allowing `14 JALAN 19/1 2ND FLR`
        to satisfy `_looks_like_measurement` via the numeric token + `/` tail.
        """
        result = classify_candidate_text(
            "GRIBBLES IT DEPARTMENTAAAAA 14 JALAN 19/1 2ND FLR",
            page_class="analyte_table_page",
            family_adapter_id="innoquest_bilingual_general",
        )
        assert result["row_type"] == "admin_metadata_row", (
            f"Address line leaked as {result['row_type']}"
        )
        assert result["is_excluded"] is True


class TestWave5UnitNormalization:
    def test_not_established_suffix_does_not_poison_percent_unit(self) -> None:
        result = parse_measurement_text(
            "Neutrophils 47 % Not Estab.",
            page_class="analyte_table_page",
            family_adapter_id="generic_layout",
        )
        assert result["row_type"] == "measured_analyte_row"
        assert result["raw_unit_string"] == "%"

    def test_trailing_footnote_is_removed_from_unit_string(self) -> None:
        result = parse_measurement_text(
            "LDL-CHOLESTEROL 150 HIGH mg/dL (calc) 01",
            page_class="analyte_table_page",
            family_adapter_id="generic_layout",
        )
        assert result["row_type"] == "measured_analyte_row"
        assert result["raw_unit_string"] == "mg/dL"
