import { useEffect, useState } from 'react';

/** True once `ms` have passed since mount. Callers mount the component that
 * uses it only while loading, so the timer naturally restarts per load. */
export function useElapsed(ms: number): boolean {
  const [elapsed, setElapsed] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setElapsed(true), ms);
    return () => clearTimeout(t);
  }, [ms]);
  return elapsed;
}

/** Skeleton block that, after ~5 s, says out loud that the query is large and
 * still running. Without it an all-India cold year (15-30 s on /categories/)
 * looked identical to a hung page. */
export function LoadingBlock({
  className = 'h-52',
  slowMessage = 'All-India totals for a year not viewed recently can take up to 30 seconds.',
}: {
  className?: string;
  slowMessage?: string;
}) {
  const slow = useElapsed(5000);
  return (
    <div className={`relative rounded-xl ${className}`} role="status" aria-live="polite" aria-busy="true">
      <div className="absolute inset-0 rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft" />
      {slow ? (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-1 px-4 text-center" data-slow-hint="true">
          <span className="text-[11px] font-semibold text-[var(--text-secondary)]">Large query — still loading…</span>
          <span className="text-[10px] text-[var(--text-muted)] font-mono">{slowMessage}</span>
        </div>
      ) : (
        <span className="sr-only">Loading…</span>
      )}
    </div>
  );
}

/** Inline variant for places that can't host a block (KPI cards). */
export function SlowHint() {
  const slow = useElapsed(5000);
  if (!slow) return null;
  return (
    <p className="text-[10px] text-[var(--text-muted)] font-mono mt-2" role="status" aria-live="polite" data-slow-hint="true">
      Large query — still loading…
    </p>
  );
}
