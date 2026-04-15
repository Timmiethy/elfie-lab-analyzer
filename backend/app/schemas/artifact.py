"""Patient and clinician artifact schemas (blueprint sections 4.3, 4.6)."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel

from app.schemas.finding import FindingSchema, NextStepClass, SeverityClass
from app.schemas.observation import CONTRACT_VERSION as OBSERVATION_CONTRACT_VERSION


class SupportBanner(StrEnum):
    FULLY_SUPPORTED = "fully_supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    COULD_NOT_ASSESS = "could_not_assess"


class TrustStatus(StrEnum):
    TRUSTED = "trusted"
    NON_TRUSTED_BETA = "non_trusted_beta"


class PromotionStatus(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    BETA_PENDING = "beta_pending"
    PROMOTED_TO_TRUSTED = "promoted_to_trusted"
    REMAINS_BETA = "remains_beta"
    UNSUPPORTED = "unsupported"


class UnsupportedReason(StrEnum):
    NO_EXTRACTABLE_TEXT = "no_extractable_text"
    UNSUPPORTED_FAMILY = "unsupported_family"
    UNSUPPORTED_UNIT_OR_REFERENCE_RANGE = "unsupported_unit_or_reference_range"
    THRESHOLD_CONFLICT = "threshold_conflict"
    COMPARABLE_HISTORY_UNAVAILABLE = "comparable_history_unavailable"
    INSUFFICIENT_SUPPORT = "insufficient_support"
    UNREADABLE_VALUE = "unreadable_value"
    UNIT_PARSE_FAIL = "unit_parse_fail"
    BILINGUAL_LABEL_UNRESOLVED = "bilingual_label_unresolved"
    AMBIGUOUS_ANALYTE = "ambiguous_analyte"
    MISSING_OVERLAY_CONTEXT = "missing_overlay_context"
    DERIVED_OBSERVATION_UNBOUND = "derived_observation_unbound"
    SPECIMEN_OR_METHOD_CONFLICT = "specimen_or_method_conflict"
    UNSUPPORTED_BETA_ROW = "unsupported_beta_row"
    PASSWORD_PROTECTED_PDF = "password_protected_pdf"
    CORRUPT_PDF = "corrupt_pdf"


class FlaggedCard(BaseModel):
    analyte_display: str
    value: str
    unit: str
    finding_sentence: str
    threshold_provenance: str
    severity_chip: SeverityClass


class UnsupportedItem(BaseModel):
    raw_label: str
    reason: UnsupportedReason
    internal_reason: str | None = None


class ComparableHistoryStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class ComparableHistoryDirection(StrEnum):
    INCREASED = "increased"
    DECREASED = "decreased"
    SIMILAR = "similar"
    TREND_UNAVAILABLE = "trend_unavailable"


class ComparableHistoryCard(BaseModel):
    analyte_display: str
    current_value: str
    current_unit: str
    previous_value: str | None = None
    previous_unit: str | None = None
    current_date: str | None = None
    previous_date: str | None = None
    direction: ComparableHistoryDirection
    comparability_status: ComparableHistoryStatus


class TraceRefs(BaseModel):
    proof_pack: str | None = None
    parser_trace: str | None = None
    normalization_trace: str | None = None
    suppression_report: str | None = None


class PatientArtifactSchema(BaseModel):
    contract_version: str = OBSERVATION_CONTRACT_VERSION
    job_id: UUID
    support_banner: SupportBanner
    trust_status: TrustStatus
    promotion_status: PromotionStatus = PromotionStatus.NOT_APPLICABLE
    overall_severity: SeverityClass
    flagged_cards: list[FlaggedCard] = []
    reviewed_not_flagged: list[str] = []
    nextstep_title: str
    nextstep_timing: str | None = None
    nextstep_reason: str | None = None
    not_assessed: list[UnsupportedItem] = []
    findings: list[FindingSchema] = []
    language_id: str = "en"
    explanation: dict | None = None
    comparable_history: ComparableHistoryCard | None = None
    trace_refs: TraceRefs | None = None


class ClinicianArtifactSchema(BaseModel):
    contract_version: str = OBSERVATION_CONTRACT_VERSION
    job_id: UUID
    report_date: str
    top_findings: list[FindingSchema] = []
    severity_classes: list[SeverityClass] = []
    nextstep_classes: list[NextStepClass] = []
    support_coverage: SupportBanner
    trust_status: TrustStatus
    promotion_status: PromotionStatus = PromotionStatus.NOT_APPLICABLE
    not_assessed: list[UnsupportedItem] = []
    provenance_link: str | None = None
    trace_refs: TraceRefs | None = None
