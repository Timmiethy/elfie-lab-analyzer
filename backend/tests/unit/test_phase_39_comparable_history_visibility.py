"""Phase 39: comparable history must not leak synthetic not_assessed rows.

v11 guardrail: patient-visible not_assessed must stay tied to unresolved
result rows, not missing longitudinal context.  When comparable_history is
unavailable the comparable_history field itself carries the neutral payload;
nothing should appear in not_assessed for that reason alone.
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest

from app.schemas.finding import NextStepClass, SeverityClass
from app.services.artifact_renderer import ArtifactRenderer


def _make_finding(
    rule_id: str,
    severity: SeverityClass = SeverityClass.S2,
    nextstep: NextStepClass = NextStepClass.A2,
    observation_ids: list[str] | None = None,
) -> dict:
    finding_id = str(uuid5(NAMESPACE_URL, f"finding:{rule_id}:{severity.value}:{nextstep.value}"))
    return {
        "finding_id": finding_id,
        "rule_id": rule_id,
        "severity_class": severity,
        "nextstep_class": nextstep,
        "threshold_source": "test",
        "suppression_active": False,
        "explanatory_scaffold_id": None,
        "observation_ids": [uuid5(NAMESPACE_URL, f"obs:{value}") for value in (observation_ids or [])],
    }


def _make_observation(
    label: str,
    support_state: str = "supported",
    suppression_reasons: list[str] | None = None,
) -> dict:
    obs_id = uuid5(NAMESPACE_URL, f"obs:{label}")
    return {
        "id": obs_id,
        "raw_analyte_label": label,
        "support_state": support_state,
        "suppression_reasons": suppression_reasons or [],
    }


@pytest.fixture
def renderer() -> ArtifactRenderer:
    return ArtifactRenderer()


class TestComparableHistoryUnavailableDoesNotLeak:
    """Comparable history unavailable must not create not_assessed noise."""

    def test_comparable_history_unavailable_stays_out_of_patient_not_assessed(
        self, renderer: ArtifactRenderer
    ) -> None:
        """Even when comparable_history.comparability_status is 'unavailable',
        no synthetic 'prior <analyte> trend' row should appear in not_assessed."""

        findings = [_make_finding("glucose-high")]
        observations = [_make_observation("Glucose", support_state="supported")]
        comparable_history = {
            "analyte_display": "Vitamin D 25-OH Total",
            "current_value": "18",
            "current_unit": "ng/mL",
            "current_date": "2026-04-11",
            "previous_value": None,
            "previous_unit": None,
            "previous_date": None,
            "direction": "trend_unavailable",
            "comparability_status": "unavailable",
            "comparability_reason": "No prior comparable history is available.",
        }

        artifact = renderer.render_patient(
            findings,
            {
                "job_id": str(uuid4()),
                "support_banner": "fully_supported",
                "trust_status": "trusted",
                "comparable_history": comparable_history,
            },
            observations=observations,
        )

        # comparable_history is preserved
        assert artifact["comparable_history"] is not None
        assert artifact["comparable_history"]["comparability_status"] == "unavailable"

        # no synthetic prior-trend row in not_assessed
        for item in artifact["not_assessed"]:
            assert "prior" not in item.get("raw_label", "").lower()
            assert item.get("reason") != "comparable_history_unavailable"

    def test_comparable_history_unavailable_with_no_observations(
        self, renderer: ArtifactRenderer
    ) -> None:
        """When there are no observations and comparable history is
        unavailable, not_assessed must be empty."""

        findings = [_make_finding("glucose-high")]
        comparable_history = {
            "analyte_display": "Vitamin D 25-OH Total",
            "current_value": "18",
            "current_unit": "ng/mL",
            "current_date": "2026-04-11",
            "previous_value": None,
            "previous_unit": None,
            "previous_date": None,
            "direction": "trend_unavailable",
            "comparability_status": "unavailable",
        }

        artifact = renderer.render_patient(
            findings,
            {
                "job_id": str(uuid4()),
                "support_banner": "fully_supported",
                "trust_status": "trusted",
                "comparable_history": comparable_history,
            },
            observations=None,
        )

        assert artifact["comparable_history"] is not None
        assert artifact["comparable_history"]["comparability_status"] == "unavailable"
        assert artifact["not_assessed"] == []

    def test_comparable_history_none_returns_empty_not_assessed(
        self, renderer: ArtifactRenderer
    ) -> None:
        """When comparable_history is explicitly None, no injection occurs."""

        findings = [_make_finding("glucose-high")]
        artifact = renderer.render_patient(
            findings,
            {
                "job_id": str(uuid4()),
                "support_banner": "fully_supported",
                "trust_status": "trusted",
                "comparable_history": None,
            },
            observations=[],
        )

        assert artifact["comparable_history"] is None
        assert artifact["not_assessed"] == []


class TestGenuineUnresolvedObservationsStillSurface:
    """Real unresolved observation rows must still appear in not_assessed."""

    def test_unsupported_observation_surfaces_in_not_assessed(
        self, renderer: ArtifactRenderer
    ) -> None:
        """An observation with support_state != 'supported' that is not covered
        by a finding must appear in not_assessed."""

        findings = [_make_finding("glucose-high")]
        observations = [
            _make_observation("Glucose", support_state="supported"),
            _make_observation("Mystery Analyte", support_state="unsupported"),
        ]
        comparable_history = {
            "analyte_display": "Vitamin D 25-OH Total",
            "current_value": "18",
            "current_unit": "ng/mL",
            "current_date": "2026-04-11",
            "previous_value": None,
            "previous_unit": None,
            "previous_date": None,
            "direction": "trend_unavailable",
            "comparability_status": "unavailable",
        }

        artifact = renderer.render_patient(
            findings,
            {
                "job_id": str(uuid4()),
                "support_banner": "partially_supported",
                "trust_status": "trusted",
                "comparable_history": comparable_history,
            },
            observations=observations,
        )

        not_assessed_labels = [item["raw_label"].lower() for item in artifact["not_assessed"]]
        assert "mystery analyte" in not_assessed_labels

    def test_partial_observation_surfaces_in_not_assessed(
        self, renderer: ArtifactRenderer
    ) -> None:
        """An observation with partial support must still appear in not_assessed."""

        findings = [_make_finding("glucose-high")]
        observations = [
            _make_observation("Glucose", support_state="supported"),
            _make_observation("Creatinine", support_state="partial"),
        ]

        artifact = renderer.render_patient(
            findings,
            {
                "job_id": str(uuid4()),
                "support_banner": "partially_supported",
                "trust_status": "trusted",
                "comparable_history": None,
            },
            observations=observations,
        )

        not_assessed_labels = [item["raw_label"].lower() for item in artifact["not_assessed"]]
        assert "creatinine" in not_assessed_labels

    def test_suppressed_sx_finding_surfaces_in_not_assessed(
        self, renderer: ArtifactRenderer
    ) -> None:
        """An SX-suppressed finding rule_id should appear in not_assessed."""

        findings = [_make_finding("mystery-rule", severity=SeverityClass.SX)]

        artifact = renderer.render_patient(
            findings,
            {
                "job_id": str(uuid4()),
                "support_banner": "could_not_assess",
                "trust_status": "trusted",
                "comparable_history": None,
            },
            observations=[],
        )

        not_assessed_labels = [item["raw_label"].lower() for item in artifact["not_assessed"]]
        assert "mystery-rule" in not_assessed_labels
