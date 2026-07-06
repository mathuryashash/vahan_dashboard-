import { useQuery } from '@tanstack/react-query';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, LineChart, Line, TooltipProps
} from 'recharts';
import { useAppStore } from '../hooks/useAppStore';
import { getYoYMonthly, getYoYSummary } from '../api/vahan';

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function YoYTooltip({ active, payload, label }: TooltipProps<number, string>) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-[#0D1829] border border-[rgba(59,130,246,0.3)] rounded-xl px-3 py-2.5 shadow-[0_8px_30px_rgba(0,0,0,0.5)]">
      <p className="text-[10px] uppercase tracking-widest text-slate-400 mb-2">{label}</p>
      {payload.map((p, i) => (
        <div key={i} className="flex items-center gap-2 mb-1">
          <div className="w-2 h-2 rounded-sm" style={{ background: p.fill }} />
          <span className="text-[11px] text-slate-400 font-mono">{p.name}:</span>
          <span className="text-xs font-bold text-white font-mono">{p.value?.toLocaleString('en-IN')}</span>
        </div>
      ))}
    </div>
  );
}

export function YoYPage() {
  const { comparisonYearA, comparisonYearB } = useAppStore();

  const { data: monthly, isLoading } = useQuery({
    queryKey: ['yoy', comparisonYearA, comparisonYearB],
    queryFn: () => getYoYMonthly(comparisonYearA, comparisonYearB),
  });

  const { data: summary } = useQuery({
    queryKey: ['yoySummary', comparisonYearA, comparisonYearB],
    queryFn: () => getYoYSummary(comparisonYearA, comparisonYearB),
  });

  const chartData = (monthly?.data || []).map((d: { month: number; [key: string]: number }) => ({
    name: MONTH_NAMES[d.month - 1],
    [`${comparisonYearA}`]: d[`year_${comparisonYearA}`],
    [`${comparisonYearB}`]: d[`year_${comparisonYearB}`],
    growth: d.growth_percent,
  }));

  const growth = summary?.growth_percent ?? 0;

  return (
    <div className="p-6 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="animate-entrance">
          <h2 className="text-xl font-bold text-white tracking-tight">Year-over-Year Analysis</h2>
          <p className="text-xs text-slate-500 mt-0.5 font-mono uppercase tracking-widest">
            Temporal comparison — {comparisonYearA} vs {comparisonYearB}
          </p>
        </div>
        <div className="flex items-center gap-3 animate-entrance" style={{ animationDelay: '50ms' }}>
          <div className="px-3 py-1.5 rounded-lg border text-xs font-mono font-semibold" style={{ background: 'rgba(255,255,255,0.03)', borderColor: 'rgba(255,255,255,0.08)', color: '#94A3B8' }}>
            {comparisonYearA} <span className="text-slate-600 mx-1">→</span>
            <span className="text-white font-mono">{(summary?.[`total_${comparisonYearA}`] || 0).toLocaleString('en-IN')}</span>
          </div>
          <div className="px-3 py-1.5 rounded-lg border text-xs font-mono font-semibold" style={{ background: 'rgba(59,130,246,0.08)', borderColor: 'rgba(59,130,246,0.25)', color: '#3B82F6' }}>
            {comparisonYearB} <span className="text-slate-600 mx-1">→</span>
            <span className="text-white font-mono">{(summary?.[`total_${comparisonYearB}`] || 0).toLocaleString('en-IN')}</span>
          </div>
          <div
            className="px-3 py-1.5 rounded-lg text-xs font-bold font-mono"
            style={{
              background: growth >= 0 ? 'rgba(16,185,129,0.1)' : 'rgba(239,68,68,0.1)',
              color: growth >= 0 ? '#10B981' : '#EF4444',
              border: `1px solid ${growth >= 0 ? 'rgba(16,185,129,0.25)' : 'rgba(239,68,68,0.25)'}`,
            }}
          >
            {growth >= 0 ? '+' : ''}{growth.toFixed(1)}%
          </div>
        </div>
      </div>

      {/* Main comparison chart */}
      <div className="bg-[#0D1829] rounded-2xl border border-[rgba(255,255,255,0.06)] p-5 animate-entrance" style={{ animationDelay: '80ms' }}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-bold text-white tracking-tight">Monthly Volume Comparison</h3>
          <div className="flex items-center gap-4 text-[11px] font-mono">
            <span className="flex items-center gap-1.5"><span className="w-3 h-0.5 rounded-full bg-slate-500 inline-block" /> {comparisonYearA}</span>
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm bg-blue-500 inline-block" /> {comparisonYearB}</span>
          </div>
        </div>
        {isLoading ? <div className="h-64 rounded-xl bg-[#111D32] animate-pulse" /> : (
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={chartData} barGap={4}>
              <CartesianGrid strokeDasharray="1 2" stroke="rgba(255,255,255,0.04)" vertical={false} />
              <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#475569', fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 10, fill: '#475569', fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${(v/1000000).toFixed(1)}M`} width={40} />
              <Tooltip content={<YoYTooltip />} />
              <Bar dataKey={`${comparisonYearA}`} fill="#475569" radius={[3, 3, 0, 0]} maxBarSize={20} />
              <Bar dataKey={`${comparisonYearB}`} fill="#3B82F6" radius={[3, 3, 0, 0]} maxBarSize={20} style={{ filter: 'drop-shadow(0 0 8px rgba(59,130,246,0.3))' }} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Growth heatmap + trend */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <div className="bg-[#0D1829] rounded-2xl border border-[rgba(255,255,255,0.06)] p-5 animate-entrance" style={{ animationDelay: '130ms' }}>
          <h3 className="text-sm font-bold text-white tracking-tight mb-4">Month-wise Growth Rate</h3>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={chartData} layout="vertical">
              <CartesianGrid strokeDasharray="1 2" stroke="rgba(255,255,255,0.04)" horizontal={false} />
              <XAxis type="number" domain={[-50, 50]} tick={{ fontSize: 10, fill: '#475569', fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${v}%`} />
              <YAxis dataKey="name" type="category" tick={{ fontSize: 10, fill: '#475569', fontFamily: 'JetBrains Mono' }} width={30} axisLine={false} tickLine={false} />
              <Tooltip formatter={(val: number) => [`${val?.toFixed(1)}%`, 'Growth']} contentStyle={{ background: '#0D1829', border: '1px solid rgba(59,130,246,0.3)', borderRadius: 8 }} />
              <Bar dataKey="growth" radius={[0, 3, 3, 0]} maxBarSize={14}>
                {chartData.map((d: { growth: number }, i: number) => (
                  <Cell key={i} fill={d.growth >= 0 ? '#10B981' : '#EF4444'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <div className="flex items-center justify-center gap-4 mt-3 text-[10px] font-mono">
            <span className="text-emerald-400">▲ Positive growth</span>
            <span className="text-rose-400">▼ Negative growth</span>
          </div>
        </div>

        <div className="bg-[#0D1829] rounded-2xl border border-[rgba(255,255,255,0.06)] p-5 animate-entrance" style={{ animationDelay: '160ms' }}>
          <h3 className="text-sm font-bold text-white tracking-tight mb-4">Dual-Year Trend Line</h3>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="1 2" stroke="rgba(255,255,255,0.04)" vertical={false} />
              <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#475569', fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 10, fill: '#475569', fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${(v/1000000).toFixed(1)}M`} width={40} />
              <Tooltip formatter={(val: number) => val.toLocaleString('en-IN')} contentStyle={{ background: '#0D1829', border: '1px solid rgba(59,130,246,0.3)', borderRadius: 8 }} />
              <Line type="monotone" dataKey={`${comparisonYearA}`} stroke="#475569" strokeWidth={1.5} dot={{ r: 3, fill: '#475569' }} />
              <Line type="monotone" dataKey={`${comparisonYearB}`} stroke="#3B82F6" strokeWidth={2.5} dot={{ r: 4, fill: '#3B82F6' }} activeDot={{ r: 6 }} style={{ filter: 'drop-shadow(0 0 6px rgba(59,130,246,0.4))' }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Monthly breakdown table */}
      <div className="bg-[#0D1829] rounded-2xl border border-[rgba(255,255,255,0.06)] p-5 animate-entrance" style={{ animationDelay: '190ms' }}>
        <h3 className="text-sm font-bold text-white tracking-tight mb-4">Month-by-Month Breakdown</h3>
        <div className="grid grid-cols-6 gap-3 mb-4 text-[10px] uppercase tracking-widest text-slate-500 font-mono px-1">
          <span>Month</span>
          <span>{comparisonYearA}</span>
          <span>{comparisonYearB}</span>
          <span className="col-span-2 text-center">Delta</span>
          <span className="text-right">Growth</span>
        </div>
        <div className="space-y-2">
          {chartData.map((d: { name: string; [key: string]: number }, i: number) => {
            const a = d[`year_${comparisonYearA}`] || 0;
            const b = d[`year_${comparisonYearB}`] || 0;
            const delta = b - a;
            const pct = d.growth || 0;
            return (
              <div key={i} className="grid grid-cols-6 gap-3 items-center px-1 py-1.5 rounded-lg hover:bg-[rgba(255,255,255,0.02)] transition-colors">
                <span className="text-xs font-mono text-slate-400 font-semibold">{d.name}</span>
                <span className="font-mono text-xs text-slate-500">{a.toLocaleString('en-IN')}</span>
                <span className="font-mono text-xs text-blue-400 font-semibold">{b.toLocaleString('en-IN')}</span>
                <div className="col-span-2 flex items-center gap-1">
                  <span className={`font-mono text-[11px] font-bold ${delta >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {delta >= 0 ? '+' : ''}{delta.toLocaleString('en-IN')}
                  </span>
                  <div className="h-0.5 flex-1 rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.06)' }}>
                    <div className="h-full rounded-full" style={{ width: `${Math.min(Math.abs(pct), 100)}%`, background: pct >= 0 ? '#10B981' : '#EF4444' }} />
                  </div>
                </div>
                <span className="text-right font-mono text-[11px] font-bold" style={{ color: pct >= 0 ? '#10B981' : '#EF4444' }}>
                  {pct >= 0 ? '+' : ''}{pct.toFixed(1)}%
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}