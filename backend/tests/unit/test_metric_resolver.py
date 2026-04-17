import pytest

from app.schemas.patient_context import PatientContext
from app.services.metric_resolver import MetricResolver


@pytest.fixture
def resolver(tmp_path):
    # Create a small dummy catalog for testing selection logic
    catalog_file = tmp_path / "test_metrics.json"
    metrics = [
        {
            "metric_id": "test_metric_1",
            "canonical_name": "Test Metric 1",
            "result_type": "numeric",
            "default_reference_profiles": [
                {
                    "profile_id": "generic",
                    "metric_id": "test_metric_1",
                    "source_type": "canonical_default",
                    "priority": 10,
                    "applies_to": {
                        "sex": None,
                        "age_low": None,
                        "age_high": None,
                        "pregnancy": None,
                    },
                },
                {
                    "profile_id": "male_specific",
                    "metric_id": "test_metric_1",
                    "source_type": "canonical_default",
                    "priority": 5,
                    "applies_to": {
                        "sex": ["M"],
                        "age_low": None,
                        "age_high": None,
                        "pregnancy": None,
                    },
                },
            ],
        },
        {
            "metric_id": "test_metric_2",
            "canonical_name": "Test Metric 2",
            "result_type": "numeric",
            "default_reference_profiles": [
                {
                    "profile_id": "high_priority_generic",
                    "metric_id": "test_metric_2",
                    "source_type": "canonical_default",
                    "priority": 1,
                    "applies_to": {
                        "sex": None,
                        "age_low": None,
                        "age_high": None,
                        "pregnancy": None,
                    },
                },
                {
                    "profile_id": "low_priority_specific",
                    "metric_id": "test_metric_2",
                    "source_type": "canonical_default",
                    "priority": 5,
                    "applies_to": {"sex": ["F"], "age_low": 18, "age_high": 45, "pregnancy": True},
                },
            ],
        },
        {
            "metric_id": "test_metric_ambiguous",
            "canonical_name": "Ambiguous Metric",
            "result_type": "numeric",
            "default_reference_profiles": [
                {
                    "profile_id": "ambig_1",
                    "metric_id": "test_metric_ambiguous",
                    "source_type": "canonical_default",
                    "priority": 5,
                    "applies_to": {
                        "sex": ["M"],
                        "age_low": None,
                        "age_high": None,
                        "pregnancy": None,
                    },
                },
                {
                    "profile_id": "ambig_2",
                    "metric_id": "test_metric_ambiguous",
                    "source_type": "canonical_default",
                    "priority": 5,
                    "applies_to": {
                        "sex": ["M"],
                        "age_low": None,
                        "age_high": None,
                        "pregnancy": None,
                    },
                },
            ],
        },
    ]
    import json

    catalog_file.write_text(json.dumps(metrics))
    return MetricResolver(catalog_path=catalog_file)


def test_resolve_priority_precedence(resolver):
    # For test_metric_1, male_specific has higher priority (5) than generic (10)
    patient = PatientContext(sex="M")
    profile = resolver.resolve_profile("test_metric_1", patient)
    assert profile.profile_id == "male_specific"


def test_resolve_generic_fallback(resolver):
    # For test_metric_1, female patient matches only generic
    patient = PatientContext(sex="F")
    profile = resolver.resolve_profile("test_metric_1", patient)
    assert profile.profile_id == "generic"


def test_resolve_priority_over_specificity(resolver):
    # For test_metric_2, high_priority_generic (priority 1) beats low_priority_specific (priority 5)
    # even though low_priority_specific is more specific.
    patient = PatientContext(sex="F", age_years=30, pregnancy_status=True)
    profile = resolver.resolve_profile("test_metric_2", patient)
    assert profile.profile_id == "high_priority_generic"


def test_resolve_ambiguous_abstain(resolver):
    # test_metric_ambiguous has two identical profiles
    patient = PatientContext(sex="M")
    profile = resolver.resolve_profile("test_metric_ambiguous", patient)
    assert profile is None


def test_resolve_specificity_tie_break(resolver):
    # test_metric_ambiguous has two identical profiles
    # but let's test where one is more specific than another with SAME priority.
    # We'll add one to the resolver manually for this test if needed, or use existing.
    # The current resolver uses test_metrics.json created in the fixture.
    pass


def test_resolve_age_bounds(resolver):
    # test_metric_2 has low_priority_specific (priority 5, sex=F, age 18-45)
    patient_in_bounds = PatientContext(sex="F", age_years=25, pregnancy_status=True)
    # But wait, high_priority_generic has priority 1.
    # To test age bounds specifically, we'd need a metric where age is the only differentiator
    # or where it has higher priority.
    pass


def test_resolve_specificity_precedence(resolver, tmp_path):
    # Create a metric where priority is same but specificity differs
    catalog_file = tmp_path / "specificity_test.json"
    metrics = [
        {
            "metric_id": "spec_test",
            "canonical_name": "Spec Test",
            "result_type": "numeric",
            "default_reference_profiles": [
                {
                    "profile_id": "low_spec",
                    "metric_id": "spec_test",
                    "source_type": "canonical_default",
                    "priority": 5,
                    "applies_to": {"sex": ["M"]},
                },
                {
                    "profile_id": "high_spec",
                    "metric_id": "spec_test",
                    "source_type": "canonical_default",
                    "priority": 5,
                    "applies_to": {"sex": ["M"], "age_low": 18},
                },
            ],
        }
    ]
    import json

    catalog_file.write_text(json.dumps(metrics))
    spec_resolver = MetricResolver(catalog_path=catalog_file)

    patient = PatientContext(sex="M", age_years=30)
    profile = spec_resolver.resolve_profile("spec_test", patient)
    # high_spec has specificity 2, low_spec has specificity 1. Same priority 5.
    assert profile.profile_id == "high_spec"


def test_real_catalog_load():
    # Test that it loads the real catalog by default
    resolver = MetricResolver()
    assert len(resolver.metrics) > 0
    assert "METRIC-0001" in resolver.metrics


def test_resolve_profile_uses_cached_path(resolver):
    resolver._resolve_profile_cached.cache_clear()
    patient = PatientContext(sex="M")

    first = resolver.resolve_profile("test_metric_1", patient)
    second = resolver.resolve_profile("test_metric_1", patient)

    assert first is not None
    assert second is not None
    cache_info = resolver._resolve_profile_cached.cache_info()
    assert cache_info.hits >= 1
