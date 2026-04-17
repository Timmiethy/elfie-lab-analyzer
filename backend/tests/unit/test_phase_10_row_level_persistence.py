"""Phase 10 acceptance tests for row-level persistence helpers."""

from __future__ import annotations

import asyncio
from uuid import uuid4

from app.db.store import TopLevelLifecycleStore


class _RecordingSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flush_calls = 0

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flush_calls += 1


def test_store_creates_extracted_row_records() -> None:
    session = _RecordingSession()
    store = TopLevelLifecycleStore(session)  # type: ignore[arg-type]
    document_id = uuid4()
    job_id = uuid4()

    extracted_row = asyncio.run(
        store.create_extracted_row(
            document_id=document_id,
            job_id=job_id,
            source_page=1,
            row_hash="row-001",
            raw_text="Glucose 180 mg/dL",
            raw_analyte_label="Glucose",
            raw_value_string="180",
            raw_unit_string="mg/dL",
            raw_reference_range="70-99",
            extraction_confidence=0.99,
        )
    )

    assert extracted_row.document_id == document_id
    assert extracted_row.job_id == job_id
    assert extracted_row.row_hash == "row-001"
    assert extracted_row.raw_analyte_label == "Glucose"
    assert session.flush_calls == 1


def test_store_creates_observation_records_linked_to_extracted_rows() -> None:
    session = _RecordingSession()
    store = TopLevelLifecycleStore(session)  # type: ignore[arg-type]
    document_id = uuid4()
    job_id = uuid4()
    extracted_row_id = uuid4()
    lineage_id = uuid4()

    observation = asyncio.run(
        store.create_observation(
            id=uuid4(),
            document_id=document_id,
            job_id=job_id,
            extracted_row_id=extracted_row_id,
            source_page=1,
            row_hash="row-001",
            raw_analyte_label="Glucose",
            raw_value_string="180",
            raw_unit_string="mg/dL",
            parsed_numeric_value=180.0,
            accepted_analyte_code="METRIC-0019",
            accepted_analyte_display="Glucose [Mass/volume] in Serum or Plasma",
            specimen_context="serum",
            method_context=None,
            raw_reference_range="70-99",
            canonical_unit="mg/dL",
            canonical_value=180.0,
            language_id="en",
            support_state="supported",
            suppression_reasons=[],
            lineage_id=lineage_id,
        )
    )

    assert observation.document_id == document_id
    assert observation.job_id == job_id
    assert observation.extracted_row_id == extracted_row_id
    assert observation.accepted_analyte_code == "METRIC-0019"
    assert observation.lineage_id == lineage_id
    assert session.flush_calls == 1


def test_store_creates_mapping_candidate_rule_event_and_policy_event_records() -> None:
    session = _RecordingSession()
    store = TopLevelLifecycleStore(session)  # type: ignore[arg-type]
    observation_id = uuid4()
    job_id = uuid4()
    rule_event_id = uuid4()

    mapping_candidate = asyncio.run(
        store.create_mapping_candidate(
            observation_id=observation_id,
            candidate_code="METRIC-0019",
            candidate_display="Glucose [Mass/volume] in Serum or Plasma",
            score=0.99,
            threshold_used=0.9,
            accepted=True,
            rejection_reason=None,
        )
    )
    rule_event = asyncio.run(
        store.create_rule_event(
            id=rule_event_id,
            job_id=job_id,
            observation_id=observation_id,
            rule_id="glucose_high_threshold",
            finding_id="glucose_high::row-001",
            threshold_source="adult_fasting_default_70_99",
            supporting_observation_ids=[observation_id],
            suppression_conditions=None,
            severity_class_candidate="S2",
            nextstep_class_candidate="A2",
        )
    )
    policy_event = asyncio.run(
        store.create_policy_event(
            job_id=job_id,
            rule_event_id=rule_event_id,
            severity_class="S2",
            nextstep_class="A2",
            severity_policy_version="severity-v1",
            nextstep_policy_version="nextstep-v1",
            suppression_active=False,
            suppression_reason=None,
        )
    )

    assert mapping_candidate.observation_id == observation_id
    assert mapping_candidate.accepted is True
    assert rule_event.rule_id == "glucose_high_threshold"
    assert rule_event.job_id == job_id
    assert policy_event.rule_event_id == rule_event_id
    assert policy_event.severity_class == "S2"
    assert session.flush_calls == 3
