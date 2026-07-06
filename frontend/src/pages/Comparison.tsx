import { useQuery } from '@tanstack/react-query';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, TooltipProps } from 'recharts';
import { useState } from 'react';
import { getStatesComparison, compareStates } from '../api/vahan';
import { useAppStore } from '../hooks/useAppStore';

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const COLORS = ['#3B82F6', '#06B6D4', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899', '#F97316'];

function StateTooltip({ active, payload, label }: TooltipProps<number, string>) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-[#0D1829] border border-[rgba(59,130,246,0.3)] rounded-xl px-3 py-2.5 shadow-[0_8px_30px_rgba(0,0,0,0.5)]">
      <p className="text-[10px] text-slate-400 uppercase tracking-widest mb-1">{label}</p>
      {payload.map((p, i) => (
        <div key={i} className="flex items-center gap-2">
          <span className="text-[10px] text-slate-400">{p.name}</span>
          <span className="font-mono text-xs font-bold text-white">{p.value?.toLocaleString('en-IN')}</span>
        </div>
      ))}
    </div>
  );
}

export function ComparisonPage() {
  const { selectedYear } = useAppStore();
  const [stateA, setStateA] = useState('Maharashtra');
  const [stateB, setStateB] = useState('Gujarat');
  const [focusState, setFocusState] = useState<string | null>(null);

  const { data: allStates } = useQuery({
    queryKey: ['states', selectedYear],
    queryFn: () => getStatesComparison(selectedYear, 36),
  });

  const { data: comparison } = useQuery({
    queryKey: ['compare', stateA, stateB, selectedYear],
    queryFn: () => compareStates(stateA, stateB, selectedYear),
    enabled: !!stateA,
  });

  const stateOptions = (allStates || []).map((s: { state_name: string }) => s.state_name);
  const aData = (comparison?.state_a_data || []).map((d: { month: number; count: number }) => ({ name: MONTH_NAMES[d.month - 1], [stateA]: d.count }));
  const bData = (comparison?.state_b_data || []).map((d: { month: number; count: number }) => ({ name: MONTH_NAMES[d.month - 1], [stateB]: d.count }));

  const merged = aData.map((d, i) => ({ ...d, ...(bData[i] || {}) }));

  const totalA = (comparison?.state_a_data || []).reduce((s: number, d: { count: number }) => s + d.count, 0);
  const totalB = (comparison?.state_b_data || []).reduce((s: number, d: { count: number }) => s + d.count, 0);

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div className="animate-entrance">
          <h2 className="text-xl font-bold text-white tracking-tight">State Comparison</h2>
          <p className="text-xs text-slate-500 mt-0.5 font-mono uppercase tracking-widest">
            Cross-state registration analysis — FY {selectedYear}
          </p>
        </div>
      </div>

      {/* State selectors */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 animate-entrance" style={{ animationDelay: '40ms' }}>
        {[{ label: 'State A', value: stateA, setter: setStateA, color: '#3B82F6' },
          { label: 'State B', value: stateB, setter: setStateB, color: '#F59E0B' },
          { label: 'States Active', value: `${stateOptions.length || 0} / 36`, setter: () => {}, color: '#10B981' }
        ].map((s, i) => (
          <div key={i} className="bg-[#0D1829] rounded-xl border border-[rgba(255,255,255,0.06)] p-4">
            <p className="text-[10px] uppercase tracking-widest text-slate-500 font-mono mb-2">{s.label}</p>
            {i < 2 ? (
              <select
                value={s.value}
                onChange={(e) => s.setter(e.target.value)}
                className="w-full bg-[#111D32] border border-[rgba(255,255,255,0.08)] rounded-lg px-3 py-2 text-sm font-semibold text-white focus:outline-none focus:border-blue-500 transition-colors"
              >
                {stateOptions.map((opt: string) => <option key={opt} value={opt}>{opt}</option>)}
              </select>
            ) : (
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse-glow" />
                <span className="font-mono text-white font-bold">{s.value}</span>
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 animate-entrance" style={{ animationDelay: '80ms' }}>
        {[{
          label: stateA, total: totalA, color: '#3B82F6',
          delta: totalB > 0 ? (((totalA - totalB) / totalB) * 100).toFixed(1) : '—',
        }, {
          label: stateB, total: totalB, color: '#F59E0B',
          delta: totalA > 0 ? (((totalB - totalA) / totalA) * 100).toFixed(1) : '—',
        }].map((card, i) => (
          <div key={i} className="bg-[#0D1829] rounded-2xl border border-[rgba(255,255,255,0.06)] p-5">
            <div className="flex items-center gap-3 mb-3">
              <div className="w-3 h-3 rounded-full" style={{ background: card.color }} />
              <span className="text-xs font-semibold text-slate-300">{card.label}</span>
            </div>
            <div className="number-display text-2xl font-bold text-white mb-1">{card.total?.toLocaleString('en-IN') || 0}</div>
            <p className="text-[11px] text-slate-500 font-mono">
              Total registrations FY {selectedYear}
            </p>
          </div>
        ))}
      </div>

      {/* Comparison chart */}
      <div className="bg-[#0D1829] rounded-2xl border border-[rgba(255,255,255,0.06)] p-5 animate-entrance" style={{ animationDelay: '120ms' }}>
        <h3 className="text-sm font-bold text-white tracking-tight mb-4">{stateA} vs {stateB} — Monthly</h3>
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={merged} barGap={6}>
            <CartesianGrid strokeDasharray="1 2" stroke="rgba(255,255,255,0.04)" vertical={false} />
            <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#475569', fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 10, fill: '#475569', fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${(v/1000).toFixed(0)}K`} width={36} />
            <Tooltip content={<StateTooltip />} />
            <Bar dataKey={stateA} fill="#3B82F6" radius={[3, 3, 0, 0]} maxBarSize={18} style={{ filter: 'drop-shadow(0 0 6px rgba(59,130,246,0.2))' }} />
            <Bar dataKey={stateB} fill="#F59E0B" radius={[3, 3, 0, 0]} maxBarSize={18} style={{ filter: 'drop-shadow(0 0 6px rgba(245,158,11,0.2))' }} />
          </BarChart>
        </ResponsiveContainer>
        <div className="flex items-center justify-center gap-6 mt-3 text-[11px] font-mono">
          <span className="text-blue-400">{stateA}</span>
          <span className="text-amber-400">{stateB}</span>
        </div>
      </div>

      {/* All states ranking */}
      <div className="bg-[#0D1829] rounded-2xl border border-[rgba(255,255,255,0.06)] p-5 animate-entrance" style={{ animationDelay: '160ms' }}>
        <h3 className="text-sm font-bold text-white tracking-tight mb-4">All States — Ranked</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
          {(allStates || []).map((s: { state_name: string; count: number; share_percent: number }, i: number) => (
            <div
              key={s.state_name}
              onClick={() => { setStateA(s.state_name); setFocusState(s.state_name); }}
              className={`bg-[#111D32] rounded-lg px-3 py-2 cursor-pointer transition-all hover:bg-[rgba(59,130,246,0.1)] border ${focusState === s.state_name ? 'border-blue-500' : 'border-transparent'}`}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[10px] text-slate-600 font-bold w-4">#{i + 1}</span>
                  <span className="text-xs text-slate-300">{s.state_name}</span>
                </div>
                <div className="text-right">
                  <span className="font-mono text-[11px] font-bold text-white">{s.count?.toLocaleString('en-IN')}</span>
                  <span className="font-mono text-[10px] text-slate-600 ml-1">{s.share_percent?.toFixed(1)}%</span>
                </div>
              </div>
              <div className="mt-1.5 h-0.5 bg-[#0D1829] rounded-full overflow-hidden">
                <div className="h-full rounded-full" style={{ width: `${s.share_percent}%`, background: COLORS[i % COLORS.length] }} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}