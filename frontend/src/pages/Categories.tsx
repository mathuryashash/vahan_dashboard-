// frontend/src/pages/Categories.tsx
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  PieChart, Pie, Cell, BarChart, Bar, ResponsiveContainer, XAxis, YAxis, CartesianGrid, Tooltip, LabelList
} from 'recharts';
import { useNavigate } from 'react-router-dom';
import { getTopMakers, getFuelBreakdown, getStates } from '../api/vahan';
import { useCategoriesQuery } from '../hooks/useCategoriesQuery';
import { LoadingBlock } from '../components/LoadingBlock';
import { LabeledSelect } from '../components/LabeledSelect';
import { formatCompact, cyLabel, cyLongLabel } from '../utils/format';
import { useAppStore } from '../hooks/useAppStore';
import { useScopeLock } from '../hooks/useScopeLock';
import { useChartTheme } from '../hooks/useChartTheme';
import { capForDonut, distinctSeriesColors } from '../theme/tokens';
import { TruncatedYAxisTick, insidePieLabel } from '../components/ChartAxisTick';
import { PowertrainToggle } from '../components/PowertrainToggle';
import { useSettledLayout } from '../hooks/useSettledLayout';
import { ExportCsvButton } from '../components/ExportCsvButton';
import { ErrorBanner } from '../components/ErrorBanner';

export function CategoriesPage() {
  const navigate = useNavigate();
  const chart = useChartTheme();
  const { selectedYear, selectedState, setSelectedState } = useAppStore();
  // The server narrows both charts below to a scoped account's own segment.
  const { lockedCategory, isStateLocked } = useScopeLock();
  // B10: every query on this page honours the shared State filter, which used
  // to be invisible here (no control, not in the subtitle) -- a user arriving
  // from Overview with Lakshadweep picked saw tiny numbers with no
  // explanation. It now has its own control (or a locked chip for a scoped
  // account), and the subtitle names the geography.
  const { data: statesList } = useQuery({ queryKey: ['states'], queryFn: getStates, enabled: !isStateLocked });
  const scopeLabel = lockedCategory ?? 'All Categories';

  // selectedState is shared app-wide, and this page used to ignore it: pick
  // Maharashtra on Overview, come here, and the mix was silently all-India.
  // CategoryDetail passes the same key/params -- they share this cache entry.
  const { data: categories, isLoading, isError, refetch } = useCategoriesQuery({ year: selectedYear, state: selectedState });

  const pieData = capForDonut((categories || []).map((c) => ({
    name: c.vehicle_category,
    value: c.total_count,
  })));
  const pieColors = distinctSeriesColors(chart, pieData.map((p) => p.name));
  const shareReady = useSettledLayout(isLoading);

  return (
    <div className="p-3 sm:p-6 space-y-6">
      {isError && (
        <ErrorBanner
          title="Couldn't load category data"
          description="The request to the server failed. Check your connection and try again."
          action={{ label: 'Retry', onClick: () => refetch() }}
        />
      )}
      <div className="flex items-end justify-between gap-4 flex-wrap animate-entrance">
        <div className="min-w-0">
          <h2 className="text-xl font-bold text-[var(--text-primary)] tracking-tight">Categories & Fuel</h2>
          <p className="text-[10px] text-[var(--text-muted)] mt-0.5 font-mono uppercase tracking-widest">
            Vehicle category and powertrain breakdown — {cyLongLabel(selectedYear)} — {selectedState ?? 'All India'}
          </p>
        </div>
        {isStateLocked ? (
          <div className="flex flex-col gap-1.5">
            <span className="text-[10px] uppercase font-mono tracking-widest text-[var(--text-muted)] font-bold">State</span>
            <div className="bg-[var(--bg-sunken)] border border-[var(--border)] text-[var(--text-primary)] text-xs font-semibold px-3 py-2 rounded-xl" data-testid="categories-state-chip">{selectedState}</div>
          </div>
        ) : (
          <LabeledSelect
            label="State"
            value={selectedState || ''}
            onChange={(e) => setSelectedState(e.target.value || null)}
            className="bg-[var(--bg-sunken)] border border-[var(--border)] text-[var(--text-primary)] text-xs font-semibold px-3 py-2 rounded-xl focus:outline-none focus:ring-2 focus:ring-[var(--accent)] min-w-[180px]"
          >
            <option value="">All India</option>
            {selectedState && !(statesList || []).some((s: { state_name: string }) => s.state_name === selectedState) && (
              <option value={selectedState}>{selectedState}</option>
            )}
            {(statesList || []).map((s: { state_name: string }) => (
              <option key={s.state_name} value={s.state_name}>{s.state_name}</option>
            ))}
          </LabeledSelect>
        )}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div className="xl:col-span-1 bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '100ms' }}>
          <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight mb-4">Category Share</h3>
          {isLoading || !shareReady ? (
            <LoadingBlock className="h-[300px]" />
          ) : (
            <>
              <div role="img" aria-label={`Category share, ${cyLabel(selectedYear)}: ${pieData.map((p) => `${p.name} ${p.value.toLocaleString('en-IN')}`).join(', ')}`}>
              <ResponsiveContainer width="100%" height={240}>
                <PieChart>
                  <Pie
                    data={pieData}
                    cx="50%"
                    cy="50%"
                    innerRadius={70}
                    outerRadius={110}
                    paddingAngle={1}
                    dataKey="value"
                    label={insidePieLabel}
                    labelLine={false}
                  >
                    {pieData.map((p: { name: string }, i: number) => (
                      <Cell key={i} fill={pieColors.get(p.name)} />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(val: number) => [val.toLocaleString('en-IN'), 'Registrations']}
                    contentStyle={chart.tooltipContentStyle({ fontSize: 12 })} {...chart.tooltipTextStyle}
                  />
                </PieChart>
              </ResponsiveContainer>
              </div>
              <div className="mt-3 space-y-1.5 max-h-44 overflow-y-auto pr-1">
                {pieData.map((p: { name: string; value: number }, i: number) => (
                  <div key={p.name} className="flex items-center justify-between text-[11px]">
                    <div className="flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-sm" style={{ backgroundColor: pieColors.get(p.name) }} />
                      <span className="text-[var(--text-secondary)] truncate max-w-[110px]">{p.name}</span>
                    </div>
                    <span className="font-mono text-[var(--text-secondary)] font-semibold">{p.value?.toLocaleString('en-IN')}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        <div className="xl:col-span-2 bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '150ms' }}>
          <div className="mb-4">
            <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">Category Breakdown</h3>
            <p className="text-[10px] text-[var(--text-muted)] font-mono mt-0.5">Click any category to explore makers & fuel · YoY vs {cyLabel(selectedYear - 1)}</p>
          </div>
          {/* B6: this card used to render NOTHING while /categories/ ran
              (15-19 s cold) -- an empty bordered box. Row-shaped skeletons now,
              with the slow-query hint after ~5 s. */}
          {isLoading ? (
            <div className="space-y-3" aria-busy="true">
              {[0, 1, 2, 3, 4].map((i) => (
                <div key={i} className="h-12 rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft" />
              ))}
              <LoadingBlock className="h-10" />
            </div>
          ) : (categories || []).length === 0 && !isError ? (
            <p className="text-xs text-[var(--text-muted)] py-6 text-center">No category data for {cyLabel(selectedYear)}{selectedState ? ` · ${selectedState}` : ''}.</p>
          ) : (
          <div className="space-y-3">
            {(categories || []).map((c) => (
              <button
                key={c.vehicle_category} type="button"
                aria-label={`View ${c.vehicle_category} breakdown`}
                onClick={() => navigate(`/categories/${encodeURIComponent(c.vehicle_category)}`)}
                className="w-full text-left flex items-center gap-4 p-3 rounded-xl cursor-pointer transition-all duration-200 border border-transparent hover:border-[var(--border-strong)] hover:bg-[var(--bg-card-hover)] group"
              >
                <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ backgroundColor: chart.seriesColor(c.vehicle_category) }} />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-semibold text-[var(--text-secondary)] group-hover:text-[var(--text-primary)] transition-colors truncate">{c.vehicle_category}</div>
                  <div className="w-full bg-[var(--bg-sunken)] rounded-full h-1.5 mt-1.5">
                    <div className="h-1.5 rounded-full transition-all duration-500" style={{ width: `${c.share_percent}%`, backgroundColor: chart.seriesColor(c.vehicle_category) }} />
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="font-mono text-sm font-bold text-[var(--text-primary)]">{c.total_count?.toLocaleString('en-IN')}</div>
                  <div className="flex items-center gap-2 justify-end mt-0.5">
                    {c.yoy_growth == null ? (
                      <span className="text-[10px] font-mono text-[var(--text-muted)]" title="no prior-year data">—</span>
                    ) : (
                      <span className="text-[10px] font-mono font-bold" style={{ color: c.yoy_growth >= 0 ? chart.success : chart.danger }}>
                        {c.yoy_growth >= 0 ? '+' : ''}{c.yoy_growth.toFixed(1)}%
                      </span>
                    )}
                    <span className="text-[10px] text-[var(--text-muted)] font-mono">{c.share_percent?.toFixed(1)}%</span>
                  </div>
                </div>
              </button>
            ))}
          </div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* These two carry selectedState as well -- with only the panels
            above state-filtered, the page showed one geography at the top
            and all-India underneath, which reads worse than being uniformly
            national. */}
        <CategoryChart title={`Top Makers — ${scopeLabel}`} queryKey="makers" fn={() => getTopMakers({ year: selectedYear, state: selectedState || undefined })} year={selectedYear} state={selectedState} chart={chart} index={0} />
        <FuelBreakdownChart title={`Fuel Type Breakdown — ${scopeLabel}`} year={selectedYear} state={selectedState} chart={chart} index={1} />
      </div>
    </div>
  );
}

function FuelBreakdownChart({ title, year, state, chart, index }: { title: string; year: number; state: string | null; chart: ReturnType<typeof useChartTheme>; index: number }) {
  const [fuelGroup, setFuelGroup] = useState<string | null>(null);
  const { data, isLoading } = useQuery({
    queryKey: ['fuel', year, fuelGroup, state],
    queryFn: () => getFuelBreakdown({ year, fuel_group: fuelGroup, state: state || undefined }),
  });

  const chartData = ((data as { fuel_type?: string; count: number }[]) || []).map((d) => ({
    name: d.fuel_type || '',
    count: d.count,
  }));

  return (
    <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: `${250 + index * 80}ms` }}>
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">{title}</h3>
        <PowertrainToggle
          value={fuelGroup}
          onChange={setFuelGroup}
          className="flex rounded-lg border border-[var(--border)] overflow-hidden"
          buttonClassName={(active) => `px-2.5 py-1 text-[10px] font-semibold transition-colors ${
            active
              ? 'bg-[var(--accent)] text-[var(--accent-contrast)]'
              : 'bg-[var(--bg-sunken)] text-[var(--text-secondary)] hover:bg-[var(--bg-card-hover)]'
          }`}
        />
      </div>
      {isLoading ? (
        <LoadingBlock className="h-[220px]" />
      ) : (
        <ResponsiveContainer width="100%" height={Math.max(220, chartData.length * 38)}>
          {/* right:76, not 48 -- an 11-character crore figure ("1,59,62,847")
              overflowed the old margin and rendered clipped as "1,59,62". */}
          <BarChart data={chartData} layout="vertical" margin={{ right: 76 }}>
            <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} horizontal={false} />
            <XAxis type="number" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} tickFormatter={formatCompact} />
            <YAxis dataKey="name" type="category" tick={(props) => <TruncatedYAxisTick {...props} fill={chart.axisText} />} width={190} />
            <Tooltip
              formatter={(val: number) => [val.toLocaleString('en-IN'), 'Count']}
              contentStyle={chart.tooltipContentStyle({ fontSize: 12 })} {...chart.tooltipTextStyle}
            />
            <Bar dataKey="count" radius={[0, 4, 4, 0]}>
              {chartData.map((d: { name: string }, i: number) => (
                <Cell key={i} fill={chart.seriesColor(d.name)} />
              ))}
              <LabelList dataKey="count" position="right" formatter={(v: number) => v.toLocaleString('en-IN')} style={{ fill: chart.axisText, fontSize: 10, fontFamily: 'JetBrains Mono' }} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

function CategoryChart({ title, queryKey, fn, year, state, chart, index }: { title: string; queryKey: string; fn: () => Promise<unknown>; year: number; state: string | null; chart: ReturnType<typeof useChartTheme>; index: number }) {
  // state is in the key, not just the fetch: without it, switching states
  // served the previous state's cached rows.
  const { data, isLoading } = useQuery({ queryKey: [queryKey, year, state], queryFn: fn });

  const chartData = ((data as { maker?: string; fuel_type?: string; count: number }[]) || []).map((d) => ({
    name: d.maker || d.fuel_type || '',
    count: d.count,
  }));

  return (
    <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: `${250 + index * 80}ms` }}>
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">{title}</h3>
        <ExportCsvButton filename={`${title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')}-cy${year}`} rows={data as Record<string, unknown>[] | undefined} />
      </div>
      {isLoading ? (
        <LoadingBlock className="h-[220px]" />
      ) : (
        <ResponsiveContainer width="100%" height={Math.max(220, chartData.length * 38)}>
          {/* right:76, not 48 -- an 11-character crore figure ("1,59,62,847")
              overflowed the old margin and rendered clipped as "1,59,62". */}
          <BarChart data={chartData} layout="vertical" margin={{ right: 76 }}>
            <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} horizontal={false} />
            <XAxis type="number" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} tickFormatter={formatCompact} />
            <YAxis dataKey="name" type="category" tick={(props) => <TruncatedYAxisTick {...props} fill={chart.axisText} />} width={190} />
            <Tooltip
              formatter={(val: number) => [val.toLocaleString('en-IN'), 'Count']}
              contentStyle={chart.tooltipContentStyle({ fontSize: 12 })} {...chart.tooltipTextStyle}
            />
            <Bar dataKey="count" radius={[0, 4, 4, 0]}>
              {chartData.map((d: { name: string }, i: number) => (
                <Cell key={i} fill={chart.seriesColor(d.name)} />
              ))}
              <LabelList dataKey="count" position="right" formatter={(v: number) => v.toLocaleString('en-IN')} style={{ fill: chart.axisText, fontSize: 10, fontFamily: 'JetBrains Mono' }} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
