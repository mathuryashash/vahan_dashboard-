// frontend/src/components/Header.tsx
import { useQueryClient } from '@tanstack/react-query';
import { triggerRefresh } from '../api/vahan';
import { useEffect, useState } from 'react';
import { ThemeToggle } from './ThemeToggle';
import type { RefreshStatus, ScrapeProgress } from '../types';
import type { AuthUser } from '../api/auth';

interface HeaderProps {
  refreshStatus: RefreshStatus | null;
  /** Timestamp of the last successful refreshStatus fetch (from react-query's
   * dataUpdatedAt). Used instead of `refreshStatus` itself as the effect
   * dependency below: react-query's structural sharing returns the *same*
   * object reference when consecutive polls return identical data (e.g. two
   * back-to-back "error" results), so a poll that changes nothing would never
   * be observed by an effect keyed on the data reference or its status value. */
  statusUpdatedAt: number;
  scrapeProgress: ScrapeProgress | null;
  auth: AuthUser;
  onLogout: () => void;
}

const SCOPE_LABEL: Record<AuthUser['scope_type'], (auth: AuthUser) => string> = {
  national: () => 'All India',
  state: (auth) => auth.scope_state_name ?? 'State-scoped',
  rto: (auth) => `${auth.scope_rto_name ?? 'RTO'} (${auth.scope_state_name ?? ''})`,
};

export function Header({ refreshStatus, statusUpdatedAt, scrapeProgress, auth, onLogout }: HeaderProps) {
  const queryClient = useQueryClient();
  const [starting, setStarting] = useState(false);

  const status = refreshStatus?.status ?? 'idle';
  const lastUpdated = refreshStatus?.last_updated ?? null;
  const isRunning = starting || status === 'running';

  useEffect(() => {
    if (!refreshStatus || refreshStatus.status === 'running') {
      return;
    }
    setStarting((wasStarting) => {
      if (wasStarting) {
        queryClient.invalidateQueries();
      }
      return false;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on statusUpdatedAt, see HeaderProps.statusUpdatedAt doc
  }, [statusUpdatedAt, queryClient]);

  const handleRefresh = async () => {
    if (isRunning) return;
    setStarting(true);
    try {
      await triggerRefresh();
    } finally {
      queryClient.invalidateQueries({ queryKey: ['refreshStatus'] });
    }
  };

  return (
    <header className="h-14 border-b border-[var(--border)] bg-[var(--bg-surface)] flex items-center justify-between px-6 shrink-0">
      <div className="flex items-center gap-3">
        <img src="/company-logo.png" alt="Logo" className="w-8 h-8 rounded-lg object-cover" />
        <div>
          <h1 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">VAHAN SEWA</h1>
          <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest">Vehicle Analytics Observatory</p>
        </div>
      </div>

      <div className="flex items-center gap-3">
        {scrapeProgress && scrapeProgress.states_done < scrapeProgress.states_total && (
          <div
            className="flex items-center gap-2"
            title={`${scrapeProgress.states_done}/${scrapeProgress.states_total} states replaced with live data (${scrapeProgress.rtos_done.toLocaleString('en-IN')} RTOs scraped so far)`}
          >
            <span className="text-[10px] text-[var(--text-muted)] font-mono uppercase tracking-widest whitespace-nowrap">
              Live Data Migration
            </span>
            <div className="w-28 h-1.5 bg-[var(--bg-sunken)] rounded-full overflow-hidden">
              <div
                className="h-full rounded-full bg-[var(--accent)] transition-all duration-700 ease-out"
                style={{ width: `${scrapeProgress.percent}%` }}
              />
            </div>
            <span className="text-[10px] font-mono font-semibold text-[var(--text-secondary)] w-10">
              {scrapeProgress.percent.toFixed(0)}%
            </span>
            <div className="w-px h-5 bg-[var(--border)]" />
          </div>
        )}

        {isRunning ? (
          <div className="flex items-center gap-1.5 text-[11px] text-[var(--text-muted)] font-mono">
            <div className="w-1.5 h-1.5 rounded-full bg-[var(--accent)] animate-pulse-soft" />
            <span>SYNCING — CAN TAKE UP TO AN HOUR</span>
          </div>
        ) : status === 'retrying' || status === 'error' ? (
          <div className="flex items-center gap-1.5 text-[11px] text-[var(--accent)] font-mono" title={refreshStatus?.error ?? 'The next scheduled refresh will retry automatically'}>
            <div className="w-1.5 h-1.5 rounded-full bg-[var(--accent)] animate-pulse-soft" />
            <span>SYNC RETRY PENDING</span>
          </div>
        ) : lastUpdated ? (
          <div className="flex items-center gap-1.5 text-[11px] text-[var(--text-muted)] font-mono">
            <div className="w-1.5 h-1.5 rounded-full bg-[var(--success)] animate-pulse-soft" />
            <span>SYNC {lastUpdated}</span>
          </div>
        ) : (
          <div className="flex items-center gap-1.5 text-[11px] text-[var(--text-muted)] font-mono">
            <div className="w-1.5 h-1.5 rounded-full bg-[var(--text-muted)]" />
            <span>NEVER SYNCED</span>
          </div>
        )}

        {auth.role === 'admin' && (
          <button
            onClick={handleRefresh}
            disabled={isRunning}
            title="Pulls fresh data from the live source. A full India refresh can take over an hour."
            className="px-3 py-1.5 bg-[var(--bg-card)] hover:bg-[var(--bg-card-hover)] border border-[var(--border)] text-[var(--text-secondary)] text-xs font-semibold rounded-lg transition-all duration-200 disabled:opacity-50"
          >
            {isRunning ? 'SYNCING...' : 'REFRESH'}
          </button>
        )}

        <div className="w-px h-5 bg-[var(--border)]" />

        <ThemeToggle />

        <div className="w-px h-5 bg-[var(--border)]" />

        <div className="flex items-center gap-2" title={`${auth.email} · ${auth.role}`}>
          <div className="text-right leading-tight">
            <div className="text-[11px] font-semibold text-[var(--text-primary)]">
              {auth.full_name ?? auth.email}
            </div>
            <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest">
              {auth.role} · {SCOPE_LABEL[auth.scope_type](auth)}
            </div>
          </div>
          <button
            onClick={onLogout}
            title="Log out"
            className="px-2 py-1 text-[11px] text-[var(--text-muted)] hover:text-[var(--text-primary)] border border-[var(--border)] rounded-lg"
          >
            Log out
          </button>
        </div>
      </div>
    </header>
  );
}
