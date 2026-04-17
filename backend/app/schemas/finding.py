"""Rule finding schema (blueprint sections 3.8-3.10)."""

from enum import Enum
from uuid import UUID

from pydantic import BaseModel

from app.schemas.observation import CONTRACT_VERSION as OBSERVATION_CONTRACT_VERSION


class SeverityClass(str, Enum):
    S0 = "S0"  # no actionable finding
    S1 = "S1"  # review routinely
    S2 = "S2"  # discuss at next planned visit
    S3 = "S3"  # contact clinician soon
    S4 = "S4"  # urgent follow-up recommended
    SX = "SX"  # cannot assess severity


class NextStepClass(str, Enum):
    A0 = "A0"  # no specific action beyond routine self-monitoring
    A1 = "A1"  # review at next planned visit
    A2 = "A2"  # schedule routine follow-up
    A3 = "A3"  # contact clinician soon
    A4 = "A4"  # seek urgent review
    AX = "AX"  # cannot suggest a next step safely


class FindingSchema(BaseModel):
    contract_version: str = OBSERVATION_CONTRACT_VERSION
    finding_id: str
    rule_id: str
    observation_ids: list[UUID]
    threshold_source: str
    severity_class: SeverityClass
    nextstep_class: NextStepClass
    suppression_conditions: dict | None = None
    suppression_active: bool = False
    suppression_reason: str | None = None
    explanatory_scaffold_id: str | None = None
