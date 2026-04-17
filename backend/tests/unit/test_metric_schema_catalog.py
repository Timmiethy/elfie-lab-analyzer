import json

from app.schemas.observation import SupportState
from app.services.metric_resolver import MetricResolver
from app.services.observation_builder import ObservationBuilder
from app.services.ucum import UcumEngine
from app.workers.pipeline import _normalize_observations


def test_observation_builder_unmapped_is_unsupported():
    builder = ObservationBuilder()
    rows = [
        {
            "document_id": "00000000-0000-0000-0000-000000000001",
            "row_hash": "hash1",
            "raw_analyte_label": "Unknown",
            "source_page": 1,
        }
    ]
    obs = builder.build(rows)
    # Goal: Unsupported-row rate improves (becomes more accurate/reduced from partial)
    assert obs[0]["support_state"] == SupportState.UNSUPPORTED


def test_pipeline_normalization_emits_selected_profile(tmp_path):
    # Setup mock metric resolver
    catalog_file = tmp_path / "test_metrics.json"
    metrics = [
        {
            "metric_id": "metric_glucose",
            "canonical_name": "Glucose",
            "result_type": "numeric",
            "default_reference_profiles": [
                {
                    "profile_id": "glucose_generic",
                    "metric_id": "metric_glucose",
                    "source_type": "canonical_default",
                    "priority": 10,
                    "applies_to": {"sex": None},
                }
            ],
        }
    ]
    catalog_file.write_text(json.dumps(metrics))
    metric_resolver = MetricResolver(catalog_path=catalog_file)

    # Mock analyte resolver to return our metric_id
    class MockAnalyteResolver:
        def resolve(self, raw_label, context=None):
            return {
                "candidates": [],
                "accepted_candidate": {
                    "candidate_code": "metric_glucose",
                    "candidate_display": "Glucose",
                },
                "support_state": "supported",
            }

    observations = [
        {
            "raw_analyte_label": "Glucose",
            "raw_value_string": "100",
            "raw_unit_string": "mg/dL",
            "parsed_numeric_value": 100.0,
            "row_hash": "row1",
            "source_page": 1,
        }
    ]

    normalized = _normalize_observations(
        observations,
        analyte_resolver=MockAnalyteResolver(),
        ucum_engine=UcumEngine(),
        metric_resolver=metric_resolver,
        patient_context={"sex": "M", "age_years": 30},
    )

    assert normalized[0]["selected_reference_profile"] == "glucose_generic"
    assert normalized[0]["support_state"] == "supported"


def test_pipeline_keeps_support_on_missing_profile(tmp_path):
    # Setup mock metric resolver with NO matching profiles
    catalog_file = tmp_path / "empty_metrics.json"
    metrics = [
        {
            "metric_id": "metric_glucose",
            "canonical_name": "Glucose",
            "result_type": "numeric",
            "default_reference_profiles": [],
        }
    ]
    catalog_file.write_text(json.dumps(metrics))
    metric_resolver = MetricResolver(catalog_path=catalog_file)

    class MockAnalyteResolver:
        def resolve(self, raw_label, context=None):
            return {
                "candidates": [],
                "accepted_candidate": {
                    "candidate_code": "metric_glucose",
                    "candidate_display": "Glucose",
                },
                "support_state": "supported",
            }

    observations = [
        {
            "raw_analyte_label": "Glucose",
            "raw_value_string": "100",
            "raw_unit_string": "mg/dL",
            "parsed_numeric_value": 100.0,
            "row_hash": "row1",
            "source_page": 1,
        }
    ]

    normalized = _normalize_observations(
        observations,
        analyte_resolver=MockAnalyteResolver(),
        ucum_engine=UcumEngine(),
        metric_resolver=metric_resolver,
        patient_context={"sex": "M", "age_years": 30},
    )

    assert normalized[0]["support_state"] == "supported"
    assert "unresolved_reference_profile" in normalized[0]["suppression_reasons"]


def test_pipeline_propagates_resolver_abstention_reasons(tmp_path):
    catalog_file = tmp_path / "minimal_metrics.json"
    metrics = [
        {
            "metric_id": "metric_glucose",
            "canonical_name": "Glucose",
            "result_type": "numeric",
            "default_reference_profiles": [],
        }
    ]
    catalog_file.write_text(json.dumps(metrics))
    metric_resolver = MetricResolver(catalog_path=catalog_file)

    class MockAnalyteResolver:
        def resolve(self, raw_label, context=None):
            return {
                "candidates": [
                    {
                        "candidate_code": "__unmapped__",
                        "candidate_display": "unmapped",
                        "score": 0.0,
                        "threshold_used": 0.9,
                        "accepted": False,
                        "rejection_reason": "unsupported_alias",
                    }
                ],
                "accepted_candidate": None,
                "support_state": "unsupported",
                "abstention_reasons": ["unsupported_alias"],
            }

    observations = [
        {
            "raw_analyte_label": "Creatinine S",
            "raw_value_string": "1.41",
            "raw_unit_string": "mg/dL",
            "parsed_numeric_value": 1.41,
            "row_hash": "row1",
            "source_page": 1,
        }
    ]

    normalized = _normalize_observations(
        observations,
        analyte_resolver=MockAnalyteResolver(),
        ucum_engine=UcumEngine(),
        metric_resolver=metric_resolver,
        patient_context={"sex": "F", "age_years": 42},
    )

    assert normalized[0]["support_state"] == "unsupported"
    assert "unsupported_alias" in normalized[0]["suppression_reasons"]
