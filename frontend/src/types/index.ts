/** Mirrors backend schema enums and types. */

export type SeverityClass = 'S0' | 'S1' | 'S2' | 'S3' | 'S4' | 'SX';
export type NextStepClass = 'A0' | 'A1' | 'A2' | 'A3' | 'A4' | 'AX';
export type SupportState = 'supported' | 'unsupported' | 'partial';
export type SupportBanner = 'fully_supported' | 'partially_supported' | 'could_not_assess';
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

export interface PatientArtifact {
  job_id: string;
  support_banner: SupportBanner;
  overall_severity: SeverityClass;
  flagged_cards: FlaggedCard[];
  reviewed_not_flagged: string[];
  nextstep_title: string;
  nextstep_timing: string | null;
  nextstep_reason: string | null;
  not_assessed: UnsupportedItem[];
  language_id: string;
}

export interface ClinicianArtifact {
  job_id: string;
  report_date: string;
  support_coverage: string;
  not_assessed: UnsupportedItem[];
  provenance_link: string | null;
}
