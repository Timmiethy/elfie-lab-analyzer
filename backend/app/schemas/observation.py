"""Observation contract (blueprint section 3.5)."""

from enum import Enum
from uuid import UUID

from pydantic import BaseModel

CONTRACT_VERSION = "observation-contract-v1"


class SupportState(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    PARTIAL = "partial"


class MappingCandidateSchema(BaseModel):
    candidate_code: str
    candidate_display: str
    score: float
    threshold_used: float
    accepted: bool
    rejection_reason: str | None = None


class ObservationSchema(BaseModel):
    contract_version: str = CONTRACT_VERSION
    id: UUID
    document_id: UUID
    source_page: int
    row_hash: str
    raw_analyte_label: str
    raw_value_string: str | None = None
    raw_unit_string: str | None = None
    parsed_numeric_value: float | None = None
    candidates: list[MappingCandidateSchema] = []
    accepted_analyte_code: str | None = None
    accepted_analyte_display: str | None = None
    specimen_context: str | None = None
    method_context: str | None = None
    raw_reference_range: str | None = None
    canonical_unit: str | None = None
    canonical_value: float | None = None
    selected_reference_profile: str | None = None
    language_id: str | None = None
    support_state: SupportState
    suppression_reasons: list[str] = []
