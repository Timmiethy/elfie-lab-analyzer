import type { ComparableHistory } from '../../types';
import { SurfaceCard } from '../common';
import { STITCH_COLORS, STITCH_RADIUS } from '../common/system';

interface Props {
  history: ComparableHistory | null;
}

const DIRECTION_META: Record<
  ComparableHistory['direction'],
  { label: string; icon: string; color: string; bg: string }
> = {
  increased: {
    label: 'Increased',
    icon: '↑',
    color: '#9A3412',
    bg: '#FFF4E5',
  },
  decreased: {
    label: 'Decreased',
    icon: '↓',
    color: '#15803D',
    bg: '#DCFCE7',
  },
  similar: {
    label: 'Similar',
    icon: '↔',
    color: STITCH_COLORS.textSecondary,
    bg: STITCH_COLORS.surfaceLow,
  },
  trend_unavailable: {
    label: 'Trend unavailable',
    icon: '—',
    color: STITCH_COLORS.textMuted,
    bg: STITCH_COLORS.surfaceLow,
  },
};

const COMPARABILITY_META: Record<
  ComparableHistory['comparability_status'],
  { label: string; color: string; bg: string }
> = {
  available: {
    label: 'Available',
    color: STITCH_COLORS.trustedText,
    bg: STITCH_COLORS.trustedBg,
  },
  unavailable: {
    label: 'Unavailable',
    color: STITCH_COLORS.warningText,
    bg: STITCH_COLORS.warningBg,
  },
};

export default function HistoryCard({ history }: Props) {
  return (
    <SurfaceCard style={{ padding: '0.88rem' }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          gap: '0.6rem',
          marginBottom: '0.65rem',
        }}
      >
        <div>
          <p
            style={{
              margin: '0 0 0.18rem',
              fontSize: '0.72rem',
              fontWeight: 800,
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              color: STITCH_COLORS.textMuted,
            }}
          >
            Comparable history
          </p>
          <p
            style={{
              margin: 0,
              fontSize: '0.84rem',
              lineHeight: 1.4,
              color: STITCH_COLORS.textSecondary,
            }}
          >
            Neutral only.
          </p>
        </div>
      </div>

      {!history ? (
        <p
          style={{
            margin: 0,
            fontSize: '0.86rem',
            lineHeight: 1.5,
            color: STITCH_COLORS.textSecondary,
          }}
        >
          No valid prior comparable observations are available.
        </p>
      ) : (
        <div
          style={{
            borderRadius: STITCH_RADIUS.md,
            backgroundColor:
              history.comparability_status === 'unavailable'
                ? '#FFF9ED'
                : STITCH_COLORS.surfacePage,
            padding: '0.78rem',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              justifyContent: 'space-between',
              gap: '0.65rem',
            }}
          >
            <div style={{ minWidth: 0 }}>
              <p
                style={{
                  margin: 0,
                  fontSize: '0.9rem',
                  fontWeight: 700,
                  color: STITCH_COLORS.textHeading,
                }}
              >
                {history.analyte_display}
              </p>
              <p
                style={{
                  margin: '0.22rem 0 0',
                  fontSize: '0.84rem',
                  lineHeight: 1.45,
                  color: STITCH_COLORS.textSecondary,
                }}
              >
                {history.current_date ? `Current ${history.current_date}` : 'Current result'}:{' '}
                {history.current_value}{' '}
                {history.current_unit}
              </p>
              <p
                style={{
                  margin: '0.14rem 0 0',
                  fontSize: '0.78rem',
                  lineHeight: 1.45,
                  color: STITCH_COLORS.textSecondary,
                }}
              >
                {history.previous_value && history.previous_date
                  ? `Prev ${history.previous_date}: ${history.previous_value} ${
                      history.previous_unit ?? ''
                    }`.trim()
                  : 'No prior value'}
              </p>
            </div>
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
                padding: '4px 8px',
                borderRadius: STITCH_RADIUS.pill,
                backgroundColor:
                  COMPARABILITY_META[history.comparability_status].bg,
                color: COMPARABILITY_META[history.comparability_status].color,
                fontSize: '0.7rem',
                fontWeight: 700,
                whiteSpace: 'nowrap',
              }}
            >
              {COMPARABILITY_META[history.comparability_status].label}
            </span>
          </div>

          <div style={{ marginTop: '0.6rem', display: 'flex', flexWrap: 'wrap', gap: '0.45rem' }}>
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
                padding: '4px 8px',
                borderRadius: STITCH_RADIUS.pill,
                backgroundColor: DIRECTION_META[history.direction].bg,
                color: DIRECTION_META[history.direction].color,
                fontSize: '0.7rem',
                fontWeight: 700,
                whiteSpace: 'nowrap',
              }}
            >
              <span aria-hidden="true">{DIRECTION_META[history.direction].icon}</span>
              {DIRECTION_META[history.direction].label}
            </span>
          </div>
        </div>
      )}
    </SurfaceCard>
  );
}
