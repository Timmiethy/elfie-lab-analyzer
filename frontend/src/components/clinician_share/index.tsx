import { useCallback, useEffect, useMemo, useState } from 'react';
import { getClinicianArtifact, getClinicianPdf } from '../../services/api';
import type {
  ClinicianArtifact,
  NextStepClass,
  PatientArtifact,
  SeverityClass,
  SupportBanner,
  TrustStatus,
} from '../../types';
import { unsupportedReasonDisplay } from '../../types';
import {
  PageChrome,
  PillBadge,
  PrimaryButton,
  SecondaryButton,
  SurfaceCard,
} from '../common';
import { STITCH_COLORS, STITCH_RADIUS, pageCardStyle } from '../common/system';

const SEVERITY_META: Record<
  SeverityClass,
  { label: string; color: string; bg: string }
> = {
  S0: { label: 'No actionable finding', color: '#15803D', bg: '#DCFCE7' },
  S1: { label: 'Review routinely', color: '#15803D', bg: '#DCFCE7' },
  S2: { label: 'Discuss at next planned visit', color: '#9A3412', bg: '#FFF4E5' },
  S3: { label: 'Contact clinician soon', color: '#B45309', bg: '#FFF0D8' },
  S4: { label: 'Urgent follow-up recommended', color: '#991B1B', bg: '#FEE2E2' },
  SX: { label: 'Cannot assess severity', color: '#4B5563', bg: '#F3F4F6' },
};

const NEXTSTEP_META: Record<
  NextStepClass,
  { label: string; color: string; bg: string }
> = {
  A0: { label: 'No specific action', color: '#15803D', bg: '#DCFCE7' },
  A1: { label: 'Review at next planned visit', color: '#15803D', bg: '#DCFCE7' },
  A2: { label: 'Schedule routine follow-up', color: '#9A3412', bg: '#FFF4E5' },
  A3: { label: 'Contact clinician soon', color: '#B45309', bg: '#FFF0D8' },
  A4: { label: 'Seek urgent review', color: '#991B1B', bg: '#FEE2E2' },
  AX: { label: 'Cannot suggest a next step safely', color: '#4B5563', bg: '#F3F4F6' },
};

const SUPPORT_COVERAGE_META: Record<
  SupportBanner,
  {
    label: string;
    tone: 'trusted' | 'beta' | 'neutral';
    color: string;
  }
> = {
  fully_supported: {
    label: 'Fully supported',
    tone: 'trusted',
    color: '#1F5C2C',
  },
  partially_supported: {
    label: 'Partially supported',
    tone: 'beta',
    color: '#9A3412',
  },
  could_not_assess: {
    label: 'Could not assess fully',
    tone: 'neutral',
    color: '#4B5563',
  },
};

const TRUST_STATUS_META: Record<
  TrustStatus,
  { label: string; tone: 'trusted' | 'beta'; color: string }
> = {
  trusted: {
    label: 'Trusted PDF lane',
    tone: 'trusted',
    color: STITCH_COLORS.trustedText,
  },
  non_trusted_beta: {
    label: 'Non-trusted beta lane',
    tone: 'beta',
    color: STITCH_COLORS.betaText,
  },
};

type DisplayFinding = {
  id: string;
  analyteLabel: string;
  measurement: string | null;
  summary: string;
  threshold: string;
  severityClass: SeverityClass;
  nextstepClass: NextStepClass | null;
  detail: string | null;
};

interface Props {
  jobId?: string;
  supportBanner?: SupportBanner;
  patientArtifact?: PatientArtifact;
  previewArtifact?: ClinicianArtifact;
  onNavigateBack?: () => void;
}

function formatRuleId(ruleId: string): string {
  return ruleId
    .replace(/[-_]/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatSupportCoverage(supportCoverage: SupportBanner): string {
  return SUPPORT_COVERAGE_META[supportCoverage].label;
}

function formatTrustStatus(trustStatus: TrustStatus): string {
  return TRUST_STATUS_META[trustStatus].label;
}

function canShare(): boolean {
  return typeof navigator !== 'undefined' && typeof navigator.share === 'function';
}

function buildDisplayFindings(
  artifact: ClinicianArtifact,
  patientArtifact?: PatientArtifact,
): DisplayFinding[] {
  if (patientArtifact?.flagged_cards.length) {
    return patientArtifact.flagged_cards.map((card, index) => {
      const finding = patientArtifact.findings[index] ?? artifact.top_findings?.[index];
      return {
        id: finding?.finding_id ?? `${card.analyte_display}-${index}`,
        analyteLabel: card.analyte_display,
        measurement: `${card.value} ${card.unit}`,
        summary: card.finding_sentence,
        threshold: card.threshold_provenance,
        severityClass: finding?.severity_class ?? card.severity_chip,
        nextstepClass: finding?.nextstep_class ?? null,
        detail: finding?.suppression_reason ?? null,
      };
    });
  }

  return (artifact.top_findings ?? []).map((finding) => ({
    id: finding.finding_id,
    analyteLabel: formatRuleId(finding.rule_id),
    measurement: null,
    summary: finding.threshold_source,
    threshold: finding.threshold_source,
    severityClass: finding.severity_class,
    nextstepClass: finding.nextstep_class,
    detail: finding.suppression_reason,
  }));
}

function buildSummaryText(
  artifact: ClinicianArtifact,
  findings: DisplayFinding[],
): string {
  const lines: string[] = [
    'Clinician Summary',
    `Report date: ${artifact.report_date}`,
    `Support coverage: ${formatSupportCoverage(artifact.support_coverage)}`,
    `Trust status: ${formatTrustStatus(artifact.trust_status)}`,
    '',
  ];

  if (findings.length > 0) {
    lines.push('Top findings:');
    findings.forEach((finding, index) => {
      const severityText = SEVERITY_META[finding.severityClass].label;
      const nextStepText = finding.nextstepClass
        ? NEXTSTEP_META[finding.nextstepClass].label
        : 'No next-step class available';
      const measurement = finding.measurement
        ? `${finding.analyteLabel}: ${finding.measurement}`
        : finding.analyteLabel;
      lines.push(
        `${index + 1}. ${measurement} — ${severityText}. ${nextStepText}. ${finding.threshold}`,
      );
    });
  } else {
    lines.push('Top findings: none provided.');
  }

  if (artifact.provenance_link) {
    lines.push('', `Provenance: ${artifact.provenance_link}`);
  }

  return lines.join('\n');
}

export default function ClinicianShare({
  jobId,
  supportBanner,
  patientArtifact,
  previewArtifact,
  onNavigateBack,
}: Props) {
  const [artifact, setArtifact] = useState<ClinicianArtifact | null>(
    previewArtifact ?? null,
  );
  const [loading, setLoading] = useState(!previewArtifact);
  const [error, setError] = useState<string | null>(null);
  const [expandedFinding, setExpandedFinding] = useState<string | null>(null);
  const [copyStatus, setCopyStatus] = useState<'idle' | 'copied' | 'failed'>(
    'idle',
  );
  const [pdfStatus, setPdfStatus] = useState<
    'idle' | 'downloading' | 'downloaded' | 'failed'
  >('idle');
  const [showAllNotAssessed, setShowAllNotAssessed] = useState(false);

  useEffect(() => {
    if (previewArtifact) {
      setArtifact(previewArtifact);
      setLoading(false);
      setError(null);
      return;
    }

    if (!jobId) {
      setArtifact(null);
      setLoading(false);
      setError('No clinician-share artifact is available for this view.');
      return;
    }

    let cancelled = false;

    const fetchArtifact = async () => {
      try {
        setLoading(true);
        const response = await getClinicianArtifact(jobId);
        if (!response.ok) {
          throw new Error(
            `Failed to load clinician artifact (status ${response.status}).`,
          );
        }
        const data: ClinicianArtifact = await response.json();
        if (!cancelled) {
          setArtifact(data);
          setError(null);
        }
      } catch (artifactError) {
        if (!cancelled) {
          setError(
            artifactError instanceof Error
              ? artifactError.message
              : 'Failed to load clinician artifact.',
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    void fetchArtifact();

    return () => {
      cancelled = true;
    };
  }, [jobId, previewArtifact]);

  const effectiveSupportCoverage =
    artifact?.support_coverage ?? supportBanner ?? artifact?.support_banner;
  const supportMeta = effectiveSupportCoverage
    ? SUPPORT_COVERAGE_META[effectiveSupportCoverage]
    : null;
  const trustMeta = artifact ? TRUST_STATUS_META[artifact.trust_status] : null;

  const displayFindings = useMemo(
    () => (artifact ? buildDisplayFindings(artifact, patientArtifact) : []),
    [artifact, patientArtifact],
  );
  const visibleNotAssessed = artifact
    ? showAllNotAssessed
      ? artifact.not_assessed
      : artifact.not_assessed.slice(0, 2)
    : [];

  const handleCopySummary = useCallback(async () => {
    if (!artifact || typeof navigator === 'undefined' || !navigator.clipboard) {
      setCopyStatus('failed');
      return;
    }

    try {
      await navigator.clipboard.writeText(buildSummaryText(artifact, displayFindings));
      setCopyStatus('copied');
      window.setTimeout(() => setCopyStatus('idle'), 2200);
    } catch {
      setCopyStatus('failed');
      window.setTimeout(() => setCopyStatus('idle'), 2200);
    }
  }, [artifact, displayFindings]);

  const handleShareSummary = useCallback(async () => {
    if (!artifact || !canShare()) {
      return;
    }

    try {
      await navigator.share({
        title: 'Clinician Summary',
        text: buildSummaryText(artifact, displayFindings),
      });
    } catch {
      // Share sheet cancellation is a valid no-op.
    }
  }, [artifact, displayFindings]);

  const handleDownloadPdf = useCallback(async () => {
    if (!jobId || !artifact) {
      return;
    }

    setPdfStatus('downloading');

    try {
      const response = await getClinicianPdf(jobId);
      if (!response.ok) {
        throw new Error(
          `Failed to download clinician PDF (status ${response.status}).`,
        );
      }

      const blob = await response.blob();
      const pdfUrl = window.URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = pdfUrl;
      anchor.download = `clinician-summary-${jobId}.pdf`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => window.URL.revokeObjectURL(pdfUrl), 1000);
      setPdfStatus('downloaded');
      window.setTimeout(() => setPdfStatus('idle'), 2200);
    } catch {
      setPdfStatus('failed');
      window.setTimeout(() => setPdfStatus('idle'), 2200);
    }
  }, [artifact, jobId]);

  const handleExportSummary = useCallback(() => {
    window.print();
  }, []);

  if (loading) {
    return (
      <PageChrome
        title="Clinician Summary"
        subtitle="Loading structured summary."
        rightSlot={<PillBadge tone="neutral">Secondary</PillBadge>}
      >
        <SurfaceCard style={{ marginTop: '1rem', padding: '1.15rem' }}>
          <p
            style={{
              margin: 0,
              fontSize: '0.94rem',
              color: STITCH_COLORS.textSecondary,
            }}
          >
            Loading clinician summary...
          </p>
        </SurfaceCard>
      </PageChrome>
    );
  }

  if (error || !artifact) {
    return (
      <PageChrome
        title="Clinician Summary"
        subtitle="Structured summary unavailable."
        rightSlot={<PillBadge tone="neutral">Secondary</PillBadge>}
      >
        <div
          role="alert"
          style={{
            ...pageCardStyle({
              marginTop: '1rem',
              padding: '1.15rem',
              backgroundColor: STITCH_COLORS.errorBg,
              color: STITCH_COLORS.errorText,
              fontSize: '0.94rem',
              lineHeight: 1.55,
            }),
          }}
        >
          {error ?? 'No clinician-share artifact available for this view.'}
        </div>
      </PageChrome>
    );
  }

  return (
    <PageChrome
      compact
      title="Clinician Summary"
      subtitle="Scannable structured handoff."
      rightSlot={
        supportMeta ? (
          <PillBadge tone={supportMeta.tone}>{supportMeta.label}</PillBadge>
        ) : undefined
      }
      contentMaxWidth={1120}
    >
      <div className="stitch-grid-two stitch-enter" style={{ marginTop: '0.75rem' }}>
        <div className="stitch-flow">
          <section>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: '0.7rem',
                marginBottom: '0.6rem',
              }}
            >
              <h3
                style={{
                  margin: 0,
                  fontSize: '1.08rem',
                  fontWeight: 700,
                  color: STITCH_COLORS.textHeading,
                }}
              >
                Top findings
              </h3>
              <PillBadge tone={displayFindings.length > 0 ? 'beta' : 'neutral'}>
                {displayFindings.length > 0
                  ? `${displayFindings.length} item${displayFindings.length > 1 ? 's' : ''}`
                  : 'None'}
              </PillBadge>
            </div>

            {displayFindings.length > 0 ? (
              <div className="stitch-flow" style={{ gap: '0.65rem' }}>
                {displayFindings.map((finding) => {
                  const severityMeta = SEVERITY_META[finding.severityClass];
                  const nextStepMeta = finding.nextstepClass
                    ? NEXTSTEP_META[finding.nextstepClass]
                    : null;
                  const isExpanded = expandedFinding === finding.id;

                  return (
                    <SurfaceCard key={finding.id} style={{ padding: '1.1rem' }}>
                      <button
                        type="button"
                        onClick={() =>
                          setExpandedFinding(isExpanded ? null : finding.id)
                        }
                        style={{
                          width: '100%',
                          border: 'none',
                          background: 'none',
                          textAlign: 'left',
                          padding: 0,
                          cursor: 'pointer',
                        }}
                        aria-expanded={isExpanded}
                      >
                        <div
                          style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            gap: '0.8rem',
                            alignItems: 'flex-start',
                          }}
                        >
                          <div style={{ minWidth: 0 }}>
                            <p
                              style={{
                                margin: 0,
                                fontSize: '0.76rem',
                                fontWeight: 800,
                                textTransform: 'uppercase',
                                letterSpacing: '0.08em',
                                color: STITCH_COLORS.textMuted,
                                lineHeight: 1.3,
                              }}
                            >
                              {finding.analyteLabel}
                            </p>
                            <p
                              style={{
                                margin: '0.28rem 0 0',
                                fontSize: '1.08rem',
                                fontWeight: 800,
                                color: STITCH_COLORS.textHeading,
                                lineHeight: 1.3,
                              }}
                            >
                              {finding.measurement ?? severityMeta.label}
                            </p>
                          </div>
                          <span
                            aria-hidden="true"
                            style={{
                              color: STITCH_COLORS.textMuted,
                              fontSize: '0.88rem',
                              width: 40,
                              height: 40,
                              borderRadius: '50%',
                              backgroundColor: STITCH_COLORS.surfaceLow,
                              display: 'inline-flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                              flexShrink: 0,
                            }}
                          >
                            {isExpanded ? '▾' : '▸'}
                          </span>
                        </div>

                        <div className="stitch-segment-row" style={{ marginTop: '0.7rem' }}>
                          <span
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              padding: '0.42rem 0.68rem',
                              borderRadius: STITCH_RADIUS.pill,
                              backgroundColor: severityMeta.bg,
                              color: severityMeta.color,
                              fontSize: '0.8rem',
                              fontWeight: 700,
                              lineHeight: 1.4,
                            }}
                          >
                            {finding.severityClass} · {severityMeta.label}
                          </span>
                          {nextStepMeta && (
                            <span
                              style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                padding: '0.42rem 0.68rem',
                                borderRadius: STITCH_RADIUS.pill,
                                backgroundColor: nextStepMeta.bg,
                                color: nextStepMeta.color,
                                fontSize: '0.8rem',
                                fontWeight: 700,
                                lineHeight: 1.4,
                              }}
                            >
                              {finding.nextstepClass} · {nextStepMeta.label}
                            </span>
                          )}
                        </div>
                      </button>

                      {isExpanded && (
                        <div className="stitch-compact-list" style={{ marginTop: '0.8rem' }}>
                          <p
                            style={{
                              margin: 0,
                              fontSize: '0.88rem',
                              lineHeight: 1.6,
                              color: STITCH_COLORS.textSecondary,
                            }}
                          >
                            {finding.threshold}
                          </p>
                          <p
                            style={{
                              margin: 0,
                              fontSize: '0.88rem',
                              lineHeight: 1.6,
                              color: STITCH_COLORS.textSecondary,
                            }}
                          >
                            {finding.detail ?? finding.summary}
                          </p>
                        </div>
                      )}
                    </SurfaceCard>
                  );
                })}
              </div>
            ) : (
              <SurfaceCard style={{ padding: '1.05rem' }}>
                <p
                  style={{
                    margin: 0,
                    fontSize: '0.92rem',
                    lineHeight: 1.6,
                    color: STITCH_COLORS.textSecondary,
                  }}
                >
                  No top findings were supplied.
                </p>
              </SurfaceCard>
            )}
          </section>

          <section>
            <SurfaceCard
              style={{
                padding: '1.05rem',
                border: '2px dashed rgba(118, 118, 126, 0.22)',
                boxShadow: 'none',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: '0.7rem',
                  marginBottom: '0.65rem',
                }}
              >
                <div style={{ minWidth: 0 }}>
                  <h3
                    style={{
                      margin: 0,
                      fontSize: '1.08rem',
                      fontWeight: 700,
                      color: STITCH_COLORS.textHeading,
                    }}
                  >
                    Items not assessed
                  </h3>
                  <p
                    style={{
                      margin: '0.22rem 0 0',
                      fontSize: '0.88rem',
                      lineHeight: 1.55,
                      color: STITCH_COLORS.textSecondary,
                    }}
                  >
                    Unsupported items remain visible for honest handoff.
                  </p>
                </div>
                {artifact.not_assessed.length > 0 && (
                  <PillBadge tone="neutral">
                    {artifact.not_assessed.length} item
                    {artifact.not_assessed.length > 1 ? 's' : ''}
                  </PillBadge>
                )}
              </div>

              {artifact.not_assessed.length > 0 ? (
                <ul
                  style={{
                    margin: 0,
                    paddingLeft: '1.15rem',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '0.5rem',
                  }}
                >
                  {visibleNotAssessed.map((item, index) => (
                    <li
                      key={`${item.raw_label}-${index}`}
                      style={{
                        fontSize: '0.9rem',
                        lineHeight: 1.6,
                        color: STITCH_COLORS.textSecondary,
                      }}
                    >
                      <strong style={{ color: STITCH_COLORS.textHeading }}>
                        {item.raw_label}
                      </strong>{' '}
                      — {unsupportedReasonDisplay(item)}
                    </li>
                  ))}
                </ul>
              ) : (
                <p
                  style={{
                    margin: 0,
                    fontSize: '0.9rem',
                    lineHeight: 1.6,
                    color: STITCH_COLORS.textSecondary,
                  }}
                >
                  No items were left unassessed.
                </p>
              )}

              {artifact.not_assessed.length > 2 && (
                <button
                  type="button"
                  onClick={() => setShowAllNotAssessed((prev) => !prev)}
                  style={{
                    marginTop: '0.85rem',
                    border: 'none',
                    background: 'none',
                    padding: 0,
                    color: STITCH_COLORS.blue,
                    fontSize: '0.88rem',
                    fontWeight: 700,
                    cursor: 'pointer',
                    minHeight: 44,
                  }}
                >
                  {showAllNotAssessed
                    ? 'Show fewer items'
                    : `Show all ${artifact.not_assessed.length} items`}
                </button>
              )}
            </SurfaceCard>
          </section>
        </div>

        <aside className="stitch-rail">
          <SurfaceCard
            style={{
              padding: '1.25rem 1.15rem',
              background:
                'linear-gradient(180deg, rgba(255,255,255,0.99) 0%, rgba(255,246,248,0.94) 100%)',
            }}
          >
            <div className="stitch-compact-list">
              <div>
                <p
                  style={{
                    margin: '0 0 0.28rem',
                    fontSize: '0.76rem',
                    fontWeight: 800,
                    textTransform: 'uppercase',
                    letterSpacing: '0.08em',
                    color: STITCH_COLORS.textMuted,
                  }}
                >
                  Report date
                </p>
                <p
                  style={{
                    margin: 0,
                    fontSize: '1.08rem',
                    fontWeight: 700,
                    color: STITCH_COLORS.textHeading,
                  }}
                >
                  {artifact.report_date}
                </p>
              </div>

              <div className="stitch-segment-row">
                {supportMeta && (
                  <PillBadge tone={supportMeta.tone}>{supportMeta.label}</PillBadge>
                )}
                {trustMeta && (
                  <span
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      padding: '5px 12px',
                      borderRadius: STITCH_RADIUS.pill,
                      backgroundColor:
                        trustMeta.tone === 'trusted'
                          ? STITCH_COLORS.trustedBg
                          : STITCH_COLORS.betaBg,
                      color: trustMeta.color,
                      fontSize: '0.74rem',
                      fontWeight: 700,
                    }}
                  >
                    {trustMeta.label}
                  </span>
                )}
              </div>

              <p
                style={{
                  margin: 0,
                  fontSize: '0.9rem',
                  lineHeight: 1.6,
                  color: STITCH_COLORS.textSecondary,
                }}
              >
                Structured findings only. No diagnosis or treatment advice.
              </p>

              {artifact.provenance_link && (
                <a
                  href={artifact.provenance_link}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '0.4rem',
                    color: STITCH_COLORS.blue,
                    fontSize: '0.88rem',
                    fontWeight: 700,
                    textDecoration: 'none',
                  }}
                >
                  Source document
                </a>
              )}

              <div className="stitch-divider" />

              <div className="stitch-flow" style={{ gap: '0.6rem' }}>
                {canShare() ? (
                  <PrimaryButton onClick={() => void handleShareSummary()}>
                    Share summary
                  </PrimaryButton>
                ) : (
                  <PrimaryButton onClick={() => void handleCopySummary()}>
                    {copyStatus === 'copied'
                      ? 'Summary copied'
                      : copyStatus === 'failed'
                        ? 'Copy failed'
                        : 'Copy summary'}
                  </PrimaryButton>
                )}
                {jobId && (
                  <SecondaryButton onClick={() => void handleDownloadPdf()}>
                    {pdfStatus === 'downloading'
                      ? 'Downloading PDF…'
                      : pdfStatus === 'downloaded'
                        ? 'PDF downloaded'
                        : pdfStatus === 'failed'
                          ? 'Download failed'
                          : 'Download clinician PDF'}
                  </SecondaryButton>
                )}
                <SecondaryButton onClick={handleExportSummary}>
                  Export summary
                </SecondaryButton>
                {onNavigateBack && (
                  <SecondaryButton onClick={onNavigateBack}>
                    Back to patient summary
                  </SecondaryButton>
                )}
              </div>

              {copyStatus === 'failed' && !canShare() && (
                <p
                  style={{
                    margin: 0,
                    fontSize: '0.82rem',
                    lineHeight: 1.5,
                    color: STITCH_COLORS.errorText,
                  }}
                >
                  Clipboard access is not available in this browser.
                </p>
              )}
            </div>
          </SurfaceCard>
        </aside>
      </div>
    </PageChrome>
  );
}
