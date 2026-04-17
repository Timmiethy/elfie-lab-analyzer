"""Phase 10 acceptance tests for pipeline-driven row-level persistence."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy.exc import IntegrityError

from app.workers import pipeline as pipeline_module


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
            db_session=object(),
        )
    )

    assert created_rule_event_ids
    assert created_policy_event_rule_ids
    assert set(created_policy_event_rule_ids) <= set(created_rule_event_ids)


def test_pipeline_prefers_bulk_row_persistence_when_available(monkeypatch) -> None:
    calls = {
        "bulk_extracted": 0,
        "bulk_observations": 0,
        "bulk_candidates": 0,
        "bulk_rules": 0,
        "bulk_policies": 0,
        "per_row": 0,
    }

    class FakeStore:
        def __init__(self, session: object) -> None:
            self.session = session

        async def bulk_create_extracted_rows(self, *, rows):
            calls["bulk_extracted"] += 1
            return {str(row["row_hash"]): uuid4() for row in rows}

        async def bulk_create_observations(self, *, rows):
            calls["bulk_observations"] += 1
            return {row["observation_uuid"]: row["observation_uuid"] for row in rows}

        async def bulk_create_mapping_candidates(self, *, rows):
            calls["bulk_candidates"] += len(rows)

        async def bulk_create_rule_events(self, *, rows):
            calls["bulk_rules"] += len(rows)
            return {row["id"]: row["id"] for row in rows}

        async def bulk_create_policy_events(self, *, rows):
            calls["bulk_policies"] += len(rows)

        async def create_extracted_row(self, **kwargs):
            calls["per_row"] += 1
            raise AssertionError("per-row path should not run when bulk methods exist")

        async def create_observation(self, **kwargs):
            calls["per_row"] += 1
            raise AssertionError("per-row path should not run when bulk methods exist")

        async def create_mapping_candidate(self, **kwargs):
            calls["per_row"] += 1
            raise AssertionError("per-row path should not run when bulk methods exist")

        async def create_rule_event(self, **kwargs):
            calls["per_row"] += 1
            raise AssertionError("per-row path should not run when bulk methods exist")

        async def create_policy_event(self, **kwargs):
            calls["per_row"] += 1
            raise AssertionError("per-row path should not run when bulk methods exist")

        async def persist_top_level_bundle(self, **kwargs):
            return None

    monkeypatch.setattr(pipeline_module, "TopLevelLifecycleStore", FakeStore)

    result = asyncio.run(
        pipeline_module.PipelineOrchestrator().run(
            "phase-10-bulk-path",
            db_session=object(),
        )
    )

    assert result["row_level_persistence"]["extracted_rows"] >= 1
    assert result["row_level_persistence"]["observations"] >= 1
    assert calls["bulk_extracted"] == 1
    assert calls["bulk_observations"] == 1
    assert calls["bulk_candidates"] >= 1
    assert calls["bulk_rules"] >= 1
    assert calls["bulk_policies"] >= 1
    assert calls["per_row"] == 0


def test_pipeline_falls_back_to_per_row_on_bulk_integrity_error(monkeypatch) -> None:
    calls = {
        "bulk_extracted": 0,
        "per_row_extracted": 0,
        "per_row_observations": 0,
        "per_row_candidates": 0,
        "per_row_rules": 0,
        "per_row_policies": 0,
    }

    class FakeStore:
        def __init__(self, session: object) -> None:
            self.session = session

        async def bulk_create_extracted_rows(self, *, rows):
            calls["bulk_extracted"] += 1
            raise IntegrityError("insert", {}, Exception("duplicate key"))

        async def bulk_create_observations(self, *, rows):
            raise AssertionError("bulk observations should not run after bulk extracted failure")

        async def bulk_create_mapping_candidates(self, *, rows):
            raise AssertionError("bulk mapping candidates should not run after fallback")

        async def bulk_create_rule_events(self, *, rows):
            raise AssertionError("bulk rule events should not run after fallback")

        async def bulk_create_policy_events(self, *, rows):
            raise AssertionError("bulk policy events should not run after fallback")

        async def create_extracted_row(self, **kwargs):
            calls["per_row_extracted"] += 1
            return SimpleNamespace(id=uuid4())

        async def create_observation(self, **kwargs):
            calls["per_row_observations"] += 1
            return SimpleNamespace(id=uuid4())

        async def create_mapping_candidate(self, **kwargs):
            calls["per_row_candidates"] += 1
            return SimpleNamespace(id=uuid4())

        async def create_rule_event(self, **kwargs):
            calls["per_row_rules"] += 1
            return SimpleNamespace(id=uuid4())

        async def create_policy_event(self, **kwargs):
            calls["per_row_policies"] += 1
            return SimpleNamespace(id=uuid4())

        async def persist_top_level_bundle(self, **kwargs):
            return None

    monkeypatch.setattr(pipeline_module, "TopLevelLifecycleStore", FakeStore)

    result = asyncio.run(
        pipeline_module.PipelineOrchestrator().run(
            "phase-10-bulk-fallback",
            db_session=object(),
        )
    )

    assert calls["bulk_extracted"] == 1
    assert calls["per_row_extracted"] == result["row_level_persistence"]["extracted_rows"]
    assert calls["per_row_observations"] == result["row_level_persistence"]["observations"]
    assert calls["per_row_candidates"] == result["row_level_persistence"]["mapping_candidates"]
    assert calls["per_row_rules"] == result["row_level_persistence"]["rule_events"]
    assert calls["per_row_policies"] == result["row_level_persistence"]["policy_events"]
