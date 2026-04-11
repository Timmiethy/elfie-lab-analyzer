import type { CSSProperties, ReactNode } from 'react';
import type { SeverityClass } from '../../types';
import {
  badgeStyle,
  CONTENT_COLUMN_STYLE,
  PAGE_SHELL_STYLE,
  STITCH_COLORS,
  STITCH_RADIUS,
  STITCH_SHADOWS,
  pageCardStyle,
  subtleCardStyle,
} from './system';

interface PageChromeProps {
  title: string;
  subtitle?: string;
  rightSlot?: ReactNode;
  children: ReactNode;
  compact?: boolean;
  contentMaxWidth?: number;
}

export function PageChrome({
  title,
  subtitle,
  rightSlot,
  children,
  compact = false,
  contentMaxWidth = 560,
}: PageChromeProps) {
  return (
    <div style={PAGE_SHELL_STYLE}>
      <div
        style={{
          position: 'relative',
          backgroundColor: STITCH_COLORS.navy,
          color: STITCH_COLORS.surfaceWhite,
          padding: compact ? '1rem 1rem 2rem' : '1rem 1rem 2.5rem',
          boxShadow: STITCH_SHADOWS.lift,
          overflow: 'hidden',
        }}
      >
        <div
          aria-hidden="true"
          style={{
            position: 'absolute',
            inset: 0,
            background:
              'radial-gradient(circle at 82% 18%, rgba(255,255,255,0.14) 0, rgba(255,255,255,0.02) 24%, transparent 26%)',
            pointerEvents: 'none',
          }}
        />
        <div
          style={{
            position: 'relative',
            zIndex: 1,
            maxWidth: contentMaxWidth,
            margin: '0 auto',
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'space-between',
            gap: '0.75rem',
          }}
        >
          <div style={{ minWidth: 0 }}>
            <p
              style={{
                fontSize: '1.02rem',
                fontWeight: 700,
                letterSpacing: '-0.02em',
                margin: 0,
                lineHeight: 1.15,
              }}
            >
              {title}
            </p>
            {subtitle && (
              <p
                style={{
                  fontSize: '0.78rem',
                  lineHeight: 1.45,
                  color: 'rgba(255,255,255,0.76)',
                  margin: '0.3rem 0 0',
                  maxWidth: 360,
                }}
              >
                {subtitle}
              </p>
            )}
          </div>
          {rightSlot ? <div style={{ flexShrink: 0 }}>{rightSlot}</div> : null}
        </div>
        <div
          aria-hidden="true"
          style={{
            position: 'absolute',
            left: 0,
            right: 0,
            bottom: -26,
            height: 52,
            backgroundColor: STITCH_COLORS.navy,
            clipPath: 'ellipse(140% 100% at 50% 0%)',
          }}
        />
      </div>
      <div style={{ ...CONTENT_COLUMN_STYLE, maxWidth: contentMaxWidth, marginTop: compact ? '-0.25rem' : '0.4rem' }}>
        {children}
      </div>
    </div>
  );
}

interface SurfaceCardProps {
  children: ReactNode;
  style?: CSSProperties;
}

export function SurfaceCard({ children, style }: SurfaceCardProps) {
  return <section style={pageCardStyle(style)}>{children}</section>;
}

export function SubtleCard({ children, style }: SurfaceCardProps) {
  return <section style={subtleCardStyle(style)}>{children}</section>;
}

interface PillBadgeProps {
  tone: 'trusted' | 'beta' | 'neutral';
  children: ReactNode;
  style?: CSSProperties;
}

export function PillBadge({ tone, children, style }: PillBadgeProps) {
  return <span style={badgeStyle(tone, style)}>{children}</span>;
}

interface BoundaryCardProps {
  title: string;
  body: string;
  tone?: 'neutral' | 'warning' | 'error';
}

export function BoundaryCard({
  title,
  body,
  tone = 'neutral',
}: BoundaryCardProps) {
  const palette =
    tone === 'warning'
      ? {
          backgroundColor: STITCH_COLORS.warningBg,
          color: STITCH_COLORS.warningText,
        }
      : tone === 'error'
        ? {
            backgroundColor: STITCH_COLORS.errorBg,
            color: STITCH_COLORS.errorText,
          }
        : {
            backgroundColor: STITCH_COLORS.surfaceLow,
            color: STITCH_COLORS.textSecondary,
          };

  return (
    <div
      role="note"
      style={{
        ...subtleCardStyle({
          padding: '1rem 1.05rem',
          backgroundColor: palette.backgroundColor,
          marginTop: '0.9rem',
        }),
      }}
    >
      <p
        style={{
          margin: '0 0 0.3rem',
          fontSize: '0.74rem',
          fontWeight: 800,
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
          color: palette.color,
        }}
      >
        {title}
      </p>
      <p
        style={{
          margin: 0,
          fontSize: '0.9rem',
          lineHeight: 1.6,
          color: palette.color,
        }}
      >
        {body}
      </p>
    </div>
  );
}

interface ButtonProps {
  children: ReactNode;
  onClick?: () => void;
  type?: 'button' | 'submit';
  disabled?: boolean;
  style?: CSSProperties;
}

export function PrimaryButton({
  children,
  onClick,
  type = 'button',
  disabled = false,
  style,
}: ButtonProps) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      style={{
        width: '100%',
        minHeight: 54,
        borderRadius: STITCH_RADIUS.pill,
        border: 'none',
        fontSize: '0.96rem',
        fontWeight: 700,
        color: STITCH_COLORS.surfaceWhite,
        background: disabled
          ? 'linear-gradient(135deg, rgba(255, 21, 112, 0.34), rgba(255, 21, 112, 0.22))'
          : `linear-gradient(135deg, ${STITCH_COLORS.pink} 0%, ${STITCH_COLORS.pinkDark} 100%)`,
        boxShadow: disabled ? 'none' : STITCH_SHADOWS.hero,
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.85 : 1,
        transition: 'transform 120ms ease, opacity 120ms ease',
        ...style,
      }}
    >
      {children}
    </button>
  );
}

export function SecondaryButton({
  children,
  onClick,
  type = 'button',
  disabled = false,
  style,
}: ButtonProps) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      style={{
        width: '100%',
        minHeight: 50,
        borderRadius: STITCH_RADIUS.pill,
        border: `1px solid ${STITCH_COLORS.borderGhost}`,
        fontSize: '0.92rem',
        fontWeight: 700,
        color: STITCH_COLORS.navy,
        backgroundColor: STITCH_COLORS.surfaceWhite,
        cursor: disabled ? 'not-allowed' : 'pointer',
        ...style,
      }}
    >
      {children}
    </button>
  );
}

const SEVERITY_META: Record<
  SeverityClass,
  { label: string; color: string; bg: string; icon: string }
> = {
  S0: {
    label: 'No actionable finding',
    color: STITCH_COLORS.trustedText,
    bg: STITCH_COLORS.trustedBg,
    icon: '\u2713',
  },
  S1: {
    label: 'Review routinely',
    color: STITCH_COLORS.trustedText,
    bg: STITCH_COLORS.trustedBg,
    icon: '\u2139',
  },
  S2: {
    label: 'Discuss at next planned visit',
    color: '#B45309',
    bg: '#FFF0D8',
    icon: '\u26A0',
  },
  S3: {
    label: 'Contact clinician soon',
    color: '#B45309',
    bg: '#FFF0D8',
    icon: '\u26A1',
  },
  S4: {
    label: 'Urgent follow-up recommended',
    color: STITCH_COLORS.errorText,
    bg: STITCH_COLORS.errorBg,
    icon: '\u{1F6A8}',
  },
  SX: {
    label: 'Cannot assess severity',
    color: STITCH_COLORS.textSecondary,
    bg: STITCH_COLORS.surfaceHigh,
    icon: '\u2753',
  },
};

export function SeverityChip({ severity }: { severity: SeverityClass }) {
  const meta = SEVERITY_META[severity];
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '5px 10px',
        borderRadius: STITCH_RADIUS.pill,
        backgroundColor: meta.bg,
        color: meta.color,
        fontSize: '0.76rem',
        fontWeight: 700,
      }}
    >
      <span aria-hidden="true">{meta.icon}</span>
      <span>{meta.label}</span>
    </span>
  );
}
