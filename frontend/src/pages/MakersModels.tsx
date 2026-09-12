// frontend/src/pages/MakersModels.tsx
import { useQuery } from '@tanstack/react-query';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, LabelList } from 'recharts';
import { getTopMakers, getCategories, getFuelBreakdown, getMakerCategoryBreakdown, getMakerFuelBreakdown, getFuelCategoryBreakdown, getAvailableYears } from '../api/vahan';
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
  // comboImpossible (both Category AND Powertrain set) already blocks the
  // whole view with its own "pick one" message below -- without this guard,
  // the title still claimed "(estimated, Jan)" even though nothing is
  // actually shown in that state (found live: monthRatio resolves off
  // whichever of selectedCategory/fuelGroup happens to be checked first,
  // regardless of whether the OTHER one is also set).
  const isEstimated = !!(month && (selectedCategory || fuelGroup) && monthRatio != null && !comboImpossible);
  // For the triple-estimate branch below: whether the month-proration layer
  // has actually resolved and been applied, not just whether a month is
  // picked -- same distinction isEstimated already makes above (found in
  // review: the title/filename were gating on raw `month`, so they could
  // briefly claim "(estimated, Jan)" before monthRatio itself had loaded,
  // while the chart was still only at year-level).
  const tripleMonthApplied = !!(month && monthRatio != null);

  // ---- Maker x Category x Fuel estimate (comboImpossible case) ----
  // No VAHAN table pivots on all three, but all three PAIRWISE cross-tabs
  // are real (Maker x Category, Maker x Fuel, Category x Fuel). The
  // "no three-factor interaction" log-linear model -- the standard
  // technique for estimating a 3-way cell from its three 2-way margins when
  // the full 3-way table isn't observed (used in small-area estimation /
  // synthetic table reconstruction) -- gives, per maker:
  //   cell(m) ~ N * r_mc(m) * r_mf(m) * r_cf / (m_total(m) * c_total * f_total)
  // Verified live before building this: raw per-maker outputs summed to
  // only ~13% of the real Category x Fuel total (r_cf) -- the one-shot
  // closed-form isn't self-consistent with the known margin on its own, so
  // every maker's raw estimate gets rescaled so they sum exactly to r_cf
  // (the one real number we have for the full combo). After rescaling,
  // results tracked real-world knowledge well on a live check (e.g. an
  // EV-only OEM subsidiary came out ~98% EV within its own Four-Wheeler
  // total; a mostly-ICE maker came out under 1%).
  const { data: rMcList, isLoading: rMcLoading } = useQuery({
    queryKey: ['tripleMakerCategory', year, selectedCategory, selectedState],
    queryFn: ({ signal }) => getMakerCategoryBreakdown({ year, vehicle_category: selectedCategory!, state: selectedState, limit: 100 }, signal),
    enabled: comboImpossible,
  });
  const { data: rMfList, isLoading: rMfLoading } = useQuery({
    queryKey: ['tripleMakerFuel', year, fuelGroup, selectedState],
    queryFn: ({ signal }) => getMakerFuelBreakdown({ year, fuel_group: fuelGroup!, state: selectedState, limit: 100 }, signal),
    enabled: comboImpossible,
  });
  const { data: rCfRows, isLoading: rCfLoading } = useQuery({
    queryKey: ['tripleCategoryFuel', year, selectedCategory, fuelGroup, selectedState],
    queryFn: ({ signal }) => getFuelCategoryBreakdown({ year, vehicle_category: selectedCategory!, fuel_group: fuelGroup!, state: selectedState }, signal),
    enabled: comboImpossible,
  });
  const { data: makerYearTotalsList, isLoading: makerYearLoading } = useQuery({
    queryKey: ['tripleMakerYear', year, selectedState],
    queryFn: ({ signal }) => getTopMakers({ year, state: selectedState, limit: 100 }, signal),
    enabled: comboImpossible,
  });
  const { data: allCategoriesForYear, isLoading: allCategoriesLoading } = useQuery({
    queryKey: ['tripleCategoryYear', year, selectedState],
    queryFn: ({ signal }) => getCategories({ year, state: selectedState }, signal),
    enabled: comboImpossible,
  });
  const { data: allFuelsForYear, isLoading: allFuelsLoading } = useQuery({
    queryKey: ['tripleFuelYear', year, selectedState],
    queryFn: () => getFuelBreakdown({ year, state: selectedState }),
    enabled: comboImpossible,
  });
  // Found in review: only tracking one of these six queries' isLoading gave
  // a false "no data" message on essentially the primary way to explore
  // this feature (e.g. toggling ICE/Hybrid/EV) -- rMcList's key doesn't
  // depend on fuelGroup so it stays cached instantly while rMfList/rCfRows
  // are still genuinely refetching for the new fuel group.
  const tripleLoading = comboImpossible && (rMcLoading || rMfLoading || rCfLoading || makerYearLoading || allCategoriesLoading || allFuelsLoading);

  const rCf = (rCfRows || []).find((r: { vehicle_category: string; count: number }) => r.vehicle_category === selectedCategory)?.count;
  const cTotal = (allCategoriesForYear || []).find((c: { vehicle_category: string; total_count: number }) => c.vehicle_category === selectedCategory)?.total_count;
  const fTotal = (allFuelsForYear || []).find((f: { fuel_type: string; count: number }) => f.fuel_type === fuelGroup)?.count;
  const grandTotalN = (allCategoriesForYear || []).reduce((sum: number, c: { total_count: number }) => sum + c.total_count, 0) || undefined;

  const tripleDataReady = comboImpossible && !!rCf && !!cTotal && !!fTotal && !!grandTotalN && !!rMcList && !!rMfList && !!makerYearTotalsList;

  let tripleChartData: { name: string; count: number }[] = [];
  if (tripleDataReady) {
    const mfMap = new Map<string, number>((rMfList || []).map((x: { maker: string; count: number }) => [x.maker, x.count]));
    const myMap = new Map<string, number>((makerYearTotalsList || []).map((x: { maker: string; count: number }) => [x.maker, x.count]));
    type RawEstimate = { name: string; raw: number };
    const raw: RawEstimate[] = (rMcList || [])
      .map((row: { maker: string; count: number }): RawEstimate | null => {
        const rMf = mfMap.get(row.maker);
        const mTotal = myMap.get(row.maker);
        if (!rMf || !mTotal) return null;
        return { name: row.maker, raw: (grandTotalN! * row.count * rMf * rCf!) / (mTotal * cTotal! * fTotal!) };
      })
      .filter((x: RawEstimate | null): x is RawEstimate => x !== null);
    const rawSum = raw.reduce((s: number, x: RawEstimate) => s + x.raw, 0);
    // Rescale so the estimates sum to the one real number we actually have
    // (r_cf) instead of just the raw closed-form output -- see comment above.
    const scale = rawSum > 0 ? rCf! / rawSum : 0;
    tripleChartData = raw
      .map((x: RawEstimate) => ({ name: x.name, count: Math.round(x.raw * scale) }))
      .sort((a: { count: number }, b: { count: number }) => b.count - a.count)
      .slice(0, 20);
    // Same month-proration as the 2-way estimate above, applied on top of
    // the already-modeled year estimate -- compounds two layers of
    // approximation, so this only ever fires when the user has explicitly
    // picked a month too, never silently.
    if (month && monthRatio != null) {
      tripleChartData = tripleChartData.map((d) => ({ name: d.name, count: Math.round(d.count * monthRatio!) }));
    }
  }

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
        <div className="bg-[var(--bg-card)] border border-dashed border-[var(--border)] rounded-xl px-4 py-2.5 text-xs text-[var(--text-secondary)] animate-entrance">
          {tripleLoading ? (
            'Computing an estimate for Maker × Category × Fuel — no VAHAN table has this combination directly…'
          ) : tripleChartData.length === 0 ? (
            <>No real pairwise data to estimate from for <span className="font-semibold text-[var(--accent)]">{selectedCategory}</span> × <span className="font-semibold text-[var(--accent)]">{fuelGroup}</span> in FY {year}. Try a different year, or clear one filter for a real ranking.</>
          ) : (
            <>
              <span className="font-semibold text-[var(--accent)]">Estimated</span> — no VAHAN table pivots on Maker × Category × Fuel together, so this ranking is modeled from the three real pairwise cross-tabs (Maker×{selectedCategory}, Maker×{fuelGroup}, {selectedCategory}×{fuelGroup}) using a standard statistical technique for reconstructing a 3-way total from 2-way margins. It assumes each maker's {fuelGroup} share within {selectedCategory} doesn't diverge from what these three real numbers already imply — treat as a rough approximation, not an observed count.
              {tripleMonthApplied && (
                <> A second layer of modeling is stacked on top for {MONTH_NAMES[month! - 1]}: the FY estimate above is further prorated by {selectedCategory}'s own real month-share of its year total ({(monthRatio! * 100).toFixed(1)}%) — two independent approximations compounded, treat this month-level number with extra caution.</>
              )}
            </>
          )}
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
            {comboImpossible
              ? `Top Manufacturers — ${selectedCategory} × ${fuelGroup}${tripleMonthApplied ? ` (estimated, ${MONTH_NAMES[month! - 1]})` : ' (estimated)'}`
              : selectedCategory || fuelGroup
              ? `Top Manufacturers — ${selectedCategory || fuelGroup}${isEstimated ? ` (estimated, ${MONTH_NAMES[month! - 1]})` : ''}`
              : 'Top Manufacturers'}
          </h3>
          <ExportCsvButton
            filename={comboImpossible
              ? `top-makers-fy${year}-${selectedCategory}-${fuelGroup}-estimated${tripleMonthApplied ? `-${MONTH_NAMES[month! - 1]}` : ''}`
              : `top-makers-fy${year}${selectedCategory ? `-${selectedCategory}` : ''}${fuelGroup ? `-${fuelGroup}` : ''}${isEstimated ? `-est-${MONTH_NAMES[month! - 1]}` : ''}`}
            rows={comboImpossible
              ? tripleChartData.map((d) => ({ maker: d.name, estimated_count: d.count, note: 'modeled from 3 real pairwise cross-tabs, not observed data' }))
              : isEstimated
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
          tripleLoading ? (
            <div className="h-[420px] rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft" />
          ) : tripleChartData.length === 0 ? (
            <EmptyState variant="no-data" title="No estimate available" description="Not enough overlapping real data between the two cross-tabs for this year/state to model a ranking." />
          ) : (
            <ResponsiveContainer width="100%" height={Math.max(280, tripleChartData.length * 38)}>
              <BarChart data={tripleChartData} layout="vertical" margin={{ right: 48 }}>
                <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} />
                <YAxis dataKey="name" type="category" tick={(props) => <TruncatedYAxisTick {...props} fill={chart.axisText} />} width={220} />
                <Tooltip
                  formatter={(val: number) => [`~${val.toLocaleString('en-IN')}`, 'Estimated registrations']}
                  contentStyle={chart.tooltipContentStyle({ fontSize: 12 })} {...chart.tooltipTextStyle}
                />
                <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                  {tripleChartData.map((d) => (
                    <Cell key={d.name} fill={chart.seriesColor(d.name)} />
                  ))}
                  <LabelList dataKey="count" position="right" formatter={(v: number) => `~${v.toLocaleString('en-IN')}`} style={{ fill: chart.axisText, fontSize: 10, fontFamily: 'JetBrains Mono' }} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )
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
