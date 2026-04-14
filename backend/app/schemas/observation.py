"""Observation contract (blueprint section 3.5)."""

from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel

CONTRACT_VERSION = "observation-contract-v2"


class SupportState(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    PARTIAL = "partial"


class RowType(str, Enum):
    MEASURED_ANALYTE_ROW = "measured_analyte_row"
    DERIVED_ANALYTE_ROW = "derived_analyte_row"
    THRESHOLD_REFERENCE_ROW = "threshold_reference_row"
    NARRATIVE_GUIDANCE_ROW = "narrative_guidance_row"
    ADMIN_METADATA_ROW = "admin_metadata_row"
    FOOTER_OR_HEADER_ROW = "footer_or_header_row"
    TESTS_REQUESTED_ROW = "tests_requested_row"
    UNKNOWN_ROW = "unknown_row"


class MeasurementKind(str, Enum):
    DIRECT_MEASUREMENT = "direct_measurement"
    DERIVED_MEASUREMENT = "derived_measurement"
    QUALITATIVE_MEASUREMENT = "qualitative_measurement"
    THRESHOLD_REFERENCE = "threshold_reference"
    NARRATIVE_CONTEXT = "narrative_context"


class SupportCode(str, Enum):
    ACCEPTED_RESULT = "accepted_result"
    PROMOTED_BETA_RESULT = "promoted_beta_result"
    PARTIAL_RESULT = "partial_result"
    UNRESOLVED_RESULT = "unresolved_result"
    BETA_PREVIEW_ONLY = "beta_preview_only"
    NON_RESULT_ROW_EXCLUDED = "non_result_row_excluded"
    SUPPORTED_RESULT = "supported_result"
    MEASURED_RESULT = "measured_result"
    DUAL_UNIT_RESULT = "dual_unit_result"
    DERIVED_RESULT = "derived_result"


class FailureCode(str, Enum):
    ADMIN_METADATA_ROW = "admin_metadata_row"
    NARRATIVE_ROW = "narrative_row"
    THRESHOLD_TABLE_ROW = "threshold_table_row"
    FOOTER_OR_HEADER_ROW = "footer_or_header_row"
    UNREADABLE_VALUE = "unreadable_value"
    UNIT_PARSE_FAIL = "unit_parse_fail"
    MIXED_MEASUREMENT_AND_THRESHOLD_ROW = "mixed_measurement_and_threshold_row"
    BILINGUAL_LABEL_UNRESOLVED = "bilingual_label_unresolved"
    AMBIGUOUS_ANALYTE = "ambiguous_analyte"
    UNSUPPORTED_FAMILY = "unsupported_family"
    MISSING_OVERLAY_CONTEXT = "missing_overlay_context"
    DERIVED_OBSERVATION_UNBOUND = "derived_observation_unbound"
    SPECIMEN_OR_METHOD_CONFLICT = "specimen_or_method_conflict"
    THRESHOLD_CONFLICT = "threshold_conflict"
    UNSUPPORTED_UNIT_OR_REFERENCE_RANGE = "unsupported_unit_or_reference_range"
    COMPARABLE_HISTORY_UNAVAILABLE = "comparable_history_unavailable"
    UNSUPPORTED_BETA_ROW = "unsupported_beta_row"
    NO_EXTRACTABLE_TEXT = "no_extractable_text"
    PASSWORD_PROTECTED_PDF = "password_protected_pdf"
    CORRUPT_PDF = "corrupt_pdf"


class MappingCandidateSchema(BaseModel):
    candidate_code: str
    candidate_display: str
    score: float
    threshold_used: float
    accepted: bool
    rejection_reason: str | None = None


class ParsedResultSchema(BaseModel):
    raw_value: str | None = None
    numeric_value: float | None = None
    unit: str | None = None
    comparator: str | None = None
    locale: str | None = None
    value_channel: str
    parse_confidence: float | None = None


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
    language_id: str | None = None
    support_state: SupportState
    support_code: SupportCode | None = None
    failure_code: FailureCode | None = None
    suppression_reasons: list[str] = []
    row_type: RowType = RowType.MEASURED_ANALYTE_ROW
    measurement_kind: MeasurementKind = MeasurementKind.DIRECT_MEASUREMENT
    source_block_id: str | None = None
    source_row_id: str | None = None
    family_adapter_id: str | None = None
    parsed_locale: str | None = None
    parsed_comparator: str | None = None
    primary_result: ParsedResultSchema | None = None
    secondary_result: ParsedResultSchema | None = None
    candidate_trace: list[dict[str, Any]] | dict[str, Any] | None = None
    derived_formula_id: str | None = None
    source_observation_ids: list[UUID] = []
