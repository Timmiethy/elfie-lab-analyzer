import { useState } from 'react';
import { Link } from 'react-router-dom';
import { supabase } from '../lib/supabase';
import {
  PageChrome,
  PrimaryButton,
  SecondaryButton,
  SurfaceCard,
} from '../components/common';
import { STITCH_COLORS, STITCH_RADIUS } from '../components/common/system';

const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: '0.9rem 1rem',
  borderRadius: STITCH_RADIUS.md,
  border: `1.5px solid ${STITCH_COLORS.borderGhost}`,
  fontSize: '1rem',
  fontFamily: 'inherit',
  color: STITCH_COLORS.textPrimary,
  backgroundColor: STITCH_COLORS.surfaceWhite,
  boxSizing: 'border-box',
  outline: 'none',
  transition: 'border-color 150ms ease',
};

const labelStyle: React.CSSProperties = {
  display: 'block',
  marginBottom: '0.5rem',
  fontSize: '0.82rem',
  fontWeight: 700,
  color: STITCH_COLORS.textSecondary,
  textTransform: 'uppercase',
  letterSpacing: '0.06em',
};

export default function SignupPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleEmailSignup = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    const { error: err } = await supabase.auth.signUp({
      email,
      password,
      options: { emailRedirectTo: `${window.location.origin}/dashboard` },
    });
    setLoading(false);
    if (err) {
      setError(err.message);
    } else {
      setSuccess(true);
    }
  };

  const handleGoogleSignup = async () => {
    const { error: err } = await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: { redirectTo: `${window.location.origin}/dashboard` },
    });
    if (err) {
      setError(err.message);
    }
  };

  if (success) {
    return (
      <PageChrome
        compact
        title="Check your email"
        subtitle="We sent a confirmation link to your inbox."
      >
        <SurfaceCard style={{ padding: '1.75rem 1.5rem', marginTop: '0.75rem' }}>
          <p
            style={{
              margin: 0,
              fontSize: '1rem',
              lineHeight: 1.65,
              color: STITCH_COLORS.textSecondary,
            }}
          >
            Click the link in the email we sent to <strong>{email}</strong> to
            activate your account, then return here to sign in.
          </p>
        </SurfaceCard>
        <p
          style={{
            textAlign: 'center',
            marginTop: '1.5rem',
            fontSize: '0.92rem',
            color: STITCH_COLORS.textSecondary,
          }}
        >
          Already confirmed?{' '}
          <Link
            to="/login"
            style={{ color: STITCH_COLORS.pink, fontWeight: 700 }}
          >
            Sign in
          </Link>
        </p>
      </PageChrome>
    );
  }

  return (
    <PageChrome
      compact
      title="Create your account"
      subtitle="Get started with Elfie Labs."
    >
      <SurfaceCard style={{ padding: '1.75rem 1.5rem', marginTop: '0.75rem' }}>
        {error && (
          <div
            role="alert"
            style={{
              marginBottom: '1.25rem',
              padding: '0.85rem 1rem',
              borderRadius: STITCH_RADIUS.sm,
              backgroundColor: STITCH_COLORS.errorBg,
              color: STITCH_COLORS.errorText,
              fontSize: '0.9rem',
              lineHeight: 1.5,
            }}
          >
            {error}
          </div>
        )}

        <form onSubmit={handleEmailSignup}>
          <div style={{ marginBottom: '1.1rem' }}>
            <label htmlFor="email" style={labelStyle}>
              Email
            </label>
            <input
              id="email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              style={inputStyle}
              placeholder="you@example.com"
            />
          </div>

          <div style={{ marginBottom: '1.5rem' }}>
            <label htmlFor="password" style={labelStyle}>
              Password
            </label>
            <input
              id="password"
              type="password"
              required
              minLength={6}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              style={inputStyle}
              placeholder="At least 6 characters"
            />
          </div>

          <PrimaryButton type="submit" disabled={loading}>
            {loading ? 'Creating account...' : 'Create account'}
          </PrimaryButton>
        </form>

        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.85rem',
            margin: '1.5rem 0',
          }}
        >
          <div
            style={{
              flex: 1,
              height: 1,
              backgroundColor: STITCH_COLORS.borderGhost,
            }}
          />
          <span
            style={{
              fontSize: '0.78rem',
              color: STITCH_COLORS.textMuted,
              fontWeight: 600,
            }}
          >
            OR
          </span>
          <div
            style={{
              flex: 1,
              height: 1,
              backgroundColor: STITCH_COLORS.borderGhost,
            }}
          />
        </div>

        <SecondaryButton onClick={handleGoogleSignup}>
          Sign up with Google
        </SecondaryButton>
      </SurfaceCard>

      <p
        style={{
          textAlign: 'center',
          marginTop: '1.5rem',
          fontSize: '0.92rem',
          color: STITCH_COLORS.textSecondary,
        }}
      >
        Already have an account?{' '}
        <Link
          to="/login"
          style={{ color: STITCH_COLORS.pink, fontWeight: 700 }}
        >
          Sign in
        </Link>
      </p>
    </PageChrome>
  );
}
