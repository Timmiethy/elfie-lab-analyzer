/** Mirrors backend schema enums and types. */

export type SeverityClass = 'S0' | 'S1' | 'S2' | 'S3' | 'S4' | 'SX';
export type NextStepClass = 'A0' | 'A1' | 'A2' | 'A3' | 'A4' | 'AX';
export type SupportState = 'supported' | 'unsupported' | 'partial';
export type SupportBanner = 'fully_supported' | 'partially_supported' | 'could_not_assess';
export type TrustStatus = 'trusted' | 'non_trusted_beta';
export type LaneType = 'trusted_pdf' | 'image_beta' | 'structured';

export interface UploadResponse {
  job_id: string;
  status: string;
  lane_type: LaneType;
  message: string;
}

export interface JobStatus {
  job_id: string;
  status: string;
  step: string;
}

export interface FlaggedCard {
  analyte_display: string;
  value: string;
  unit: string;
  finding_sentence: string;
  threshold_provenance: string;
  severity_chip: SeverityClass;
}

export interface UnsupportedItem {
  raw_label: string;
  reason: string;
}

/** Mirrors backend FindingSchema (rule finding shape, app/schemas/finding.py). */
export interface FindingSchema {
  finding_id: string;
  rule_id: string;
  observation_ids: string[];
  threshold_source: string;
  severity_class: SeverityClass;
  nextstep_class: NextStepClass;
  suppression_conditions: Record<string, unknown> | null;
  suppression_active: boolean;
  suppression_reason: string | null;
  explanatory_scaffold_id: string | null;
}

export interface ComparableHistoryEntry {
  analyte_display: string;
  current_value: string;
  current_unit: string;
  previous_value: string | null;
  previous_unit: string | null;
  current_date?: string | null;
  previous_date: string | null;
  direction: 'increased' | 'decreased' | 'similar' | 'trend_unavailable';
  comparability_status:
    | 'comparable'
    | 'not_comparable'
    | 'available'
    | 'unavailable';
  comparability_reason?: string | null;
}

export type ComparableHistoryPayload =
  | ComparableHistoryEntry[]
  | ComparableHistoryEntry
  | null;

export interface PatientArtifact {
  job_id: string;
  support_banner: SupportBanner;
  trust_status?: TrustStatus;
  overall_severity: SeverityClass;
  flagged_cards: FlaggedCard[];
  reviewed_not_flagged: string[];
  nextstep_title: string;
  nextstep_timing: string | null;
  nextstep_reason: string | null;
  not_assessed: UnsupportedItem[];
  findings: FindingSchema[];
  language_id: string;
  comparable_history: ComparableHistoryPayload;
}

/** Mirrors backend ClinicianArtifactSchema (app/schemas/artifact.py). */
export interface ClinicianArtifact {
  job_id: string;
  report_date: string;
  top_findings?: FindingSchema[];
  severity_classes?: SeverityClass[];
  nextstep_classes?: NextStepClass[];
  support_coverage: SupportBanner | string;
  trust_status?: TrustStatus;
  not_assessed: UnsupportedItem[];
  provenance_link: string | null;
  support_banner?: SupportBanner;
}
