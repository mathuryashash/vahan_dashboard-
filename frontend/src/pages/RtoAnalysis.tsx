// frontend/src/pages/RtoAnalysis.tsx
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { BarChart, Bar, PieChart, Pie, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import { getStates, getRtosForState, getRtoAnalysis, getAvailableYears } from '../api/vahan';
import { useChartTheme } from '../hooks/useChartTheme';
import { capForDonut, distinctSeriesColors } from '../theme/tokens';
import { TruncatedYAxisTick } from '../components/ChartAxisTick';
import { EmptyState } from '../components/EmptyState';
import type { RTOListItem, RTOAnalysis } from '../types';

// Indian financial year: April `fyYear` through March `fyYear + 1`.
const now = new Date();
const CURRENT_FY = now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1;
const fyMonthsElapsed = (fyYear: number) => (fyYear === CURRENT_FY ? now.getMonth() - 3 + 1 : 12);

export function RtoAnalysisPage() {
  const chart = useChartTheme();
  const [fyYear, setFyYear] = useState<number>(CURRENT_FY);
  const [stateCode, setStateCode] = useState<string>('');
  const [rtoCode, setRtoCode] = useState<string | null>(null);

  const { data: states } = useQuery({ queryKey: ['states'], queryFn: getStates });
  const { data: availableYears } = useQuery({ queryKey: ['availableYears'], queryFn: getAvailableYears });

  const { data: rtos, isLoading: rtosLoading } = useQuery<RTOListItem[]>({
    queryKey: ['rtoList', stateCode, fyYear],
    queryFn: () => getRtosForState(stateCode, fyYear),
    enabled: !!stateCode,
  });

  const { data: analysis, isLoading: analysisLoading } = useQuery<RTOAnalysis>({
    queryKey: ['rtoAnalysis', rtoCode, fyYear],
    queryFn: () => getRtoAnalysis(rtoCode!, fyYear),
    enabled: !!rtoCode,
  });

  const rtoChartData = (rtos || []).map((r) => ({ name: r.rto_name || r.rto_code, code: r.rto_code, count: r.total }));

  const total = analysis?.total || 0;
  const makerPieData = capForDonut(
    (analysis?.makers || []).map((m) => ({ name: m.maker, value: m.count })),
    6
  ).map((d) => ({ ...d, share: total ? Math.round((d.value / total) * 1000) / 10 : 0 }));
  const makerPieColors = distinctSeriesColors(chart, makerPieData.map((d) => d.name));

  return (
    <div className="p-6 space-y-6">
      <div className="animate-entrance">
        <h2 className="text-xl font-bold text-[var(--text-primary)] tracking-tight">RTO Analysis</h2>
        <p className="text-[10px] text-[var(--text-muted)] mt-0.5 font-mono uppercase tracking-widest">
          State → RTO → company share breakdown — FY {fyYear}-{String((fyYear + 1) % 100).padStart(2, '0')}
        </p>
      </div>

      <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance flex flex-wrap gap-4">
        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] uppercase font-mono tracking-widest text-[var(--text-muted)] font-bold">State</label>
          <select
            value={stateCode}
            onChange={(e) => { setStateCode(e.target.value); setRtoCode(null); }}
            className="bg-[var(--bg-sunken)] border border-[var(--border)] rounded-lg px-3 py-2 text-xs font-mono font-semibold focus:outline-none cursor-pointer w-full max-w-xs"
          >
            <option value="">Select a state...</option>
            {(states || []).map((s: { state_code: string; state_name: string }) => (
              <option key={s.state_code} value={s.state_code}>{s.state_name}</option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] uppercase font-mono tracking-widest text-[var(--text-muted)] font-bold">Financial Year</label>
          <select
            value={fyYear}
            onChange={(e) => setFyYear(Number(e.target.value))}
            className="bg-[var(--bg-sunken)] border border-[var(--border)] rounded-lg px-3 py-2 text-xs font-mono font-semibold focus:outline-none cursor-pointer"
          >
            {(availableYears || [fyYear]).map((y) => (
              <option key={y} value={y}>FY {y}-{String((y + 1) % 100).padStart(2, '0')}</option>
            ))}
          </select>
        </div>
      </div>

      {!stateCode ? (
        <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)]">
          <EmptyState variant="no-selection" title="Pick a state" description="Select a state above to see its RTOs, ranked by registration volume." />
        </div>
      ) : (
        <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">RTOs</h3>
              <p className="text-[10px] text-[var(--text-muted)] font-mono mt-0.5">click an RTO to see its company breakdown below</p>
            </div>
            {rtoCode && (
              <button onClick={() => setRtoCode(null)} className="text-[9px] uppercase font-mono tracking-wider text-[var(--accent)] hover:opacity-80 transition-opacity">
                Clear Selection
              </button>
            )}
          </div>
          {rtosLoading ? (
            <div className="h-[300px] rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft" />
          ) : rtoChartData.length === 0 ? (
            <EmptyState variant="no-data" title="No data for this state/year" description="Try a different year or state." />
          ) : (
            <ResponsiveContainer width="100%" height={Math.max(280, rtoChartData.length * 22)}>
              <BarChart data={rtoChartData} layout="vertical">
                <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} />
                <YAxis dataKey="name" type="category" tick={(props) => <TruncatedYAxisTick {...props} fill={chart.axisText} />} width={180} />
                <Tooltip formatter={(val: number) => [val.toLocaleString('en-IN'), 'Registrations']} contentStyle={chart.tooltipContentStyle({ fontSize: 12 })} {...chart.tooltipTextStyle} />
                <Bar
                  dataKey="count"
                  radius={[0, 4, 4, 0]}
                  onClick={(data: { code?: string }) => data?.code && setRtoCode(data.code)}
                  cursor="pointer"
                >
                  {rtoChartData.map((d, i: number) => (
                    <Cell key={i} fill={chart.seriesColor(d.name)} fillOpacity={rtoCode && rtoCode !== d.code ? 0.35 : 1} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      )}

      {rtoCode && (
        <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance">
          {analysisLoading ? (
            <div className="h-[400px] rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft" />
          ) : (
            <>
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">
                  {analysis?.rto_name || rtoCode} — Overview
                </h3>
                <span className="text-[10px] text-[var(--text-muted)] font-mono">{analysis?.state_name}</span>
              </div>
              <div className="grid grid-cols-3 gap-3 mb-6">
                <div className="rounded-xl p-4 border border-[var(--border)]" style={{ background: 'var(--bg-sunken)' }}>
                  <p className="text-[9px] uppercase tracking-widest text-[var(--text-muted)] font-mono mb-1">Total Registrations</p>
                  <p className="text-lg font-bold font-mono text-[var(--text-primary)]">{(analysis?.total || 0).toLocaleString('en-IN')}</p>
                </div>
                <div className="rounded-xl p-4 border border-[var(--border)]" style={{ background: 'var(--bg-sunken)' }}>
                  <p className="text-[9px] uppercase tracking-widest text-[var(--text-muted)] font-mono mb-1">Avg / Month</p>
                  <p className="text-lg font-bold font-mono text-[var(--accent)]">{(analysis?.avg_monthly || 0).toLocaleString('en-IN')}</p>
                </div>
                <div className="rounded-xl p-4 border border-[var(--border)]" style={{ background: 'var(--bg-sunken)' }}>
                  <p className="text-[9px] uppercase tracking-widest text-[var(--text-muted)] font-mono mb-1">Months With Data</p>
                  <p className="text-lg font-bold font-mono text-[var(--text-primary)]">
                    {analysis?.months_with_data || 0} / {fyMonthsElapsed(fyYear)}
                  </p>
                  {fyYear === CURRENT_FY && (
                    <p className="text-[9px] text-[var(--text-muted)] font-mono mt-1">FY in progress</p>
                  )}
                </div>
              </div>

              <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight mb-1">Company Share</h3>
              <p className="text-[10px] text-[var(--text-muted)] font-mono mb-4">% of this RTO's registrations, top {makerPieData.length} companies</p>
              {makerPieData.length === 0 ? (
                <EmptyState variant="no-data" title="No company data for this RTO/year" />
              ) : (
                <div className="flex flex-col lg:flex-row items-center gap-6">
                  <ResponsiveContainer width="100%" height={320} className="lg:max-w-md">
                    <PieChart>
                      <Pie data={makerPieData} cx="50%" cy="50%" innerRadius={70} outerRadius={120} paddingAngle={1} dataKey="value">
                        {makerPieData.map((d, i: number) => (
                          <Cell key={i} fill={d.name === 'Other' ? chart.grid : makerPieColors.get(d.name)} />
                        ))}
                      </Pie>
                      <Tooltip
                        formatter={(val: number, _name, item) => [`${item.payload.share}% (${val.toLocaleString('en-IN')})`, 'Share']}
                        contentStyle={chart.tooltipContentStyle({ fontSize: 12 })} {...chart.tooltipTextStyle}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="w-full space-y-2">
                    {makerPieData.map((d, i: number) => (
                      <div key={i} className="flex items-center justify-between text-xs">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ backgroundColor: d.name === 'Other' ? chart.grid : makerPieColors.get(d.name) }} />
                          <span className="text-[var(--text-secondary)] truncate">{d.name}</span>
                        </div>
                        <span className="font-mono font-bold text-[var(--text-primary)] shrink-0 ml-2">{d.share}%</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
