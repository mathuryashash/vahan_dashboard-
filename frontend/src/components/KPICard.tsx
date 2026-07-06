import clsx from 'clsx';

interface KPICardProps {
  label: string;
  value: number | string;
  change?: number;
  icon?: React.ReactNode;
  loading?: boolean;
  accent?: 'blue' | 'cyan' | 'emerald' | 'amber';
  index?: number;
}

const accentMap = {
  blue: { border: 'rgba(59,130,246,0.3)', glow: 'rgba(59,130,246,0.15)', text: '#3B82F6' },
  cyan: { border: 'rgba(6,182,212,0.3)', glow: 'rgba(6,182,212,0.15)', text: '#06B6D4' },
  emerald: { border: 'rgba(16,185,129,0.3)', glow: 'rgba(16,185,129,0.15)', text: '#10B981' },
  amber: { border: 'rgba(245,158,11,0.3)', glow: 'rgba(245,158,11,0.15)', text: '#F59E0B' },
};

export function KPICard({ label, value, change, icon, loading, accent = 'blue', index = 0 }: KPICardProps) {
  const colors = accentMap[accent];

  if (loading) {
    return (
      <div
        className="bg-[#0D1829] rounded-2xl p-5 border border-[rgba(255,255,255,0.06)] animate-entrance"
        style={{ animationDelay: `${index * 80}ms` }}
      >
        <div className="h-3 w-20 rounded bg-slate-800 mb-4 animate-pulse" />
        <div className="h-9 w-32 rounded bg-slate-800 mb-3 animate-pulse" />
        <div className="h-3 w-16 rounded bg-slate-800 animate-pulse" />
      </div>
    );
  }

  return (
    <div
      className="bg-[#0D1829] rounded-2xl p-5 border border-[rgba(255,255,255,0.06)] glow-card group animate-entrance cursor-pointer transition-all duration-300 hover:border-[rgba(59,130,246,0.3)] hover:shadow-[0_0_30px_rgba(59,130,246,0.1)]"
      style={{ animationDelay: `${index * 80}ms` }}
    >
      <div className="flex items-center justify-between mb-4">
        <span className="text-[11px] uppercase tracking-[0.15em] font-semibold text-slate-400">{label}</span>
        <div
          className="w-9 h-9 rounded-xl flex items-center justify-center transition-colors"
          style={{ background: colors.glow, color: colors.text }}
        >
          {icon}
        </div>
      </div>
      <div className="number-display text-3xl font-bold text-slate-100 mb-2 glow-text" style={{ color: colors.text }}>
        {typeof value === 'number' ? value.toLocaleString('en-IN') : value}
      </div>
      {change !== undefined && (
        <div
          className={clsx(
            'text-xs font-semibold px-2.5 py-1 rounded-lg inline-flex items-center gap-1 font-mono',
          )}
          style={{
            background: change >= 0 ? 'rgba(16,185,129,0.1)' : 'rgba(239,68,68,0.1)',
            color: change >= 0 ? '#10B981' : '#EF4444',
          }}
        >
          <span className="text-[10px]">{change >= 0 ? '▲' : '▼'}</span>
          {Math.abs(change).toFixed(1)}%
        </div>
      )}
      <div
        className="mt-3 h-px rounded-full opacity-0 group-hover:opacity-100 transition-opacity"
        style={{ background: `linear-gradient(90deg, ${colors.text}, transparent)` }}
      />
    </div>
  );
}