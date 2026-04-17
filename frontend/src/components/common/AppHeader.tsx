import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
} from 'react';
import { useAuth } from '../../hooks/useAuth';
import { STITCH_COLORS, STITCH_RADIUS } from '../common/system';

export interface HeaderNavItem {
  id: string;
  label: string;
  description?: string;
  icon?: string;
  onSelect: () => void;
  disabled?: boolean;
  /** Reason shown on hover when disabled. */
  disabledReason?: string;
}

interface AppHeaderProps {
  navItems?: HeaderNavItem[];
  activeItemId?: string;
}

/**
 * Floating, always-visible app header.
 *
 * - Warm medical-care aesthetic (soft pink-cream, navy, pink accent).
 * - Sticky across scroll.
 * - Settings button opens a fully keyboard-navigable menu with the primary
 *   app tabs and sign-out.
 *
 * Interactivity on each nav row:
 *   - Hover lift + soft pink wash
 *   - Keyboard focus ring
 *   - ↑/↓ arrows to move, Home/End to jump, Enter/Space to activate, Esc closes
 *   - Disabled rows show a lock icon and a tooltip explaining why
 *   - Active tab shows a check mark + pink left bar
 *   - Trailing chevron slides on hover
 */
export default function AppHeader({ navItems = [], activeItemId }: AppHeaderProps) {
  const { signOut, user } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [pressedId, setPressedId] = useState<string | null>(null);
  const [triggerHovered, setTriggerHovered] = useState(false);
  const [triggerPressed, setTriggerPressed] = useState(false);

  const menuRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const itemRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const signOutRef = useRef<HTMLButtonElement | null>(null);

  // Ordered list of focusable row ids (skips disabled) used for arrow-nav.
  const focusableIds = useMemo(() => {
    const ids = navItems.filter((i) => !i.disabled).map((i) => i.id);
    ids.push('__signout__');
    return ids;
  }, [navItems]);

  const focusRow = useCallback((id: string) => {
    if (id === '__signout__') {
      signOutRef.current?.focus();
      return;
    }
    itemRefs.current[id]?.focus();
  }, []);

  // Close on outside click or Escape.
  useEffect(() => {
    if (!menuOpen) return;
    const onDocClick = (e: MouseEvent) => {
      const target = e.target as Node;
      if (menuRef.current?.contains(target)) return;
      if (triggerRef.current?.contains(target)) return;
      setMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setMenuOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener('mousedown', onDocClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDocClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [menuOpen]);

  // Auto-focus first focusable row on open.
  useEffect(() => {
    if (!menuOpen) return;
    const first = focusableIds[0];
    if (first) {
      // small delay so the element is mounted
      const id = window.setTimeout(() => focusRow(first), 0);
      return () => window.clearTimeout(id);
    }
  }, [menuOpen, focusableIds, focusRow]);

  const handleSignOut = async () => {
    setMenuOpen(false);
    await signOut();
  };

  const handleNavClick = (item: HeaderNavItem) => {
    if (item.disabled) return;
    setMenuOpen(false);
    item.onSelect();
  };

  const handleRowKeyDown = (
    e: ReactKeyboardEvent<HTMLButtonElement>,
    currentId: string,
  ) => {
    const index = focusableIds.indexOf(currentId);
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      const next = focusableIds[(index + 1) % focusableIds.length];
      focusRow(next);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      const prev =
        focusableIds[(index - 1 + focusableIds.length) % focusableIds.length];
      focusRow(prev);
    } else if (e.key === 'Home') {
      e.preventDefault();
      focusRow(focusableIds[0]);
    } else if (e.key === 'End') {
      e.preventDefault();
      focusRow(focusableIds[focusableIds.length - 1]);
    }
  };

  const triggerStyle: CSSProperties = {
    width: 42,
    height: 42,
    borderRadius: STITCH_RADIUS.pill,
    border: `1px solid ${menuOpen ? STITCH_COLORS.pink : STITCH_COLORS.borderGhost}`,
    backgroundColor: menuOpen
      ? 'rgba(255, 21, 112, 0.08)'
      : STITCH_COLORS.surfaceWhite,
    color: menuOpen ? STITCH_COLORS.pink : STITCH_COLORS.navy,
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: '1.1rem',
    boxShadow: triggerPressed
      ? '0 1px 3px rgba(18,26,51,0.12)'
      : triggerHovered || menuOpen
        ? '0 10px 24px rgba(255,21,112,0.26)'
        : '0 2px 6px rgba(18,26,51,0.06)',
    transform: triggerPressed
      ? 'scale(0.92)'
      : triggerHovered
        ? 'translateY(-2px) scale(1.04)'
        : 'none',
    transition:
      'transform 240ms cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 260ms ease, background-color 220ms ease, color 220ms ease, border-color 220ms ease',
    outline: 'none',
  };

  return (
    <header
      className="stitch-app-header"
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 1000,
        padding: '10px 16px',
        backdropFilter: 'blur(14px)',
        WebkitBackdropFilter: 'blur(14px)',
        backgroundColor: 'rgba(255, 246, 248, 0.86)',
        borderBottom: `1px solid ${STITCH_COLORS.borderGhost}`,
      }}
    >
      {/* inline keyframes + focus-ring fallback so this file is self-contained */}
      <style>{`
        @keyframes stitchHeaderMenuIn {
          from {
            opacity: 0;
            transform: translateY(-8px) scale(0.96);
          }
          to {
            opacity: 1;
            transform: translateY(0) scale(1);
          }
        }
        @keyframes stitchHeaderRowIn {
          from {
            opacity: 0;
            transform: translateX(-6px);
          }
          to {
            opacity: 1;
            transform: translateX(0);
          }
        }
        @keyframes stitchHeaderPulse {
          0%, 100% {
            box-shadow: 0 0 0 0 rgba(255, 21, 112, 0.45);
          }
          50% {
            box-shadow: 0 0 0 6px rgba(255, 21, 112, 0);
          }
        }
        @keyframes stitchHeaderShimmer {
          0% { transform: translateX(-120%) skewX(-18deg); }
          100% { transform: translateX(220%) skewX(-18deg); }
        }
        @keyframes stitchHeaderHeartbeat {
          0%, 100% { transform: scale(1); }
          20% { transform: scale(1.12); }
          40% { transform: scale(0.96); }
          60% { transform: scale(1.06); }
        }

        .stitch-header-row:focus-visible {
          outline: 2px solid ${STITCH_COLORS.pink};
          outline-offset: 2px;
        }

        .stitch-header-brand-heart {
          animation: stitchHeaderHeartbeat 2.6s ease-in-out infinite;
          transform-origin: center;
        }

        .stitch-header-gear {
          transition: transform 320ms cubic-bezier(0.34, 1.56, 0.64, 1);
          display: inline-block;
        }
        .stitch-header-trigger:hover .stitch-header-gear {
          transform: rotate(90deg);
        }
        .stitch-header-trigger[aria-expanded="true"] .stitch-header-gear {
          transform: rotate(180deg);
        }

        .stitch-header-chevron {
          transition:
            transform 220ms cubic-bezier(0.34, 1.56, 0.64, 1),
            opacity 220ms ease;
          opacity: 0.35;
        }
        .stitch-header-row:hover .stitch-header-chevron,
        .stitch-header-row:focus-visible .stitch-header-chevron {
          transform: translateX(5px);
          opacity: 1;
        }

        .stitch-header-icon {
          transition:
            transform 280ms cubic-bezier(0.34, 1.56, 0.64, 1),
            background-color 220ms ease,
            color 220ms ease,
            box-shadow 220ms ease;
        }
        .stitch-header-row:hover .stitch-header-icon {
          transform: scale(1.08) rotate(-4deg);
        }
        .stitch-header-row:hover .stitch-header-icon--active {
          transform: scale(1.08);
        }

        .stitch-header-current-pill {
          animation: stitchHeaderPulse 2s ease-out infinite;
        }

        .stitch-header-row-label {
          transition: transform 220ms ease;
        }
        .stitch-header-row:hover .stitch-header-row-label {
          transform: translateX(2px);
        }
      `}</style>

      <div
        style={{
          maxWidth: 1120,
          margin: '0 auto',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
        }}
      >
        {/* Brand mark */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            minWidth: 0,
          }}
        >
          <div
            aria-hidden="true"
            className="stitch-header-brand-heart"
            style={{
              width: 36,
              height: 36,
              borderRadius: 12,
              background: `linear-gradient(135deg, ${STITCH_COLORS.pink} 0%, #FF6FA1 100%)`,
              color: STITCH_COLORS.surfaceWhite,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '1.05rem',
              boxShadow: '0 6px 14px rgba(255, 21, 112, 0.22)',
            }}
          >
            ♥
          </div>
          <div style={{ minWidth: 0, lineHeight: 1.15 }}>
            <p
              style={{
                margin: 0,
                fontSize: '0.98rem',
                fontWeight: 800,
                color: STITCH_COLORS.navy,
                letterSpacing: '-0.01em',
              }}
            >
              Elfie Labs
            </p>
            <p
              style={{
                margin: 0,
                fontSize: '0.72rem',
                fontWeight: 600,
                color: STITCH_COLORS.textMuted,
              }}
            >
              Gentle clarity for your results
            </p>
          </div>
        </div>

        {/* Settings trigger */}
        <div style={{ position: 'relative' }}>
          <button
            ref={triggerRef}
            type="button"
            className="stitch-header-trigger"
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            aria-label={menuOpen ? 'Close menu' : 'Open menu'}
            onClick={() => setMenuOpen((prev) => !prev)}
            onMouseEnter={() => setTriggerHovered(true)}
            onMouseLeave={() => {
              setTriggerHovered(false);
              setTriggerPressed(false);
            }}
            onMouseDown={() => setTriggerPressed(true)}
            onMouseUp={() => setTriggerPressed(false)}
            onBlur={() => setTriggerPressed(false)}
            style={triggerStyle}
          >
            <span aria-hidden="true" className="stitch-header-gear">
              ⚙
            </span>
          </button>

          {menuOpen && (
            <div
              ref={menuRef}
              role="menu"
              aria-label="App menu"
              style={{
                position: 'absolute',
                top: 50,
                right: 0,
                width: 300,
                padding: 10,
                borderRadius: STITCH_RADIUS.lg,
                backgroundColor: STITCH_COLORS.surfaceWhite,
                border: `1px solid ${STITCH_COLORS.borderGhost}`,
                boxShadow: '0 24px 56px rgba(18, 26, 51, 0.22)',
                display: 'flex',
                flexDirection: 'column',
                gap: 2,
                transformOrigin: 'top right',
                animation:
                  'stitchHeaderMenuIn 220ms cubic-bezier(0.34, 1.56, 0.64, 1) both',
              }}
            >
              {user?.email && (
                <div
                  style={{
                    padding: '8px 12px 10px',
                    borderBottom: `1px solid ${STITCH_COLORS.borderGhost}`,
                    marginBottom: 6,
                  }}
                >
                  <p
                    style={{
                      margin: 0,
                      fontSize: '0.7rem',
                      fontWeight: 800,
                      letterSpacing: '0.08em',
                      textTransform: 'uppercase',
                      color: STITCH_COLORS.textMuted,
                    }}
                  >
                    Signed in
                  </p>
                  <p
                    style={{
                      margin: '2px 0 0',
                      fontSize: '0.86rem',
                      fontWeight: 700,
                      color: STITCH_COLORS.textHeading,
                      wordBreak: 'break-all',
                    }}
                  >
                    {user.email}
                  </p>
                </div>
              )}

              {navItems.length > 0 && (
                <>
                  <p
                    style={{
                      margin: '4px 12px 6px',
                      fontSize: '0.68rem',
                      fontWeight: 800,
                      letterSpacing: '0.08em',
                      textTransform: 'uppercase',
                      color: STITCH_COLORS.textMuted,
                    }}
                  >
                    Navigate
                  </p>
                  {navItems.map((item, rowIndex) => {
                    const active = item.id === activeItemId;
                    const hovered = hoveredId === item.id && !item.disabled;
                    const pressed = pressedId === item.id && !item.disabled;
                    const tooltip =
                      item.disabled && item.disabledReason
                        ? item.disabledReason
                        : item.disabled
                          ? 'Available after you upload a report.'
                          : undefined;

                    const rowBg = item.disabled
                      ? 'transparent'
                      : active
                        ? 'rgba(255, 21, 112, 0.12)'
                        : hovered
                          ? 'rgba(255, 21, 112, 0.06)'
                          : 'transparent';

                    return (
                      <button
                        key={item.id}
                        ref={(el) => {
                          itemRefs.current[item.id] = el;
                        }}
                        role="menuitem"
                        type="button"
                        disabled={item.disabled}
                        aria-current={active ? 'page' : undefined}
                        title={tooltip}
                        onClick={() => handleNavClick(item)}
                        onMouseEnter={() => setHoveredId(item.id)}
                        onMouseLeave={() => {
                          if (hoveredId === item.id) setHoveredId(null);
                          if (pressedId === item.id) setPressedId(null);
                        }}
                        onMouseDown={() => setPressedId(item.id)}
                        onMouseUp={() => setPressedId(null)}
                        onKeyDown={(e) => handleRowKeyDown(e, item.id)}
                        className="stitch-header-row"
                        style={{
                          position: 'relative',
                          display: 'flex',
                          alignItems: 'center',
                          gap: 10,
                          width: '100%',
                          padding: '10px 12px 10px 14px',
                          border: 'none',
                          borderRadius: STITCH_RADIUS.md,
                          backgroundColor: rowBg,
                          color: item.disabled
                            ? STITCH_COLORS.textMuted
                            : STITCH_COLORS.textHeading,
                          textAlign: 'left',
                          cursor: item.disabled ? 'not-allowed' : 'pointer',
                          opacity: item.disabled ? 0.55 : 1,
                          fontWeight: 600,
                          minHeight: 48,
                          overflow: 'hidden',
                          transform: pressed
                            ? 'scale(0.975)'
                            : hovered
                              ? 'translateX(4px) scale(1.015)'
                              : 'none',
                          transition:
                            'transform 220ms cubic-bezier(0.34, 1.56, 0.64, 1), background-color 220ms ease, opacity 220ms ease',
                          animation: `stitchHeaderRowIn 260ms cubic-bezier(0.22, 1, 0.36, 1) ${
                            40 + rowIndex * 35
                          }ms both`,
                          outline: 'none',
                        }}
                      >
                        {/* Left pink bar — visible only when active */}
                        <span
                          aria-hidden="true"
                          style={{
                            position: 'absolute',
                            left: 4,
                            top: 10,
                            bottom: 10,
                            width: 3,
                            borderRadius: 2,
                            backgroundColor: active
                              ? STITCH_COLORS.pink
                              : 'transparent',
                            transform: active ? 'scaleY(1)' : 'scaleY(0.2)',
                            transformOrigin: 'center',
                            transition:
                              'background-color 220ms ease, transform 240ms cubic-bezier(0.34, 1.56, 0.64, 1)',
                          }}
                        />

                        {/* Icon tile */}
                        <span
                          aria-hidden="true"
                          className={
                            active
                              ? 'stitch-header-icon stitch-header-icon--active'
                              : 'stitch-header-icon'
                          }
                          style={{
                            width: 30,
                            height: 30,
                            borderRadius: 10,
                            backgroundColor: active
                              ? STITCH_COLORS.pink
                              : hovered
                                ? 'rgba(255, 21, 112, 0.16)'
                                : STITCH_COLORS.surfaceLow,
                            color: active
                              ? STITCH_COLORS.surfaceWhite
                              : hovered
                                ? STITCH_COLORS.pink
                                : STITCH_COLORS.navy,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            fontSize: '0.95rem',
                            flexShrink: 0,
                            boxShadow: active
                              ? '0 6px 14px rgba(255, 21, 112, 0.28)'
                              : 'none',
                          }}
                        >
                          {item.disabled ? '🔒' : (item.icon ?? '•')}
                        </span>

                        {/* Text */}
                        <span
                          className="stitch-header-row-label"
                          style={{ minWidth: 0, flex: 1 }}
                        >
                          <span
                            style={{
                              display: 'flex',
                              alignItems: 'center',
                              gap: 6,
                              fontSize: '0.92rem',
                              fontWeight: 700,
                              color: active
                                ? STITCH_COLORS.pink
                                : STITCH_COLORS.textHeading,
                              transition: 'color 220ms ease',
                            }}
                          >
                            {item.label}
                            {active && (
                              <span
                                aria-label="current"
                                className="stitch-header-current-pill"
                                style={{
                                  fontSize: '0.7rem',
                                  padding: '1px 7px',
                                  borderRadius: 999,
                                  backgroundColor: STITCH_COLORS.pink,
                                  color: STITCH_COLORS.surfaceWhite,
                                  fontWeight: 800,
                                  letterSpacing: '0.04em',
                                }}
                              >
                                CURRENT
                              </span>
                            )}
                          </span>
                          {item.description && (
                            <span
                              style={{
                                display: 'block',
                                fontSize: '0.76rem',
                                color: STITCH_COLORS.textSecondary,
                                marginTop: 1,
                              }}
                            >
                              {item.description}
                            </span>
                          )}
                        </span>

                        {/* Trailing chevron */}
                        {!item.disabled && !active && (
                          <span
                            aria-hidden="true"
                            className="stitch-header-chevron"
                            style={{
                              fontSize: '0.95rem',
                              color: STITCH_COLORS.textMuted,
                              flexShrink: 0,
                            }}
                          >
                            ›
                          </span>
                        )}
                      </button>
                    );
                  })}
                  <div
                    style={{
                      height: 1,
                      backgroundColor: STITCH_COLORS.borderGhost,
                      margin: '8px 6px',
                    }}
                  />
                </>
              )}

              <button
                ref={signOutRef}
                role="menuitem"
                type="button"
                onClick={() => void handleSignOut()}
                onMouseEnter={() => setHoveredId('__signout__')}
                onMouseLeave={() => {
                  if (hoveredId === '__signout__') setHoveredId(null);
                  if (pressedId === '__signout__') setPressedId(null);
                }}
                onMouseDown={() => setPressedId('__signout__')}
                onMouseUp={() => setPressedId(null)}
                onKeyDown={(e) => handleRowKeyDown(e, '__signout__')}
                className="stitch-header-row"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  width: '100%',
                  padding: '10px 12px',
                  border: 'none',
                  borderRadius: STITCH_RADIUS.md,
                  backgroundColor:
                    hoveredId === '__signout__'
                      ? 'rgba(153, 27, 27, 0.10)'
                      : 'transparent',
                  color: STITCH_COLORS.errorText,
                  textAlign: 'left',
                  cursor: 'pointer',
                  fontWeight: 700,
                  minHeight: 44,
                  transform:
                    pressedId === '__signout__'
                      ? 'scale(0.975)'
                      : hoveredId === '__signout__'
                        ? 'translateX(4px) scale(1.015)'
                        : 'none',
                  transition:
                    'transform 220ms cubic-bezier(0.34, 1.56, 0.64, 1), background-color 220ms ease',
                  animation:
                    'stitchHeaderRowIn 260ms cubic-bezier(0.22, 1, 0.36, 1) 260ms both',
                  outline: 'none',
                }}
              >
                <span
                  aria-hidden="true"
                  className="stitch-header-icon"
                  style={{
                    width: 30,
                    height: 30,
                    borderRadius: 10,
                    backgroundColor: STITCH_COLORS.errorBg,
                    color: STITCH_COLORS.errorText,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: '0.95rem',
                    flexShrink: 0,
                  }}
                >
                  ⎋
                </span>
                <span className="stitch-header-row-label" style={{ fontSize: '0.92rem' }}>
                  Sign out
                </span>
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
