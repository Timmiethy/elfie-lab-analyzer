"""Patient and clinician artifact schemas (blueprint sections 4.3, 4.6)."""

from uuid import UUID

from pydantic import BaseModel

from app.schemas.finding import FindingSchema, NextStepClass, SeverityClass


class FlaggedCard(BaseModel):
    analyte_display: str
    value: str
    unit: str
    finding_sentence: str
    threshold_provenance: str
    severity_chip: SeverityClass


class UnsupportedItem(BaseModel):
    raw_label: str
    reason: str


class PatientArtifactSchema(BaseModel):
    job_id: UUID
    support_banner: str  # fully_supported | partially_supported | could_not_assess
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
    job_id: UUID
    report_date: str
    top_findings: list[FindingSchema] = []
    severity_classes: list[SeverityClass] = []
    nextstep_classes: list[NextStepClass] = []
    support_coverage: str
    not_assessed: list[UnsupportedItem] = []
    provenance_link: str | None = None
