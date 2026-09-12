// frontend/src/pages/MakersModels.tsx
import { useQuery } from '@tanstack/react-query';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, LabelList } from 'recharts';
import { getTopMakers, getCategories, getFuelBreakdown, getMakerCategoryBreakdown, getMakerFuelBreakdown, getAvailableYears } from '../api/vahan';
import { useChartTheme } from '../hooks/useChartTheme';
import { useAppStore } from '../hooks/useAppStore';
import { TruncatedYAxisTick } from '../components/ChartAxisTick';
import { ExportCsvButton } from '../components/ExportCsvButton';
import { EmptyState } from '../components/EmptyState';
import { ErrorBanner } from '../components/ErrorBanner';

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export function MakersModelsPage() {
  const chart = useChartTheme();
  // Year/Month/Category/Powertrain/State are shared across every tab (see
  // useAppStore) -- picking Two-Wheeler here or on Overview shows up on both.
  const {
    selectedYear: year, setSelectedYear: setYear,
    selectedMonth: month, setSelectedMonth: setMonth,
    selectedCategory, setSelectedCategory,
    fuelGroup, setFuelGroup,
    selectedState,
  } = useAppStore();

  const { data: availableYears } = useQuery({ queryKey: ['availableYears'], queryFn: getAvailableYears });
  const { data: categories } = useQuery({
    queryKey: ['categories', year, month],
    queryFn: () => getCategories({ year, month }),
  });

  // Category and Powertrain each have a real Maker cross-tab (Maker x
  // Vehicle Category, Maker x Fuel -- both year-only, no month column, see
  // docs/superpowers/specs/2026-08-25-maker-category-crosstab-design.md),
  // but there's no third cross-tab for all of Maker + Category + Fuel
  // together -- picking both at once is a genuinely unanswerable combo, same
  // structural limit as the Overview page's combined filters. `month` only
  // applies to the plain (no category, no fuel) leaderboard.
  const comboImpossible = !!(selectedCategory && fuelGroup);
  const { data: makers, isLoading: makersLoading, isError: makersError, refetch: refetchMakers } = useQuery({
    queryKey: ['makers-full', year, month, selectedCategory, fuelGroup, selectedState],
    queryFn: ({ signal }) => {
      if (selectedCategory) return getMakerCategoryBreakdown({ year, vehicle_category: selectedCategory, state: selectedState, limit: 20 }, signal);
      if (fuelGroup) return getMakerFuelBreakdown({ year, fuel_group: fuelGroup, state: selectedState, limit: 20 }, signal);
      return getTopMakers({ year, month, state: selectedState, limit: 20 }, signal);
    },
    enabled: !comboImpossible,
  });

  // Neither Maker x Category nor Maker x Fuel has a month column (same
  // structural limit as Overview's FuelCategoryPanel) -- but Category/Fuel
  // ALONE has real month-level data. Estimate each maker's month value by
  // prorating their real FY crosstab count by Category/Fuel's own real
  // month-share of its FY total -- e.g. "Four-Wheeler was 8% of its FY
  // total in August, so assume every maker's Four-Wheeler count was too."
  // One ratio applied uniformly to every maker (not a per-maker curve --
  // that data doesn't exist), so this assumes every maker's seasonal
  // pattern within the category roughly tracks the category's aggregate
  // pattern. Clearly labeled as modeled wherever it's shown, same as
  // Overview's dual-estimate panel.
  const { data: categoryYearTotals } = useQuery({
    queryKey: ['makersCategoryYear', year, selectedState],
    queryFn: ({ signal }) => getCategories({ year, month: null, state: selectedState }, signal),
    enabled: !!selectedCategory && !!month,
  });
  const { data: categoryMonthTotals } = useQuery({
    queryKey: ['makersCategoryMonth', year, month, selectedState],
    queryFn: ({ signal }) => getCategories({ year, month, state: selectedState }, signal),
    enabled: !!selectedCategory && !!month,
  });
  const { data: fuelYearTotals } = useQuery({
    queryKey: ['makersFuelYear', year, selectedState],
    queryFn: () => getFuelBreakdown({ year, month: null, state: selectedState }),
    enabled: !!fuelGroup && !!month,
  });
  const { data: fuelMonthTotals } = useQuery({
    queryKey: ['makersFuelMonth', year, month, selectedState],
    queryFn: () => getFuelBreakdown({ year, month, state: selectedState }),
    enabled: !!fuelGroup && !!month,
  });

  let monthRatio: number | null = null;
  if (month && selectedCategory) {
    const y = (categoryYearTotals || []).find((c: { vehicle_category: string; total_count: number }) => c.vehicle_category === selectedCategory)?.total_count;
    const m = (categoryMonthTotals || []).find((c: { vehicle_category: string; total_count: number }) => c.vehicle_category === selectedCategory)?.total_count;
    monthRatio = (y && m != null) ? m / y : null;
  } else if (month && fuelGroup) {
    const y = (fuelYearTotals || []).find((f: { fuel_type: string; count: number }) => f.fuel_type === fuelGroup)?.count;
    const m = (fuelMonthTotals || []).find((f: { fuel_type: string; count: number }) => f.fuel_type === fuelGroup)?.count;
    monthRatio = (y && m != null) ? m / y : null;
  }
  const isEstimated = !!(month && (selectedCategory || fuelGroup) && monthRatio != null);

  const makerChartData = (makers || []).map((m: { maker: string; count: number }) => ({
    name: m.maker,
    count: isEstimated ? Math.round(m.count * monthRatio!) : m.count,
  }));
  const selectClass = "bg-[var(--bg-sunken)] border border-[var(--border)] text-xs font-semibold px-3 py-2 rounded-xl cursor-pointer";

  return (
    <div className="p-6 space-y-6">
      {makersError && (
        <ErrorBanner
          title="Couldn't load maker data"
          description="The request to the server failed. Check your connection and try again."
          action={{ label: 'Retry', onClick: () => refetchMakers() }}
        />
      )}
      <div className="animate-entrance">
        <h2 className="text-xl font-bold text-[var(--text-primary)] tracking-tight">Makers</h2>
        <p className="text-[10px] text-[var(--text-muted)] mt-0.5 font-mono uppercase tracking-widest">
          Manufacturer leaderboard — FY {year}{selectedState ? ` · ${selectedState}` : ''}
        </p>
      </div>

      <div className="flex items-center gap-3 flex-wrap animate-entrance" style={{ animationDelay: '40ms' }}>
        <select value={year} onChange={(e) => setYear(Number(e.target.value))} className={selectClass}>
          {(availableYears || [year]).map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
        <select
          value={month || ''}
          onChange={(e) => setMonth(e.target.value ? Number(e.target.value) : null)}
          title={(selectedCategory || fuelGroup) ? "Picking a month here shows an ESTIMATE (modeled, not real month-level data) -- see the banner below" : undefined}
          className={selectClass}
        >
          <option value="">All Months</option>
          {MONTH_NAMES.map((name, idx) => (
            <option key={name} value={idx + 1}>{name}</option>
          ))}
        </select>
        <select
          value={selectedCategory || ''}
          onChange={(e) => setSelectedCategory(e.target.value || null)}
          className={selectClass}
        >
          <option value="">All Categories</option>
          {(categories || []).map((c: { vehicle_category: string }) => (
            <option key={c.vehicle_category} value={c.vehicle_category}>{c.vehicle_category}</option>
          ))}
        </select>
        <div className="flex rounded-xl border border-[var(--border)] overflow-hidden h-[34px]">
          {(['ICE', 'Hybrid', 'EV'] as const).map((group) => (
            <button
              key={group}
              onClick={() => setFuelGroup(fuelGroup === group ? null : group)}
              className={`px-3 text-xs font-semibold transition-colors ${
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
      {comboImpossible ? (
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl px-4 py-2.5 text-xs text-[var(--text-secondary)] animate-entrance">
          Category and Powertrain can't be combined here — no VAHAN table pivots on Maker × Category × Fuel together. Clear one of them to see a ranking.
        </div>
      ) : (selectedCategory || fuelGroup) && (
        <div className={`bg-[var(--bg-card)] border rounded-xl px-4 py-2.5 text-xs text-[var(--text-secondary)] animate-entrance ${isEstimated ? 'border-dashed border-[var(--border)]' : 'border-[var(--border)]'}`}>
          {isEstimated ? (
            <>
              <span className="font-semibold text-[var(--accent)]">Estimated</span> — Maker × {selectedCategory || fuelGroup} has no real data for {MONTH_NAMES[month! - 1]}, VAHAN only gives a year total for this combo. Every maker's FY {year} count below is prorated by {selectedCategory || fuelGroup}'s own real month-share of its year total ({(monthRatio! * 100).toFixed(1)}%) — modeled, not observed.
            </>
          ) : month && (selectedCategory || fuelGroup) ? (
            <>Ranked by <span className="font-semibold text-[var(--accent)]">{selectedCategory || fuelGroup}</span> registrations for FY {year} — no data yet to estimate {MONTH_NAMES[month - 1]}, showing the year total instead.</>
          ) : (
            <>Ranked by <span className="font-semibold text-[var(--accent)]">{selectedCategory || fuelGroup}</span> registrations for FY {year} — a year total. Pick a month above for an estimated month-level breakdown.</>
          )}
        </div>
      )}

      <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '80ms' }}>
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">
            {selectedCategory || fuelGroup
              ? `Top Manufacturers — ${selectedCategory || fuelGroup}${isEstimated ? ` (estimated, ${MONTH_NAMES[month! - 1]})` : ''}`
              : 'Top Manufacturers'}
          </h3>
          <ExportCsvButton
            filename={`top-makers-fy${year}${selectedCategory ? `-${selectedCategory}` : ''}${fuelGroup ? `-${fuelGroup}` : ''}${isEstimated ? `-est-${MONTH_NAMES[month! - 1]}` : ''}`}
            rows={isEstimated
              // Export must match what's on screen -- keeps both the real FY
              // total and the modeled estimate as separate labeled columns
              // rather than silently swapping one for the other (found in
              // review: the chart/title showed the estimate, CSV still
              // exported the untouched real year total with no indication).
              ? (makers || []).map((m: { maker: string; count: number }, i: number) => ({
                  maker: m.maker,
                  fy_total: m.count,
                  [`estimated_${MONTH_NAMES[month! - 1].toLowerCase()}_${year}`]: makerChartData[i]?.count,
                  note: 'estimated month count is modeled from the FY total, not observed data',
                }))
              : makers}
          />
        </div>
        {comboImpossible ? (
          <EmptyState variant="no-data" title="Pick one: Category or Powertrain" description="Maker x Category and Maker x Fuel are two separate cross-tabs -- there's no combined Maker x Category x Fuel table to rank against." />
        ) : makersLoading ? (
          <div className="h-[420px] rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft" />
        ) : makerChartData.length === 0 ? (
          <EmptyState
            variant="no-data"
            title={`No maker data for FY ${year}${selectedCategory ? ` / ${selectedCategory}` : ''}${fuelGroup ? ` / ${fuelGroup}` : ''}`}
            description="Try a different year."
          />
        ) : (
          <ResponsiveContainer width="100%" height={Math.max(280, makerChartData.length * 38)}>
            <BarChart data={makerChartData} layout="vertical" margin={{ right: 48 }}>
              <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} horizontal={false} />
              <XAxis type="number" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} />
              <YAxis dataKey="name" type="category" tick={(props) => <TruncatedYAxisTick {...props} fill={chart.axisText} />} width={220} />
              <Tooltip
                formatter={(val: number) => [`${isEstimated ? '~' : ''}${val.toLocaleString('en-IN')}`, isEstimated ? 'Estimated registrations' : 'Registrations']}
                contentStyle={chart.tooltipContentStyle({ fontSize: 12 })} {...chart.tooltipTextStyle}
              />
              <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                {makerChartData.map((d: { name: string }, i: number) => (
                  <Cell key={i} fill={chart.seriesColor(d.name)} />
                ))}
                {/* "~" prefix when estimated matches Overview's dual-estimate
                    panel convention -- a modeled number must never look
                    identical to a real one, even in a screenshot cropped to
                    just the bars (found in review). */}
                <LabelList dataKey="count" position="right" formatter={(v: number) => `${isEstimated ? '~' : ''}${v.toLocaleString('en-IN')}`} style={{ fill: chart.axisText, fontSize: 10, fontFamily: 'JetBrains Mono' }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
