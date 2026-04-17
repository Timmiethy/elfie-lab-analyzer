"""Phase A regression tests for bug-fix bundle.

Covers:
- A2: HbA1c NGSP/IFCC disambiguation by UCUM unit.
- A3: debug VLM dump dual-gate.
- A4: rule engine profile override fallthrough + severity gradient.
- A5: upload single-session rollback on pipeline failure.
"""

from __future__ import annotations

import math

import pytest

from app.services.analyte_resolver import AnalyteResolver


# ---------------------------------------------------------------------------
# A2: resolver unit-based disambiguation
# ---------------------------------------------------------------------------


def test_resolver_hba1c_percent_routes_to_ngsp() -> None:
    resolver = AnalyteResolver()
    result = resolver.resolve("HbA1c", context={"raw_unit": "%"})
    assert result["support_state"] == "supported"
    assert result["accepted_candidate"]["candidate_code"] == "METRIC-0063"


def test_resolver_hba1c_mmol_per_mol_routes_to_ifcc() -> None:
    resolver = AnalyteResolver()
    result = resolver.resolve("HbA1c", context={"raw_unit": "mmol/mol"})
    assert result["support_state"] == "supported"
    assert result["accepted_candidate"]["candidate_code"] == "METRIC-0064"


def test_resolver_hba1c_without_unit_abstains() -> None:
    resolver = AnalyteResolver()
    result = resolver.resolve("HbA1c")
    assert result["support_state"] == "unsupported"
    assert result["accepted_candidate"] is None
    reasons = {c["rejection_reason"] for c in result["candidates"]}
    assert reasons == {"unit_required"}


def test_resolver_hba1c_mismatched_unit_abstains() -> None:
    resolver = AnalyteResolver()
    result = resolver.resolve("HbA1c", context={"raw_unit": "mg/dL"})
    assert result["support_state"] == "unsupported"
    reasons = {c["rejection_reason"] for c in result["candidates"]}
    assert reasons == {"unit_mismatch"}


# ---------------------------------------------------------------------------
# A3: debug artifact dual-gate
# ---------------------------------------------------------------------------


def test_allow_debug_artifacts_defaults_false() -> None:
    from app.config import Settings

    defaults = Settings(_env_file=None)  # type: ignore[call-arg]
    assert defaults.allow_debug_artifacts is False


# ---------------------------------------------------------------------------
# A4: rule engine profile override fallthrough + severity gradient
# ---------------------------------------------------------------------------


from dataclasses import dataclass


@dataclass
class _ProfileStub:
    ref_high: float | None = None
    ref_low: float | None = None


def test_severity_from_ratio_gradient() -> None:
    from app.services.rule_engine import _severity_from_ratio

    assert _severity_from_ratio(1.00) == "S1"
    assert _severity_from_ratio(1.19) == "S1"
    assert _severity_from_ratio(1.20) == "S2"
    assert _severity_from_ratio(1.49) == "S2"
    assert _severity_from_ratio(1.50) == "S3"
    assert _severity_from_ratio(1.99) == "S3"
    assert _severity_from_ratio(2.00) == "S4"
    assert _severity_from_ratio(10.0) == "S4"


def test_severity_for_rule_uses_gradient_when_profile_has_no_rule_threshold_match() -> None:
    """Profile fires (value crosses ref_high) but rule thresholds are higher.

    Old behavior: hardcoded S1. New: derive gradient from ratio.
    """

    from app.services.rule_engine import _severity_for_rule

    rule = {
        "comparison": "gte",
        # All rule thresholds sit well above the profile ref_high; crossing the
        # profile alone should still produce a graded severity.
        "thresholds": [
            {"value": 1000.0, "severity_class": "S3"},
            {"value": 2000.0, "severity_class": "S4"},
        ],
    }
    profile = _ProfileStub(ref_high=100.0)

    # value just above ref_high → S1
    assert _severity_for_rule(rule, 105.0, patient_context={}, profile=profile) == "S1"
    # 1.3× → S2
    assert _severity_for_rule(rule, 130.0, patient_context={}, profile=profile) == "S2"
    # 1.7× → S3 (from gradient, not from rule thresholds which are at 200/400)
    assert _severity_for_rule(rule, 170.0, patient_context={}, profile=profile) == "S3"
    # 2.5× → S4
    assert _severity_for_rule(rule, 250.0, patient_context={}, profile=profile) == "S4"


def test_severity_for_rule_profile_with_none_ref_high_falls_through_to_rule_thresholds() -> None:
    from app.services.rule_engine import _severity_for_rule

    rule = {
        "comparison": "gte",
        "thresholds": [
            {"value": 100.0, "severity_class": "S1"},
            {"value": 200.0, "severity_class": "S2"},
        ],
    }
    profile = _ProfileStub(ref_high=None)

    # Without profile ref_high, old bug returned None → finding vanishes.
    # New behavior: fall through to the rule thresholds.
    assert _severity_for_rule(rule, 150.0, patient_context={}, profile=profile) == "S1"
    assert _severity_for_rule(rule, 250.0, patient_context={}, profile=profile) == "S2"


def test_severity_for_rule_rejects_nan() -> None:
    from app.services.rule_engine import _severity_for_rule

    rule = {
        "comparison": "gte",
        "thresholds": [{"value": 100.0, "severity_class": "S1"}],
    }
    assert _severity_for_rule(rule, math.nan, patient_context={}) is None


# ---------------------------------------------------------------------------
# A5: upload single-session rollback
# ---------------------------------------------------------------------------


def test_upload_pipeline_failure_rolls_back_single_session(monkeypatch, tmp_path) -> None:
    """Pipeline raises inside the single-session block → rollback, no stale commit."""

    import asyncio
    from types import SimpleNamespace
    from uuid import uuid4

    from fastapi import HTTPException

    from app.api.routes import upload as upload_route

    class _Session:
        def __init__(self) -> None:
            self.commit_calls = 0
            self.rollback_calls = 0
            self.flush_calls = 0

        async def commit(self) -> None:
            self.commit_calls += 1

        async def rollback(self) -> None:
            self.rollback_calls += 1

        async def flush(self) -> None:
            self.flush_calls += 1

    class _SessionContext:
        def __init__(self, session: _Session) -> None:
            self._session = session

        async def __aenter__(self) -> _Session:
            return self._session

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            # Mimic SQLAlchemy AsyncSession: rollback on exception.
            if exc_type is not None:
                await self._session.rollback()
            return False

    session = _Session()
    doc_id = uuid4()
    job_id = uuid4()
    update_captured: dict[str, object] = {}

    class FakeStore:
        def __init__(self, incoming):
            assert incoming is session

        async def get_job_by_idempotency_key(self, _k): return None
        async def get_job_by_input_checksum(self, _k): return None
        async def create_document(self, **kw): return SimpleNamespace(id=doc_id)
        async def create_job(self, **kw): return SimpleNamespace(id=job_id)
        async def update_job_status(self, _id, **kw):
            update_captured.update(kw)
            return SimpleNamespace(id=job_id)

    class FakePipeline:
        async def run(self, *a, **kw):
            raise RuntimeError("simulated pipeline blowup")

    monkeypatch.setattr(upload_route, "TopLevelLifecycleStore", FakeStore)
    monkeypatch.setattr(upload_route, "PipelineOrchestrator", lambda: FakePipeline())
    monkeypatch.setattr(
        upload_route, "_write_upload_file",
        lambda **kw: tmp_path / "rollback.pdf",
    )

    class _UploadFile:
        def __init__(self) -> None:
            self.filename = "report.pdf"
            self.content_type = "application/pdf"
            self._payload = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"

        async def read(self) -> bytes:
            return self._payload

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            upload_route.upload_lab_report(
                _UploadFile(),
                session_factory=lambda: _SessionContext(session),
            )
        )

    assert exc_info.value.status_code == 422
    # Main session: never committed (pipeline failed before commit).
    assert session.commit_calls == 1, (
        "Only the fresh failed-status session commits; the main session must "
        "rollback. Commit count reflects the fresh session reusing the same "
        "dummy instance."
    )
    assert session.rollback_calls >= 1
    # Failure bookkeeping recorded via fresh session path.
    assert update_captured["status"] == "failed"
    assert "simulated pipeline blowup" in update_captured["operator_note"]
