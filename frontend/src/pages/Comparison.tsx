// frontend/src/pages/Comparison.tsx
import { useQuery } from '@tanstack/react-query';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, TooltipProps } from 'recharts';
import { useState } from 'react';
import { getStatesComparison, compareStates } from '../api/vahan';
import { useAppStore } from '../hooks/useAppStore';
import { useChartTheme } from '../hooks/useChartTheme';

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function StateTooltip({ active, payload, label, chart }: TooltipProps<number, string> & { chart: ReturnType<typeof useChartTheme> }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl px-3 py-2.5" style={{ background: chart.tooltipBg, border: `1px solid ${chart.tooltipBorder}` }}>
      <p className="text-[10px] uppercase tracking-widest mb-1" style={{ color: chart.axisText }}>{label}</p>
      {payload.map((p, i) => (
        <div key={i} className="flex items-center gap-2">
          <span className="text-[10px]" style={{ color: chart.axisText }}>{p.name}:</span>
          <span className="text-xs font-bold font-mono" style={{ color: chart.tooltipText }}>{p.value?.toLocaleString('en-IN')}</span>
        </div>
      ))}
    </div>
  );
}

export function ComparisonPage() {
  const chart = useChartTheme();
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
  const aData: { name: string; [key: string]: string | number }[] = (comparison?.state_a_data || []).map((d: { month: number; count: number }) => ({ name: MONTH_NAMES[d.month - 1], [stateA]: d.count }));
  const bData: { name: string; [key: string]: string | number }[] = (comparison?.state_b_data || []).map((d: { month: number; count: number }) => ({ name: MONTH_NAMES[d.month - 1], [stateB]: d.count }));

  const merged = aData.map((d, i) => ({ ...d, ...(bData[i] || {}) }));

  const totalA = (comparison?.state_a_data || []).reduce((s: number, d: { count: number }) => s + d.count, 0);
  const totalB = (comparison?.state_b_data || []).reduce((s: number, d: { count: number }) => s + d.count, 0);

  const colorA = chart.seriesColor(stateA);
  const colorB = chart.seriesColor(stateB);

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div className="animate-entrance">
          <h2 className="text-xl font-bold text-[var(--text-primary)] tracking-tight">State Comparison</h2>
          <p className="text-xs text-[var(--text-muted)] mt-0.5 font-mono uppercase tracking-widest">
            Cross-state registration analysis — FY {selectedYear}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 animate-entrance" style={{ animationDelay: '40ms' }}>
        {[{ label: 'State A', value: stateA, setter: setStateA, color: colorA },
          { label: 'State B', value: stateB, setter: setStateB, color: colorB },
          { label: 'States Active', value: `${stateOptions.length || 0} / 36`, setter: () => {}, color: 'var(--success)' }
        ].map((s, i) => (
          <div key={i} className="bg-[var(--bg-card)] rounded-xl border border-[var(--border)] p-4">
            <p className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] font-mono mb-2">{s.label}</p>
            {i < 2 ? (
              stateOptions.length === 0 ? (
                // /comparison/all-states is slow enough (seconds, not
                // milliseconds) that a plain <select> with zero <option>s
                // renders with no visible selection during that window --
                // a browser can't select a value that isn't one of its
                // options yet, even though stateA/stateB are already
                // correctly "Maharashtra"/"Gujarat" internally. Found by
                // live click-through QA as a blank dropdown with no cue of
                // which states are being compared; a real loading state
                // is honest about what's actually happening instead of
                // silently showing an empty control.
                <div className="w-full bg-[var(--bg-sunken)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text-muted)] animate-pulse-soft">
                  Loading states…
                </div>
              ) : (
                <select
                  value={s.value}
                  onChange={(e) => s.setter(e.target.value)}
                  className="w-full bg-[var(--bg-sunken)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm font-semibold text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)] transition-colors"
                >
                  {stateOptions.map((opt: string) => <option key={opt} value={opt}>{opt}</option>)}
                </select>
              )
            ) : (
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full" style={{ background: s.color }} />
                <span className="font-mono text-[var(--text-primary)] font-bold">{s.value}</span>
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 animate-entrance" style={{ animationDelay: '80ms' }}>
        {[{
          label: stateA, total: totalA, color: colorA,
        }, {
          label: stateB, total: totalB, color: colorB,
        }].map((card, i) => (
          <div key={i} className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5">
            <div className="flex items-center gap-3 mb-3">
              <div className="w-3 h-3 rounded-full" style={{ background: card.color }} />
              <span className="text-xs font-semibold text-[var(--text-secondary)]">{card.label}</span>
            </div>
            <div className="number-display text-2xl font-bold text-[var(--text-primary)] mb-1">{card.total?.toLocaleString('en-IN') || 0}</div>
            <p className="text-[11px] text-[var(--text-muted)] font-mono">
              Total registrations FY {selectedYear}
            </p>
          </div>
        ))}
      </div>

      <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '120ms' }}>
        <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight mb-4">{stateA} vs {stateB} — Monthly</h3>
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={merged} layout="vertical" barGap={6}>
            <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} horizontal={false} />
            <XAxis type="number" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${(v/1000).toFixed(0)}K`} />
            <YAxis dataKey="name" type="category" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} width={36} />
            <Tooltip content={<StateTooltip chart={chart} />} />
            <Bar dataKey={stateA} fill={colorA} radius={[0, 3, 3, 0]} maxBarSize={16} />
            <Bar dataKey={stateB} fill={colorB} radius={[0, 3, 3, 0]} maxBarSize={16} />
          </BarChart>
        </ResponsiveContainer>
        <div className="flex items-center justify-center gap-6 mt-3 text-[11px] font-mono">
          <span style={{ color: colorA }}>{stateA}</span>
          <span style={{ color: colorB }}>{stateB}</span>
        </div>
      </div>

      <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '160ms' }}>
        <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight mb-4">All States — Ranked</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
          {(allStates || []).map((s: { state_name: string; count: number; share_percent: number }, i: number) => (
            <div
              key={s.state_name}
              onClick={() => { setStateA(s.state_name); setFocusState(s.state_name); }}
              className="bg-[var(--bg-sunken)] rounded-lg px-3 py-2 cursor-pointer transition-all hover:bg-[var(--bg-card-hover)] border"
              style={{ borderColor: focusState === s.state_name ? 'var(--accent)' : 'transparent' }}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[10px] text-[var(--text-muted)] font-bold w-4">#{i + 1}</span>
                  <span className="text-xs text-[var(--text-secondary)]">{s.state_name}</span>
                </div>
                <div className="text-right">
                  <span className="font-mono text-[11px] font-bold text-[var(--text-primary)]">{s.count?.toLocaleString('en-IN')}</span>
                  <span className="font-mono text-[10px] text-[var(--text-muted)] ml-1">{s.share_percent?.toFixed(1)}%</span>
                </div>
              </div>
              <div className="mt-1.5 h-0.5 bg-[var(--bg-card)] rounded-full overflow-hidden">
                <div className="h-full rounded-full" style={{ width: `${s.share_percent}%`, background: chart.seriesColor(s.state_name) }} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
