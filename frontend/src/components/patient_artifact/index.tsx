import { useState } from 'react';
import type { PatientArtifact } from '../../types';
import HistoryCard from '../history_card';
import {
  PageChrome,
  PillBadge,
  PrimaryButton,
  SecondaryButton,
  SeverityChip,
  SurfaceCard,
} from '../common';
import { STITCH_COLORS, STITCH_RADIUS } from '../common/system';

const SUPPORT_BANNER_META: Record<
  PatientArtifact['support_banner'],
  {
    label: string;
    body: string;
    tone: 'trusted' | 'beta' | 'neutral';
    bg: string;
    color: string;
  }
> = {
  fully_supported: {
    label: 'Fully supported',
    body: 'Supported rows reviewed.',
    tone: 'trusted',
    bg: '#EEF8EF',
    color: '#1F5C2C',
  },
  partially_supported: {
    label: 'Partially supported',
    body: 'Unsupported rows kept visible.',
    tone: 'beta',
    bg: '#FFF4E5',
    color: '#9A3412',
  },
  could_not_assess: {
    label: 'Could not assess fully',
    body: 'File not fully structured.',
    tone: 'neutral',
    bg: '#F3F4F6',
    color: '#4B5563',
  },
};

const TRUST_STATUS_META: Record<
  PatientArtifact['trust_status'],
  { label: string; tone: 'trusted' | 'beta'; body: string }
> = {
  trusted: { label: 'Trusted PDF lane', tone: 'trusted', body: 'Trusted PDF path.' },
  non_trusted_beta: { label: 'Non-trusted beta lane', tone: 'beta', body: 'Image beta path.' },
};

const SEVERITY_META: Record<
  PatientArtifact['overall_severity'],
  { label: string; bg: string; color: string; icon: string }
> = {
  S0: { label: 'No actionable finding', bg: '#EEF8EF', color: '#1F5C2C', icon: '\u2713' },
  S1: { label: 'Review routinely', bg: '#EEF8EF', color: '#1F5C2C', icon: '\u2139' },
  S2: { label: 'Discuss at next visit', bg: '#FFF4E5', color: '#9A3412', icon: '\u26A0' },
  S3: { label: 'Contact clinician soon', bg: '#FFF0D8', color: '#B45309', icon: '\u26A1' },
  S4: { label: 'Urgent follow-up', bg: '#FEE2E2', color: '#991B1B', icon: '\u{1F6A8}' },
  SX: { label: 'Cannot assess severity', bg: '#F3F4F6', color: '#4B5563', icon: '\u2753' },
};

function splitReviewedItem(item: string): { label: string; value: string } {
  const [label, ...rest] = item.split('\u2014');
  return {
    label: label.trim(),
    value: rest.join('\u2014').trim() || 'Reviewed',
  };
}

interface Props {
  artifact: PatientArtifact;
  onNavigateBack?: () => void;
  onViewClinicianShare?: () => void;
  onViewGuidedAsk?: () => void;
}

type ResultsTab = 'flagged' | 'reviewed' | 'not_assessed';

export default function PatientArtifact({
  artifact,
  onNavigateBack,
  onViewClinicianShare,
  onViewGuidedAsk,
}: Props) {
  const [expandedCard, setExpandedCard] = useState<number | null>(null);
  const supportMeta = SUPPORT_BANNER_META[artifact.support_banner];
  const trustMeta = TRUST_STATUS_META[artifact.trust_status];
  const severityMeta = SEVERITY_META[artifact.overall_severity];
  const hasFlagged = artifact.flagged_cards.length > 0;
  const hasReviewed = artifact.reviewed_not_flagged.length > 0;
  const hasNotAssessed = artifact.not_assessed.length > 0;
  const hasNextStep =
    artifact.nextstep_title !== '' ||
    artifact.nextstep_timing !== null ||
    artifact.nextstep_reason !== null;

  const initialTab: ResultsTab = hasFlagged
    ? 'flagged'
    : hasReviewed
      ? 'reviewed'
      : 'not_assessed';
  const [resultsTab, setResultsTab] = useState<ResultsTab>(initialTab);

  const handleShareSummary = async () => {
    const shareText = [
      'Elfie lab summary',
      hasFlagged
        ? artifact.flagged_cards
            .map(
              (card) =>
                `${card.analyte_display}: ${card.value} ${card.unit} — ${card.finding_sentence}`,
            )
            .join('\n')
        : 'No supported rows were flagged.',
      artifact.nextstep_title ? `Next step: ${artifact.nextstep_title}` : '',
    ]
      .filter(Boolean)
      .join('\n\n');

    if (navigator.share) {
      await navigator.share({ title: 'Elfie lab summary', text: shareText });
      return;
    }
    await navigator.clipboard.writeText(shareText);
    window.alert('Summary copied to clipboard.');
  };

  const handleExportPdf = () => window.print();

  const tabs: { id: ResultsTab; label: string; count: number }[] = [
    { id: 'flagged', label: 'Flagged', count: artifact.flagged_cards.length },
    { id: 'reviewed', label: 'Normal', count: artifact.reviewed_not_flagged.length },
    { id: 'not_assessed', label: 'Not assessed', count: artifact.not_assessed.length },
  ];

  const tabButtonStyle = (active: boolean) => ({
    flex: 1,
    minHeight: 44,
    padding: '0.55rem 0.8rem',
    border: 'none',
    borderRadius: STITCH_RADIUS.md,
    background: active ? STITCH_COLORS.surfaceWhite : 'transparent',
    boxShadow: active ? '0 2px 8px rgba(18,26,51,0.08)' : 'none',
    color: active ? STITCH_COLORS.textHeading : STITCH_COLORS.textSecondary,
    fontSize: '0.88rem',
    fontWeight: 700,
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
  });

  return (
    <PageChrome
      compact
      title="Your Lab Results"
      subtitle="Supported rows first."
      rightSlot={<PillBadge tone={supportMeta.tone}>{supportMeta.label}</PillBadge>}
      contentMaxWidth={1120}
    >
      <div className="stitch-grid-two stitch-enter" style={{ marginTop: '0.75rem' }}>
        <div className="stitch-flow" style={{ gap: '0.9rem' }}>
          {/* ==================== SECTION 1: OVERVIEW ==================== */}
          <SurfaceCard
            style={{
              padding: '1.25rem',
              background: `linear-gradient(180deg, ${severityMeta.bg} 0%, rgba(255,255,255,0.94) 100%)`,
            }}
          >
            <div
              style={{
                display: 'flex',
                flexWrap: 'wrap',
                gap: 8,
                marginBottom: '0.9rem',
              }}
            >
              <PillBadge tone={supportMeta.tone}>{supportMeta.label}</PillBadge>
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
                  color:
                    trustMeta.tone === 'trusted'
                      ? STITCH_COLORS.trustedText
                      : STITCH_COLORS.betaText,
                  fontSize: '0.74rem',
                  fontWeight: 700,
                }}
              >
                {trustMeta.label}
              </span>
            </div>

            <div style={{ display: 'flex', gap: '1rem', alignItems: 'flex-start' }}>
              <div
                aria-hidden="true"
                style={{
                  width: 52,
                  height: 52,
                  borderRadius: STITCH_RADIUS.md,
                  backgroundColor: 'rgba(255,255,255,0.72)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                  color: severityMeta.color,
                  fontSize: '1.1rem',
                }}
              >
                {severityMeta.icon}
              </div>
              <div style={{ minWidth: 0, flex: 1 }}>
                <p
                  style={{
                    margin: 0,
                    fontSize: '0.74rem',
                    fontWeight: 800,
                    letterSpacing: '0.08em',
                    textTransform: 'uppercase',
                    color: severityMeta.color,
                  }}
                >
                  Overall severity
                </p>
                <p
                  style={{
                    margin: '0.15rem 0 0',
                    fontSize: '1.25rem',
                    fontWeight: 800,
                    lineHeight: 1.3,
                    color: STITCH_COLORS.textHeading,
                  }}
                >
                  {severityMeta.label}
                </p>
                {hasNextStep && (
                  <p
                    style={{
                      margin: '0.4rem 0 0',
                      fontSize: '0.92rem',
                      lineHeight: 1.5,
                      color: STITCH_COLORS.textSecondary,
                    }}
                  >
                    <strong style={{ color: STITCH_COLORS.textHeading }}>
                      Next step:
                    </strong>{' '}
                    {artifact.nextstep_title || 'Available'}
                    {artifact.nextstep_timing ? ` · ${artifact.nextstep_timing}` : ''}
                    {artifact.nextstep_reason ? ` — ${artifact.nextstep_reason}` : ''}
                  </p>
                )}
              </div>
            </div>

            <div
              style={{
                display: 'flex',
                flexWrap: 'wrap',
                gap: 14,
                marginTop: '1rem',
                paddingTop: '0.9rem',
                borderTop: `1px solid ${STITCH_COLORS.borderGhost}`,
                fontSize: '0.86rem',
                color: STITCH_COLORS.textSecondary,
              }}
            >
              <span>
                <strong style={{ color: STITCH_COLORS.textHeading }}>
                  {artifact.flagged_cards.length}
                </strong>{' '}
                flagged
              </span>
              <span style={{ color: STITCH_COLORS.textMuted }}>·</span>
              <span>
                <strong style={{ color: STITCH_COLORS.textHeading }}>
                  {artifact.reviewed_not_flagged.length}
                </strong>{' '}
                normal
              </span>
              <span style={{ color: STITCH_COLORS.textMuted }}>·</span>
              <span>
                <strong style={{ color: STITCH_COLORS.textHeading }}>
                  {artifact.not_assessed.length}
                </strong>{' '}
                not assessed
              </span>
              <span style={{ color: STITCH_COLORS.textMuted, marginLeft: 'auto' }}>
                Informational only
              </span>
            </div>
          </SurfaceCard>

          {/* ==================== SECTION 2: RESULTS ==================== */}
          <SurfaceCard style={{ padding: '1rem' }}>
            <div
              role="tablist"
              aria-label="Results"
              style={{
                display: 'flex',
                gap: 4,
                padding: 4,
                borderRadius: STITCH_RADIUS.lg,
                backgroundColor: STITCH_COLORS.surfaceLow,
                marginBottom: '0.9rem',
              }}
            >
              {tabs.map((tab) => (
                <button
                  key={tab.id}
                  role="tab"
                  aria-selected={resultsTab === tab.id}
                  type="button"
                  onClick={() => setResultsTab(tab.id)}
                  style={tabButtonStyle(resultsTab === tab.id)}
                >
                  {tab.label}
                  <span
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      minWidth: 20,
                      height: 20,
                      padding: '0 6px',
                      borderRadius: 999,
                      fontSize: '0.72rem',
                      fontWeight: 800,
                      backgroundColor:
                        resultsTab === tab.id
                          ? STITCH_COLORS.pink
                          : STITCH_COLORS.surfaceHigh,
                      color:
                        resultsTab === tab.id
                          ? STITCH_COLORS.surfaceWhite
                          : STITCH_COLORS.textSecondary,
                    }}
                  >
                    {tab.count}
                  </span>
                </button>
              ))}
            </div>

            {/* Flagged */}
            {resultsTab === 'flagged' &&
              (hasFlagged ? (
                <div className="stitch-flow" style={{ gap: '0.55rem' }}>
                  {artifact.flagged_cards.map((card, index) => {
                    const isExpanded = expandedCard === index;
                    return (
                      <div
                        key={`${card.analyte_display}-${index}`}
                        style={{
                          padding: '0.85rem 0.95rem',
                          borderRadius: STITCH_RADIUS.md,
                          backgroundColor: STITCH_COLORS.surfaceLow,
                        }}
                      >
                        <button
                          type="button"
                          onClick={() => setExpandedCard(isExpanded ? null : index)}
                          aria-expanded={isExpanded}
                          style={{
                            width: '100%',
                            border: 'none',
                            background: 'none',
                            padding: 0,
                            textAlign: 'left',
                            cursor: 'pointer',
                            display: 'flex',
                            justifyContent: 'space-between',
                            gap: '0.75rem',
                            alignItems: 'flex-start',
                          }}
                        >
                          <div style={{ minWidth: 0, flex: 1 }}>
                            <div
                              style={{
                                display: 'flex',
                                alignItems: 'baseline',
                                gap: 8,
                                flexWrap: 'wrap',
                              }}
                            >
                              <span
                                style={{
                                  fontSize: '0.95rem',
                                  fontWeight: 700,
                                  color: STITCH_COLORS.textHeading,
                                }}
                              >
                                {card.analyte_display}
                              </span>
                              <span
                                style={{
                                  fontSize: '1.05rem',
                                  fontWeight: 800,
                                  color: STITCH_COLORS.pink,
                                }}
                              >
                                {card.value}
                              </span>
                              <span
                                style={{
                                  fontSize: '0.82rem',
                                  color: STITCH_COLORS.textSecondary,
                                }}
                              >
                                {card.unit}
                              </span>
                              <SeverityChip severity={card.severity_chip} />
                            </div>
                            <p
                              style={{
                                margin: '0.35rem 0 0',
                                fontSize: '0.86rem',
                                lineHeight: 1.5,
                                color: STITCH_COLORS.textSecondary,
                              }}
                            >
                              {card.finding_sentence}
                            </p>
                          </div>
                          <span
                            aria-hidden="true"
                            style={{
                              color: STITCH_COLORS.textMuted,
                              fontSize: '0.88rem',
                              flexShrink: 0,
                              paddingTop: 4,
                            }}
                          >
                            {isExpanded ? '\u25BE' : '\u25B8'}
                          </span>
                        </button>
                        {isExpanded && (
                          <p
                            style={{
                              margin: '0.6rem 0 0',
                              paddingTop: '0.6rem',
                              borderTop: `1px solid ${STITCH_COLORS.borderGhost}`,
                              fontSize: '0.82rem',
                              lineHeight: 1.6,
                              color: STITCH_COLORS.textSecondary,
                            }}
                          >
                            <strong>Threshold source:</strong>{' '}
                            {card.threshold_provenance}
                          </p>
                        )}
                      </div>
                    );
                  })}
                </div>
              ) : (
                <p
                  style={{
                    margin: 0,
                    padding: '0.5rem 0.25rem',
                    fontSize: '0.9rem',
                    color: STITCH_COLORS.textSecondary,
                  }}
                >
                  No supported rows flagged.
                </p>
              ))}

            {/* Reviewed */}
            {resultsTab === 'reviewed' &&
              (hasReviewed ? (
                <div
                  className="stitch-compact-list"
                  style={{ display: 'grid', gap: '0.5rem' }}
                >
                  {artifact.reviewed_not_flagged.map((item, index) => {
                    const parsed = splitReviewedItem(item);
                    return (
                      <div
                        key={`${item}-${index}`}
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          gap: '0.75rem',
                          alignItems: 'center',
                          padding: '0.7rem 0.85rem',
                          borderRadius: STITCH_RADIUS.md,
                          backgroundColor: STITCH_COLORS.surfaceLow,
                        }}
                      >
                        <div style={{ minWidth: 0 }}>
                          <p
                            style={{
                              margin: 0,
                              fontSize: '0.88rem',
                              fontWeight: 700,
                              color: STITCH_COLORS.textHeading,
                            }}
                          >
                            {parsed.label}
                          </p>
                          <p
                            style={{
                              margin: '0.15rem 0 0',
                              fontSize: '0.82rem',
                              color: STITCH_COLORS.textSecondary,
                            }}
                          >
                            {parsed.value}
                          </p>
                        </div>
                        <span
                          aria-hidden="true"
                          style={{
                            width: 24,
                            height: 24,
                            borderRadius: '50%',
                            backgroundColor: '#DCFCE7',
                            color: STITCH_COLORS.trustedText,
                            display: 'inline-flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            fontSize: '0.74rem',
                            fontWeight: 800,
                            flexShrink: 0,
                          }}
                        >
                          ✓
                        </span>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <p
                  style={{
                    margin: 0,
                    padding: '0.5rem 0.25rem',
                    fontSize: '0.9rem',
                    color: STITCH_COLORS.textSecondary,
                  }}
                >
                  No normal reviewed rows.
                </p>
              ))}

            {/* Not assessed */}
            {resultsTab === 'not_assessed' &&
              (hasNotAssessed ? (
                <>
                  <p
                    style={{
                      margin: '0 0 0.6rem',
                      fontSize: '0.82rem',
                      color: STITCH_COLORS.textSecondary,
                    }}
                  >
                    Unsupported rows remain visible, never hidden.
                  </p>
                  <ul
                    style={{
                      margin: 0,
                      padding: 0,
                      listStyle: 'none',
                      display: 'grid',
                      gap: '0.45rem',
                    }}
                  >
                    {artifact.not_assessed.map((item, index) => (
                      <li
                        key={`${item.raw_label}-${index}`}
                        style={{
                          padding: '0.6rem 0.8rem',
                          borderRadius: STITCH_RADIUS.md,
                          backgroundColor: STITCH_COLORS.surfaceLow,
                          fontSize: '0.86rem',
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
                </>
              ) : (
                <p
                  style={{
                    margin: 0,
                    padding: '0.5rem 0.25rem',
                    fontSize: '0.9rem',
                    color: STITCH_COLORS.textSecondary,
                  }}
                >
                  No supported rows excluded.
                </p>
              ))}
          </SurfaceCard>
        </div>

        {/* ==================== SECTION 3: SIDEBAR ==================== */}
        <aside className="stitch-rail">
          <SurfaceCard
            style={{
              padding: '1.15rem',
              backgroundColor: STITCH_COLORS.navy,
              color: STITCH_COLORS.surfaceWhite,
            }}
          >
            <p
              style={{
                margin: '0 0 0.55rem',
                fontSize: '0.74rem',
                fontWeight: 800,
                textTransform: 'uppercase',
                letterSpacing: '0.08em',
                color: 'rgba(255,255,255,0.68)',
              }}
            >
              Actions
            </p>
            <div className="stitch-flow" style={{ gap: '0.5rem' }}>
              <PrimaryButton onClick={() => void handleShareSummary()}>
                Share to care team
              </PrimaryButton>
              <SecondaryButton
                onClick={handleExportPdf}
                style={{
                  backgroundColor: 'rgba(255,255,255,0.08)',
                  borderColor: 'rgba(255,255,255,0.12)',
                  color: STITCH_COLORS.surfaceWhite,
                }}
              >
                Export summary
              </SecondaryButton>
              {onViewClinicianShare && (
                <SecondaryButton
                  onClick={onViewClinicianShare}
                  style={{
                    backgroundColor: 'rgba(255,255,255,0.08)',
                    borderColor: 'rgba(255,255,255,0.12)',
                    color: STITCH_COLORS.surfaceWhite,
                  }}
                >
                  Clinician summary
                </SecondaryButton>
              )}
              {onViewGuidedAsk && (
                <SecondaryButton
                  onClick={onViewGuidedAsk}
                  style={{
                    backgroundColor: 'rgba(255,255,255,0.08)',
                    borderColor: 'rgba(255,255,255,0.12)',
                    color: STITCH_COLORS.surfaceWhite,
                  }}
                >
                  Ask guided questions
                </SecondaryButton>
              )}
            </div>

            <div
              style={{
                marginTop: '1rem',
                paddingTop: '0.9rem',
                borderTop: '1px solid rgba(255,255,255,0.12)',
                fontSize: '0.82rem',
                lineHeight: 1.55,
                color: 'rgba(255,255,255,0.76)',
              }}
            >
              {supportMeta.body} {trustMeta.body} Informational.
              {onNavigateBack && (
                <>
                  {' '}
                  <button
                    type="button"
                    onClick={onNavigateBack}
                    style={{
                      border: 'none',
                      background: 'none',
                      padding: 0,
                      color: STITCH_COLORS.surfaceWhite,
                      fontSize: '0.82rem',
                      fontWeight: 700,
                      cursor: 'pointer',
                      textDecoration: 'underline',
                    }}
                  >
                    Upload another
                  </button>
                  .
                </>
              )}
            </div>
          </SurfaceCard>

          <HistoryCard history={artifact.comparable_history} />
        </aside>
      </div>

      <p
        style={{
          margin: '1rem 0 0',
          textAlign: 'center',
          fontSize: '0.78rem',
          color: STITCH_COLORS.textMuted,
        }}
      >
        Informational only — not a diagnosis.
      </p>
    </PageChrome>
  );
}
