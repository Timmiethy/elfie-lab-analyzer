"""Phase 10 acceptance tests for pipeline-driven row-level persistence."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid4, uuid5

from app.workers import pipeline as pipeline_module
from tests.support.pdf_builder import build_text_pdf


def _sample_trusted_pdf_bytes() -> bytes:
    return build_text_pdf([
        "Glucose 180 mg/dL 70-99",
        "HbA1c 6.8 % <5.7",
    ])


def test_pipeline_persists_row_level_entities_when_db_session_is_provided(monkeypatch) -> None:
    calls: dict[str, list[dict] | dict] = {
        "extracted_rows": [],
        "observations": [],
        "mapping_candidates": [],
        "rule_events": [],
        "policy_events": [],
    }
    extracted_row_ids: dict[str, object] = {}

    class FakeStore:
        def __init__(self, session: object) -> None:
            self.session = session

        async def create_extracted_row(self, **kwargs):
            row_id = uuid4()
            extracted_row_ids[kwargs["row_hash"]] = row_id
            calls["extracted_rows"].append(kwargs)
            return SimpleNamespace(id=row_id)

        async def create_observation(self, **kwargs):
            observation_id = uuid4()
            calls["observations"].append(kwargs)
            return SimpleNamespace(id=observation_id)

        async def create_mapping_candidate(self, **kwargs):
            calls["mapping_candidates"].append(kwargs)
            return SimpleNamespace(id=uuid4())

        async def create_rule_event(self, **kwargs):
            rule_event_id = uuid4()
            calls["rule_events"].append({**kwargs, "id": rule_event_id})
            return SimpleNamespace(id=rule_event_id)

        async def create_policy_event(self, **kwargs):
            calls["policy_events"].append(kwargs)
            return SimpleNamespace(id=uuid4())

        async def persist_top_level_bundle(self, **kwargs):
            calls["top_level"] = kwargs

    monkeypatch.setattr(pipeline_module, "TopLevelLifecycleStore", FakeStore)

    result = asyncio.run(
        pipeline_module.PipelineOrchestrator().run(
            "phase-10-row-persist",
            file_bytes=_sample_trusted_pdf_bytes(),
            lane_type="trusted_pdf",
            db_session=object(),
        )
    )

    expected_job_uuid = uuid5(NAMESPACE_URL, "job:phase-10-row-persist")

    assert len(calls["extracted_rows"]) == len(result["qa"]["clean_rows"])
    assert len(calls["observations"]) == len(result["observations"])
    assert len(calls["mapping_candidates"]) >= 1
    assert len(calls["rule_events"]) >= 1
    assert len(calls["policy_events"]) >= 1
    assert all(row["job_id"] == expected_job_uuid for row in calls["extracted_rows"])
    assert all(observation["job_id"] == expected_job_uuid for observation in calls["observations"])
    assert all(
        observation["extracted_row_id"] in extracted_row_ids.values()
        for observation in calls["observations"]
    )


def test_pipeline_policy_events_reference_created_rule_events(monkeypatch) -> None:
    created_rule_event_ids: list[object] = []
    created_policy_event_rule_ids: list[object] = []

    class FakeStore:
        def __init__(self, session: object) -> None:
            self.session = session

        async def create_extracted_row(self, **kwargs):
            return SimpleNamespace(id=uuid4())

        async def create_observation(self, **kwargs):
            return SimpleNamespace(id=uuid4())

        async def create_mapping_candidate(self, **kwargs):
            return SimpleNamespace(id=uuid4())

        async def create_rule_event(self, **kwargs):
            rule_event_id = uuid4()
            created_rule_event_ids.append(rule_event_id)
            return SimpleNamespace(id=rule_event_id)

        async def create_policy_event(self, **kwargs):
            created_policy_event_rule_ids.append(kwargs["rule_event_id"])
            return SimpleNamespace(id=uuid4())

        async def persist_top_level_bundle(self, **kwargs):
            return None

    monkeypatch.setattr(pipeline_module, "TopLevelLifecycleStore", FakeStore)

    asyncio.run(
        pipeline_module.PipelineOrchestrator().run(
            "phase-10-policy-linkage",
            file_bytes=_sample_trusted_pdf_bytes(),
            lane_type="trusted_pdf",
            db_session=object(),
        )
    )

    assert created_rule_event_ids
    assert created_policy_event_rule_ids
    assert set(created_policy_event_rule_ids) <= set(created_rule_event_ids)
