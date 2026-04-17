import { useState } from 'react';
import type { PatientArtifact, TrustStatus } from '../../types';
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
    body: 'Unsupported rows remain visible.',
    tone: 'beta',
    bg: '#FFF4E5',
    color: '#9A3412',
  },
  could_not_assess: {
    label: 'Could not assess fully',
    body: 'The file could not be fully structured.',
    tone: 'neutral',
    bg: '#F3F4F6',
    color: '#4B5563',
  },
};

const TRUST_STATUS_META: Record<
  TrustStatus,
  { label: string; tone: 'trusted' | 'beta'; body: string }
> = {
  trusted: {
    label: 'Trusted PDF lane',
    tone: 'trusted',
    body: 'Trusted PDF path.',
  },
  non_trusted_beta: {
    label: 'Non-trusted beta lane',
    tone: 'beta',
    body: 'Image beta path.',
  },
};

const SEVERITY_META: Record<
  PatientArtifact['overall_severity'],
  { label: string; bg: string; color: string; icon: string }
> = {
  S0: { label: 'No actionable finding', bg: '#EEF8EF', color: '#1F5C2C', icon: '\u2713' },
  S1: { label: 'Review routinely', bg: '#EEF8EF', color: '#1F5C2C', icon: '\u2139' },
  S2: { label: 'Discuss at next planned visit', bg: '#FFF4E5', color: '#9A3412', icon: '\u26A0' },
  S3: { label: 'Contact clinician soon', bg: '#FFF0D8', color: '#B45309', icon: '\u26A1' },
  S4: { label: 'Urgent follow-up recommended', bg: '#FEE2E2', color: '#991B1B', icon: '\u{1F6A8}' },
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

export default function PatientArtifact({
  artifact,
  onNavigateBack,
  onViewClinicianShare,
  onViewGuidedAsk,
}: Props) {
  const [expandedCard, setExpandedCard] = useState<number | null>(null);
  const [reviewedCollapsed, setReviewedCollapsed] = useState(true);
  const [showAllNotAssessed, setShowAllNotAssessed] = useState(false);
  const supportMeta =
    SUPPORT_BANNER_META[artifact.support_banner] ?? SUPPORT_BANNER_META.could_not_assess;
  const trustMeta =
    TRUST_STATUS_META[artifact.trust_status ?? 'non_trusted_beta'] ??
    TRUST_STATUS_META.non_trusted_beta;
  const severityMeta = SEVERITY_META[artifact.overall_severity] ?? SEVERITY_META.SX;
  const flaggedCards = Array.isArray(artifact.flagged_cards) ? artifact.flagged_cards : [];
  const reviewedNotFlagged = Array.isArray(artifact.reviewed_not_flagged)
    ? artifact.reviewed_not_flagged
    : [];
  const notAssessed = Array.isArray(artifact.not_assessed) ? artifact.not_assessed : [];
  const comparableHistory = Array.isArray(artifact.comparable_history)
    ? artifact.comparable_history
    : artifact.comparable_history
      ? [artifact.comparable_history]
      : [];
  const hasFlagged = flaggedCards.length > 0;
  const hasReviewed = reviewedNotFlagged.length > 0;
  const hasNextStep =
    artifact.nextstep_title !== '' ||
    artifact.nextstep_timing !== null ||
    artifact.nextstep_reason !== null;
  const visibleNotAssessed = showAllNotAssessed
    ? notAssessed
    : notAssessed.slice(0, 2);

  const summaryFacts = [
    {
      label: 'Flagged',
      value: hasFlagged
        ? `${flaggedCards.length} item${flaggedCards.length > 1 ? 's' : ''}`
        : 'None',
    },
    {
      label: 'Reviewed',
      value: hasReviewed
        ? `${reviewedNotFlagged.length} normal`
        : 'None',
    },
    {
      label: 'Not assessed',
      value: notAssessed.length
        ? `${notAssessed.length} visible`
        : 'None',
    },
    {
      label: 'Boundary',
      value: 'Informational only',
    },
  ];

  const handleShareSummary = async () => {
    const shareText = [
      'Elfie lab summary',
      hasFlagged
        ? flaggedCards
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

  const handleExportPdf = () => {
    window.print();
  };

  return (
    <PageChrome
      compact
      title="Your Lab Results"
      subtitle="Supported rows first."
      rightSlot={<PillBadge tone={supportMeta.tone}>{supportMeta.label}</PillBadge>}
      contentMaxWidth={1120}
    >
      <div className="stitch-grid-two stitch-enter" style={{ marginTop: '0.55rem' }}>
        <div className="stitch-flow">
          <SurfaceCard
            style={{
              padding: '1rem',
              background:
                `linear-gradient(180deg, ${severityMeta.bg} 0%, rgba(255,255,255,0.94) 100%)`,
            }}
          >
            <div className="stitch-summary-grid">
              <div style={{ minWidth: 0 }}>
                <div className="stitch-segment-row" style={{ marginBottom: '0.7rem' }}>
                  <PillBadge tone={supportMeta.tone}>{supportMeta.label}</PillBadge>
                  <span
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      padding: '4px 10px',
                      borderRadius: STITCH_RADIUS.pill,
                      backgroundColor:
                        trustMeta.tone === 'trusted'
                          ? STITCH_COLORS.trustedBg
                          : STITCH_COLORS.betaBg,
                      color:
                        trustMeta.tone === 'trusted'
                          ? STITCH_COLORS.trustedText
                          : STITCH_COLORS.betaText,
                      fontSize: '0.72rem',
                      fontWeight: 700,
                    }}
                  >
                    {trustMeta.label}
                  </span>
                </div>

                <div style={{ display: 'flex', gap: '0.85rem', alignItems: 'flex-start' }}>
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
                  <div style={{ minWidth: 0 }}>
                    <p
                      style={{
                        margin: 0,
                        fontSize: '0.74rem',
                        fontWeight: 800,
                        letterSpacing: '0.08em',
                        textTransform: 'uppercase',
                        lineHeight: 1.35,
                        color: severityMeta.color,
                      }}
                    >
                      Overall severity
                    </p>
                    <p
                      style={{
                        margin: '0.16rem 0 0',
                        fontSize: '1.2rem',
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
                          margin: '0.32rem 0 0',
                          fontSize: '0.9rem',
                          lineHeight: 1.55,
                          color: STITCH_COLORS.textSecondary,
                        }}
                      >
                        {artifact.nextstep_title || 'Next step available'}
                        {artifact.nextstep_timing ? ` · ${artifact.nextstep_timing}` : ''}
                      </p>
                    )}
                    {artifact.nextstep_reason && (
                      <p
                        style={{
                          margin: '0.2rem 0 0',
                          fontSize: '0.82rem',
                          lineHeight: 1.55,
                          color: STITCH_COLORS.textSecondary,
                        }}
                      >
                        {artifact.nextstep_reason}
                      </p>
                    )}
                  </div>
                </div>
              </div>

              <div className="stitch-detail-grid">
                {summaryFacts.map((item) => (
                  <div
                    key={item.label}
                    style={{
                      padding: '0.8rem',
                      borderRadius: STITCH_RADIUS.md,
                      backgroundColor: 'rgba(255,255,255,0.74)',
                    }}
                  >
                    <p
                      style={{
                        margin: '0 0 0.18rem',
                        fontSize: '0.7rem',
                        fontWeight: 800,
                        letterSpacing: '0.08em',
                        textTransform: 'uppercase',
                        color: STITCH_COLORS.textMuted,
                      }}
                    >
                      {item.label}
                    </p>
                    <p
                      style={{
                        margin: 0,
                        fontSize: '0.94rem',
                        fontWeight: 700,
                        lineHeight: 1.4,
                        color: STITCH_COLORS.textHeading,
                      }}
                    >
                      {item.value}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          </SurfaceCard>

          <section>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: '0.6rem',
                marginBottom: '0.45rem',
              }}
            >
              <h3
                style={{
                  margin: 0,
                  fontSize: '0.96rem',
                  fontWeight: 700,
                  color: STITCH_COLORS.textHeading,
                }}
              >
                Flagged for review
              </h3>
              <PillBadge tone={hasFlagged ? 'beta' : 'trusted'}>
                {hasFlagged
                  ? `${flaggedCards.length} item${flaggedCards.length > 1 ? 's' : ''}`
                  : 'None'}
              </PillBadge>
            </div>

            {hasFlagged ? (
              <div className="stitch-flow" style={{ gap: '0.55rem' }}>
                {flaggedCards.map((card, index) => {
                  const isExpanded = expandedCard === index;

                  return (
                    <SurfaceCard
                      key={`${card.analyte_display}-${index}`}
                      style={{ padding: '0.9rem' }}
                    >
                      <button
                        type="button"
                        onClick={() => setExpandedCard(isExpanded ? null : index)}
                        style={{
                          width: '100%',
                          border: 'none',
                          background: 'none',
                          padding: 0,
                          textAlign: 'left',
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
                                fontSize: '0.72rem',
                                fontWeight: 800,
                                textTransform: 'uppercase',
                                letterSpacing: '0.07em',
                                color: STITCH_COLORS.textMuted,
                              }}
                            >
                              {card.analyte_display}
                            </p>
                            <div
                              style={{
                                marginTop: '0.2rem',
                                display: 'flex',
                                alignItems: 'baseline',
                                gap: '0.3rem',
                                flexWrap: 'wrap',
                              }}
                            >
                              <span
                                style={{
                                  fontSize: '1.55rem',
                                  fontWeight: 800,
                                  letterSpacing: '-0.05em',
                                  color: STITCH_COLORS.pink,
                                  overflowWrap: 'anywhere',
                                }}
                              >
                                {card.value}
                              </span>
                              <span
                                style={{
                                  fontSize: '0.86rem',
                                  color: STITCH_COLORS.textSecondary,
                                  fontWeight: 600,
                                }}
                              >
                                {card.unit}
                              </span>
                            </div>
                            <div style={{ marginTop: '0.45rem' }}>
                              <SeverityChip severity={card.severity_chip} />
                            </div>
                            <p
                              style={{
                                margin: '0.5rem 0 0',
                                fontSize: '0.82rem',
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
                            {isExpanded ? '\u25BE' : '\u25B8'}
                          </span>
                        </div>
                      </button>

                      {isExpanded && (
                        <p
                          style={{
                            margin: '0.65rem 0 0',
                            fontSize: '0.76rem',
                            lineHeight: 1.55,
                            color: STITCH_COLORS.textSecondary,
                          }}
                        >
                          <strong>Threshold source:</strong>{' '}
                          {card.threshold_provenance}
                        </p>
                      )}
                    </SurfaceCard>
                  );
                })}
              </div>
            ) : (
              <SurfaceCard style={{ padding: '0.85rem' }}>
                <p
                  style={{
                    margin: 0,
                    fontSize: '0.84rem',
                    lineHeight: 1.55,
                    color: STITCH_COLORS.textSecondary,
                  }}
                >
                  No supported rows were flagged.
                </p>
              </SurfaceCard>
            )}
          </section>

          {hasReviewed && (
            <section>
              <SurfaceCard
                style={{
                  padding: '0.9rem',
                  backgroundColor: STITCH_COLORS.surfaceLow,
                  boxShadow: 'none',
                }}
              >
                <button
                  type="button"
                  onClick={() => setReviewedCollapsed((prev) => !prev)}
                  style={{
                    width: '100%',
                    border: 'none',
                    background: 'none',
                    padding: 0,
                    minHeight: 44,
                    cursor: 'pointer',
                    textAlign: 'left',
                  }}
                  aria-expanded={!reviewedCollapsed}
                >
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      gap: '0.6rem',
                    }}
                  >
                    <div style={{ minWidth: 0 }}>
                      <h3
                        style={{
                          margin: 0,
                          fontSize: '0.96rem',
                          fontWeight: 700,
                          color: STITCH_COLORS.textHeading,
                        }}
                      >
                        Reviewed and not flagged
                      </h3>
                      <p
                        style={{
                          margin: '0.18rem 0 0',
                          fontSize: '0.82rem',
                          lineHeight: 1.5,
                          color: STITCH_COLORS.textSecondary,
                        }}
                      >
                        {reviewedNotFlagged.length} supported item
                        {reviewedNotFlagged.length > 1 ? 's' : ''} looked normal.
                      </p>
                    </div>
                    <span
                      aria-hidden="true"
                      style={{
                        color: STITCH_COLORS.textMuted,
                        fontSize: '0.88rem',
                        width: 36,
                        height: 36,
                        borderRadius: '50%',
                        backgroundColor: STITCH_COLORS.surfaceWhite,
                        display: 'inline-flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        flexShrink: 0,
                      }}
                    >
                      {reviewedCollapsed ? '\u25B8' : '\u25BE'}
                    </span>
                  </div>
                </button>

                {!reviewedCollapsed && (
                  <div className="stitch-compact-list" style={{ marginTop: '0.85rem' }}>
                    {reviewedNotFlagged.map((item, index) => {
                      const parsed = splitReviewedItem(item);
                      return (
                        <div
                          key={`${item}-${index}`}
                          style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            gap: '0.75rem',
                            alignItems: 'center',
                            padding: '0.8rem',
                            borderRadius: STITCH_RADIUS.md,
                            backgroundColor: STITCH_COLORS.surfaceWhite,
                          }}
                        >
                          <div style={{ minWidth: 0 }}>
                            <p
                              style={{
                                margin: 0,
                                fontSize: '0.68rem',
                                fontWeight: 800,
                                textTransform: 'uppercase',
                                color: STITCH_COLORS.textMuted,
                                lineHeight: 1.35,
                              }}
                            >
                              {parsed.label}
                            </p>
                            <p
                              style={{
                                margin: '0.22rem 0 0',
                                fontSize: '0.88rem',
                                fontWeight: 700,
                                color: STITCH_COLORS.textPrimary,
                                lineHeight: 1.4,
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
                              fontSize: '0.75rem',
                              fontWeight: 800,
                              flexShrink: 0,
                            }}
                          >
                            {'\u2713'}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                )}
              </SurfaceCard>
            </section>
          )}

          <section>
            <SurfaceCard
              style={{
                padding: '0.9rem',
                border: `2px dashed rgba(118, 118, 126, 0.22)`,
                boxShadow: 'none',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: '0.6rem',
                  marginBottom: '0.55rem',
                }}
              >
                <div style={{ minWidth: 0 }}>
                  <h3
                    style={{
                      margin: 0,
                      fontSize: '0.96rem',
                      fontWeight: 700,
                      color: STITCH_COLORS.textHeading,
                    }}
                  >
                    What was not assessed
                  </h3>
                  <p
                    style={{
                      margin: '0.18rem 0 0',
                      fontSize: '0.82rem',
                      lineHeight: 1.5,
                      color: STITCH_COLORS.textSecondary,
                    }}
                  >
                    Unsupported items stay visible here instead of disappearing.
                  </p>
                </div>
                {notAssessed.length > 0 && (
                  <PillBadge tone="neutral">
                    {notAssessed.length} item
                    {notAssessed.length > 1 ? 's' : ''}
                  </PillBadge>
                )}
              </div>

              {notAssessed.length > 0 ? (
                <ul
                  style={{
                    margin: 0,
                    paddingLeft: '1rem',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '0.45rem',
                  }}
                >
                  {visibleNotAssessed.map((item, index) => (
                    <li
                      key={`${item.raw_label}-${index}`}
                      style={{
                        fontSize: '0.84rem',
                        lineHeight: 1.55,
                        color: STITCH_COLORS.textSecondary,
                      }}
                    >
                      <strong style={{ color: STITCH_COLORS.textHeading }}>
                        {item.raw_label}
                      </strong>{' '}
                      - {item.reason}
                    </li>
                  ))}
                </ul>
              ) : (
                <p
                  style={{
                    margin: 0,
                    fontSize: '0.82rem',
                    lineHeight: 1.55,
                    color: STITCH_COLORS.textSecondary,
                  }}
                >
                  No supported rows were excluded from assessment.
                </p>
              )}

              {notAssessed.length > 2 && (
                <button
                  type="button"
                  onClick={() => setShowAllNotAssessed((prev) => !prev)}
                  style={{
                    marginTop: '0.75rem',
                    border: 'none',
                    background: 'none',
                    padding: 0,
                    color: STITCH_COLORS.blue,
                    fontSize: '0.82rem',
                    fontWeight: 700,
                    cursor: 'pointer',
                  }}
                >
                  {showAllNotAssessed
                    ? 'Show fewer items'
                    : `Show all ${notAssessed.length} items`}
                </button>
              )}
            </SurfaceCard>
          </section>
        </div>

        <aside className="stitch-rail">
          <HistoryCard observations={comparableHistory} />

          <SurfaceCard
            style={{
              padding: '0.95rem',
              backgroundColor: STITCH_COLORS.navy,
              color: STITCH_COLORS.surfaceWhite,
            }}
          >
            <p
              style={{
                margin: '0 0 0.45rem',
                fontSize: '0.72rem',
                fontWeight: 800,
                textTransform: 'uppercase',
                letterSpacing: '0.08em',
                color: 'rgba(255,255,255,0.68)',
              }}
            >
              Quick actions
            </p>

            {(onViewClinicianShare || onViewGuidedAsk) && (
              <div className="stitch-flow" style={{ gap: '0.5rem' }}>
                {onViewClinicianShare && (
                  <SecondaryButton
                    onClick={onViewClinicianShare}
                    style={{
                      minHeight: 46,
                      backgroundColor: 'rgba(255,255,255,0.08)',
                      borderColor: 'rgba(255,255,255,0.12)',
                      color: STITCH_COLORS.surfaceWhite,
                    }}
                  >
                    View clinician summary
                  </SecondaryButton>
                )}
                {onViewGuidedAsk && (
                  <SecondaryButton
                    onClick={onViewGuidedAsk}
                    style={{
                      minHeight: 46,
                      backgroundColor: 'rgba(255,255,255,0.08)',
                      borderColor: 'rgba(255,255,255,0.12)',
                      color: STITCH_COLORS.surfaceWhite,
                    }}
                  >
                    Ask guided questions
                  </SecondaryButton>
                )}
              </div>
            )}

            <p
              style={{
                margin: onViewClinicianShare || onViewGuidedAsk ? '0.8rem 0 0' : 0,
                fontSize: '0.8rem',
                lineHeight: 1.55,
                color: 'rgba(255,255,255,0.76)',
              }}
            >
              {supportMeta.body} {trustMeta.body} Informational only.
            </p>

            <div style={{ marginTop: '0.95rem' }}>
              <p
                style={{
                  margin: '0 0 0.45rem',
                  fontSize: '0.72rem',
                  fontWeight: 800,
                  textTransform: 'uppercase',
                  letterSpacing: '0.08em',
                  color: 'rgba(255,255,255,0.68)',
                }}
              >
                Share results
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
              </div>
            </div>

            {onNavigateBack && (
              <p
                style={{
                  margin: '0.95rem 0 0',
                  fontSize: '0.82rem',
                  lineHeight: 1.55,
                  color: 'rgba(255,255,255,0.76)',
                }}
              >
                Need to scan something else?{' '}
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
                  }}
                >
                  Upload another file
                </button>
              </p>
            )}
          </SurfaceCard>
        </aside>
      </div>

      <p
        style={{
          margin: '0.8rem 0 0',
          textAlign: 'center',
          fontSize: '0.74rem',
          lineHeight: 1.45,
          color: STITCH_COLORS.textMuted,
        }}
      >
        Results are informational only and never a diagnosis.
      </p>
    </PageChrome>
  );
}