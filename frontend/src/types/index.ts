/** Mirrors backend schema enums and types.
 *
 * Source of truth: backend/app/schemas/*. Keep this file in sync with:
 *   - app/schemas/upload.py       → UploadResponse
 *   - app/schemas/finding.py      → SeverityClass, NextStepClass, FindingSchema
 *   - app/schemas/observation.py  → SupportState
 *   - app/schemas/artifact.py     → SupportBanner, TrustStatus, PromotionStatus,
 *                                    UnsupportedReason, ComparableHistory*,
 *                                    TraceRefs, PatientArtifact, ClinicianArtifact
 *   - app/api/routes/jobs.py      → job status payload
 *   - app/services/input_gateway/ → LaneType values
 */

export type SeverityClass = 'S0' | 'S1' | 'S2' | 'S3' | 'S4' | 'SX';
export type NextStepClass = 'A0' | 'A1' | 'A2' | 'A3' | 'A4' | 'AX';
export type SupportState = 'supported' | 'unsupported' | 'partial';
export type SupportBanner =
  | 'fully_supported'
  | 'partially_supported'
  | 'could_not_assess';
export type TrustStatus = 'trusted' | 'non_trusted_beta';

/** Matches backend input_gateway runtime lane values. */
export type LaneType = 'trusted_pdf' | 'image_beta' | 'unsupported';

/** Matches backend PromotionStatus (app/schemas/artifact.py). */
export type PromotionStatus =
  | 'not_applicable'
  | 'beta_pending'
  | 'promoted_to_trusted'
  | 'remains_beta'
  | 'unsupported';

/** Matches backend UnsupportedReason (app/schemas/artifact.py). */
export type UnsupportedReason =
  | 'no_extractable_text'
  | 'unsupported_family'
  | 'unsupported_unit_or_reference_range'
  | 'threshold_conflict'
  | 'comparable_history_unavailable'
  | 'insufficient_support'
  | 'unreadable_value'
  | 'unit_parse_fail'
  | 'bilingual_label_unresolved'
  | 'ambiguous_analyte'
  | 'missing_overlay_context'
  | 'derived_observation_unbound'
  | 'specimen_or_method_conflict'
  | 'unsupported_beta_row'
  | 'password_protected_pdf'
  | 'corrupt_pdf';

/** Human-friendly labels for the enum codes above (UI-only). */
export const UNSUPPORTED_REASON_LABELS: Record<UnsupportedReason, string> = {
  no_extractable_text: 'No readable text in the document.',
  unsupported_family: 'Outside the current supported analyte set.',
  unsupported_unit_or_reference_range:
    'Unit or reference range is not supported.',
  threshold_conflict: 'Conflicting thresholds could not be resolved.',
  comparable_history_unavailable: 'No comparable history available.',
  insufficient_support: 'Not enough information to assess safely.',
  unreadable_value: 'Value could not be read.',
  unit_parse_fail: 'Unit could not be parsed.',
  bilingual_label_unresolved: 'Bilingual label could not be resolved.',
  ambiguous_analyte: 'Could not map to a known standard analyte.',
  missing_overlay_context: 'Missing overlay context.',
  derived_observation_unbound: 'Derived observation could not be bound.',
  specimen_or_method_conflict: 'Specimen or method conflict.',
  unsupported_beta_row: 'Row unsupported in beta preview.',
  password_protected_pdf: 'PDF is password protected.',
  corrupt_pdf: 'PDF is corrupt or unreadable.',
};

/**
 * Render an unsupported item in the UI. Prefers the free-text
 * `internal_reason` (human-authored) and falls back to the enum label.
 */
export function unsupportedReasonDisplay(item: {
  reason: UnsupportedReason;
  internal_reason?: string | null;
}): string {
  return (
    item.internal_reason ||
    UNSUPPORTED_REASON_LABELS[item.reason] ||
    item.reason
  );
}

export interface UploadResponse {
  job_id: string;
  status: string;
  lane_type: LaneType;
  message: string;
  is_mocked?: boolean;
}

export interface JobStatus {
  job_id: string;
  status: string;
  step?: string | null;
  lane_type?: LaneType;
  is_mocked?: boolean;
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
  reason: UnsupportedReason;
  internal_reason?: string | null;
}

/** Mirrors backend FindingSchema (rule finding shape, app/schemas/finding.py). */
export interface FindingSchema {
  contract_version?: string;
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

/** Mirrors backend ComparableHistoryCard (app/schemas/artifact.py). */
export interface ComparableHistory {
  analyte_display: string;
  current_value: string;
  current_unit: string;
  previous_value: string | null;
  previous_unit: string | null;
  current_date: string | null;
  previous_date: string | null;
  direction: 'increased' | 'decreased' | 'similar' | 'trend_unavailable';
  comparability_status: 'available' | 'unavailable';
}

/** Mirrors backend TraceRefs (app/schemas/artifact.py). */
export interface TraceRefs {
  proof_pack?: string | null;
  parser_trace?: string | null;
  normalization_trace?: string | null;
  suppression_report?: string | null;
}

/** Mirrors backend PatientArtifactSchema (app/schemas/artifact.py). */
export interface PatientArtifact {
  contract_version?: string;
  job_id: string;
  support_banner: SupportBanner;
  trust_status: TrustStatus;
  promotion_status?: PromotionStatus;
  overall_severity: SeverityClass;
  flagged_cards: FlaggedCard[];
  reviewed_not_flagged: string[];
  nextstep_title: string;
  nextstep_timing: string | null;
  nextstep_reason: string | null;
  not_assessed: UnsupportedItem[];
  findings: FindingSchema[];
  language_id: string;
  explanation?: Record<string, unknown> | null;
  comparable_history: ComparableHistory | null;
  trace_refs?: TraceRefs | null;
}

/** Mirrors backend ClinicianArtifactSchema (app/schemas/artifact.py). */
export interface ClinicianArtifact {
  contract_version?: string;
  job_id: string;
  report_date: string;
  top_findings: FindingSchema[];
  severity_classes: SeverityClass[];
  nextstep_classes: NextStepClass[];
  support_coverage: SupportBanner;
  trust_status: TrustStatus;
  promotion_status?: PromotionStatus;
  not_assessed: UnsupportedItem[];
  provenance_link: string | null;
  trace_refs?: TraceRefs | null;
  /**
   * Not in backend schema but used locally in the UI to pass through the
   * patient-artifact banner when rendering the clinician page. Remove once
   * the UI reads `support_coverage` directly.
   */
  support_banner?: SupportBanner;
}
