from __future__ import annotations

from app.workers.pipeline import _support_banner_from_runtime


def _observation(support_state: str) -> dict:
    return {"support_state": support_state}


def _finding(*, severity_class: str, suppression_active: bool) -> dict:
    return {
        "severity_class": severity_class,
        "suppression_active": suppression_active,
    }


def test_support_banner_downgrades_to_could_not_assess_when_all_findings_suppressed() -> None:
    result = _support_banner_from_runtime(
        observations=[_observation("supported")],
        findings=[
            _finding(severity_class="SX", suppression_active=True),
            _finding(severity_class="SX", suppression_active=True),
        ],
        comparable_history=None,
    )

    assert result == "could_not_assess"


def test_support_banner_downgrades_to_partially_supported_for_mixed_assessment() -> None:
    result = _support_banner_from_runtime(
        observations=[_observation("supported")],
        findings=[
            _finding(severity_class="SX", suppression_active=True),
            _finding(severity_class="S0", suppression_active=False),
        ],
        comparable_history=None,
    )

    assert result == "partially_supported"


def test_support_banner_remains_fully_supported_when_comparable_history_unavailable() -> None:
    result = _support_banner_from_runtime(
        observations=[_observation("supported")],
        findings=[_finding(severity_class="S0", suppression_active=False)],
        comparable_history={
            "comparability_status": "unavailable",
            "analyte_display": "cholesterol",
        },
    )

    assert result == "fully_supported"
