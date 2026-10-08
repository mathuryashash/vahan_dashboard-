// frontend/src/components/Header.tsx
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { triggerRefresh, getDataQuality, getSourceHealth } from '../api/vahan';
import { useEffect, useState } from 'react';
import { ThemeToggle } from './ThemeToggle';
import type { RefreshStatus, ScrapeProgress } from '../types';
import type { AuthUser } from '../api/auth';
import { Menu } from './Icons';
import { useAppStore } from '../hooks/useAppStore';

const INTEGRITY_COLOR: Record<'green' | 'amber' | 'red', string> = {
  green: 'var(--success)',
  amber: 'var(--accent)',
  red: 'var(--danger)',
};
// 'red' used to mean "FADA has no data" -- a second source this deployment
// no longer scrapes or displays, so the backend stopped emitting that level
// and the label would have been meaningless to a reader. The API still types
// red as possible, so it keeps an entry, reworded to say something true if
// it ever appears again.
const INTEGRITY_LABEL: Record<'green' | 'amber' | 'red', string> = {
  green: 'Data integrity: clean',
  amber: 'Data integrity: check needed',
  red: 'Data integrity: quality check failing',
};

function DataIntegrityBadge() {
  const { data } = useQuery({
    queryKey: ['dataQuality'],
    queryFn: getDataQuality,
    refetchInterval: 5 * 60 * 1000,
  });
  if (!data) return null;
  const pct = data.quality_check.pct_clean;
  const tooltip = [
    INTEGRITY_LABEL[data.level],
    pct !== null ? `${pct}% of ${data.quality_check.cells_checked} RTO/month cells verified clean` : 'No quality check run yet',
    data.scrape_fresh ? 'Last scrape <24h old' : 'Last scrape >24h old',
  ].join(' — ');
  return (
    <div className="flex items-center gap-1.5" title={tooltip}>
      <div className="w-2 h-2 rounded-full" style={{ background: INTEGRITY_COLOR[data.level] }} />
      <span className="text-[10px] text-[var(--text-muted)] font-mono uppercase tracking-widest hidden lg:inline">
        {data.level}
      </span>
    </div>
  );
}

const SOURCE_LABEL: Record<string, string> = {
  old_site: 'VAHAN dashboard',
  new_site: 'VAHAN analytics site',
};

// Admin-only: are the scrapers' sources still usable? (backend
// app/services/source_health.py). Silent while both are fine. The old
// dashboard is past its announced shutdown date, so its "down" pill is the
// alert that matters -- every maker/class/fuel scrape depends on it.
function SourceHealthAlert() {
  const { data } = useQuery({
    queryKey: ['sourceHealth'],
    queryFn: getSourceHealth,
    refetchInterval: 5 * 60 * 1000,
  });
  if (!data) return null;
  // A single failed probe is not an outage: newer backends re-check before
  // declaring a source down and report `consecutive_failures`. With exactly
  // one failure the pill says "check failed, retrying" in amber instead of a
  // red "down" that a transient blip used to raise. Older backends omit the
  // field and keep the original behaviour.
  const flagged = Object.entries(data).filter(([, s]) => !s.ok || (s.consecutive_failures ?? 0) >= 1);
  if (!flagged.length) return null;
  return (
    <>
      {flagged.map(([name, s]) => {
        const retrying = s.consecutive_failures === 1;
        const label = SOURCE_LABEL[name] ?? name;
        const tooltip = retrying
          ? `${label}: check failed, retrying — one probe failed (${s.detail}); it is re-checked before being reported down.`
          : `${s.detail}${s.down_since ? ` — down since ${new Date(s.down_since).toLocaleString('en-IN')}` : ''}${s.consecutive_failures ? ` (${s.consecutive_failures} checks failed in a row)` : ''}. Scrapes that depend on it will fail.`;
        const color = retrying ? 'var(--warning, #d97706)' : 'var(--danger)';
        return (
          <div
            key={name}
            role={retrying ? 'status' : 'alert'}
            className="flex items-center gap-1.5 text-[10px] font-mono uppercase tracking-widest font-bold"
            style={{ color }}
            title={tooltip}
            aria-label={tooltip}
            data-testid={`source-health-${name}`}
          >
            <div className="w-2 h-2 rounded-full animate-pulse-soft" style={{ background: color }} />
            {label} {retrying ? 'check failed, retrying' : 'down'}
          </div>
        );
      })}
      <div className="w-px h-5 bg-[var(--border)]" />
    </>
  );
}

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
  const mobileNavOpen = useAppStore((s) => s.mobileNavOpen);
  const setMobileNavOpen = useAppStore((s) => s.setMobileNavOpen);

  const status = refreshStatus?.status ?? 'idle';
  const lastUpdated = refreshStatus?.last_updated ?? null;
  const isRunning = starting || status === 'running';

  useEffect(() => {
    if (!refreshStatus || refreshStatus.status === 'running') {
      return;
    }
    // Not a prop-sync -- this effect's real job is the external side effect
    // (invalidateQueries) once a poll confirms the scrape finished;
    // resetting `starting` is bundled into the same state update rather
    // than a second effect run.
    // eslint-disable-next-line react-hooks/set-state-in-effect
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
    <header className="h-14 border-b border-[var(--border)] bg-[var(--bg-surface)] flex items-center justify-between gap-2 px-3 md:px-6 shrink-0">
      <div className="flex items-center gap-3 min-w-0">
        <button
          type="button"
          className="md:hidden p-1.5 -ml-1 rounded-lg text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-card-hover)]"
          aria-label="Open navigation"
          aria-controls="app-sidebar"
          aria-expanded={mobileNavOpen}
          onClick={() => setMobileNavOpen(true)}
        >
          <Menu className="w-5 h-5" />
        </button>
        <img src="/company-logo.png" alt="Grydence" className="w-8 h-8 rounded-lg object-cover hidden sm:block" />
        <div className="hidden sm:block">
          <h1 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">GRYDENCE</h1>
          <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest">Market Intelligence &amp; MIS</p>
        </div>
      </div>

      <div className="flex items-center gap-2 md:gap-3 min-w-0 overflow-x-auto">
        {auth.role === 'admin' && <SourceHealthAlert />}
        <DataIntegrityBadge />
        <div className="w-px h-5 bg-[var(--border)]" />

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
              {/* Category scope is a separate axis from the geographic one
                  (an account can be both), so it appends rather than
                  replaces -- "analyst · All India · Four-Wheeler". */}
              {auth.role} · {SCOPE_LABEL[auth.scope_type](auth)}
              {auth.scope_vehicle_category ? ` · ${auth.scope_vehicle_category}` : ''}
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
