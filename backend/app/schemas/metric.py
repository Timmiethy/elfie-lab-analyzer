"""Metric and Reference Profile definitions (Blueprint Section)."""

from enum import Enum

from pydantic import BaseModel, Field


class ResultType(str, Enum):
    NUMERIC = "numeric"
    QUALITATIVE = "qualitative"
    ORDINAL = "ordinal"
    RATIO = "ratio"
    TEXT = "text"
    DERIVED = "derived"


class SourceType(str, Enum):
    ROW = "report_row"
    TABLE = "report_table"
    FAMILY_OVERRIDE = "family_override"
    CANONICAL_DEFAULT = "canonical_default"


class AppliesTo(BaseModel):
    sex: list[str] | None = Field(default=None, description="['M', 'F']")
    age_low: float | None = Field(default=None, description="Minimum age in years")
    age_high: float | None = Field(default=None, description="Maximum age in years")
    pregnancy: bool | None = Field(default=None, description="True if applies to pregnant patients")
    specimen: str | None = Field(default=None, description="Target specimen context")
    method: str | None = Field(default=None, description="Target analytical method")
    analyzer: str | None = Field(default=None, description="Target analyzer")


class ReferenceProfile(BaseModel):
    profile_id: str
    metric_id: str
    source_type: SourceType
    applies_to: AppliesTo
    ref_low: float | None = None
    ref_high: float | None = None
    ref_text: str | None = None
    comparator_policy: str | None = None
    priority: int = 5  # Lower number = higher priority (0 highest)


class MetricDefinition(BaseModel):
    metric_id: str
    canonical_name: str
    loinc_candidates: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    specimen: str | None = None
    result_type: ResultType
    canonical_unit_ucum: str | None = None
    accepted_report_units: list[str] = Field(default_factory=list)
    conversion_rule_id: str | None = None
    sex_applicability: list[str] | None = None
    age_applicability: list[float] | None = None
    pregnancy_applicability: bool | None = None
    method_scope: list[str] | None = None
    analyzer_scope: list[str] | None = None
    default_reference_profiles: list[ReferenceProfile] = Field(default_factory=list)
    qualitative_expected_values: list[str] = Field(default_factory=list)
    derived_formula_id: str | None = None
