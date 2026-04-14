from __future__ import annotations

from app.services.extraction_qa import ExtractionQA


def _base_row(**overrides):
    row = {
        "row_hash": "row-1",
        "raw_text": "Glucose 180 mg/dL",
        "raw_analyte_label": "Glucose",
        "row_type": "measured_analyte_row",
        "raw_value_string": "180",
        "raw_unit_string": "mg/dL",
        "raw_reference_range": "70-99",
        "parsed_numeric_value": 180.0,
    }
    row.update(overrides)
    return row


def test_extraction_qa_v2_reports_linkage_metrics_for_clean_rows() -> None:
    report = ExtractionQA().validate([_base_row()])

    assert report["contract_version"] == "extraction-qa-report-v2"
    assert report["passed"] is True
    assert report["metrics"]["clean_rows"] == 1
    assert report["linkage_report"]["contract_version"] == "linkage-report-v1"
    assert report["linkage_report"]["counts"]["candidate_rows"] == 1
    assert report["linkage_report"]["counts"]["analyte_value_linked"] == 1
    assert report["linkage_report"]["counts"]["value_unit_linked"] == 1
    assert report["linkage_report"]["counts"]["value_reference_linked"] == 1


def test_extraction_qa_v2_rejects_contaminated_admin_narrative_rows() -> None:
    contaminated = _base_row(
        row_hash="row-2",
        raw_text="DOB: 1970-01-01 Collected: 2026-04-14",
    )
    report = ExtractionQA().validate([contaminated])

    assert report["passed"] is False
    assert report["metrics"]["clean_rows"] == 0
    assert report["metrics"]["rejection_counts"]["contaminated_row_text"] == 1
    assert report["leak_report"]["counts"]["contaminated_row_text"] == 1


def test_extraction_qa_v2_rejects_reference_fragment_value_rows() -> None:
    ref_fragment = _base_row(
        row_hash="row-3",
        raw_value_string="70-99",
        parsed_numeric_value=None,
        raw_reference_range="70-99",
    )
    report = ExtractionQA().validate([ref_fragment])

    assert report["passed"] is False
    assert report["metrics"]["rejection_counts"]["reference_fragment_row"] == 1


def test_extraction_qa_v2_allows_qualitative_result_without_numeric_value() -> None:
    qualitative = _base_row(
        row_hash="row-4",
        raw_text="Ketones positive",
        raw_analyte_label="Ketones",
        row_type="qualitative_result_row",
        raw_value_string="positive",
        raw_unit_string=None,
        raw_reference_range=None,
        parsed_numeric_value=None,
    )

    report = ExtractionQA().validate([qualitative])

    assert report["passed"] is True
    assert report["metrics"]["clean_rows"] == 1
    assert report["linkage_report"]["counts"]["analyte_value_linked"] == 1
