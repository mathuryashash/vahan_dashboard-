import { useState } from 'react';
import axios from 'axios';
import { login } from '../api/auth';
import type { AuthUser } from '../api/auth';

interface LoginPageProps {
  onLogin: (auth: AuthUser) => void;
}

export function LoginPage({ onLogin }: LoginPageProps) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const auth = await login(email, password);
      onLogin(auth);
    } catch (err) {
      // 429 = the backend's 5-failures-in-5-min lockout; show its "try again
      // in N minute(s)" text instead of claiming the password is wrong.
      const res = axios.isAxiosError(err) ? err.response : undefined;
      if (res?.status === 429) {
        setError(typeof res.data?.detail === 'string' ? res.data.detail : 'Too many failed attempts. Try again in a few minutes.');
      } else if (!res) {
        setError('Could not reach the server. Check your connection and try again.');
      } else {
        setError('Incorrect email or password.');
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="h-screen flex items-center justify-center bg-[var(--bg-app)]">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm bg-[var(--bg-surface)] border border-[var(--border)] rounded-xl p-8 shadow-sm"
      >
        <div className="flex items-center gap-3 mb-6">
          <img src="/company-logo.png" alt="Grydence" className="w-8 h-8 rounded-lg object-cover" />
          <div>
            <h1 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">GRYDENCE</h1>
            <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest">Sign in</p>
          </div>
        </div>

        <label htmlFor="login-email" className="block text-xs font-semibold text-[var(--text-secondary)] mb-1">Email</label>
        <input
          id="login-email"
          type="email"
          required
          autoFocus
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="w-full mb-4 px-3 py-2 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)]"
        />

        <label htmlFor="login-password" className="block text-xs font-semibold text-[var(--text-secondary)] mb-1">Password</label>
        <input
          id="login-password"
          type="password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full mb-4 px-3 py-2 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)]"
        />

        {error && <p className="text-xs text-red-500 mb-4">{error}</p>}

        <button
          type="submit"
          disabled={submitting}
          className="w-full py-2 bg-[var(--accent)] text-white text-sm font-semibold rounded-lg disabled:opacity-50"
        >
          {submitting ? 'Signing in...' : 'Sign in'}
        </button>
      </form>
    </div>
  );
}
