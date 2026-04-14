"""Row assembler grouping regressions for qualitative rows."""

from __future__ import annotations

from app.services.document_system.row_assembler.line_classifier import LineClassification, LineClassifier
from app.services.document_system.row_assembler.row_grouping import group_lines


def _classify(lines: list[str]) -> list:
    classifier = LineClassifier()
    return [
        classifier.classify_line(
            line,
            page_class="analyte_table_page",
            family_adapter_id="generic_layout",
        )
        for line in lines
    ]


def test_line_classifier_marks_categorical_line_as_value() -> None:
    item = _classify(["Urine Ketones Positive"])[0]
    assert item.line_type == "value"
    assert item.row_type == "measured_analyte_row"


def test_group_lines_keeps_single_qualitative_row() -> None:
    groups = group_lines(_classify(["Urine Ketones Positive"]))
    assert len(groups) == 1
    assert groups[0].has_value is True
    assert groups[0].lines == ["Urine Ketones Positive"]


def test_group_lines_merges_label_with_qualitative_value_line() -> None:
    groups = group_lines(_classify(["HBsAg S/Co", "Non Reactive"]))
    assert len(groups) == 1
    assert groups[0].has_value is True
    assert groups[0].lines == ["HBsAg S/Co", "Non Reactive"]


def test_group_lines_does_not_merge_non_result_label_group() -> None:
    groups = group_lines(
        [
            LineClassification(
                line="Final Diagnosis",
                line_type="label",
                row_type="unparsed_row",
                support_code="excluded",
                failure_code="unparsed_row",
            ),
            LineClassification(
                line="5.6 mmol/L",
                line_type="value",
                row_type="measured_analyte_row",
                support_code="supported",
                failure_code=None,
            ),
        ]
    )

    assert len(groups) == 1
    assert groups[0].has_value is True
    assert groups[0].lines == ["5.6 mmol/L"]


def test_group_lines_does_not_carry_older_label_groups_forward() -> None:
    groups = group_lines(
        [
            LineClassification(
                line="Kidney Panel",
                line_type="label",
                row_type="unparsed_row",
                support_code="supported",
                failure_code=None,
            ),
            LineClassification(
                line="Creatinine",
                line_type="label",
                row_type="measured_analyte_row",
                support_code="supported",
                failure_code=None,
            ),
            LineClassification(
                line="88 umol/L",
                line_type="value",
                row_type="measured_analyte_row",
                support_code="supported",
                failure_code=None,
            ),
        ]
    )

    assert len(groups) == 1
    assert groups[0].has_value is True
    assert groups[0].lines == ["Creatinine", "88 umol/L"]
