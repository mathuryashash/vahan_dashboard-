// frontend/src/components/KPICard.tsx
import { SlowHint } from './LoadingBlock';

interface KPICardProps {
  label: string;
  value: number | string;
  /** Percent change badge. `null` = there is no prior period to compare
   * against: rendered as a muted "— no prior-year data" note instead of a
   * green "▲ 0.0%", which read as "flat" when the truth is "unknown". */
  change?: number | null;
  /** Override the text shown when `change` is null. */
  noChangeLabel?: string;
  icon?: React.ReactNode;
  loading?: boolean;
  index?: number;
  /** Small caption under the value. */
  sub?: string;
}

export function KPICard({ label, value, change, noChangeLabel = 'no prior-year data', icon, loading, index = 0, sub }: KPICardProps) {
  if (loading) {
    return (
      <div
        className="bg-[var(--bg-card)] rounded-2xl p-5 border border-[var(--border)] animate-entrance min-w-0"
        style={{ animationDelay: `${index * 80}ms` }}
        aria-busy="true"
      >
        <div className="h-3 w-20 rounded bg-[var(--bg-sunken)] mb-4 animate-pulse-soft" />
        <div className="h-9 w-32 max-w-full rounded bg-[var(--bg-sunken)] mb-3 animate-pulse-soft" />
        <div className="h-3 w-16 rounded bg-[var(--bg-sunken)] animate-pulse-soft" />
        <SlowHint />
      </div>
    );
  }

  return (
    <div
      className="bg-[var(--bg-card)] rounded-2xl p-5 border border-[var(--border)] group animate-entrance transition-colors duration-200 hover:border-[var(--border-strong)] min-w-0"
      style={{ animationDelay: `${index * 80}ms` }}
    >
      <div className="flex items-center justify-between gap-2 mb-4">
        <span className="text-[11px] uppercase tracking-[0.15em] font-semibold text-[var(--text-muted)] min-w-0">{label}</span>
        {icon && (
          <div className="w-9 h-9 shrink-0 rounded-xl flex items-center justify-center bg-[var(--bg-sunken)] text-[var(--accent)]">
            {icon}
          </div>
        )}
      </div>
      {/* Smaller on narrow screens and allowed to wrap: at 390 px an Indian
          crore figure ("2,26,77,982") used to clip to "2,26,77…". */}
      <div className="number-display text-2xl sm:text-3xl font-bold text-[var(--text-primary)] mb-2 break-words">
        {typeof value === 'number' ? value.toLocaleString('en-IN') : value}
      </div>
      {sub && <p className="text-[10px] text-[var(--text-muted)] font-mono mb-1">{sub}</p>}
      {change === null ? (
        <span className="text-[11px] text-[var(--text-muted)] font-mono">— {noChangeLabel}</span>
      ) : change !== undefined ? (
        <div
          className="text-xs font-semibold px-2.5 py-1 rounded-lg inline-flex items-center gap-1 font-mono"
          style={{
            background: change >= 0 ? 'color-mix(in srgb, var(--success) 15%, transparent)' : 'color-mix(in srgb, var(--danger) 15%, transparent)',
            color: change >= 0 ? 'var(--success)' : 'var(--danger)',
          }}
        >
          <span className="text-[10px]" aria-hidden="true">{change >= 0 ? '▲' : '▼'}</span>
          <span className="sr-only">{change >= 0 ? 'up' : 'down'}</span>
          {Math.abs(change).toFixed(1)}% YoY
        </div>
      ) : null}
    </div>
  );
}
