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
import { STITCH_COLORS, STITCH_RADIUS, pageCardStyle } from '../common/system';

const SUPPORT_BANNER_META: Record<
  PatientArtifact['support_banner'],
  { label: string; body: string; tone: 'trusted' | 'beta' | 'neutral'; bg: string; color: string }
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
  PatientArtifact['trust_status'],
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
  const [expandedCard, setExpandedCard] = useState<number | null>(0);
  const [reviewedCollapsed, setReviewedCollapsed] = useState(true);
  const supportMeta = SUPPORT_BANNER_META[artifact.support_banner];
  const trustMeta = TRUST_STATUS_META[artifact.trust_status];
  const severityMeta = SEVERITY_META[artifact.overall_severity];
  const hasFlagged = artifact.flagged_cards.length > 0;
  const hasNextStep =
    artifact.nextstep_title !== '' ||
    artifact.nextstep_timing !== null ||
    artifact.nextstep_reason !== null;
  const hasReviewed = artifact.reviewed_not_flagged.length > 0;

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

  const handleExportPdf = () => {
    window.print();
  };

  return (
    <PageChrome
      compact
      title="Your Lab Results"
      subtitle="Supported rows first."
      rightSlot={<PillBadge tone={supportMeta.tone}>{supportMeta.label}</PillBadge>}
    >
      <div
        role="status"
        style={{
          ...pageCardStyle({
            marginTop: '0.5rem',
            padding: '0.75rem 0.8rem',
            backgroundColor: severityMeta.bg,
            color: severityMeta.color,
          }),
        }}
      >
        <div style={{ display: 'flex', gap: '0.6rem', alignItems: 'center' }}>
          <div
            style={{
              width: 38,
              height: 38,
              borderRadius: STITCH_RADIUS.sm,
              backgroundColor: 'rgba(255,255,255,0.65)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
              fontSize: '0.9rem',
            }}
          >
            {severityMeta.icon}
          </div>
          <div style={{ minWidth: 0, flex: 1 }}>
            <p
              style={{
                margin: 0,
                fontSize: '0.88rem',
                fontWeight: 700,
                lineHeight: 1.3,
              }}
            >
              {severityMeta.label}
            </p>
            {artifact.nextstep_timing && (
              <p
                style={{
                  margin: '0.16rem 0 0',
                  fontSize: '0.76rem',
                  color: 'inherit',
                  lineHeight: 1.35,
                }}
              >
                {artifact.nextstep_timing}
              </p>
            )}
          </div>
        </div>
      </div>

      <p
        style={{
          margin: '0.35rem 0 0',
          fontSize: '0.72rem',
          lineHeight: 1.4,
          color: STITCH_COLORS.textSecondary,
        }}
      >
        Wellness-support only. No diagnosis, treatment, or medication advice.
      </p>

      <p
        style={{
          margin: '0.35rem 0 0',
          fontSize: '0.72rem',
          lineHeight: 1.4,
          color:
            trustMeta.tone === 'trusted'
              ? STITCH_COLORS.trustedText
              : STITCH_COLORS.betaText,
          fontWeight: 700,
        }}
      >
        {trustMeta.body}
      </p>

      <div style={{ marginTop: '0.85rem' }}>
        <HistoryCard history={artifact.comparable_history} />
      </div>

      <section style={{ marginTop: '0.7rem' }}>
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
              ? `${artifact.flagged_cards.length} item${artifact.flagged_cards.length > 1 ? 's' : ''}`
              : 'None'}
          </PillBadge>
        </div>

        {hasFlagged ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            {artifact.flagged_cards.map((card, index) => {
              const isExpanded = expandedCard === index;
              return (
                <SurfaceCard
                  key={`${card.analyte_display}-${index}`}
                  style={{ padding: '0.7rem' }}
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
                        gap: '0.6rem',
                        alignItems: 'flex-start',
                      }}
                    >
                      <div style={{ minWidth: 0 }}>
                        <p
                          style={{
                            margin: 0,
                            fontSize: '0.7rem',
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
                              fontSize: '1.6rem',
                              fontWeight: 800,
                              letterSpacing: '-0.04em',
                              color: STITCH_COLORS.pink,
                              overflowWrap: 'anywhere',
                            }}
                          >
                            {card.value}
                          </span>
                          <span
                            style={{
                              fontSize: '0.84rem',
                              color: STITCH_COLORS.textSecondary,
                              fontWeight: 600,
                            }}
                          >
                            {card.unit}
                          </span>
                        </div>
                      </div>
                      <span
                        aria-hidden="true"
                        style={{
                          color: STITCH_COLORS.textMuted,
                          fontSize: '0.88rem',
                          width: 44,
                          height: 44,
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

                    <div style={{ marginTop: '0.4rem' }}>
                      <SeverityChip severity={card.severity_chip} />
                    </div>
                  </button>

                  {isExpanded && (
                    <>
                      <div
                        style={{
                          marginTop: '0.6rem',
                          padding: '0.6rem',
                          borderRadius: STITCH_RADIUS.sm,
                          backgroundColor: '#FFF3F7',
                          color: '#8A124A',
                          fontSize: '0.82rem',
                          lineHeight: 1.5,
                        }}
                      >
                        {card.finding_sentence}
                      </div>
                      <p
                        style={{
                          margin: '0.4rem 0 0',
                          fontSize: '0.74rem',
                          lineHeight: 1.45,
                          color: STITCH_COLORS.textSecondary,
                        }}
                      >
                        <strong>Threshold source:</strong>{' '}
                        {card.threshold_provenance}
                      </p>
                    </>
                  )}
                </SurfaceCard>
              );
            })}
          </div>
        ) : (
          <SurfaceCard style={{ padding: '0.7rem' }}>
            <p style={{ margin: 0, fontSize: '0.84rem', lineHeight: 1.5, color: STITCH_COLORS.textSecondary }}>
              No supported rows were flagged.
            </p>
          </SurfaceCard>
        )}
      </section>

      {hasReviewed && (
        <section style={{ marginTop: '0.7rem' }}>
          <button
            type="button"
            onClick={() => setReviewedCollapsed((prev) => !prev)}
            style={{
              width: '100%',
              border: 'none',
              background: 'none',
              padding: '0.2rem 0',
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
                Reviewed and not flagged
              </h3>
              <span
                aria-hidden="true"
                style={{
                  color: STITCH_COLORS.textMuted,
                  fontSize: '0.88rem',
                  width: 44,
                  height: 44,
                  borderRadius: '50%',
                  backgroundColor: STITCH_COLORS.surfaceLow,
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
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))',
                gap: '0.5rem',
              }}
            >
              {artifact.reviewed_not_flagged.map((item, index) => {
                const parsed = splitReviewedItem(item);
                return (
                  <SurfaceCard
                    key={`${item}-${index}`}
                    style={{
                      padding: '0.65rem',
                      minHeight: 80,
                      display: 'flex',
                      flexDirection: 'column',
                      justifyContent: 'space-between',
                    }}
                  >
                    <div>
                      <p
                        style={{
                          margin: 0,
                          fontSize: '0.66rem',
                          fontWeight: 800,
                          textTransform: 'uppercase',
                          color: STITCH_COLORS.textMuted,
                          lineHeight: 1.3,
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
                          lineHeight: 1.3,
                        }}
                      >
                        {parsed.value}
                      </p>
                    </div>
                    <span
                      aria-hidden="true"
                      style={{
                        marginTop: '0.4rem',
                        width: 20,
                        height: 20,
                        borderRadius: '50%',
                        backgroundColor: '#DCFCE7',
                        color: STITCH_COLORS.trustedText,
                        display: 'inline-flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontSize: '0.68rem',
                        fontWeight: 800,
                      }}
                    >
                      {'\u2713'}
                    </span>
                  </SurfaceCard>
                );
              })}
            </div>
          )}
        </section>
      )}

      {hasNextStep && (
        <section style={{ marginTop: '0.7rem' }}>
          <h3
            style={{
              margin: '0 0 0.4rem',
              fontSize: '0.96rem',
              fontWeight: 700,
              color: STITCH_COLORS.textHeading,
            }}
          >
            What to do next
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.45rem' }}>
            {artifact.nextstep_title && (
              <SurfaceCard style={{ padding: '0.65rem 0.75rem' }}>
                <div style={{ display: 'flex', gap: '0.6rem', alignItems: 'center' }}>
                  <div
                    style={{
                      width: 36,
                      height: 36,
                      borderRadius: STITCH_RADIUS.sm,
                      backgroundColor: STITCH_COLORS.blueSoft,
                      color: STITCH_COLORS.navy,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: '0.9rem',
                      flexShrink: 0,
                    }}
                  >
                    {'\u2139'}
                  </div>
                  <div>
                    <p
                      style={{
                        margin: 0,
                        fontSize: '0.88rem',
                        fontWeight: 700,
                        color: STITCH_COLORS.textHeading,
                      }}
                    >
                      {artifact.nextstep_title}
                    </p>
                    {artifact.nextstep_timing && (
                      <p
                        style={{
                          margin: '0.08rem 0 0',
                          fontSize: '0.74rem',
                          color: STITCH_COLORS.textSecondary,
                        }}
                      >
                        {artifact.nextstep_timing}
                      </p>
                    )}
                  </div>
                </div>
              </SurfaceCard>
            )}
            {artifact.nextstep_reason && (
              <SurfaceCard style={{ padding: '0.65rem 0.75rem' }}>
                <p
                  style={{
                    margin: 0,
                    fontSize: '0.82rem',
                    lineHeight: 1.5,
                    color: STITCH_COLORS.textSecondary,
                  }}
                >
                  {artifact.nextstep_reason}
                </p>
              </SurfaceCard>
            )}
          </div>
        </section>
      )}

      <section style={{ marginTop: '0.7rem' }}>
        <h3
          style={{
            margin: '0 0 0.4rem',
            fontSize: '0.96rem',
            fontWeight: 700,
            color: STITCH_COLORS.textHeading,
          }}
        >
          What was not assessed
        </h3>
        <div
          style={{
            ...pageCardStyle({
              padding: '0.7rem',
              border: `2px dashed rgba(118, 118, 126, 0.22)`,
              boxShadow: 'none',
            }),
          }}
        >
          {artifact.not_assessed.length > 0 ? (
            <ul
              style={{
                margin: 0,
                paddingLeft: '1rem',
                display: 'flex',
                flexDirection: 'column',
                gap: '0.35rem',
              }}
            >
              {artifact.not_assessed.map((item, index) => (
                <li
                  key={`${item.raw_label}-${index}`}
                  style={{
                    fontSize: '0.82rem',
                    lineHeight: 1.45,
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
            <p style={{ margin: 0, fontSize: '0.82rem', lineHeight: 1.5, color: STITCH_COLORS.textSecondary }}>
              No supported rows were excluded from assessment.
            </p>
          )}
        </div>
      </section>

      <section style={{ marginTop: '0.7rem' }}>
        {(onViewClinicianShare || onViewGuidedAsk) && (
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: '0.5rem',
            }}
          >
            {onViewClinicianShare && (
              <SecondaryButton
                onClick={onViewClinicianShare}
                style={{
                  minHeight: 46,
                  backgroundColor: STITCH_COLORS.surfaceLow,
                  borderColor: STITCH_COLORS.borderGhost,
                  color: STITCH_COLORS.textHeading,
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
                  backgroundColor: STITCH_COLORS.surfaceLow,
                  borderColor: STITCH_COLORS.borderGhost,
                  color: STITCH_COLORS.textHeading,
                }}
              >
                Ask guided questions
              </SecondaryButton>
            )}
          </div>
        )}

        <div style={{ marginTop: onViewClinicianShare || onViewGuidedAsk ? '1rem' : 0 }}>
          <p
            style={{
              margin: '0 0 0.5rem',
              fontSize: '0.72rem',
              fontWeight: 800,
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              color: STITCH_COLORS.textMuted,
              textAlign: 'center',
            }}
          >
            Share results
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <PrimaryButton onClick={() => void handleShareSummary()}>
              Share to care team
            </PrimaryButton>
            <SecondaryButton onClick={handleExportPdf}>
              Export summary
            </SecondaryButton>
          </div>
        </div>

        {onNavigateBack && (
          <p
            style={{
              margin: '0.9rem 0 0',
              fontSize: '0.82rem',
              lineHeight: 1.5,
              color: STITCH_COLORS.textSecondary,
              textAlign: 'center',
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
                color: STITCH_COLORS.blue,
                fontSize: '0.82rem',
                fontWeight: 700,
                cursor: 'pointer',
              }}
            >
              Upload another file
            </button>
          </p>
        )}
      </section>

      <p
        style={{
          margin: '0.75rem 0 0',
          textAlign: 'center',
          fontSize: '0.74rem',
          lineHeight: 1.4,
          color: STITCH_COLORS.textMuted,
        }}
      >
        Results are informational only and never a diagnosis.
      </p>
    </PageChrome>
  );
}
