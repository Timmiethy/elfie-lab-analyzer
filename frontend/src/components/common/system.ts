import type { CSSProperties } from 'react';

export const STITCH_FONT_STACK =
  "'Be Vietnam Pro', 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif";

export const STITCH_COLORS = {
  navy: '#121A33',
  navyMuted: '#3E4661',
  pink: '#FF1570',
  pinkDark: '#E61168',
  blue: '#1D4ED8',
  blueSoft: '#D4DBFD',
  surfacePage: '#F8F9FE',
  surfaceWarm: '#FFF6F8',
  surfaceWhite: '#FFFFFF',
  surfaceLow: '#F2F3F8',
  surfaceHigh: '#E7E8ED',
  textHeading: '#191C1F',
  textPrimary: '#252833',
  textSecondary: '#58607D',
  textMuted: '#76767E',
  borderGhost: 'rgba(198, 198, 206, 0.45)',
  shadowTint: 'rgba(18, 26, 51, 0.08)',
  trustedBg: '#DCFCE7',
  trustedText: '#15803D',
  betaBg: '#FEF3C7',
  betaText: '#B45309',
  errorBg: '#FEE2E2',
  errorText: '#991B1B',
  warningBg: '#FFF4E5',
  warningText: '#9A3412',
  neutralBg: '#EEF2FF',
  neutralText: '#3730A3',
};

export const STITCH_RADIUS = {
  sm: 12,
  md: 18,
  lg: 24,
  xl: 30,
  pill: 999,
};

export const STITCH_SHADOWS = {
  card: `0 20px 40px ${STITCH_COLORS.shadowTint}`,
  lift: `0 12px 28px ${STITCH_COLORS.shadowTint}`,
  hero: '0 16px 36px rgba(255, 21, 112, 0.18)',
  dock: '0 10px 30px rgba(0, 0, 0, 0.28)',
};

export const PAGE_SHELL_STYLE: CSSProperties = {
  minHeight: '100svh',
  background: `linear-gradient(180deg, ${STITCH_COLORS.surfacePage} 0%, ${STITCH_COLORS.surfaceWarm} 100%)`,
  color: STITCH_COLORS.textPrimary,
  fontFamily: STITCH_FONT_STACK,
};

export const CONTENT_COLUMN_STYLE: CSSProperties = {
  width: '100%',
  maxWidth: 560,
  margin: '0 auto',
  padding: '0 1rem 2.75rem',
  boxSizing: 'border-box',
};

export function pageCardStyle(
  overrides: CSSProperties = {},
): CSSProperties {
  return {
    backgroundColor: STITCH_COLORS.surfaceWhite,
    borderRadius: STITCH_RADIUS.lg,
    boxShadow: STITCH_SHADOWS.card,
    border: 'none',
    ...overrides,
  };
}

export function subtleCardStyle(
  overrides: CSSProperties = {},
): CSSProperties {
  return {
    ...pageCardStyle(),
    backgroundColor: STITCH_COLORS.surfaceLow,
    boxShadow: 'none',
    ...overrides,
  };
}

export function badgeStyle(
  tone: 'trusted' | 'beta' | 'neutral',
  overrides: CSSProperties = {},
): CSSProperties {
  const toneMap = {
    trusted: {
      backgroundColor: STITCH_COLORS.trustedBg,
      color: STITCH_COLORS.trustedText,
    },
    beta: {
      backgroundColor: STITCH_COLORS.betaBg,
      color: STITCH_COLORS.betaText,
    },
    neutral: {
      backgroundColor: STITCH_COLORS.blueSoft,
      color: STITCH_COLORS.navy,
    },
  };

  return {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    padding: '4px 10px',
    borderRadius: STITCH_RADIUS.pill,
    fontSize: '0.7rem',
    fontWeight: 700,
    letterSpacing: '0.02em',
    textTransform: 'uppercase',
    ...toneMap[tone],
    ...overrides,
  };
}
