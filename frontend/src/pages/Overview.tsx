// frontend/src/pages/Overview.tsx
import { useQuery } from '@tanstack/react-query';
import {
  AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, TooltipProps, ResponsiveContainer
} from 'recharts';
import { TrendingUp, Award, Car, Bike } from '../components/Icons';
import { KPICard } from '../components/KPICard';
import { EmptyState } from '../components/EmptyState';
import { getKPIs, getTrend, getStateRanking, getCategories, getStates, getTopMakers, getModelBreakdown, getMonthDetail, getAvailableYears } from '../api/vahan';
import { useAppStore } from '../hooks/useAppStore';
import { useSettledLayout } from '../hooks/useSettledLayout';
import { useChartTheme } from '../hooks/useChartTheme';
import { capForDonut, distinctSeriesColors } from '../theme/tokens';
import { useIsLiveData } from '../hooks/useIsLiveData';
import type { MonthDetail } from '../types';

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function PeriodStat({ label, count, growth }: { label: string; count: number; growth: number | null }) {
  return (
    <div className="bg-[var(--bg-sunken)] rounded-xl p-4">
      <p className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] font-mono mb-2">{label}</p>
      <p className="number-display text-xl font-bold text-[var(--text-primary)] mb-2">{count.toLocaleString('en-IN')}</p>
      {growth == null ? (
        <span className="text-[11px] text-[var(--text-muted)] font-mono">YoY N/A — no prior-year data</span>
      ) : (
        <div
          className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded-lg font-mono"
          style={{
            background: growth >= 0 ? 'color-mix(in srgb, var(--success) 15%, transparent)' : 'color-mix(in srgb, var(--danger) 15%, transparent)',
            color: growth >= 0 ? 'var(--success)' : 'var(--danger)',
          }}
        >
          <span className="text-[10px]">{growth >= 0 ? '▲' : '▼'}</span>
          {Math.abs(growth).toFixed(1)}% YoY
        </div>
      )}
    </div>
  );
}

function CustomTooltip({ active, payload, label, chart }: TooltipProps<number, string> & { chart: ReturnType<typeof useChartTheme> }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl px-3 py-2.5" style={{ background: chart.tooltipBg, border: `1px solid ${chart.tooltipBorder}` }}>
      <p className="text-[10px] uppercase tracking-widest mb-1" style={{ color: chart.axisText }}>{label}</p>
      <p className="font-mono text-base font-bold" style={{ color: chart.tooltipText }}>{payload[0].value?.toLocaleString('en-IN')}</p>
      <p className="text-[10px]" style={{ color: chart.axisText }}>registrations</p>
    </div>
  );
}

export function OverviewPage() {
  const chart = useChartTheme();
  const isLiveData = useIsLiveData();
  const {
    selectedYear,
    selectedMonth,
    selectedState,
    selectedCategory,
    selectedMaker,
    selectedModel,
    setSelectedYear,
    setSelectedMonth,
    setSelectedState,
    setSelectedCategory,
    setSelectedMaker,
    setSelectedModel,
  } = useAppStore();

  const { data: statesList } = useQuery({ queryKey: ['states'], queryFn: getStates });
  const { data: availableYears } = useQuery({ queryKey: ['availableYears'], queryFn: getAvailableYears });

  const { data: kpis, isLoading: kpisLoading } = useQuery({
    queryKey: ['kpis', selectedYear, selectedMonth, selectedState, selectedCategory, selectedMaker, selectedModel],
    queryFn: () => getKPIs({
      year: selectedYear,
      month: selectedMonth,
      state: selectedState,
      vehicle_class: selectedCategory,
      maker: selectedMaker,
      vehicle_model: selectedModel
    }),
  });

  const { data: trend, isLoading: trendLoading } = useQuery({
    queryKey: ['trend', selectedYear, selectedState, selectedCategory, selectedMaker, selectedModel],
    queryFn: () => getTrend({
      year: selectedYear,
      state: selectedState,
      vehicle_class: selectedCategory,
      maker: selectedMaker,
      vehicle_model: selectedModel
    }),
  });

  const { data: ranking, isLoading: rankingLoading } = useQuery({
    queryKey: ['stateRanking', selectedYear, selectedMonth, selectedState, selectedCategory, selectedMaker, selectedModel],
    queryFn: () => getStateRanking({
      year: selectedYear,
      month: selectedMonth,
      state: selectedState,
      vehicle_class: selectedCategory,
      maker: selectedMaker,
      vehicle_model: selectedModel,
      limit: 10
    }),
  });

  const { data: categories, isLoading: categoriesLoading } = useQuery({
    queryKey: ['categories', selectedYear, selectedMonth, selectedState, selectedMaker, selectedModel],
    queryFn: () => getCategories({
      year: selectedYear,
      month: selectedMonth,
      state: selectedState,
      maker: selectedMaker,
      vehicle_model: selectedModel
    }),
  });

  // Deliberately NOT filtered by selectedCategory: the live scraper can only
  // pivot one dimension (maker OR vehicle_class) per RTO visit, so the
  // canonical maker-pass rows always store vehicle_class='All' and the
  // vehicle_class-pass rows always store maker=NULL -- maker + a specific
  // category never coexist on the same row for any live-scraped year.
  // Filtering this dropdown by category would always return zero brands.
  const { data: makers } = useQuery({
    queryKey: ['makers', selectedYear, selectedMonth, selectedState],
    queryFn: () => getTopMakers({
      year: selectedYear,
      month: selectedMonth,
      state: selectedState,
      limit: 30
    }),
  });

  const { data: models, isLoading: modelsLoading } = useQuery({
    queryKey: ['models', selectedCategory, selectedMaker, selectedYear, selectedMonth, selectedState],
    queryFn: () => getModelBreakdown({
      vehicle_class: selectedCategory,
      maker: selectedMaker,
      year: selectedYear,
      month: selectedMonth,
      state: selectedState,
      limit: 15
    }),
  });

  // The live VAHAN4 site has no day-level granularity at all -- its finest
  // X-axis option is "Month Wise" (confirmed against the live site's own
  // axis-selector options). A specific-date picker was built against that
  // assumption before this was known; it's replaced with a month + YTD
  // detail driven by the Year/Month filters above, since a real month total
  // (and year-to-date through it) is the finest granularity this data source
  // can ever supply.
  const { data: monthDetail, isLoading: monthDetailLoading, isError: monthDetailError } = useQuery<MonthDetail>({
    queryKey: ['monthDetail', selectedYear, selectedMonth, selectedState, selectedCategory, selectedMaker, selectedModel],
    queryFn: () => getMonthDetail({
      year: selectedYear,
      month: selectedMonth!,
      state: selectedState,
      vehicle_class: selectedCategory,
      maker: selectedMaker,
      vehicle_model: selectedModel,
    }),
    enabled: selectedMonth != null,
  });

  const chartData = (trend || []).map((d: { month?: number; count: number }) => ({
    name: d.month ? MONTH_NAMES[d.month - 1] : '',
    count: d.count,
  }));

  const pieData = capForDonut((categories || []).map((c: { vehicle_class: string; total_count: number }) => ({
    name: c.vehicle_class,
    value: c.total_count,
  })));
  const pieColors = distinctSeriesColors(chart, pieData.map((p) => p.name));
  const vehicleMixReady = useSettledLayout(categoriesLoading);

  // The live scraper can only pivot one dimension (maker OR vehicle_class)
  // per RTO visit, so a category filter and a brand filter can never both
  // match the same row for any live-scraped year -- combining them always
  // zeroes out every KPI. Surfaced explicitly so it reads as a known
  // data-source limitation instead of looking like broken data.
  const impossibleCrossFilter = !!(selectedCategory && selectedMaker);

  const activeFiltersCount = [
    selectedState,
    selectedMonth,
    selectedCategory,
    selectedMaker,
    selectedModel
  ].filter(Boolean).length;

  const handleResetFilters = () => {
    setSelectedState(null);
    setSelectedMonth(null);
    setSelectedCategory(null);
    setSelectedMaker(null);
    setSelectedModel(null);
  };

  const selectClass = "w-full bg-[var(--bg-sunken)] border border-[var(--border)] hover:border-[var(--border-strong)] text-[var(--text-primary)] text-xs font-semibold px-3 py-2 rounded-xl focus:outline-none focus:ring-2 focus:ring-[var(--accent)] transition-all duration-200 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed";

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div className="animate-entrance">
          <h2 className="text-xl font-bold text-[var(--text-primary)] tracking-tight">
            Overview
          </h2>
          <p className="text-xs text-[var(--text-muted)] mt-0.5 font-mono uppercase tracking-widest">
            India Vehicle Registration Observatory — FY {selectedYear}
          </p>
        </div>
        <div className="flex items-center gap-4 text-[10px] text-[var(--text-muted)] font-mono">
          {activeFiltersCount > 0 && (
            <button
              onClick={handleResetFilters}
              className="text-xs text-[var(--accent)] hover:opacity-80 font-semibold transition-opacity bg-[var(--bg-card)] border border-[var(--border)] px-2.5 py-1 rounded-lg"
            >
              Reset Filters ({activeFiltersCount})
            </button>
          )}
          {isLiveData ? (
            <div className="flex items-center gap-1.5" title="Sourced from Parivahan/VAHAN4">
              <div className="w-1.5 h-1.5 rounded-full bg-[var(--success)]" />
              <span>LIVE DATA</span>
            </div>
          ) : (
            <div className="flex items-center gap-1.5" title="Sample data for demonstration — not sourced from Parivahan yet">
              <div className="w-1.5 h-1.5 rounded-full bg-[var(--accent)]" />
              <span>DEMO DATA</span>
            </div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-3 bg-[var(--bg-card)] border border-[var(--border)] p-4 rounded-2xl animate-entrance">
        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] uppercase font-mono tracking-widest text-[var(--text-muted)] font-bold">State</label>
          <select value={selectedState || ''} onChange={(e) => setSelectedState(e.target.value || null)} className={selectClass}>
            <option value="">All States</option>
            {(statesList || []).map((s: { state_name: string }) => (
              <option key={s.state_name} value={s.state_name}>{s.state_name}</option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] uppercase font-mono tracking-widest text-[var(--text-muted)] font-bold">Year</label>
          <select value={selectedYear} onChange={(e) => setSelectedYear(Number(e.target.value))} className={selectClass}>
            {(availableYears || [selectedYear]).map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] uppercase font-mono tracking-widest text-[var(--text-muted)] font-bold">Month</label>
          <select value={selectedMonth || ''} onChange={(e) => setSelectedMonth(e.target.value ? Number(e.target.value) : null)} className={selectClass}>
            <option value="">All Months</option>
            {MONTH_NAMES.map((name, idx) => (
              <option key={name} value={idx + 1}>{name}</option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] uppercase font-mono tracking-widest text-[var(--text-muted)] font-bold">Category</label>
          <select value={selectedCategory || ''} onChange={(e) => setSelectedCategory(e.target.value || null)} className={selectClass}>
            <option value="">All Categories</option>
            {(categories || []).map((c: { vehicle_class: string }) => (
              <option key={c.vehicle_class} value={c.vehicle_class}>{c.vehicle_class}</option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] uppercase font-mono tracking-widest text-[var(--text-muted)] font-bold">OEM / Brand</label>
          <select value={selectedMaker || ''} onChange={(e) => setSelectedMaker(e.target.value || null)} className={selectClass}>
            <option value="">All Brands</option>
            {(makers || []).map((m: { maker: string }) => (
              <option key={m.maker} value={m.maker}>{m.maker}</option>
            ))}
          </select>
          {selectedCategory && (
            <p className="text-[9px] text-[var(--text-muted)] font-mono leading-tight">
              not scoped to {selectedCategory} — VAHAN can't cross maker × category
            </p>
          )}
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] uppercase font-mono tracking-widest text-[var(--text-muted)] font-bold">Vehicle Model</label>
          <select value={selectedModel || ''} onChange={(e) => setSelectedModel(e.target.value || null)} disabled={!selectedMaker} className={selectClass}>
            <option value="">{selectedMaker ? 'All Models' : 'Select OEM first'}</option>
            {selectedMaker && (models || []).map((m: { model: string }) => (
              <option key={m.model} value={m.model}>{m.model}</option>
            ))}
          </select>
        </div>
      </div>

      {impossibleCrossFilter && (
        <div className="bg-[var(--bg-card)] border border-[var(--accent)] rounded-xl px-4 py-2.5 text-xs text-[var(--text-secondary)] animate-entrance">
          <span className="font-semibold text-[var(--accent)]">Category + Brand together always shows 0 —</span>{' '}
          VAHAN's scraper can only capture one of these dimensions per RTO visit, so no row ever has both a specific category and a specific brand for live-scraped years. This isn't missing data, it's a source limitation. Clear one filter to see real numbers.
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <KPICard label="Total Registrations" value={kpis?.total_this_month ?? 0} change={kpis?.yoy_growth_percent} icon={<Car className="w-4 h-4" />} loading={kpisLoading} index={0} />
        <KPICard label="YoY Growth" value={kpis?.yoy_growth_percent ? `${kpis.yoy_growth_percent.toFixed(1)}%` : '—'} change={kpis?.yoy_growth_percent} icon={<TrendingUp className="w-4 h-4" />} loading={kpisLoading} index={1} />
        <KPICard label="Latest Day Sales" value={kpis?.total_registrations_today ?? 0} icon={<Bike className="w-4 h-4" />} loading={kpisLoading} index={2} />
        <KPICard label="Top State" value={kpis?.top_state ?? '—'} icon={<Award className="w-4 h-4" />} loading={kpisLoading} index={3} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div className="xl:col-span-2 bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '200ms' }}>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">Registration Trend</h3>
              <p className="text-[10px] text-[var(--text-muted)] font-mono mt-0.5">Monthly View — FY {selectedYear}</p>
            </div>
            <span className="text-[10px] font-mono px-2 py-1 rounded-md" style={{ color: chart.seriesColors[0], background: 'var(--bg-sunken)' }}>
              MONTHLY
            </span>
          </div>
          {trendLoading ? (
            <div className="h-52 rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft" />
          ) : (
            <ResponsiveContainer width="100%" height={208}>
              <AreaChart data={chartData}>
                <defs>
                  <linearGradient id="gradAccent" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={chart.seriesColors[0]} stopOpacity={0.25} />
                    <stop offset="95%" stopColor={chart.seriesColors[0]} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} tickFormatter={(v: number) => v >= 1000000 ? `${(v/1000000).toFixed(1)}M` : v.toLocaleString('en-IN')} width={45} />
                <Tooltip content={<CustomTooltip chart={chart} />} />
                <Area type="monotone" dataKey="count" stroke={chart.seriesColors[0]} strokeWidth={2.5} fill="url(#gradAccent)" dot={{ r: 3, fill: chart.seriesColors[0], strokeWidth: 0 }} activeDot={{ r: 5, fill: chart.seriesColors[0] }} />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '250ms' }}>
          <div className="mb-4">
            <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">Vehicle Mix</h3>
            <p className="text-[10px] text-[var(--text-muted)] font-mono mt-0.5">by category — {selectedYear}</p>
          </div>
          {categoriesLoading || !vehicleMixReady ? (
            <div className="h-52 rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft" />
          ) : pieData.length === 0 ? (
            <EmptyState
              title="No Category Data"
              description="Run a sync for 'vehicle_class' to load category breakdowns."
              variant="no-data"
              className="py-8"
            />
          ) : (
            <>
              <ResponsiveContainer width="100%" height={160}>
                <PieChart>
                  <Pie data={pieData} cx="50%" cy="50%" innerRadius={45} outerRadius={75} paddingAngle={2} dataKey="value">
                    {pieData.map((p: { name: string }, i: number) => <Cell key={i} fill={pieColors.get(p.name)} />)}
                  </Pie>
                  <Tooltip formatter={(val: number) => [val.toLocaleString('en-IN'), '']} contentStyle={chart.tooltipContentStyle()} {...chart.tooltipTextStyle} />
                </PieChart>
              </ResponsiveContainer>
              <div className="mt-2 space-y-1.5 max-h-28 overflow-y-auto pr-1">
                {pieData.map((p: { name: string; value: number }, i: number) => (
                  <div key={i} className="flex items-center justify-between text-[11px]">
                    <div className="flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-sm" style={{ backgroundColor: pieColors.get(p.name) }} />
                      <span className="text-[var(--text-secondary)] truncate max-w-[100px]">{p.name}</span>
                    </div>
                    <span className="font-mono text-[var(--text-secondary)] font-semibold">{p.value?.toLocaleString('en-IN')}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>

      {/* Always rendered (not just once a month happens to be selected) so this
          feature is discoverable rather than silently absent. Driven by the
          Year/Month filters above rather than its own date picker: VAHAN4 has
          no day-level granularity at all (confirmed against the live site's
          own axis-selector options — its finest is "Month Wise"), so a
          real month total and year-to-date through it are the finest detail
          this data source can ever supply. */}
      <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '280ms' }}>
        <div className="mb-4">
          <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">Month &amp; Year-to-Date Detail</h3>
          <p className="text-[10px] text-[var(--text-muted)] font-mono mt-0.5">
            Select a month above to see its total and year-to-date, each vs. the same point last year
          </p>
        </div>

        {!selectedMonth ? (
          <div className="h-24 flex flex-col items-center justify-center gap-1 text-[var(--text-muted)] text-xs border border-dashed border-[var(--border)] rounded-xl text-center px-4">
            <span>Select a specific month above (not "All Months") for its detail</span>
          </div>
        ) : monthDetailLoading ? (
          <div className="h-24 rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft" />
        ) : monthDetailError || !monthDetail ? (
          <div className="h-24 flex items-center justify-center text-[var(--danger)] text-xs border border-dashed border-[var(--border)] rounded-xl">
            Couldn't load detail for {MONTH_NAMES[selectedMonth - 1]} {selectedYear}
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <PeriodStat label={`${MONTH_NAMES[selectedMonth - 1]} ${selectedYear}`} count={monthDetail.month_count} growth={monthDetail.month_yoy_growth_percent} />
            <PeriodStat label={`Year to Date (through ${MONTH_NAMES[selectedMonth - 1]})`} count={monthDetail.ytd_count} growth={monthDetail.ytd_yoy_growth_percent} />
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '300ms' }}>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">State Ranking</h3>
              <p className="text-[10px] text-[var(--text-muted)] font-mono mt-0.5">Top 10 by registrations</p>
            </div>
          </div>
          {rankingLoading ? (
            <div className="h-44 rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft" />
          ) : (
            <div className="space-y-3 max-h-96 overflow-y-auto pr-1">
              {(ranking || []).map((s: { state_name: string; total_count: number; share_percent: number }, i: number) => {
                const max = (ranking || [])[0]?.total_count || 1;
                const pct = (s.total_count / max) * 100;
                const color = chart.seriesColor(s.state_name);
                return (
                  <div key={s.state_name} className="flex items-center gap-3 group cursor-pointer" onClick={() => setSelectedState(s.state_name)}>
                    <span className="font-mono text-[11px] font-bold text-[var(--text-muted)] w-4 text-right shrink-0">#{i + 1}</span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs font-semibold text-[var(--text-secondary)] group-hover:text-[var(--text-primary)] transition-colors">{s.state_name}</span>
                        <span className="font-mono text-[11px] text-[var(--text-muted)]">{s.share_percent?.toFixed(1)}%</span>
                      </div>
                      <div className="h-1.5 bg-[var(--bg-sunken)] rounded-full overflow-hidden">
                        <div className="h-full rounded-full transition-all duration-700 ease-out" style={{ width: `${pct}%`, backgroundColor: color }} />
                      </div>
                    </div>
                    <span className="font-mono text-[11px] font-bold text-[var(--text-secondary)] w-20 text-right shrink-0">
                      {s.total_count?.toLocaleString('en-IN')}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '350ms' }}>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">Top Vehicle Models</h3>
              <p className="text-[10px] text-[var(--text-muted)] font-mono mt-0.5">
                {selectedMaker ? `${selectedMaker} Models Breakdown` : 'Top Models Breakdown'}
              </p>
            </div>
            {selectedMaker && (
              <button onClick={() => setSelectedMaker(null)} className="text-[9px] uppercase font-mono tracking-wider text-[var(--accent)] hover:opacity-80 transition-opacity">
                Clear Brand
              </button>
            )}
          </div>
          {modelsLoading ? (
            <div className="h-44 rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft" />
          ) : (models || []).length === 0 ? (
            <div className="h-44 flex flex-col items-center justify-center text-[var(--text-muted)] text-xs border border-dashed border-[var(--border)] rounded-xl">
              <span>No vehicle models match the active filters</span>
              <span className="text-[10px] mt-1">Try selecting a different OEM or category</span>
            </div>
          ) : (
            <div className="space-y-3 max-h-96 overflow-y-auto pr-1">
              {(models || []).map((m: { model: string; count: number; share_percent: number }, i: number) => {
                const max = (models || [])[0]?.count || 1;
                const pct = (m.count / max) * 100;
                const color = chart.seriesColor(m.model);
                return (
                  <div key={m.model} className="flex items-center gap-3 group cursor-pointer" onClick={() => setSelectedModel(m.model)}>
                    <span className="font-mono text-[11px] font-bold text-[var(--text-muted)] w-4 text-right shrink-0">#{i + 1}</span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs font-semibold text-[var(--text-secondary)] group-hover:text-[var(--text-primary)] transition-colors">{m.model}</span>
                        <span className="font-mono text-[11px] text-[var(--text-muted)]">{m.share_percent?.toFixed(1)}%</span>
                      </div>
                      <div className="h-1.5 bg-[var(--bg-sunken)] rounded-full overflow-hidden">
                        <div className="h-full rounded-full transition-all duration-700 ease-out" style={{ width: `${pct}%`, backgroundColor: color }} />
                      </div>
                    </div>
                    <span className="font-mono text-[11px] font-bold text-[var(--text-secondary)] w-20 text-right shrink-0">
                      {m.count?.toLocaleString('en-IN')}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {[
          { label: 'States Active', value: '36 / 36', sub: 'All states reporting', colorIdx: 3 },
          { label: 'Avg per State', value: kpis ? Math.round(kpis.total_this_month / 36).toLocaleString('en-IN') : '—', sub: 'registrations per state', colorIdx: 0 },
          { label: 'Peak Trend Point', value: chartData.length > 0 ? chartData.reduce((a: { count: number }, b: { count: number }) => a.count > b.count ? a : b).name : '—', sub: 'highest volume time point', colorIdx: 5 },
        ].map((stat, i) => (
          <div key={i} className="bg-[var(--bg-card)] rounded-xl border border-[var(--border)] p-4 flex items-center gap-4 animate-entrance" style={{ animationDelay: `${350 + i * 60}ms` }}>
            <div className="w-1 h-10 rounded-full" style={{ background: chart.seriesColors[stat.colorIdx] }} />
            <div>
              <p className="text-[10px] uppercase tracking-widest text-[var(--text-muted)]">{stat.label}</p>
              <p className="font-mono text-lg font-bold" style={{ color: chart.seriesColors[stat.colorIdx] }}>{stat.value}</p>
              <p className="text-[10px] text-[var(--text-muted)]">{stat.sub}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
