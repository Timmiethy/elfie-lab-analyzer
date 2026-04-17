import { Routes, Route, Navigate } from 'react-router-dom';
import LoginPage from './pages/LoginPage';
import SignupPage from './pages/SignupPage';
import App from './App';
import { ProtectedRoute } from './components/auth/ProtectedRoute';
import { useAuth } from './contexts/AuthContext';

function PublicRoute({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (user) return <Navigate to="/dashboard" replace />;
  return <>{children}</>;
}

function LogoutButton() {
  const { signOut, user } = useAuth();
  if (!user) return null;
  return (
    <button
      onClick={signOut}
      style={{
        position: 'fixed',
        top: 16,
        right: 20,
        zIndex: 1000,
        padding: '8px 18px',
        borderRadius: 999,
        border: '1px solid rgba(255,255,255,0.25)',
        backgroundColor: 'rgba(18, 26, 51, 0.6)',
        color: '#fff',
        fontSize: '0.78rem',
        fontWeight: 700,
        cursor: 'pointer',
        backdropFilter: 'blur(8px)',
        letterSpacing: '0.03em',
        minHeight: 36,
      }}
    >
      Sign out
    </button>
  );
}

export default function AppRouter() {
  return (
    <Routes>
      <Route
        path="/login"
        element={
          <PublicRoute>
            <LoginPage />
          </PublicRoute>
        }
      />
      <Route
        path="/signup"
        element={
          <PublicRoute>
            <SignupPage />
          </PublicRoute>
        }
      />
      <Route
        path="/dashboard"
        element={
          <ProtectedRoute>
            <LogoutButton />
            <App />
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}
