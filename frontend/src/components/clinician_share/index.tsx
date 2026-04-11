import { useCallback, useEffect, useMemo, useState } from 'react';
import { getClinicianArtifact } from '../../services/api';
import type {
  ClinicianArtifact,
  NextStepClass,
  PatientArtifact,
  SeverityClass,
  SupportBanner,
} from '../../types';
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

const SUPPORT_BANNER_META: Record<
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
    `Support coverage: ${artifact.support_coverage}`,
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

  const effectiveSupportBanner = artifact?.support_banner ?? supportBanner;
  const supportMeta = effectiveSupportBanner
    ? SUPPORT_BANNER_META[effectiveSupportBanner]
    : null;

  const displayFindings = useMemo(
    () => (artifact ? buildDisplayFindings(artifact, patientArtifact) : []),
    [artifact, patientArtifact],
  );

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
        <SurfaceCard style={{ marginTop: '0.8rem', padding: '0.9rem' }}>
          <p
            style={{
              margin: 0,
              fontSize: '0.9rem',
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
              marginTop: '0.8rem',
              padding: '0.9rem',
              backgroundColor: STITCH_COLORS.errorBg,
              color: STITCH_COLORS.errorText,
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
      rightSlot={supportMeta ? <PillBadge tone={supportMeta.tone}>{supportMeta.label}</PillBadge> : undefined}
    >
      <SurfaceCard style={{ marginTop: '0.65rem', padding: '0.85rem' }}>
        <div style={{ minWidth: 0 }}>
          <p
            style={{
              margin: '0 0 0.22rem',
              fontSize: '0.72rem',
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
              fontSize: '0.98rem',
              fontWeight: 700,
              color: STITCH_COLORS.textHeading,
            }}
          >
            {artifact.report_date}
          </p>
        </div>

        <p
          style={{
            margin: '0.5rem 0 0',
            fontSize: '0.88rem',
            lineHeight: 1.55,
            color: STITCH_COLORS.textSecondary,
          }}
        >
          {artifact.support_coverage}
        </p>

        <p
          style={{
            margin: '0.45rem 0 0',
            fontSize: '0.74rem',
            lineHeight: 1.45,
            color: STITCH_COLORS.textMuted,
            fontWeight: 600,
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
              gap: '0.35rem',
              marginTop: '0.55rem',
              color: STITCH_COLORS.blue,
              fontSize: '0.82rem',
              fontWeight: 700,
              textDecoration: 'none',
            }}
          >
            Source document
          </a>
        )}
      </SurfaceCard>

      <section style={{ marginTop: '0.85rem' }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '0.6rem',
            marginBottom: '0.5rem',
          }}
        >
          <h3
            style={{
              margin: 0,
              fontSize: '1rem',
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
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.55rem' }}>
            {displayFindings.map((finding) => {
              const severityMeta = SEVERITY_META[finding.severityClass];
              const nextStepMeta = finding.nextstepClass
                ? NEXTSTEP_META[finding.nextstepClass]
                : null;
              const isExpanded = expandedFinding === finding.id;

              return (
                <SurfaceCard key={finding.id} style={{ padding: '0.82rem' }}>
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
                        gap: '0.6rem',
                        alignItems: 'flex-start',
                      }}
                    >
                      <div style={{ minWidth: 0 }}>
                        <p
                          style={{
                            margin: 0,
                            fontSize: '0.72rem',
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
                            margin: '0.24rem 0 0',
                            fontSize: '1.05rem',
                            fontWeight: 800,
                            color: STITCH_COLORS.textHeading,
                            lineHeight: 1.25,
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
                          width: 30,
                          height: 30,
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

                    <div
                      style={{
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '0.35rem',
                        marginTop: '0.55rem',
                      }}
                    >
                      <div
                        style={{
                          padding: '0.55rem 0.65rem',
                          borderRadius: STITCH_RADIUS.md,
                          backgroundColor: severityMeta.bg,
                          color: severityMeta.color,
                          fontSize: '0.8rem',
                          fontWeight: 700,
                          lineHeight: 1.45,
                        }}
                      >
                        {finding.severityClass} · {severityMeta.label}
                      </div>
                      {nextStepMeta && (
                        <div
                          style={{
                            padding: '0.55rem 0.65rem',
                            borderRadius: STITCH_RADIUS.md,
                            backgroundColor: nextStepMeta.bg,
                            color: nextStepMeta.color,
                            fontSize: '0.8rem',
                            fontWeight: 700,
                            lineHeight: 1.45,
                          }}
                        >
                          {finding.nextstepClass} · {nextStepMeta.label}
                        </div>
                      )}
                    </div>

                    <p
                      style={{
                        margin: '0.55rem 0 0',
                        fontSize: '0.8rem',
                        lineHeight: 1.5,
                        color: STITCH_COLORS.textSecondary,
                      }}
                    >
                      {finding.threshold}
                    </p>
                  </button>

                  {isExpanded && (
                    <p
                      style={{
                        margin: '0.55rem 0 0',
                        fontSize: '0.82rem',
                        lineHeight: 1.55,
                        color: STITCH_COLORS.textSecondary,
                      }}
                    >
                      {finding.detail ?? finding.summary}
                    </p>
                  )}
                </SurfaceCard>
              );
            })}
          </div>
        ) : (
          <SurfaceCard style={{ padding: '0.84rem' }}>
            <p
              style={{
                margin: 0,
                fontSize: '0.86rem',
                lineHeight: 1.55,
                color: STITCH_COLORS.textSecondary,
              }}
            >
              No top findings were supplied.
            </p>
          </SurfaceCard>
        )}
      </section>

      <section style={{ marginTop: '0.85rem' }}>
        <h3
          style={{
            margin: '0 0 0.45rem',
            fontSize: '1rem',
            fontWeight: 700,
            color: STITCH_COLORS.textHeading,
          }}
        >
          Items not assessed
        </h3>
        <div
          style={{
            ...pageCardStyle({
              padding: '0.8rem',
              border: '2px dashed rgba(118, 118, 126, 0.22)',
              boxShadow: 'none',
            }),
          }}
        >
          {artifact.not_assessed.length > 0 ? (
            <ul
              style={{
                margin: 0,
                paddingLeft: '1.05rem',
                display: 'flex',
                flexDirection: 'column',
                gap: '0.42rem',
              }}
            >
              {artifact.not_assessed.map((item, index) => (
                <li
                  key={`${item.raw_label}-${index}`}
                  style={{
                    fontSize: '0.84rem',
                    lineHeight: 1.5,
                    color: STITCH_COLORS.textSecondary,
                  }}
                >
                  <strong style={{ color: STITCH_COLORS.textHeading }}>
                    {item.raw_label}
                  </strong>{' '}
                  — {item.reason}
                </li>
              ))}
            </ul>
          ) : (
            <p
              style={{
                margin: 0,
                fontSize: '0.84rem',
                lineHeight: 1.5,
                color: STITCH_COLORS.textSecondary,
              }}
            >
              No items were left unassessed.
            </p>
          )}
        </div>
      </section>

      <section style={{ marginTop: '0.85rem' }}>
        <div
          style={{
            backgroundColor: STITCH_COLORS.navy,
            borderRadius: STITCH_RADIUS.lg,
            padding: '0.75rem',
            color: STITCH_COLORS.surfaceWhite,
          }}
        >
          <p
            style={{
              margin: '0 0 0.5rem',
              fontSize: '0.68rem',
              fontWeight: 800,
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              color: 'rgba(255,255,255,0.64)',
              textAlign: 'center',
            }}
          >
            Share or save
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
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
            <SecondaryButton onClick={handleExportSummary}>
              Export summary
            </SecondaryButton>
          </div>
        </div>
      </section>

      {onNavigateBack && (
        <SecondaryButton onClick={onNavigateBack} style={{ marginTop: '0.85rem' }}>
          Back to patient summary
        </SecondaryButton>
      )}
    </PageChrome>
  );
}
