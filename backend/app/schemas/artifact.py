"""Patient and clinician artifact schemas (blueprint sections 4.3, 4.6)."""

from enum import Enum
from uuid import UUID

from pydantic import BaseModel

from app.schemas.finding import FindingSchema, NextStepClass, SeverityClass
from app.schemas.observation import CONTRACT_VERSION as OBSERVATION_CONTRACT_VERSION


class SupportBanner(str, Enum):
    FULLY_SUPPORTED = "fully_supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    COULD_NOT_ASSESS = "could_not_assess"


class TrustStatus(str, Enum):
    TRUSTED = "trusted"
    NON_TRUSTED_BETA = "non_trusted_beta"


class UnsupportedReason(str, Enum):
    NO_EXTRACTABLE_TEXT = "no_extractable_text"
    UNSUPPORTED_ANALYTE_FAMILY = "unsupported_analyte_family"
    UNSUPPORTED_UNIT_OR_REFERENCE_RANGE = "unsupported_unit_or_reference_range"
    THRESHOLD_CONFLICT = "threshold_conflict"
    COMPARABLE_HISTORY_UNAVAILABLE = "comparable_history_unavailable"
    INSUFFICIENT_SUPPORT = "insufficient_support"


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


class PatientArtifactSchema(BaseModel):
    contract_version: str = OBSERVATION_CONTRACT_VERSION
    job_id: UUID
    support_banner: SupportBanner
    trust_status: TrustStatus
    overall_severity: SeverityClass
    flagged_cards: list[FlaggedCard] = []
    reviewed_not_flagged: list[str] = []
    nextstep_title: str
    nextstep_timing: str | None = None
    nextstep_reason: str | None = None
    not_assessed: list[UnsupportedItem] = []
    findings: list[FindingSchema] = []
    language_id: str = "en"


class ClinicianArtifactSchema(BaseModel):
    contract_version: str = OBSERVATION_CONTRACT_VERSION
    job_id: UUID
    report_date: str
    top_findings: list[FindingSchema] = []
    severity_classes: list[SeverityClass] = []
    nextstep_classes: list[NextStepClass] = []
    support_coverage: SupportBanner
    trust_status: TrustStatus
    not_assessed: list[UnsupportedItem] = []
    provenance_link: str | None = None
