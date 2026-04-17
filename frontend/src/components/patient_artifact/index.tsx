import { useState } from 'react';
import type { PatientArtifact } from '../../types';
import { unsupportedReasonDisplay } from '../../types';
import HistoryCard from '../history_card';
import {
  PageChrome,
  PillBadge,
  PrimaryButton,
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
  const [expandedReviewed, setExpandedReviewed] = useState<number | null>(null);
  const [expandedNotAssessed, setExpandedNotAssessed] = useState<number | null>(
    null,
  );
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
          {/* ==================== MERGED: OVERVIEW + RESULTS ==================== */}
          <SurfaceCard style={{ padding: 0, overflow: 'hidden' }}>
            {/* --- Overview (top, severity-tinted) --- */}
            <div
              style={{
                padding: '1.6rem 1.6rem 1.7rem',
                background: `linear-gradient(180deg, ${severityMeta.bg} 0%, rgba(255,255,255,0.94) 100%)`,
              }}
            >
              <div
                style={{
                  display: 'flex',
                  flexWrap: 'wrap',
                  gap: 8,
                marginBottom: '0.9rem',
                alignItems: 'center',
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
              <div style={{ minWidth: 0, flex: 1 }}>
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: 10,
                  }}
                >
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
                  <span
                    aria-hidden="true"
                    title={severityMeta.label}
                    style={{
                      width: 26,
                      height: 26,
                      borderRadius: '50%',
                      backgroundColor: 'rgba(255,255,255,0.82)',
                      color: severityMeta.color,
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: '0.85rem',
                      flexShrink: 0,
                      boxShadow: '0 1px 2px rgba(18,26,51,0.08)',
                    }}
                  >
                    {severityMeta.icon}
                  </span>
                </div>
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
            </div>
            {/* end overview */}

            {/* subtle divider between overview and results */}
            <div
              aria-hidden="true"
              style={{
                height: 1,
                margin: '0.25rem 1.6rem',
                background: `linear-gradient(90deg, transparent 0%, ${STITCH_COLORS.borderGhost} 12%, ${STITCH_COLORS.borderGhost} 88%, transparent 100%)`,
              }}
            />

            {/* --- Results (tabs + body), same card --- */}
            <div style={{ padding: '1.4rem 1.6rem 1.6rem' }}>
            <div
              role="tablist"
              aria-label="Results"
              style={{
                display: 'flex',
                gap: 4,
                padding: 4,
                borderRadius: STITCH_RADIUS.lg,
                backgroundColor: STITCH_COLORS.surfaceLow,
                marginBottom: '1.25rem',
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
                <div
                  className="stitch-flow"
                  style={{ gap: '1.1rem', padding: '0.1rem' }}
                >
                  {artifact.flagged_cards.map((card, index) => {
                    const isExpanded = expandedCard === index;
                    return (
                      <div
                        key={`${card.analyte_display}-${index}`}
                        style={{
                          border: `1px solid ${STITCH_COLORS.borderGhost}`,
                          borderRadius: STITCH_RADIUS.md,
                          backgroundColor: isExpanded
                            ? 'rgba(255, 21, 112, 0.03)'
                            : STITCH_COLORS.surfaceWhite,
                          boxShadow: isExpanded
                            ? '0 4px 14px rgba(255, 21, 112, 0.08)'
                            : '0 1px 3px rgba(18,26,51,0.04)',
                          transition:
                            'background-color 220ms ease, box-shadow 220ms ease, border-color 220ms ease',
                          overflow: 'hidden',
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
                            padding: '0.9rem 1rem',
                            textAlign: 'left',
                            cursor: 'pointer',
                            display: 'flex',
                            gap: '0.8rem',
                            alignItems: 'center',
                          }}
                        >
                          <span
                            aria-hidden="true"
                            style={{
                              width: 26,
                              height: 26,
                              borderRadius: '50%',
                              backgroundColor: 'rgba(255, 21, 112, 0.14)',
                              color: STITCH_COLORS.pink,
                              display: 'inline-flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                              fontSize: '0.74rem',
                              fontWeight: 800,
                              flexShrink: 0,
                            }}
                          >
                            ●
                          </span>
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
                            </div>
                            <div style={{ marginTop: 6 }}>
                              <SeverityChip severity={card.severity_chip} />
                            </div>
                          </div>
                          <span
                            aria-hidden="true"
                            style={{
                              color: STITCH_COLORS.textMuted,
                              fontSize: '0.95rem',
                              flexShrink: 0,
                              transform: isExpanded
                                ? 'rotate(90deg)'
                                : 'rotate(0deg)',
                              transition: 'transform 220ms ease',
                              lineHeight: 1,
                            }}
                          >
                            ▸
                          </span>
                        </button>
                        {isExpanded && (
                          <div
                            style={{
                              padding: '0 1rem 1rem 3.1rem',
                              display: 'flex',
                              flexDirection: 'column',
                              gap: '0.55rem',
                              animation: 'stitchHeaderRowIn 220ms ease both',
                            }}
                          >
                            <p
                              style={{
                                margin: 0,
                                fontSize: '0.88rem',
                                lineHeight: 1.55,
                                color: STITCH_COLORS.textSecondary,
                              }}
                            >
                              {card.finding_sentence}
                            </p>
                            <p
                              style={{
                                margin: 0,
                                fontSize: '0.78rem',
                                lineHeight: 1.55,
                                color: STITCH_COLORS.textMuted,
                              }}
                            >
                              <strong style={{ color: STITCH_COLORS.textSecondary }}>
                                Threshold source:
                              </strong>{' '}
                              {card.threshold_provenance}
                            </p>
                          </div>
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
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '0.9rem',
                    padding: '0.1rem',
                  }}
                >
                  {artifact.reviewed_not_flagged.map((item, index) => {
                    const parsed = splitReviewedItem(item);
                    const isExpanded = expandedReviewed === index;
                    return (
                      <div
                        key={`${item}-${index}`}
                        style={{
                          border: `1px solid ${STITCH_COLORS.borderGhost}`,
                          borderRadius: STITCH_RADIUS.md,
                          backgroundColor: isExpanded
                            ? '#F3FBF5'
                            : STITCH_COLORS.surfaceWhite,
                          boxShadow: isExpanded
                            ? '0 4px 14px rgba(31, 92, 44, 0.08)'
                            : '0 1px 3px rgba(18,26,51,0.04)',
                          transition:
                            'background-color 220ms ease, box-shadow 220ms ease',
                          overflow: 'hidden',
                        }}
                      >
                        <button
                          type="button"
                          onClick={() =>
                            setExpandedReviewed(isExpanded ? null : index)
                          }
                          aria-expanded={isExpanded}
                          style={{
                            width: '100%',
                            border: 'none',
                            background: 'none',
                            padding: '0.85rem 1rem',
                            textAlign: 'left',
                            cursor: 'pointer',
                            display: 'flex',
                            gap: '0.8rem',
                            alignItems: 'center',
                          }}
                        >
                          <span
                            aria-hidden="true"
                            style={{
                              width: 26,
                              height: 26,
                              borderRadius: '50%',
                              backgroundColor: '#DCFCE7',
                              color: STITCH_COLORS.trustedText,
                              display: 'inline-flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                              fontSize: '0.78rem',
                              fontWeight: 800,
                              flexShrink: 0,
                            }}
                          >
                            ✓
                          </span>
                          <p
                            style={{
                              margin: 0,
                              minWidth: 0,
                              flex: 1,
                              fontSize: '0.92rem',
                              fontWeight: 700,
                              color: STITCH_COLORS.textHeading,
                            }}
                          >
                            {parsed.label}
                          </p>
                          <span
                            aria-hidden="true"
                            style={{
                              color: STITCH_COLORS.textMuted,
                              fontSize: '0.95rem',
                              flexShrink: 0,
                              transform: isExpanded
                                ? 'rotate(90deg)'
                                : 'rotate(0deg)',
                              transition: 'transform 220ms ease',
                              lineHeight: 1,
                            }}
                          >
                            ▸
                          </span>
                        </button>
                        {isExpanded && (
                          <p
                            style={{
                              margin: 0,
                              padding: '0 1rem 0.9rem 3.1rem',
                              fontSize: '0.84rem',
                              lineHeight: 1.55,
                              color: STITCH_COLORS.textSecondary,
                              animation: 'stitchHeaderRowIn 220ms ease both',
                            }}
                          >
                            {parsed.value}
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
                  No normal reviewed rows.
                </p>
              ))}

            {/* Not assessed */}
            {resultsTab === 'not_assessed' &&
              (hasNotAssessed ? (
                <>
                  <p
                    style={{
                      margin: '0 0 1rem',
                      fontSize: '0.82rem',
                      color: STITCH_COLORS.textSecondary,
                    }}
                  >
                    Unsupported rows remain visible, never hidden.
                  </p>
                  <div
                    style={{
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '0.9rem',
                      padding: '0.1rem',
                    }}
                  >
                    {artifact.not_assessed.map((item, index) => {
                      const isExpanded = expandedNotAssessed === index;
                      return (
                        <div
                          key={`${item.raw_label}-${index}`}
                          style={{
                            border: `1px solid ${STITCH_COLORS.borderGhost}`,
                            borderRadius: STITCH_RADIUS.md,
                            backgroundColor: isExpanded
                              ? STITCH_COLORS.surfaceLow
                              : STITCH_COLORS.surfaceWhite,
                            boxShadow: isExpanded
                              ? '0 4px 14px rgba(18, 26, 51, 0.08)'
                              : '0 1px 3px rgba(18,26,51,0.04)',
                            transition:
                              'background-color 220ms ease, box-shadow 220ms ease',
                            overflow: 'hidden',
                          }}
                        >
                          <button
                            type="button"
                            onClick={() =>
                              setExpandedNotAssessed(isExpanded ? null : index)
                            }
                            aria-expanded={isExpanded}
                            style={{
                              width: '100%',
                              border: 'none',
                              background: 'none',
                              padding: '0.85rem 1rem',
                              textAlign: 'left',
                              cursor: 'pointer',
                              display: 'flex',
                              gap: '0.8rem',
                              alignItems: 'center',
                            }}
                          >
                            <span
                              aria-hidden="true"
                              style={{
                                width: 26,
                                height: 26,
                                borderRadius: '50%',
                                backgroundColor: STITCH_COLORS.surfaceLow,
                                color: STITCH_COLORS.textMuted,
                                display: 'inline-flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                fontSize: '0.82rem',
                                fontWeight: 800,
                                flexShrink: 0,
                              }}
                            >
                              —
                            </span>
                            <p
                              style={{
                                margin: 0,
                                minWidth: 0,
                                flex: 1,
                                fontSize: '0.92rem',
                                fontWeight: 700,
                                color: STITCH_COLORS.textHeading,
                              }}
                            >
                              {item.raw_label}
                            </p>
                            <span
                              aria-hidden="true"
                              style={{
                                color: STITCH_COLORS.textMuted,
                                fontSize: '0.95rem',
                                flexShrink: 0,
                                transform: isExpanded
                                  ? 'rotate(90deg)'
                                  : 'rotate(0deg)',
                                transition: 'transform 220ms ease',
                                lineHeight: 1,
                              }}
                            >
                              ▸
                            </span>
                          </button>
                          {isExpanded && (
                            <p
                              style={{
                                margin: 0,
                                padding: '0 1rem 0.9rem 3.1rem',
                                fontSize: '0.84rem',
                                lineHeight: 1.55,
                                color: STITCH_COLORS.textSecondary,
                                animation: 'stitchHeaderRowIn 220ms ease both',
                              }}
                            >
                              {unsupportedReasonDisplay(item)}
                            </p>
                          )}
                        </div>
                      );
                    })}
                  </div>
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
            </div>
            {/* end results */}
          </SurfaceCard>
        </div>

        {/* ==================== SECTION 3: SIDEBAR ==================== */}
        <aside className="stitch-rail">
          <SurfaceCard
            style={{
              padding: 0,
              overflow: 'hidden',
              background:
                'linear-gradient(180deg, #FFF6F8 0%, rgba(255,255,255,0.96) 55%, #FFFFFF 100%)',
              border: `1px solid ${STITCH_COLORS.borderGhost}`,
            }}
          >
            {/* Header */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '1rem 1.1rem 0.75rem',
              }}
            >
              <span
                aria-hidden="true"
                style={{
                  width: 30,
                  height: 30,
                  borderRadius: 10,
                  background: `linear-gradient(135deg, ${STITCH_COLORS.pink} 0%, #FF6FA1 100%)`,
                  color: STITCH_COLORS.surfaceWhite,
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: '0.95rem',
                  boxShadow: '0 4px 10px rgba(255,21,112,0.22)',
                }}
              >
                ♥
              </span>
              <div style={{ minWidth: 0 }}>
                <p
                  style={{
                    margin: 0,
                    fontSize: '1rem',
                    fontWeight: 800,
                    color: STITCH_COLORS.textHeading,
                    letterSpacing: '-0.01em',
                  }}
                >
                  What next?
                </p>
                <p
                  style={{
                    margin: 0,
                    fontSize: '0.76rem',
                    fontWeight: 600,
                    color: STITCH_COLORS.textMuted,
                  }}
                >
                  Gentle next steps, at your pace
                </p>
              </div>
            </div>

            {/* Primary action (hero) */}
            <div style={{ padding: '0 1.1rem 0.7rem' }}>
              <PrimaryButton onClick={() => void handleShareSummary()}>
                <span
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 8,
                  }}
                >
                  <span aria-hidden="true">✉</span>
                  Share with care team
                </span>
              </PrimaryButton>
            </div>

            {/* Featured: Chat with Elfie — major feature entry point */}
            {onViewGuidedAsk && (
              <div style={{ padding: '0 1.1rem 0.9rem' }}>
                <button
                  type="button"
                  onClick={onViewGuidedAsk}
                  className="stitch-chat-cta"
                  aria-label="Open Chat with Elfie — ask about your results"
                  style={{
                    position: 'relative',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 16,
                    width: '100%',
                    padding: '18px 18px 18px 20px',
                    border: 'none',
                    borderRadius: 22,
                    background: `
                      radial-gradient(circle at 92% 12%, rgba(255,183,209,0.55) 0%, rgba(255,183,209,0) 42%),
                      radial-gradient(circle at 6% 95%, rgba(107,254,156,0.22) 0%, rgba(107,254,156,0) 40%),
                      linear-gradient(135deg, #1A1F3D 0%, #2A1B4A 55%, #4A1D5C 100%)
                    `,
                    color: STITCH_COLORS.surfaceWhite,
                    textAlign: 'left',
                    cursor: 'pointer',
                    fontWeight: 700,
                    minHeight: 104,
                    boxShadow:
                      '0 18px 40px rgba(26, 31, 61, 0.32), 0 2px 0 rgba(255,255,255,0.06) inset, 0 0 0 1.5px rgba(255,255,255,0.08) inset',
                    overflow: 'hidden',
                    transition:
                      'transform 260ms cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 260ms ease, filter 220ms ease',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.transform =
                      'translateY(-3px) scale(1.015)';
                    e.currentTarget.style.boxShadow =
                      '0 26px 52px rgba(26, 31, 61, 0.42), 0 2px 0 rgba(255,255,255,0.08) inset, 0 0 0 1.5px rgba(255,21,112,0.35) inset';
                    e.currentTarget.style.filter = 'brightness(1.06)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.transform = 'none';
                    e.currentTarget.style.boxShadow =
                      '0 18px 40px rgba(26, 31, 61, 0.32), 0 2px 0 rgba(255,255,255,0.06) inset, 0 0 0 1.5px rgba(255,255,255,0.08) inset';
                    e.currentTarget.style.filter = 'none';
                  }}
                >
                  {/* Decorative sparkles */}
                  <span
                    aria-hidden="true"
                    style={{
                      position: 'absolute',
                      top: 10,
                      right: 54,
                      fontSize: 11,
                      color: 'rgba(255,255,255,0.75)',
                      textShadow: '0 0 8px rgba(255,183,209,0.8)',
                    }}
                  >
                    ✦
                  </span>
                  <span
                    aria-hidden="true"
                    style={{
                      position: 'absolute',
                      bottom: 14,
                      right: 82,
                      fontSize: 8,
                      color: 'rgba(255,255,255,0.6)',
                    }}
                  >
                    ✦
                  </span>

                  {/* Avatar with pink halo + online dot */}
                  <span
                    aria-hidden="true"
                    style={{
                      position: 'relative',
                      flexShrink: 0,
                      width: 62,
                      height: 62,
                      borderRadius: '50%',
                      background: `linear-gradient(135deg, ${STITCH_COLORS.pink} 0%, #FF6FA1 100%)`,
                      padding: 3,
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      boxShadow:
                        '0 0 0 4px rgba(255,21,112,0.18), 0 8px 20px rgba(255,21,112,0.38)',
                    }}
                  >
                    <span
                      style={{
                        width: '100%',
                        height: '100%',
                        borderRadius: '50%',
                        backgroundColor: '#FFFFFF',
                        display: 'inline-flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        overflow: 'hidden',
                      }}
                    >
                      <img
                        src="/elfie-bot.svg"
                        alt=""
                        width={50}
                        height={50}
                        style={{ display: 'block' }}
                      />
                    </span>
                    <span
                      style={{
                        position: 'absolute',
                        bottom: 2,
                        right: 2,
                        width: 14,
                        height: 14,
                        borderRadius: '50%',
                        backgroundColor: '#6BFE9C',
                        border: '2.5px solid #1A1F3D',
                        boxShadow: '0 0 0 2px rgba(107,254,156,0.35)',
                      }}
                    />
                  </span>

                  {/* Text block */}
                  <span style={{ minWidth: 0, flex: 1 }}>
                    <span
                      style={{
                        display: 'block',
                        fontSize: '0.64rem',
                        fontWeight: 800,
                        letterSpacing: '0.14em',
                        textTransform: 'uppercase',
                        color: '#FFB3CC',
                        marginBottom: 4,
                      }}
                    >
                      AI · Live assistant
                    </span>
                    <span
                      style={{
                        display: 'block',
                        fontSize: '1.22rem',
                        fontWeight: 800,
                        color: STITCH_COLORS.surfaceWhite,
                        letterSpacing: '-0.015em',
                        lineHeight: 1.2,
                      }}
                    >
                      Chat with Elfie
                    </span>
                    <span
                      style={{
                        display: 'block',
                        fontSize: '0.82rem',
                        color: 'rgba(255,255,255,0.78)',
                        marginTop: 4,
                        lineHeight: 1.4,
                      }}
                    >
                      Ask anything about your results — in plain words.
                    </span>
                    <span
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 6,
                        marginTop: 10,
                        padding: '5px 12px',
                        borderRadius: 999,
                        background: `linear-gradient(135deg, ${STITCH_COLORS.pink} 0%, #FF6FA1 100%)`,
                        color: STITCH_COLORS.surfaceWhite,
                        fontSize: '0.76rem',
                        fontWeight: 800,
                        letterSpacing: '0.01em',
                        boxShadow: '0 6px 14px rgba(255,21,112,0.45)',
                      }}
                    >
                      Open chat
                      <span aria-hidden="true" style={{ fontSize: '0.9rem' }}>
                        →
                      </span>
                    </span>
                  </span>
                </button>
              </div>
            )}

            {/* Secondary action list — real-looking buttons */}
            <div
              style={{
                padding: '0.4rem 1.1rem 0.9rem',
                display: 'flex',
                flexDirection: 'column',
                gap: 10,
              }}
            >
              {[
                {
                  icon: '⤓',
                  label: 'Export summary',
                  description: 'Save or print a PDF copy',
                  onClick: handleExportPdf,
                  show: true,
                },
                {
                  icon: '⚕',
                  label: 'Clinician summary',
                  description: 'Structured handoff for your clinician',
                  onClick: onViewClinicianShare,
                  show: Boolean(onViewClinicianShare),
                },
              ]
                .filter((row) => row.show)
                .map((row) => (
                  <button
                    key={row.label}
                    type="button"
                    onClick={row.onClick}
                    className="stitch-secondary-action"
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 12,
                      width: '100%',
                      padding: '12px 14px',
                      border: `1.5px solid ${STITCH_COLORS.borderGhost}`,
                      borderRadius: STITCH_RADIUS.md,
                      backgroundColor: STITCH_COLORS.surfaceWhite,
                      color: STITCH_COLORS.textHeading,
                      textAlign: 'left',
                      cursor: 'pointer',
                      fontWeight: 600,
                      minHeight: 60,
                      boxShadow: '0 1px 3px rgba(18,26,51,0.05)',
                      transition:
                        'transform 220ms cubic-bezier(0.34, 1.56, 0.64, 1), background-color 220ms ease, border-color 220ms ease, box-shadow 220ms ease',
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.backgroundColor =
                        'rgba(255, 21, 112, 0.04)';
                      e.currentTarget.style.borderColor =
                        'rgba(255, 21, 112, 0.35)';
                      e.currentTarget.style.boxShadow =
                        '0 8px 20px rgba(255,21,112,0.14)';
                      e.currentTarget.style.transform = 'translateY(-1px)';
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.backgroundColor =
                        STITCH_COLORS.surfaceWhite;
                      e.currentTarget.style.borderColor =
                        STITCH_COLORS.borderGhost;
                      e.currentTarget.style.boxShadow =
                        '0 1px 3px rgba(18,26,51,0.05)';
                      e.currentTarget.style.transform = 'none';
                    }}
                  >
                    <span
                      aria-hidden="true"
                      style={{
                        width: 38,
                        height: 38,
                        borderRadius: 12,
                        background: `linear-gradient(135deg, rgba(255,21,112,0.12) 0%, rgba(255,111,161,0.18) 100%)`,
                        color: STITCH_COLORS.pink,
                        display: 'inline-flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontSize: '1.05rem',
                        fontWeight: 800,
                        flexShrink: 0,
                      }}
                    >
                      {row.icon}
                    </span>
                    <span style={{ minWidth: 0, flex: 1 }}>
                      <span
                        style={{
                          display: 'block',
                          fontSize: '0.94rem',
                          fontWeight: 800,
                          color: STITCH_COLORS.textHeading,
                          letterSpacing: '-0.005em',
                        }}
                      >
                        {row.label}
                      </span>
                      <span
                        style={{
                          display: 'block',
                          fontSize: '0.78rem',
                          color: STITCH_COLORS.textSecondary,
                          marginTop: 2,
                        }}
                      >
                        {row.description}
                      </span>
                    </span>
                    <span
                      aria-hidden="true"
                      className="stitch-header-chevron"
                      style={{
                        fontSize: '1rem',
                        color: STITCH_COLORS.pink,
                        flexShrink: 0,
                        fontWeight: 800,
                      }}
                    >
                      ›
                    </span>
                  </button>
                ))}
            </div>

            {/* Informational footer + centered Upload-another */}
            <div
              style={{
                margin: '0 1.1rem 1rem',
                padding: '0.85rem 0.95rem 1rem',
                borderRadius: STITCH_RADIUS.md,
                backgroundColor: 'rgba(255, 21, 112, 0.04)',
                border: '1px solid rgba(255, 21, 112, 0.12)',
              }}
            >
              <p
                style={{
                  margin: 0,
                  fontSize: '0.8rem',
                  lineHeight: 1.55,
                  color: STITCH_COLORS.textSecondary,
                  textAlign: 'center',
                }}
              >
                <span aria-hidden="true" style={{ marginRight: 6 }}>
                  ℹ
                </span>
                {supportMeta.body} {trustMeta.body} Informational only.
              </p>
              {onNavigateBack && (
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'center',
                    marginTop: 12,
                  }}
                >
                  <button
                    type="button"
                    onClick={onNavigateBack}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: 8,
                      padding: '10px 22px',
                      border: `1.5px solid ${STITCH_COLORS.pink}`,
                      borderRadius: STITCH_RADIUS.pill,
                      backgroundColor: STITCH_COLORS.surfaceWhite,
                      color: STITCH_COLORS.pink,
                      fontSize: '0.88rem',
                      fontWeight: 800,
                      cursor: 'pointer',
                      boxShadow: '0 2px 8px rgba(255,21,112,0.12)',
                      transition:
                        'transform 200ms ease, background-color 200ms ease, color 200ms ease, box-shadow 200ms ease',
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.backgroundColor = STITCH_COLORS.pink;
                      e.currentTarget.style.color = STITCH_COLORS.surfaceWhite;
                      e.currentTarget.style.transform = 'translateY(-1px)';
                      e.currentTarget.style.boxShadow =
                        '0 10px 22px rgba(255,21,112,0.28)';
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.backgroundColor =
                        STITCH_COLORS.surfaceWhite;
                      e.currentTarget.style.color = STITCH_COLORS.pink;
                      e.currentTarget.style.transform = 'none';
                      e.currentTarget.style.boxShadow =
                        '0 2px 8px rgba(255,21,112,0.12)';
                    }}
                  >
                    <span aria-hidden="true">⬆</span> Upload another
                  </button>
                </div>
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
