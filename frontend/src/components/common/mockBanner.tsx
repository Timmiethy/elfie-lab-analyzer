/**
 * Global "mock mode" signal + banner.
 *
 * The API layer calls `markMocked()` any time it returns a mock response.
 * The banner subscribes and flashes a persistent red strip so nobody
 * confuses fixture data for real backend output.
 */

import { useEffect, useState } from 'react';
import { STITCH_COLORS } from './system';

type Listener = (active: boolean) => void;

let active = false;
let lastReason = '';
const listeners = new Set<Listener>();

export function markMocked(reason: string): void {
  active = true;
  lastReason = reason;
  listeners.forEach((l) => l(true));
}

export function clearMocked(): void {
  active = false;
  lastReason = '';
  listeners.forEach((l) => l(false));
}

export function isCurrentlyMocked(): boolean {
  return active;
}

export function subscribeMocked(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function MockDataBanner() {
  const [on, setOn] = useState(active);
  const [reason, setReason] = useState(lastReason);

  useEffect(() => {
    return subscribeMocked((v) => {
      setOn(v);
      setReason(lastReason);
    });
  }, []);

  if (!on) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        position: 'sticky',
        top: 62,
        zIndex: 999,
        margin: '0 auto',
        maxWidth: 1120,
        padding: '8px 14px',
        borderRadius: 10,
        backgroundColor: STITCH_COLORS.errorBg,
        color: STITCH_COLORS.errorText,
        fontSize: '0.82rem',
        fontWeight: 700,
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        boxShadow: '0 4px 12px rgba(153,27,27,0.18)',
        borderLeft: `4px solid ${STITCH_COLORS.errorText}`,
      }}
    >
      <span aria-hidden="true">⚠</span>
      <span>
        Showing mock / preview data — backend is unreachable or the response
        was served from local fixtures. {reason ? `(${reason})` : ''}
      </span>
    </div>
  );
}
