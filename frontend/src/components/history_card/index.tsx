import { SurfaceCard } from '../common';
import { STITCH_COLORS, STITCH_RADIUS } from '../common/system';

export interface HistoryObservation {
  analyte_display: string;
  current_value: string;
  current_unit: string;
  previous_value: string | null;
  previous_unit: string | null;
  previous_date: string | null;
  direction: 'increased' | 'decreased' | 'similar' | 'trend_unavailable';
  comparability_status: 'comparable' | 'not_comparable';
  comparability_reason: string | null;
}

interface Props {
  observations: HistoryObservation[];
}

const DIRECTION_META: Record<
  HistoryObservation['direction'],
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

export default function HistoryCard({ observations }: Props) {
  return (
    <SurfaceCard style={{ padding: '0.88rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.6rem', marginBottom: '0.65rem' }}>
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

      {observations.length === 0 ? (
        <p style={{ margin: 0, fontSize: '0.86rem', lineHeight: 1.5, color: STITCH_COLORS.textSecondary }}>
          No valid prior comparable observations are available.
        </p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.55rem' }}>
          {observations.map((observation, index) => {
            const meta = DIRECTION_META[observation.direction];
            const notComparable =
              observation.comparability_status === 'not_comparable';

            return (
              <div
                key={`${observation.analyte_display}-${index}`}
                style={{
                  borderRadius: STITCH_RADIUS.md,
                  backgroundColor: notComparable
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
                      {observation.analyte_display}
                    </p>
                    <p
                      style={{
                        margin: '0.28rem 0 0',
                        fontSize: '0.84rem',
                        lineHeight: 1.45,
                        color: STITCH_COLORS.textSecondary,
                      }}
                    >
                      {observation.current_value} {observation.current_unit}
                    </p>
                    <p
                      style={{
                        margin: '0.14rem 0 0',
                        fontSize: '0.78rem',
                        lineHeight: 1.45,
                        color: STITCH_COLORS.textSecondary,
                      }}
                    >
                      {observation.previous_value && observation.previous_date
                        ? `Prev ${observation.previous_date}: ${observation.previous_value} ${observation.previous_unit ?? ''}`.trim()
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
                      backgroundColor: meta.bg,
                      color: meta.color,
                      fontSize: '0.7rem',
                      fontWeight: 700,
                      whiteSpace: 'nowrap',
                    }}
                  >
                    <span aria-hidden="true">{meta.icon}</span>
                    {meta.label}
                  </span>
                </div>
                {notComparable && observation.comparability_reason && (
                  <p
                    style={{
                      margin: '0.45rem 0 0',
                      fontSize: '0.78rem',
                      lineHeight: 1.45,
                      color: '#9A3412',
                    }}
                  >
                    {observation.comparability_reason}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </SurfaceCard>
  );
}
