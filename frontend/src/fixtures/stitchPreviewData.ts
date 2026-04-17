/**
 * Deterministic preview fixtures for the patient artifact surface.
 *
 * These fixtures are reviewable without backend artifact routes.
 * They are clearly separated from the live fetch flow and conform
 * to the current PatientArtifact type contract.
 *
 * Supported preview variants:
 * - fully_supported (EN / VI)
 * - partially_supported (EN / VI)
 * - could_not_assess (EN / VI)
 *
 * Each variant may carry comparable-history metadata for App preview routing.
 */

import type {
  PatientArtifact,
  ClinicianArtifact,
  FlaggedCard,
  UnsupportedItem,
  FindingSchema,
  SeverityClass,
  NextStepClass,
} from '../types';

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

const EMPTY_FINDINGS: FindingSchema[] = [];

function makeFinding(
  ruleId: string,
  severity: SeverityClass,
  nextstep: NextStepClass,
): FindingSchema {
  return {
    finding_id: `finding-${ruleId}`,
    rule_id: ruleId,
    observation_ids: [`obs-${ruleId}-1`],
    threshold_source: 'Lab-printed reference range',
    severity_class: severity,
    nextstep_class: nextstep,
    suppression_conditions: null,
    suppression_active: false,
    suppression_reason: null,
    explanatory_scaffold_id: null,
  };
}

// ---------------------------------------------------------------------------
// EN — fully supported
// ---------------------------------------------------------------------------

const EN_FULLY_FLAGGED: FlaggedCard[] = [
  {
    analyte_display: 'Fasting glucose',
    value: '126',
    unit: 'mg/dL',
    finding_sentence:
      'Your fasting glucose is above the reference range (70–100 mg/dL). This can be a sign of prediabetes or diabetes and should be reviewed with your clinician.',
    threshold_provenance: 'Lab-printed reference range: 70–100 mg/dL',
    severity_chip: 'S2',
  },
  {
    analyte_display: 'HbA1c',
    value: '6.8',
    unit: '%',
    finding_sentence:
      'Your HbA1c is above the reference range (< 5.7%). This level falls in the diabetes range and should be discussed with your clinician at your next visit.',
    threshold_provenance: 'Lab-printed reference range: < 5.7%',
    severity_chip: 'S2',
  },
];

const EN_FULLY_NOT_FLAGGED: string[] = [
  'Total cholesterol — 185 mg/dL',
  'HDL cholesterol — 52 mg/dL',
  'LDL cholesterol — 110 mg/dL',
  'Triglycerides — 115 mg/dL',
  'Creatinine — 0.9 mg/dL',
];

const EN_FULLY_NOT_ASSESSED: UnsupportedItem[] = [];

const EN_FULLY_ARTIFACT: PatientArtifact = {
  job_id: 'preview-en-fully-supported',
  support_banner: 'fully_supported',
  overall_severity: 'S2',
  flagged_cards: EN_FULLY_FLAGGED,
  reviewed_not_flagged: EN_FULLY_NOT_FLAGGED,
  nextstep_title: 'Discuss these results with your clinician at your next visit.',
  nextstep_timing: 'Within the next few weeks',
  nextstep_reason:
    'Elevated fasting glucose and HbA1c suggest further review is appropriate.',
  not_assessed: EN_FULLY_NOT_ASSESSED,
  findings: [
    makeFinding('glucose-high', 'S2', 'A2'),
    makeFinding('hba1c-high', 'S2', 'A2'),
  ],
  language_id: 'en',
  comparable_history: [],
};

const EN_FULLY_CLINICIAN: ClinicianArtifact = {
  job_id: 'preview-en-fully-supported',
  report_date: '2026-04-11',
  top_findings: EN_FULLY_ARTIFACT.findings,
  severity_classes: ['S2'],
  nextstep_classes: ['A2'],
  support_coverage:
    'All supported rows were reviewed from a trusted PDF upload. Unsupported rows: none.',
  not_assessed: EN_FULLY_NOT_ASSESSED,
  provenance_link:
    'data:text/plain,Preview provenance for fasting glucose and HbA1c derived from supported PDF rows.',
  support_banner: 'fully_supported',
};

// ---------------------------------------------------------------------------
// EN — partially supported
// ---------------------------------------------------------------------------

const EN_PARTIAL_FLAGGED: FlaggedCard[] = [
  {
    analyte_display: 'Creatinine',
    value: '1.4',
    unit: 'mg/dL',
    finding_sentence:
      'Your creatinine is above the reference range (0.7–1.3 mg/dL). This may suggest reduced kidney function and should be discussed with your clinician.',
    threshold_provenance: 'Lab-printed reference range: 0.7–1.3 mg/dL',
    severity_chip: 'S2',
  },
];

const EN_PARTIAL_NOT_FLAGGED: string[] = [
  'Fasting glucose — 92 mg/dL',
  'Total cholesterol — 200 mg/dL',
];

const EN_PARTIAL_NOT_ASSESSED: UnsupportedItem[] = [
  {
    raw_label: 'Urine microalbumin',
    reason: 'Could not map to a known standard analyte in the supported list.',
  },
  {
    raw_label: 'Vitamin D (25-OH)',
    reason: 'Outside the current supported analyte set.',
  },
];

const EN_PARTIAL_ARTIFACT: PatientArtifact = {
  job_id: 'preview-en-partially-supported',
  support_banner: 'partially_supported',
  overall_severity: 'S2',
  flagged_cards: EN_PARTIAL_FLAGGED,
  reviewed_not_flagged: EN_PARTIAL_NOT_FLAGGED,
  nextstep_title: 'Discuss these results with your clinician.',
  nextstep_timing: 'At your next planned visit',
  nextstep_reason:
    'Creatinine is elevated; some items could not be assessed.',
  not_assessed: EN_PARTIAL_NOT_ASSESSED,
  findings: [makeFinding('creatinine-high', 'S2', 'A2')],
  language_id: 'en',
  comparable_history: [
    {
      analyte_display: 'Creatinine',
      current_value: '1.4',
      current_unit: 'mg/dL',
      previous_value: '1.1',
      previous_unit: 'mg/dL',
      previous_date: '2025-01-15',
      direction: 'increased',
      comparability_status: 'comparable',
      comparability_reason: null,
    },
  ],
};

const EN_PARTIAL_CLINICIAN: ClinicianArtifact = {
  job_id: 'preview-en-partially-supported',
  report_date: '2026-04-11',
  top_findings: EN_PARTIAL_ARTIFACT.findings,
  severity_classes: ['S2'],
  nextstep_classes: ['A2'],
  support_coverage:
    'Supported rows were reviewed, but one or more source rows could not be mapped or fell outside the supported analyte set.',
  not_assessed: EN_PARTIAL_NOT_ASSESSED,
  provenance_link:
    'data:text/plain,Preview provenance for creatinine derived from supported rows with unsupported items retained.',
  support_banner: 'partially_supported',
};

// ---------------------------------------------------------------------------
// EN — could not assess
// ---------------------------------------------------------------------------

const EN_CNA_ARTIFACT: PatientArtifact = {
  job_id: 'preview-en-could-not-assess',
  support_banner: 'could_not_assess',
  overall_severity: 'SX',
  flagged_cards: [],
  reviewed_not_flagged: [],
  nextstep_title: '',
  nextstep_timing: null,
  nextstep_reason: null,
  not_assessed: [
    {
      raw_label: 'All rows',
      reason:
        'The document could not be parsed into supported structured rows.',
    },
  ],
  findings: EMPTY_FINDINGS,
  language_id: 'en',
  comparable_history: [],
};

const EN_CNA_CLINICIAN: ClinicianArtifact = {
  job_id: 'preview-en-could-not-assess',
  report_date: '2026-04-11',
  top_findings: [],
  severity_classes: ['SX'],
  nextstep_classes: ['AX'],
  support_coverage:
    'The source document could not be parsed into supported structured rows, so this summary remains limited.',
  not_assessed: EN_CNA_ARTIFACT.not_assessed,
  provenance_link:
    'data:text/plain,Preview provenance unavailable because the source report could not be fully structured.',
  support_banner: 'could_not_assess',
};

// ---------------------------------------------------------------------------
// VI — fully supported
// ---------------------------------------------------------------------------

const VI_FULLY_FLAGGED: FlaggedCard[] = [
  {
    analyte_display: 'Glucose đói',
    value: '130',
    unit: 'mg/dL',
    finding_sentence:
      'Glucose đói của bạn cao hơn khoảng tham chiếu (70–100 mg/dL). Đây có thể là dấu hiệu của tiền tiểu đường hoặc tiểu đường và cần được bác sĩ xem xét.',
    threshold_provenance: 'Khoảng tham chiếu in trên phiếu: 70–100 mg/dL',
    severity_chip: 'S2',
  },
];

const VI_FULLY_NOT_FLAGGED: string[] = [
  'Cholesterol toàn phần — 180 mg/dL',
  'HDL cholesterol — 55 mg/dL',
];

const VI_FULLY_NOT_ASSESSED: UnsupportedItem[] = [];

const VI_FULLY_ARTIFACT: PatientArtifact = {
  job_id: 'preview-vi-fully-supported',
  support_banner: 'fully_supported',
  overall_severity: 'S2',
  flagged_cards: VI_FULLY_FLAGGED,
  reviewed_not_flagged: VI_FULLY_NOT_FLAGGED,
  nextstep_title: 'Trao đổi kết quả này với bác sĩ tại lần khám tiếp theo.',
  nextstep_timing: 'Trong vài tuần tới',
  nextstep_reason:
    'Glucose đói tăng cao, cần được xem xét thêm.',
  not_assessed: VI_FULLY_NOT_ASSESSED,
  findings: [makeFinding('glucose-high-vi', 'S2', 'A2')],
  language_id: 'vi',
  comparable_history: [],
};

const VI_FULLY_CLINICIAN: ClinicianArtifact = {
  job_id: 'preview-vi-fully-supported',
  report_date: '2026-04-11',
  top_findings: VI_FULLY_ARTIFACT.findings,
  severity_classes: ['S2'],
  nextstep_classes: ['A2'],
  support_coverage:
    'Tất cả các dòng được hỗ trợ đã được xem xét từ tệp PDF tin cậy. Không có mục nào bị bỏ sót.',
  not_assessed: VI_FULLY_NOT_ASSESSED,
  provenance_link:
    'data:text/plain,Ban xem truoc provenance cho glucose doi duoc trich tu PDF ho tro.',
  support_banner: 'fully_supported',
};

// ---------------------------------------------------------------------------
// VI — partially supported
// ---------------------------------------------------------------------------

const VI_PARTIAL_FLAGGED: FlaggedCard[] = [
  {
    analyte_display: 'Creatinine',
    value: '1.5',
    unit: 'mg/dL',
    finding_sentence:
      'Creatinine của bạn cao hơn khoảng tham chiếu (0.7–1.3 mg/dL). Điều này có thể cho thấy chức năng thận giảm và cần trao đổi với bác sĩ.',
    threshold_provenance: 'Khoảng tham chiếu in trên phiếu: 0.7–1.3 mg/dL',
    severity_chip: 'S2',
  },
];

const VI_PARTIAL_NOT_FLAGGED: string[] = [
  'Glucose đói — 95 mg/dL',
];

const VI_PARTIAL_NOT_ASSESSED: UnsupportedItem[] = [
  {
    raw_label: 'Vitamin D (25-OH)',
    reason: 'Nằm ngoài tập hợp chất phân tích được hỗ trợ hiện tại.',
  },
];

const VI_PARTIAL_ARTIFACT: PatientArtifact = {
  job_id: 'preview-vi-partially-supported',
  support_banner: 'partially_supported',
  overall_severity: 'S2',
  flagged_cards: VI_PARTIAL_FLAGGED,
  reviewed_not_flagged: VI_PARTIAL_NOT_FLAGGED,
  nextstep_title: 'Trao đổi kết quả này với bác sĩ.',
  nextstep_timing: 'Tại lần khám theo kế hoạch tiếp theo',
  nextstep_reason:
    'Creatinine tăng cao; một số mục không thể đánh giá.',
  not_assessed: VI_PARTIAL_NOT_ASSESSED,
  findings: [makeFinding('creatinine-high-vi', 'S2', 'A2')],
  language_id: 'vi',
  comparable_history: [
    {
      analyte_display: 'Creatinine',
      current_value: '1.5',
      current_unit: 'mg/dL',
      previous_value: '1.0',
      previous_unit: 'mg/dL',
      previous_date: '2025-02-10',
      direction: 'increased',
      comparability_status: 'comparable',
      comparability_reason: null,
    },
  ],
};

const VI_PARTIAL_CLINICIAN: ClinicianArtifact = {
  job_id: 'preview-vi-partially-supported',
  report_date: '2026-04-11',
  top_findings: VI_PARTIAL_ARTIFACT.findings,
  severity_classes: ['S2'],
  nextstep_classes: ['A2'],
  support_coverage:
    'Các dòng được hỗ trợ đã được xem xét, nhưng một số dòng nguồn không thể ánh xạ hoặc nằm ngoài phạm vi hỗ trợ hiện tại.',
  not_assessed: VI_PARTIAL_NOT_ASSESSED,
  provenance_link:
    'data:text/plain,Ban xem truoc provenance cho creatinine tu cac dong duoc ho tro.',
  support_banner: 'partially_supported',
};

// ---------------------------------------------------------------------------
// VI — could not assess
// ---------------------------------------------------------------------------

const VI_CNA_ARTIFACT: PatientArtifact = {
  job_id: 'preview-vi-could-not-assess',
  support_banner: 'could_not_assess',
  overall_severity: 'SX',
  flagged_cards: [],
  reviewed_not_flagged: [],
  nextstep_title: '',
  nextstep_timing: null,
  nextstep_reason: null,
  not_assessed: [
    {
      raw_label: 'Tất cả các dòng',
      reason:
        'Không thể phân tích tài liệu thành các dòng có cấu trúc được hỗ trợ.',
    },
  ],
  findings: EMPTY_FINDINGS,
  language_id: 'vi',
  comparable_history: [],
};

const VI_CNA_CLINICIAN: ClinicianArtifact = {
  job_id: 'preview-vi-could-not-assess',
  report_date: '2026-04-11',
  top_findings: [],
  severity_classes: ['SX'],
  nextstep_classes: ['AX'],
  support_coverage:
    'Không thể phân tích tài liệu nguồn thành các dòng có cấu trúc được hỗ trợ nên bản tóm tắt này còn hạn chế.',
  not_assessed: VI_CNA_ARTIFACT.not_assessed,
  provenance_link:
    'data:text/plain,Ban xem truoc provenance khong kha dung vi tai lieu khong the duoc cau truc day du.',
  support_banner: 'could_not_assess',
};

// ---------------------------------------------------------------------------
// Index — keyed by support state and language for easy preview routing
// ---------------------------------------------------------------------------

export type PreviewVariant =
  | 'fully_supported'
  | 'partially_supported'
  | 'could_not_assess';

export type PreviewLanguage = 'en' | 'vi';

export interface PreviewFixture {
  patientArtifact: PatientArtifact;
  clinicianArtifact: ClinicianArtifact;
  variant: PreviewVariant;
  language: PreviewLanguage;
  hasComparableHistory: boolean;
}

const FIXTURES: Record<
  `${PreviewLanguage}_${PreviewVariant}`,
  PreviewFixture
> = {
  en_fully_supported: {
    patientArtifact: EN_FULLY_ARTIFACT,
    clinicianArtifact: EN_FULLY_CLINICIAN,
    variant: 'fully_supported',
    language: 'en',
    hasComparableHistory: false,
  },
  en_partially_supported: {
    patientArtifact: EN_PARTIAL_ARTIFACT,
    clinicianArtifact: EN_PARTIAL_CLINICIAN,
    variant: 'partially_supported',
    language: 'en',
    hasComparableHistory: true,
  },
  en_could_not_assess: {
    patientArtifact: EN_CNA_ARTIFACT,
    clinicianArtifact: EN_CNA_CLINICIAN,
    variant: 'could_not_assess',
    language: 'en',
    hasComparableHistory: false,
  },
  vi_fully_supported: {
    patientArtifact: VI_FULLY_ARTIFACT,
    clinicianArtifact: VI_FULLY_CLINICIAN,
    variant: 'fully_supported',
    language: 'vi',
    hasComparableHistory: false,
  },
  vi_partially_supported: {
    patientArtifact: VI_PARTIAL_ARTIFACT,
    clinicianArtifact: VI_PARTIAL_CLINICIAN,
    variant: 'partially_supported',
    language: 'vi',
    hasComparableHistory: true,
  },
  vi_could_not_assess: {
    patientArtifact: VI_CNA_ARTIFACT,
    clinicianArtifact: VI_CNA_CLINICIAN,
    variant: 'could_not_assess',
    language: 'vi',
    hasComparableHistory: false,
  },
};

/**
 * Returns a deterministic preview fixture by variant and language.
 * Falls back to the English fully-supported fixture if the key is unknown.
 */
export function getPreviewFixture(
  variant: PreviewVariant = 'fully_supported',
  language: PreviewLanguage = 'en',
): PreviewFixture {
  const key = `${language}_${variant}` as const;
  return FIXTURES[key] ?? FIXTURES.en_fully_supported;
}

/** Lists all available preview fixtures. */
export function listPreviewFixtures(): PreviewFixture[] {
  return Object.values(FIXTURES);
}
