from __future__ import annotations

from app.workers.pipeline import _support_banner


def test_support_banner_marks_partial_for_unsupported_family_rows() -> None:
    observations = [
        {
            "raw_analyte_label": "Glucose",
            "support_state": "supported",
            "failure_code": None,
        },
        {
            "raw_analyte_label": "Unknown Marker",
            "support_state": "partial",
            "failure_code": "unsupported_family",
        },
    ]

    assert _support_banner(observations) == "partially_supported"


def test_support_banner_ignores_unbound_derived_observation() -> None:
    observations = [
        {
            "raw_analyte_label": "Creatinine",
            "support_state": "supported",
            "failure_code": None,
        },
        {
            "raw_analyte_label": "eGFR",
            "support_state": "unsupported",
            "failure_code": "derived_observation_unbound",
        },
    ]

    assert _support_banner(observations) == "fully_supported"
