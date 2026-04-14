"""Shared row-type, support-code, and failure-code enums."""

from __future__ import annotations

from enum import StrEnum


class RowTypeV1(StrEnum):
    MEASURED_ANALYTE_ROW = "measured_analyte_row"
    DERIVED_ANALYTE_ROW = "derived_analyte_row"
    QUALITATIVE_RESULT_ROW = "qualitative_result_row"
    THRESHOLD_REFERENCE_ROW = "threshold_reference_row"
    ADMIN_METADATA_ROW = "admin_metadata_row"
    NARRATIVE_GUIDANCE_ROW = "narrative_guidance_row"
    HEADER_FOOTER_ROW = "header_footer_row"
    TEST_REQUEST_ROW = "test_request_row"
    UNPARSED_ROW = "unparsed_row"


class SupportCodeV1(StrEnum):
    SUPPORTED = "supported"
    PARTIAL = "partial"
    EXCLUDED = "excluded"


class FailureCodeV1(StrEnum):
    ADMIN_METADATA_ROW = "admin_metadata_row"
    NARRATIVE_GUIDANCE_ROW = "narrative_guidance_row"
    THRESHOLD_REFERENCE_ROW = "threshold_reference_row"
    HEADER_FOOTER_ROW = "header_footer_row"
    TEST_REQUEST_ROW = "test_request_row"
    EMPTY_OR_NOISE = "empty_or_noise"
    UNPARSED_ROW = "unparsed_row"
    UNIT_PARSE_FAIL = "unit_parse_fail"
    UNSUPPORTED_FAMILY = "unsupported_family"
    DERIVED_OBSERVATION_UNBOUND = "derived_observation_unbound"


ROW_TYPE_VALUES = {member.value for member in RowTypeV1}
SUPPORT_CODE_VALUES = {member.value for member in SupportCodeV1}
FAILURE_CODE_VALUES = {member.value for member in FailureCodeV1}
