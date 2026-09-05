// frontend/src/pages/Overview.tsx
import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, TooltipProps, ResponsiveContainer
} from 'recharts';
import { TrendingUp, Award, Car, Bike } from '../components/Icons';
import { KPICard } from '../components/KPICard';
import { EmptyState } from '../components/EmptyState';
import { ExportCsvButton } from '../components/ExportCsvButton';
import { getKPIs, getTrend, getStateRanking, getCategories, getStates, getTopMakers, getMonthDetail, getAvailableYears, getMakerCategoryBreakdown, getFuelCategoryBreakdown, getMakerFuelBreakdown, getCrosstabCoverage } from '../api/vahan';
import { useAppStore } from '../hooks/useAppStore';
import { useSettledLayout } from '../hooks/useSettledLayout';
import { useChartTheme } from '../hooks/useChartTheme';
import { capForDonut, distinctSeriesColors } from '../theme/tokens';
import { useAuth } from '../contexts/AuthContext';
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
  const auth = useAuth();
  const {
    selectedYear,
    selectedMonth,
    selectedState,
    selectedCategory,
    fuelGroup,
    selectedMaker,
    setSelectedYear,
    setSelectedMonth,
    setSelectedState,
    setSelectedCategory,
    setFuelGroup,
    setSelectedMaker,
  } = useAppStore();

  // State/RTO-scoped users are clamped server-side regardless, but showing
  // them a dropdown for a choice they don't actually have reads as broken --
  // force the shared filter store to their own state and never let it drift,
  // so every existing state-filtered query on this page (and the "click a
  // state to filter" row below) already reflects the lock with no other
  // changes needed.
  const isStateLocked = auth.scope_type !== 'national';
  useEffect(() => {
    if (isStateLocked && selectedState !== auth.scope_state_name) {
      setSelectedState(auth.scope_state_name);
    }
  }, [isStateLocked, auth.scope_state_name, selectedState, setSelectedState]);

  const { data: statesList } = useQuery({ queryKey: ['states'], queryFn: getStates });
  const { data: availableYears } = useQuery({ queryKey: ['availableYears'], queryFn: getAvailableYears });
  // Which years each cross-tab actually has ANY data for -- fetched once
  // here and passed to the three panels below so they can tell "not
  // scraped this year" apart from "scraped, this specific maker/state/fuel
  // combination is a real zero" (a filtered query returns empty for both
  // reasons; only this unfiltered per-year signal disambiguates them).
  const { data: crosstabCoverage } = useQuery({ queryKey: ['crosstabCoverage'], queryFn: getCrosstabCoverage });

  // Any two of {Maker, Vehicle Category, Fuel} together are structurally
  // unanswerable from the raw Registration table (see the impossible*Filter
  // comments below) -- kpis/trend/ranking/monthDetail all sum Registration
  // directly, so all four would silently return a hard 0 for these combos
  // rather than "not available". Computed here (ahead of the flags'
  // declarations further down, which is fine -- these are just booleans)
  // so the queries below can gate on it directly instead of firing a
  // request guaranteed to come back zero.
  const kpiComboImpossible = !!((selectedCategory && selectedMaker) || (selectedCategory && fuelGroup) || (selectedMaker && fuelGroup));
  // Exactly one of the three pairs active (not all three at once) means one
  // of the cross-tab panels below already has the real total -- pull it up
  // here too instead of leaving "Total Registrations" as an unexplained
  // dash when the exact number is visible one panel down. All three filters
  // set at once has no cross-tab that answers it (none of the three pivots
  // cover all of Maker + Category + Fuel together), so that case still
  // falls back to '--'. Same queryKey/queryFn as the matching panel further
  // down -- react-query dedupes this into the same cache entry, so this
  // isn't a second network request.
  const exactlyOnePairActive = [!!selectedCategory, !!selectedMaker, !!fuelGroup].filter(Boolean).length === 2;

  const { data: crosstabMakerCategory, isLoading: crosstabMakerCategoryLoading } = useQuery({
    queryKey: ['makerCategoryBreakdown', selectedYear, selectedCategory, selectedMaker, selectedState],
    queryFn: () => getMakerCategoryBreakdown({ year: selectedYear, vehicle_category: selectedCategory!, maker: selectedMaker!, state: selectedState }),
    enabled: exactlyOnePairActive && !!selectedCategory && !!selectedMaker,
  });
  const { data: crosstabFuelCategory, isLoading: crosstabFuelCategoryLoading } = useQuery({
    queryKey: ['fuelCategoryBreakdown', selectedYear, selectedCategory, fuelGroup, selectedState],
    queryFn: () => getFuelCategoryBreakdown({ year: selectedYear, vehicle_category: selectedCategory!, fuel_group: fuelGroup!, state: selectedState }),
    enabled: exactlyOnePairActive && !!selectedCategory && !!fuelGroup,
  });
  const { data: crosstabMakerFuel, isLoading: crosstabMakerFuelLoading } = useQuery({
    queryKey: ['makerFuelBreakdown', selectedYear, selectedMaker, fuelGroup, selectedState],
    queryFn: () => getMakerFuelBreakdown({ year: selectedYear, maker: selectedMaker!, fuel_group: fuelGroup!, state: selectedState }),
    enabled: exactlyOnePairActive && !!selectedMaker && !!fuelGroup,
  });

  let crosstabTotal: number | undefined;
  let crosstabLoading = false;
  if (exactlyOnePairActive && selectedCategory && selectedMaker) {
    crosstabTotal = (crosstabMakerCategory || []).find((r: { maker: string; count: number }) => r.maker === selectedMaker)?.count;
    crosstabLoading = crosstabMakerCategoryLoading;
  } else if (exactlyOnePairActive && selectedCategory && fuelGroup) {
    crosstabTotal = (crosstabFuelCategory || []).find((r: { vehicle_category: string; count: number }) => r.vehicle_category === selectedCategory)?.count;
    crosstabLoading = crosstabFuelCategoryLoading;
  } else if (exactlyOnePairActive && selectedMaker && fuelGroup) {
    crosstabTotal = (crosstabMakerFuel || []).find((r: { maker: string; count: number }) => r.maker === selectedMaker)?.count;
    crosstabLoading = crosstabMakerFuelLoading;
  }
  // Cross-tabs are year totals, no day-level granularity to divide by the
  // actual elapsed days -- 365 is the same coarse approximation the rest of
  // this page already uses elsewhere for a full-year average.
  const crosstabAvgDaily = crosstabTotal !== undefined ? Math.round(crosstabTotal / 365) : undefined;

  const { data: kpis, isLoading: kpisLoading } = useQuery({
    queryKey: ['kpis', selectedYear, selectedMonth, selectedState, selectedCategory, fuelGroup, selectedMaker],
    queryFn: () => getKPIs({
      year: selectedYear,
      month: selectedMonth,
      state: selectedState,
      vehicle_category: selectedCategory,
      fuel_group: fuelGroup,
      maker: selectedMaker,
    }),
    enabled: !kpiComboImpossible,
  });

  const { data: trend, isLoading: trendLoading } = useQuery({
    queryKey: ['trend', selectedYear, selectedState, selectedCategory, fuelGroup, selectedMaker],
    queryFn: () => getTrend({
      year: selectedYear,
      state: selectedState,
      vehicle_category: selectedCategory,
      fuel_group: fuelGroup,
      maker: selectedMaker,
    }),
    enabled: !kpiComboImpossible,
  });

  const { data: ranking, isLoading: rankingLoading } = useQuery({
    queryKey: ['stateRanking', selectedYear, selectedMonth, selectedState, selectedCategory, fuelGroup, selectedMaker],
    queryFn: () => getStateRanking({
      year: selectedYear,
      month: selectedMonth,
      state: selectedState,
      vehicle_category: selectedCategory,
      fuel_group: fuelGroup,
      maker: selectedMaker,
      limit: 10
    }),
    enabled: !kpiComboImpossible,
  });

  const { data: categories, isLoading: categoriesLoading } = useQuery({
    queryKey: ['categories', selectedYear, selectedMonth, selectedState, selectedMaker],
    queryFn: () => getCategories({
      year: selectedYear,
      month: selectedMonth,
      state: selectedState,
      maker: selectedMaker,
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

  // The live VAHAN4 site has no day-level granularity at all -- its finest
  // X-axis option is "Month Wise" (confirmed against the live site's own
  // axis-selector options). A specific-date picker was built against that
  // assumption before this was known; it's replaced with a month + YTD
  // detail driven by the Year/Month filters above, since a real month total
  // (and year-to-date through it) is the finest granularity this data source
  // can ever supply.
  const { data: monthDetail, isLoading: monthDetailLoading, isError: monthDetailError } = useQuery<MonthDetail>({
    queryKey: ['monthDetail', selectedYear, selectedMonth, selectedState, selectedCategory, fuelGroup, selectedMaker],
    queryFn: () => getMonthDetail({
      year: selectedYear,
      month: selectedMonth!,
      state: selectedState,
      vehicle_category: selectedCategory,
      fuel_group: fuelGroup,
      maker: selectedMaker,
    }),
    enabled: selectedMonth != null && !kpiComboImpossible,
  });

  const chartData = (trend || []).map((d: { month?: number; count: number }) => ({
    name: d.month ? MONTH_NAMES[d.month - 1] : '',
    count: d.count,
  }));

  const pieData = capForDonut((categories || []).map((c: { vehicle_category: string; total_count: number }) => ({
    name: c.vehicle_category,
    value: c.total_count,
  })));
  const pieColors = distinctSeriesColors(chart, pieData.map((p) => p.name));
  const vehicleMixReady = useSettledLayout(categoriesLoading);

  // The KPI cards/trend chart above can't combine Category + Maker (the live
  // scraper's maker-pass and vehicle_class-pass never share a row for the
  // same RTO/month). A real answer for this combination DOES exist though --
  // the separate Maker x Vehicle Class cross-tab (year-only, no month
  // breakdown, see docs/superpowers/specs/2026-08-25-maker-category-crosstab-design.md)
  // -- surfaced below via MakerCategoryPanel instead of leaving this an
  // always-zero dead end.
  const impossibleCrossFilter = !!(selectedCategory && selectedMaker);
  // Same limitation, same fix shape, between Category and Powertrain instead
  // of Category and Maker: the fuel-dimension pass also always stores
  // vehicle_class='All', so fuel_group can't combine with a real category on
  // Registration rows either. FuelCategoryPanel below is sourced from the
  // separate Fuel x Vehicle Class cross-tab (see FuelCategoryTotal).
  const impossibleFuelCategoryFilter = !!(selectedCategory && fuelGroup);
  // Third pairing of {Maker, Vehicle Class, Fuel}: a maker name and a real
  // fuel_type never coexist on the same Registration row either, so
  // selecting a Brand/OEM together with the Powertrain filter always
  // zeroed out. MakerFuelPanel below is sourced from the separate Maker x
  // Fuel cross-tab (see MakerFuelTotal).
  const impossibleMakerFuelFilter = !!(selectedMaker && fuelGroup);

  const activeFiltersCount = [
    selectedState,
    selectedMonth,
    selectedCategory,
    fuelGroup,
    selectedMaker,
  ].filter(Boolean).length;

  const handleResetFilters = () => {
    setSelectedState(null);
    setSelectedMonth(null);
    setSelectedCategory(null);
    setFuelGroup(null);
    setSelectedMaker(null);
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
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-7 gap-3 bg-[var(--bg-card)] border border-[var(--border)] p-4 rounded-2xl animate-entrance">
        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] uppercase font-mono tracking-widest text-[var(--text-muted)] font-bold">State</label>
          {isStateLocked ? (
            <div className={`${selectClass} cursor-default hover:border-[var(--border)]`}>{auth.scope_state_name}</div>
          ) : (
            <select value={selectedState || ''} onChange={(e) => setSelectedState(e.target.value || null)} className={selectClass}>
              <option value="">All States</option>
              {(statesList || []).map((s: { state_name: string }) => (
                <option key={s.state_name} value={s.state_name}>{s.state_name}</option>
              ))}
            </select>
          )}
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
            {(categories || []).map((c: { vehicle_category: string }) => (
              <option key={c.vehicle_category} value={c.vehicle_category}>{c.vehicle_category}</option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] uppercase font-mono tracking-widest text-[var(--text-muted)] font-bold">Powertrain</label>
          <div className="flex rounded-xl border border-[var(--border)] overflow-hidden h-[34px]">
            {(['ICE', 'Hybrid', 'EV'] as const).map((group) => (
              <button
                key={group}
                onClick={() => setFuelGroup(fuelGroup === group ? null : group)}
                className={`flex-1 text-xs font-semibold transition-colors ${
                  fuelGroup === group
                    ? 'bg-[var(--accent)] text-[var(--accent-contrast)]'
                    : 'bg-[var(--bg-sunken)] text-[var(--text-secondary)] hover:bg-[var(--bg-card-hover)]'
                }`}
              >
                {group}
              </button>
            ))}
          </div>
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
          {fuelGroup && (
            <p className="text-[9px] text-[var(--text-muted)] font-mono leading-tight">
              not scoped to {fuelGroup} — VAHAN can't cross maker × fuel here, see panel below
            </p>
          )}
        </div>
      </div>

      {impossibleCrossFilter && (
        <MakerCategoryPanel
          year={selectedYear}
          category={selectedCategory!}
          maker={selectedMaker!}
          month={selectedMonth}
          state={selectedState}
          hasYearData={crosstabCoverage ? crosstabCoverage.maker_category.includes(selectedYear) : true}
        />
      )}

      {impossibleFuelCategoryFilter && (
        <FuelCategoryPanel
          year={selectedYear}
          category={selectedCategory!}
          fuelGroup={fuelGroup!}
          month={selectedMonth}
          state={selectedState}
          hasYearData={crosstabCoverage ? crosstabCoverage.fuel_category.includes(selectedYear) : true}
        />
      )}

      {impossibleMakerFuelFilter && (
        <MakerFuelPanel
          year={selectedYear}
          maker={selectedMaker!}
          fuelGroup={fuelGroup!}
          month={selectedMonth}
          hasYearData={crosstabCoverage ? crosstabCoverage.maker_fuel.includes(selectedYear) : true}
          state={selectedState}
        />
      )}

      {kpiComboImpossible && (
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl px-4 py-2.5 text-xs text-[var(--text-secondary)] animate-entrance">
          {exactlyOnePairActive
            ? <>Total Registrations and Avg Daily below are sourced from the cross-tab panel (a <span className="font-semibold text-[var(--accent)]">year total</span>, not this month) since VAHAN has no single table for this combination. YoY Growth and Top State genuinely aren't computable from a year-only total.</>
            : <>Totals below aren't available with all three of Category, Brand, and Powertrain selected together — no VAHAN table pivots on all three at once. Drop one of them, or see the cross-tab panels below for any two together.</>}
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <KPICard
          label="Total Registrations"
          value={kpiComboImpossible ? (crosstabTotal ?? '—') : (kpis?.total_this_month ?? 0)}
          change={kpiComboImpossible ? undefined : kpis?.yoy_growth_percent}
          icon={<Car className="w-4 h-4" />}
          loading={kpiComboImpossible ? crosstabLoading : kpisLoading}
          index={0}
        />
        <KPICard label="YoY Growth" value={kpiComboImpossible ? '—' : (kpis?.yoy_growth_percent ? `${kpis.yoy_growth_percent.toFixed(1)}%` : '—')} change={kpiComboImpossible ? undefined : kpis?.yoy_growth_percent} icon={<TrendingUp className="w-4 h-4" />} loading={kpisLoading} index={1} />
        <KPICard
          label="Avg Daily Registrations"
          value={kpiComboImpossible ? (crosstabAvgDaily ?? '—') : (kpis?.total_registrations_today ?? 0)}
          icon={<Bike className="w-4 h-4" />}
          loading={kpiComboImpossible ? crosstabLoading : kpisLoading}
          index={2}
        />
        <KPICard label="Top State" value={kpiComboImpossible ? '—' : (kpis?.top_state ?? '—')} icon={<Award className="w-4 h-4" />} loading={kpisLoading} index={3} />
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

      <div className="grid grid-cols-1 gap-4">
        <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '300ms' }}>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">State Ranking</h3>
              <p className="text-[10px] text-[var(--text-muted)] font-mono mt-0.5">Top 10 by registrations</p>
            </div>
            <ExportCsvButton filename={`state-ranking-fy${selectedYear}`} rows={ranking} />
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

/** Real Category + Maker combined data, from the separate Maker x Vehicle
 * Class cross-tab (year-only, no month breakdown -- see
 * docs/superpowers/specs/2026-08-25-maker-category-crosstab-design.md).
 * Rendered only when both selectedCategory and selectedMaker are set. */
function MakerCategoryPanel({ year, category, maker, month, state, hasYearData }: { year: number; category: string; maker: string; month: number | null; state: string | null; hasYearData: boolean }) {
  const { data, isLoading } = useQuery({
    queryKey: ['makerCategoryBreakdown', year, category, maker, state],
    queryFn: () => getMakerCategoryBreakdown({ year, vehicle_category: category, maker, state }),
  });

  // hasYearData (from /categories/crosstab-coverage, fetched once by the
  // parent) says whether this crosstab has ANY rows for `year` -- an empty
  // *filtered* response here is ambiguous between "not scraped this year"
  // and "this exact maker/state/category combo is a real zero" (confirmed
  // live: TVS Motor Company has real 2025 data but legitimately zero
  // Four-Wheeler rows in some states). Only the unfiltered per-year signal
  // can tell those apart -- a plain `data.length === 0` check can't.
  // `?? 0` reads as "zero registrations" when the honest answer is "not
  // scraped for this year yet".
  const noDataForYear = !hasYearData;
  const count = (data || []).find((r: { maker: string; count: number }) => r.maker === maker)?.count ?? 0;

  return (
    <div className="bg-[var(--bg-card)] border border-[var(--accent)] rounded-xl px-4 py-3 text-xs text-[var(--text-secondary)] animate-entrance">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <span>
          <span className="font-semibold text-[var(--accent)]">{maker}</span> in{' '}
          <span className="font-semibold text-[var(--accent)]">{category}</span>, FY {year}
          {state && <> · {state}</>}:
        </span>
        {isLoading ? (
          <span className="font-mono text-sm font-bold animate-pulse-soft">···</span>
        ) : noDataForYear ? (
          <span className="font-mono text-xs text-[var(--text-muted)]">not scraped for FY {year}</span>
        ) : (
          <span className="font-mono text-sm font-bold text-[var(--text-primary)]">{count.toLocaleString('en-IN')}</span>
        )}
      </div>
      {month && (
        <p className="text-[10px] text-[var(--text-muted)] mt-1">
          This is a year total — the underlying data has no month breakdown, so the Month filter doesn't apply here.
        </p>
      )}
    </div>
  );
}

/** Same shape as MakerCategoryPanel, sourced from the separate Fuel x
 * Vehicle Class cross-tab (see FuelCategoryTotal / fuel-category-breakdown).
 * Rendered only when both selectedCategory and fuelGroup are set. */
function FuelCategoryPanel({ year, category, fuelGroup, month, state, hasYearData }: { year: number; category: string; fuelGroup: string; month: number | null; state: string | null; hasYearData: boolean }) {
  const { data, isLoading } = useQuery({
    queryKey: ['fuelCategoryBreakdown', year, category, fuelGroup, state],
    queryFn: () => getFuelCategoryBreakdown({ year, vehicle_category: category, fuel_group: fuelGroup, state }),
  });

  // See MakerCategoryPanel's comment above -- hasYearData (not an empty
  // filtered response) tells "not scraped this year" apart from a real zero.
  const noDataForYear = !hasYearData;
  const count = (data || []).find((r: { vehicle_category: string; count: number }) => r.vehicle_category === category)?.count ?? 0;

  return (
    <div className="bg-[var(--bg-card)] border border-[var(--accent)] rounded-xl px-4 py-3 text-xs text-[var(--text-secondary)] animate-entrance">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <span>
          <span className="font-semibold text-[var(--accent)]">{fuelGroup}</span> {category}, FY {year}
          {state && <> · {state}</>}:
        </span>
        {isLoading ? (
          <span className="font-mono text-sm font-bold animate-pulse-soft">···</span>
        ) : noDataForYear ? (
          <span className="font-mono text-xs text-[var(--text-muted)]">not scraped for FY {year}</span>
        ) : (
          <span className="font-mono text-sm font-bold text-[var(--text-primary)]">{count.toLocaleString('en-IN')}</span>
        )}
      </div>
      {month && (
        <p className="text-[10px] text-[var(--text-muted)] mt-1">
          This is a year total — the underlying data has no month breakdown, so the Month filter doesn't apply here.
        </p>
      )}
    </div>
  );
}

/** Same shape as MakerCategoryPanel/FuelCategoryPanel, sourced from the
 * separate Maker x Fuel cross-tab (see MakerFuelTotal /
 * maker-fuel-breakdown). Rendered only when both selectedMaker and
 * fuelGroup are set. */
function MakerFuelPanel({ year, maker, fuelGroup, month, state, hasYearData }: { year: number; maker: string; fuelGroup: string; month: number | null; state: string | null; hasYearData: boolean }) {
  const { data, isLoading } = useQuery({
    queryKey: ['makerFuelBreakdown', year, maker, fuelGroup, state],
    queryFn: () => getMakerFuelBreakdown({ year, maker, fuel_group: fuelGroup, state }),
  });

  // /maker-fuel-breakdown returns one row keyed by "maker" (not "fuel_group")
  // when both maker and fuel_group are passed together -- both are always
  // set here, since this panel only renders when they both are (see
  // impossibleMakerFuelFilter). Matches how FuelCategoryPanel reads its own
  // sibling endpoint's "both given" shape (keyed by "vehicle_category", not
  // "fuel_group") a few lines up. Searching for r.fuel_group here (a field
  // this response shape never has) always returned undefined -- silently
  // showing 0 for every maker+fuel combination regardless of real data.
  // See MakerCategoryPanel's comment above -- hasYearData (not an empty
  // filtered response) tells "not scraped this year" apart from a real
  // zero (confirmed live: TVS Motor Company has real 2025 maker-fuel data
  // but legitimately zero Hybrid-bucket rows in Bihar specifically).
  const noDataForYear = !hasYearData;
  const count = (data || []).find((r: { maker: string; count: number }) => r.maker === maker)?.count ?? 0;

  return (
    <div className="bg-[var(--bg-card)] border border-[var(--accent)] rounded-xl px-4 py-3 text-xs text-[var(--text-secondary)] animate-entrance">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <span>
          <span className="font-semibold text-[var(--accent)]">{maker}</span> — <span className="font-semibold text-[var(--accent)]">{fuelGroup}</span>, FY {year}
          {state && <> · {state}</>}:
        </span>
        {isLoading ? (
          <span className="font-mono text-sm font-bold animate-pulse-soft">···</span>
        ) : noDataForYear ? (
          <span className="font-mono text-xs text-[var(--text-muted)]">not scraped for FY {year}</span>
        ) : (
          <span className="font-mono text-sm font-bold text-[var(--text-primary)]">{count.toLocaleString('en-IN')}</span>
        )}
      </div>
      {month && (
        <p className="text-[10px] text-[var(--text-muted)] mt-1">
          This is a year total — the underlying data has no month breakdown, so the Month filter doesn't apply here.
        </p>
      )}
    </div>
  );
}
