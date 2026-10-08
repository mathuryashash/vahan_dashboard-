// frontend/src/pages/Comparison.tsx
import { useQuery } from '@tanstack/react-query';
import { BarChart, Bar, LabelList, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, TooltipProps } from 'recharts';
import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { getStatesComparison, compareStates, getStates, getCategoryFuelComparison } from '../api/vahan';
import { useCategoriesQuery } from '../hooks/useCategoriesQuery';
import { LoadingBlock } from '../components/LoadingBlock';
import { formatCompact, cyLabel, cyLongLabel } from '../utils/format';
import { useAppStore } from '../hooks/useAppStore';
import { useScopeLock } from '../hooks/useScopeLock';
import { useChartTheme } from '../hooks/useChartTheme';
import { ErrorBanner } from '../components/ErrorBanner';
import { LabeledSelect } from '../components/LabeledSelect';
import { PowertrainToggle } from '../components/PowertrainToggle';

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
  // Category/Powertrain are shared across every tab (see useAppStore) --
  // picking Two-Wheeler on Overview filters this page's comparison too.
  const { selectedYear, selectedState, setSelectedState, selectedCategory, setSelectedCategory, fuelGroup, setFuelGroup } = useAppStore();
  const { isCategoryLocked, lockedCategory } = useScopeLock();
  // State A mirrors the shared selection (see useAppStore) -- picking Bihar
  // on Overview shows Bihar here as one side of the comparison too. State B
  // has no cross-tab equivalent, always a locally-picked second state.
  const [stateA, setStateALocal] = useState(selectedState || 'Maharashtra');
  // State B lives in the URL as `state_b` so a deep link / refresh keeps the
  // pair (State A rides on the shared `state` param). Read once at mount.
  const [stateB, setStateB] = useState(() => {
    const fromUrl = new URLSearchParams(window.location.search).get('state_b');
    const a = selectedState || 'Maharashtra';
    if (fromUrl && fromUrl !== a) return fromUrl;
    return a === 'Gujarat' ? 'Maharashtra' : 'Gujarat';
  });
  const navigate = useNavigate();
  useEffect(() => {
    // Read the LIVE query string (not a render-time snapshot) so the shared
    // filter params written by useUrlSyncedFilters in the same commit survive.
    const next = new URLSearchParams(window.location.search);
    if (next.get('state_b') === stateB) return;
    next.set('state_b', stateB);
    navigate({ search: `?${next.toString()}` }, { replace: true });
  }, [stateB, navigate]);
  const [focusState, setFocusState] = useState<string | null>(null);

  useEffect(() => {
    // Syncing local stateA from the shared Overview-page selection; the
    // effect's own condition (only fire on a real external change) is
    // exactly the dependency-gating the render-time alternative would
    // have to reconstruct anyway.
    if (selectedState && selectedState !== stateA) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setStateALocal(selectedState);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only react to external (Overview) changes, not stateA's own local edits
  }, [selectedState]);

  const setStateA = (value: string) => {
    // Picking B's state as A (e.g. from the ranked tiles) swaps the pair
    // rather than producing a state-vs-itself comparison.
    if (value === stateB) setStateB(stateA);
    setStateALocal(value);
    setSelectedState(value);
  };

  // Shared /categories/ cache entry (all-India, whole year) -- the same one
  // Categories/YoY-era pages use, so switching tabs doesn't re-run it.
  const { data: categories } = useCategoriesQuery({ year: selectedYear });

  // Category x Powertrain can't be answered from the raw Registration table
  // (the class pass carries the category, the fuel pass the fuel, never both
  // on one row) -- that is why this page used to refuse the pair outright.
  // fuel_category_totals DOES cross them per RTO per calendar year and
  // reconciles with the category totals for most years, so the pair is
  // answered from there instead: calendar-year totals per state, no monthly
  // split, and an explicit per-year notice when that year's crosstab is
  // missing or visibly incomplete.
  const crossMode = !!(selectedCategory && fuelGroup);

  const { data: cross, isLoading: crossLoading, isError: crossError, refetch: refetchCross } = useQuery({
    queryKey: ['categoryFuelComparison', selectedYear, selectedCategory, fuelGroup],
    queryFn: () => getCategoryFuelComparison({ year: selectedYear, vehicle_category: selectedCategory!, fuel_group: fuelGroup! }),
    enabled: crossMode,
  });

  const { data: rankedStates, isLoading: rankedLoading } = useQuery({
    queryKey: ['states', selectedYear, selectedCategory, fuelGroup],
    queryFn: () => getStatesComparison(selectedYear, 36, selectedCategory, fuelGroup),
    enabled: !crossMode,
  });
  const allStates = crossMode ? cross?.states : rankedStates;
  const allStatesLoading = crossMode ? crossLoading : rankedLoading;

  // The A/B pickers list which states EXIST, not which ones the current
  // filters happen to return rows for -- sourcing them from the filtered
  // ranking above left both dropdowns permanently empty whenever that ranking
  // came back empty (any impossible combo, or a year with no data yet).
  // /states/ is scope-clamped server-side the same way, so a state-locked
  // user still can't pick someone else's state.
  const { data: pickerStates } = useQuery({
    // Same key Overview/RtoAnalysis use for this endpoint.
    queryKey: ['states'],
    queryFn: getStates,
  });

  // Comparing a state with itself renders two identical bars and reads as a
  // real (if dull) answer. Blocked at the picker (each side's option list
  // omits the other side's state) and, for a URL/store-driven collision,
  // the query doesn't fire and the page says why.
  const sameState = stateA === stateB;
  const { data: comparison, isLoading: comparisonLoading, isError: comparisonError, refetch: refetchComparison } = useQuery({
    queryKey: ['compare', stateA, stateB, selectedYear, selectedCategory, fuelGroup],
    queryFn: () => compareStates(stateA, stateB, selectedYear, selectedCategory, fuelGroup),
    enabled: !!stateA && !crossMode && !sameState,
  });

  const stateOptions = (allStates || []).map((s: { state_name: string }) => s.state_name);
  const pickerOptions: string[] = (pickerStates || []).map((s: { state_name: string }) => s.state_name);
  // Until the list arrives (or if it somehow omits the current selection), the
  // selected value is still its own option -- a <select> can't display a value
  // that isn't one of its options, which is what used to render blank.
  const optionsFor = (value: string, other: string) =>
    (pickerOptions.includes(value) ? pickerOptions : [value, ...pickerOptions]).filter((o) => o === value || o !== other);
  // Merged on the MONTH, never on array position. Each state's series comes
  // from its own GROUP BY and only contains months that have rows, so if B
  // is missing any month A has, a positional merge shifts every later B
  // value up a row and renders it under the wrong month -- silently, with
  // no visual artifact, and only for particular state pairs. Keying by month
  // also keeps a month that exists in B but not A, which the old
  // aData.map() dropped outright.
  const merged = (() => {
    const byMonth = new Map<number, { name: string; [key: string]: string | number }>();
    for (const d of (comparison?.state_a_data || []) as { month: number; count: number }[]) {
      byMonth.set(d.month, { name: MONTH_NAMES[d.month - 1], [stateA]: d.count });
    }
    for (const d of (comparison?.state_b_data || []) as { month: number; count: number }[]) {
      const row = byMonth.get(d.month) ?? { name: MONTH_NAMES[d.month - 1] };
      byMonth.set(d.month, { ...row, [stateB]: d.count });
    }
    return [...byMonth.entries()].sort(([a], [b]) => a - b).map(([, row]) => row);
  })();

  const crossCount = (name: string) => cross?.states.find((r) => r.state_name === name)?.count ?? 0;
  const crossOff = (name: string) => {
    const row = cross?.states.find((r) => r.state_name === name);
    return row?.incomplete ? row.coverage_pct_off : null;
  };
  const totalA = crossMode ? crossCount(stateA) : (comparison?.state_a_data || []).reduce((s: number, d: { count: number }) => s + d.count, 0);
  const totalB = crossMode ? crossCount(stateB) : (comparison?.state_b_data || []).reduce((s: number, d: { count: number }) => s + d.count, 0);
  const totalsLoading = crossMode ? crossLoading : comparisonLoading;
  const crossUnavailable = crossMode && !!cross && !cross.available;

  const colorA = chart.seriesColor(stateA);
  const colorB = chart.seriesColor(stateB);

  return (
    <div className="p-3 sm:p-6 space-y-5">
      {crossError && (
        <ErrorBanner
          title="Couldn't load the category × powertrain comparison"
          description="The request to the server failed. Check your connection and try again."
          action={{ label: 'Retry', onClick: () => refetchCross() }}
        />
      )}
      {comparisonError && (
        <ErrorBanner
          title="Couldn't load comparison data"
          description="The request to the server failed. Check your connection and try again."
          action={{ label: 'Retry', onClick: () => refetchComparison() }}
        />
      )}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div className="animate-entrance">
          <h2 className="text-xl font-bold text-[var(--text-primary)] tracking-tight">State Comparison</h2>
          <p className="text-xs text-[var(--text-muted)] mt-0.5 font-mono uppercase tracking-widest">
            Cross-state registration analysis — {cyLongLabel(selectedYear)}
            {selectedCategory ? ` · ${selectedCategory}` : ''}
            {fuelGroup ? ` · ${fuelGroup}` : ''}
          </p>
          {crossMode && (
            <p className="text-[9px] text-[var(--text-muted)] font-mono leading-tight mt-1" data-testid="cross-source-note">
              Source: VAHAN fuel × vehicle-class report (calendar-year totals, no monthly split)
            </p>
          )}
        </div>
        <div className="flex items-end gap-3 animate-entrance" style={{ animationDelay: '20ms' }}>
          {isCategoryLocked ? (
            // Segment accounts get the locked value, not a dropdown -- same
            // treatment as Overview/Makers. Without this the control offered
            // categories the account can't have, and picking one visibly
            // snapped back as the scope lock reverted it.
            <div className="flex flex-col gap-1.5">
              <span className="text-[10px] uppercase font-mono tracking-widest text-[var(--text-muted)] font-bold">Category</span>
              <div className="bg-[var(--bg-sunken)] border border-[var(--border)] text-[var(--text-primary)] text-xs font-semibold px-3 py-2 rounded-xl cursor-default">{lockedCategory}</div>
            </div>
          ) : (
            <LabeledSelect
              label="Category"
              value={selectedCategory || ''}
              onChange={(e) => setSelectedCategory(e.target.value || null)}
              className="bg-[var(--bg-sunken)] border border-[var(--border)] text-[var(--text-primary)] text-xs font-semibold px-3 py-2 rounded-xl focus:outline-none focus:ring-2 focus:ring-[var(--accent)]"
            >
              <option value="">All Categories</option>
              {(categories || []).map((c: { vehicle_category: string }) => (
                <option key={c.vehicle_category} value={c.vehicle_category}>{c.vehicle_category}</option>
              ))}
            </LabeledSelect>
          )}
          <div className="flex flex-col gap-1.5">
            {/* span, not label: PowertrainToggle is a button group, not a
                single form control a <label> can associate with -- its own
                aria-label carries the accessible name instead. */}
            <span className="text-[10px] uppercase font-mono tracking-widest text-[var(--text-muted)] font-bold">Powertrain</span>
            <PowertrainToggle
              value={fuelGroup}
              onChange={setFuelGroup}
              buttonClassName={(active) => `px-3 text-xs font-semibold transition-colors ${
                active
                  ? 'bg-[var(--accent)] text-[var(--accent-contrast)]'
                  : 'bg-[var(--bg-sunken)] text-[var(--text-secondary)] hover:bg-[var(--bg-card-hover)]'
              }`}
            />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 animate-entrance md:grid-cols-3" style={{ animationDelay: '40ms' }}>
        {[{ label: 'State A', value: stateA, other: stateB, setter: setStateA },
          { label: 'State B', value: stateB, other: stateA, setter: setStateB },
        ].map((s) => (
          <div key={s.label} className="bg-[var(--bg-card)] rounded-xl border border-[var(--border)] p-4">
            <LabeledSelect
              label={s.label}
              value={s.value}
              onChange={(e) => s.setter(e.target.value)}
              className="w-full bg-[var(--bg-sunken)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm font-semibold text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)] transition-colors"
            >
              {optionsFor(s.value, s.other).map((opt) => <option key={opt} value={opt}>{opt}</option>)}
            </LabeledSelect>
          </div>
        ))}
        {/* States with data under the current filters. */}
        {(
          <div className="bg-[var(--bg-card)] rounded-xl border border-[var(--border)] p-4">
            <p className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] font-mono mb-2">States Active</p>
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full" style={{ background: 'var(--success)' }} />
              <span className="font-mono text-[var(--text-primary)] font-bold">{allStatesLoading ? '…' : `${stateOptions.length} / 36`}</span>
            </div>
          </div>
        )}
      </div>

      {crossUnavailable && (
        // Per-year, not a blanket refusal: the crosstab exists for most years.
        <div role="status" className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-6 animate-entrance" data-testid="cross-unavailable">
          <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight mb-2">
            No {selectedCategory} × {fuelGroup} figures for {cyLabel(selectedYear)}
          </h3>
          <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
            {cross?.unanswerable_reason} Pick another year, or clear one filter.
          </p>
        </div>
      )}
      {crossMode && cross?.available && cross.coverage_incomplete && (
        <div role="status" className="bg-[var(--bg-card)] rounded-xl border border-[var(--border)] px-4 py-3 text-xs text-[var(--text-secondary)]" data-testid="cross-incomplete">
          {cyLabel(selectedYear)} is incomplete in this report: its all-category total is {Math.abs(cross.coverage_pct_off ?? 0).toFixed(1)}%
          {(cross.coverage_pct_off ?? 0) < 0 ? ' below' : ' above'} the category totals. States marked * are off by more than 2%.
        </div>
      )}

      {!crossUnavailable && sameState && (
        <div role="status" className="bg-[var(--bg-card)] rounded-xl border border-[var(--border)] px-4 py-3 text-xs text-[var(--text-secondary)]">
          State A and State B are both <span className="font-semibold">{stateA}</span> — pick a different state for B to compare.
        </div>
      )}

      {!crossUnavailable && !sameState && (
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 animate-entrance" style={{ animationDelay: '80ms' }}>
        {[{
          label: stateA, total: totalA, color: colorA,
        }, {
          label: stateB, total: totalB, color: colorB,
        // index key is correct here (not the same-pattern bug as pieData/
        // chartData lists elsewhere): this is a fixed 2-slot A/B pair, not a
        // reorderable list, and card.label is the *selected state name* --
        // colliding when a user picks the same state for both A and B.
        }].map((card, i) => (
          <div key={i} className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5">
            <div className="flex items-center gap-3 mb-3">
              <div className="w-3 h-3 rounded-full" style={{ background: card.color }} />
              <span className="text-xs font-semibold text-[var(--text-secondary)]">{card.label}</span>
            </div>
            {/* A skeleton while loading -- the old `|| 0` printed a confident
                "0" for both states until the request came back. */}
            {totalsLoading ? (
              <div className="h-8 w-32 rounded bg-[var(--bg-sunken)] animate-pulse-soft mb-1" />
            ) : (
              <div className="number-display text-2xl font-bold text-[var(--text-primary)] mb-1 break-words">{(card.total ?? 0).toLocaleString('en-IN')}</div>
            )}
            <p className="text-[11px] text-[var(--text-muted)] font-mono">
              {crossMode ? `${selectedCategory} × ${fuelGroup} registrations ${cyLabel(selectedYear)}` : `Total registrations ${cyLabel(selectedYear)}`}
            </p>
            {crossMode && crossOff(card.label) != null && (
              <p className="text-[10px] text-[var(--warning,var(--text-muted))] font-mono mt-1" data-testid="cross-state-incomplete">
                * this state's {cyLabel(selectedYear)} report is {Math.abs(crossOff(card.label)!).toFixed(1)}% {crossOff(card.label)! < 0 ? 'below' : 'above'} its category totals — treat as incomplete
              </p>
            )}
          </div>
        ))}
      </div>
      )}

      {!crossMode && !sameState && (
      <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '120ms' }}>
        <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight mb-4">{stateA} vs {stateB} — Monthly, {cyLabel(selectedYear)}</h3>
        {comparisonLoading ? <LoadingBlock className="h-[280px]" /> : (
        <div role="img" aria-label={`${stateA} vs ${stateB} monthly registrations, ${cyLabel(selectedYear)}: total ${totalA.toLocaleString('en-IN')} vs ${totalB.toLocaleString('en-IN')}`}>
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={merged} layout="vertical" barGap={6} margin={{ right: 40 }}>
            <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} horizontal={false} />
            <XAxis type="number" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} tickFormatter={formatCompact} />
            <YAxis dataKey="name" type="category" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} width={36} />
            <Tooltip content={<StateTooltip chart={chart} />} />
            <Bar dataKey={stateA} fill={colorA} radius={[0, 3, 3, 0]} maxBarSize={16}>
              <LabelList dataKey={stateA} position="right" formatter={formatCompact} style={{ fill: chart.axisText, fontSize: 9, fontFamily: 'JetBrains Mono' }} />
            </Bar>
            <Bar dataKey={stateB} fill={colorB} radius={[0, 3, 3, 0]} maxBarSize={16}>
              <LabelList dataKey={stateB} position="right" formatter={formatCompact} style={{ fill: chart.axisText, fontSize: 9, fontFamily: 'JetBrains Mono' }} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
        </div>
        )}
        <div className="flex items-center justify-center gap-6 mt-3 text-[11px] font-mono">
          <span style={{ color: colorA }}>{stateA}</span>
          <span style={{ color: colorB }}>{stateB}</span>
        </div>
      </div>
      )}

      {!crossUnavailable && (
      <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '160ms' }}>
        <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight mb-4">All States — Ranked, {cyLabel(selectedYear)}</h3>
        {allStatesLoading ? <LoadingBlock className="h-40" /> : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
          {(allStates || []).map((s: { state_name: string; count: number; share_percent: number; incomplete?: boolean }, i: number) => (
            <button
              key={s.state_name} type="button"
              aria-label={`Set State A to ${s.state_name}`}
              onClick={() => { setStateA(s.state_name); setFocusState(s.state_name); }}
              className="w-full text-left bg-[var(--bg-sunken)] rounded-lg px-3 py-2 cursor-pointer transition-all hover:bg-[var(--bg-card-hover)] border"
              style={{ borderColor: focusState === s.state_name ? 'var(--accent)' : 'transparent' }}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[10px] text-[var(--text-muted)] font-bold w-4">#{i + 1}</span>
                  <span className="text-xs text-[var(--text-secondary)]">{s.state_name}{s.incomplete ? ' *' : ''}</span>
                </div>
                <div className="text-right">
                  <span className="font-mono text-[11px] font-bold text-[var(--text-primary)]">{s.count?.toLocaleString('en-IN')}</span>
                  <span className="font-mono text-[10px] text-[var(--text-muted)] ml-1">{s.share_percent?.toFixed(1)}%</span>
                </div>
              </div>
              <div className="mt-1.5 h-0.5 bg-[var(--bg-card)] rounded-full overflow-hidden">
                <div className="h-full rounded-full" style={{ width: `${s.share_percent}%`, background: chart.seriesColor(s.state_name) }} />
              </div>
            </button>
          ))}
        </div>
        )}
      </div>
      )}
    </div>
  );
}
