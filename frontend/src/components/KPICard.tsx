// frontend/src/components/KPICard.tsx
interface KPICardProps {
  label: string;
  value: number | string;
  change?: number;
  icon?: React.ReactNode;
  loading?: boolean;
  index?: number;
}

export function KPICard({ label, value, change, icon, loading, index = 0 }: KPICardProps) {
  if (loading) {
    return (
      <div
        className="bg-[var(--bg-card)] rounded-2xl p-5 border border-[var(--border)] animate-entrance"
        style={{ animationDelay: `${index * 80}ms` }}
      >
        <div className="h-3 w-20 rounded bg-[var(--bg-sunken)] mb-4 animate-pulse-soft" />
        <div className="h-9 w-32 rounded bg-[var(--bg-sunken)] mb-3 animate-pulse-soft" />
        <div className="h-3 w-16 rounded bg-[var(--bg-sunken)] animate-pulse-soft" />
      </div>
    );
  }

  return (
    <div
      className="bg-[var(--bg-card)] rounded-2xl p-5 border border-[var(--border)] group animate-entrance transition-colors duration-200 hover:border-[var(--border-strong)]"
      style={{ animationDelay: `${index * 80}ms` }}
    >
      <div className="flex items-center justify-between mb-4">
        <span className="text-[11px] uppercase tracking-[0.15em] font-semibold text-[var(--text-muted)]">{label}</span>
        {icon && (
          <div className="w-9 h-9 rounded-xl flex items-center justify-center bg-[var(--bg-sunken)] text-[var(--accent)]">
            {icon}
          </div>
        )}
      </div>
      <div className="number-display text-3xl font-bold text-[var(--text-primary)] mb-2">
        {typeof value === 'number' ? value.toLocaleString('en-IN') : value}
      </div>
      {change !== undefined && (
        <div
          className="text-xs font-semibold px-2.5 py-1 rounded-lg inline-flex items-center gap-1 font-mono"
          style={{
            background: change >= 0 ? 'color-mix(in srgb, var(--success) 15%, transparent)' : 'color-mix(in srgb, var(--danger) 15%, transparent)',
            color: change >= 0 ? 'var(--success)' : 'var(--danger)',
          }}
        >
          <span className="text-[10px]">{change >= 0 ? '▲' : '▼'}</span>
          {Math.abs(change).toFixed(1)}%
        </div>
      )}
    </div>
  );
}
