// frontend/src/pages/Comparison.tsx
import { useQuery } from '@tanstack/react-query';
import { BarChart, Bar, LabelList, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, TooltipProps } from 'recharts';
import { useState, useEffect } from 'react';
import { getStatesComparison, compareStates, getCategories, getStates } from '../api/vahan';
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
  const [stateB, setStateB] = useState('Gujarat');
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
    setStateALocal(value);
    setSelectedState(value);
  };

  const { data: categories } = useQuery({
    queryKey: ['categories', selectedYear],
    queryFn: () => getCategories({ year: selectedYear }),
  });

  // Category x Powertrain can never be answered from the raw Registration
  // table: the vehicle_class-dimension pass is the only one carrying a real
  // vehicle_category and the fuel-dimension pass the only one carrying a real
  // fuel_type, and the scraper never writes both on one row. Same flag as
  // Overview's impossibleFuelCategoryFilter. Both queries below return a
  // structurally-guaranteed empty result for such a combo, so don't fire them
  // -- the sections they feed are hidden instead of rendering zeros.
  const comboImpossible = !!(selectedCategory && fuelGroup);

  const { data: allStates } = useQuery({
    queryKey: ['states', selectedYear, selectedCategory, fuelGroup],
    queryFn: () => getStatesComparison(selectedYear, 36, selectedCategory, fuelGroup),
    enabled: !comboImpossible,
  });

  // The A/B pickers list which states EXIST, not which ones the current
  // filters happen to return rows for -- sourcing them from the filtered
  // ranking above left both dropdowns permanently empty whenever that ranking
  // came back empty (any impossible combo, or a year with no data yet).
  // /states/ is scope-clamped server-side the same way, so a state-locked
  // user still can't pick someone else's state.
  const { data: pickerStates } = useQuery({
    queryKey: ['states-all'],
    queryFn: getStates,
  });

  const { data: comparison, isError: comparisonError, refetch: refetchComparison } = useQuery({
    queryKey: ['compare', stateA, stateB, selectedYear, selectedCategory, fuelGroup],
    queryFn: () => compareStates(stateA, stateB, selectedYear, selectedCategory, fuelGroup),
    enabled: !!stateA && !comboImpossible,
  });

  const stateOptions = (allStates || []).map((s: { state_name: string }) => s.state_name);
  const pickerOptions: string[] = (pickerStates || []).map((s: { state_name: string }) => s.state_name);
  // Until the list arrives (or if it somehow omits the current selection), the
  // selected value is still its own option -- a <select> can't display a value
  // that isn't one of its options, which is what used to render blank.
  const optionsFor = (value: string) => (pickerOptions.includes(value) ? pickerOptions : [value, ...pickerOptions]);
  const aData: { name: string; [key: string]: string | number }[] = (comparison?.state_a_data || []).map((d: { month: number; count: number }) => ({ name: MONTH_NAMES[d.month - 1], [stateA]: d.count }));
  const bData: { name: string; [key: string]: string | number }[] = (comparison?.state_b_data || []).map((d: { month: number; count: number }) => ({ name: MONTH_NAMES[d.month - 1], [stateB]: d.count }));

  const merged = aData.map((d, i) => ({ ...d, ...(bData[i] || {}) }));

  const totalA = (comparison?.state_a_data || []).reduce((s: number, d: { count: number }) => s + d.count, 0);
  const totalB = (comparison?.state_b_data || []).reduce((s: number, d: { count: number }) => s + d.count, 0);

  const colorA = chart.seriesColor(stateA);
  const colorB = chart.seriesColor(stateB);

  return (
    <div className="p-6 space-y-5">
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
            Cross-state registration analysis — FY {selectedYear}
            {selectedCategory ? ` · ${selectedCategory}` : ''}
            {fuelGroup ? ` · ${fuelGroup}` : ''}
          </p>
          {comboImpossible && (
            <p className="text-[9px] text-[var(--text-muted)] font-mono leading-tight mt-1">
              VAHAN can't cross category × powertrain — drop one filter to compare states
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

      <div className={`grid grid-cols-1 gap-4 animate-entrance ${comboImpossible ? 'md:grid-cols-2' : 'md:grid-cols-3'}`} style={{ animationDelay: '40ms' }}>
        {[{ label: 'State A', value: stateA, setter: setStateA },
          { label: 'State B', value: stateB, setter: setStateB },
        ].map((s) => (
          <div key={s.label} className="bg-[var(--bg-card)] rounded-xl border border-[var(--border)] p-4">
            <LabeledSelect
              label={s.label}
              value={s.value}
              onChange={(e) => s.setter(e.target.value)}
              className="w-full bg-[var(--bg-sunken)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm font-semibold text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)] transition-colors"
            >
              {optionsFor(s.value).map((opt) => <option key={opt} value={opt}>{opt}</option>)}
            </LabeledSelect>
          </div>
        ))}
        {/* States with data under the current filters -- meaningless (and
            always 0) when the filters can't co-exist, so it goes away with
            the ranking it summarises. */}
        {!comboImpossible && (
          <div className="bg-[var(--bg-card)] rounded-xl border border-[var(--border)] p-4">
            <p className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] font-mono mb-2">States Active</p>
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full" style={{ background: 'var(--success)' }} />
              <span className="font-mono text-[var(--text-primary)] font-bold">{stateOptions.length} / 36</span>
            </div>
          </div>
        )}
      </div>

      {!comboImpossible && (
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
            <div className="number-display text-2xl font-bold text-[var(--text-primary)] mb-1">{card.total?.toLocaleString('en-IN') || 0}</div>
            <p className="text-[11px] text-[var(--text-muted)] font-mono">
              Total registrations FY {selectedYear}
            </p>
          </div>
        ))}
      </div>
      )}

      {!comboImpossible && (
      <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '120ms' }}>
        <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight mb-4">{stateA} vs {stateB} — Monthly</h3>
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={merged} layout="vertical" barGap={6} margin={{ right: 40 }}>
            <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} horizontal={false} />
            <XAxis type="number" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${(v/1000).toFixed(0)}K`} />
            <YAxis dataKey="name" type="category" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} width={36} />
            <Tooltip content={<StateTooltip chart={chart} />} />
            <Bar dataKey={stateA} fill={colorA} radius={[0, 3, 3, 0]} maxBarSize={16}>
              <LabelList dataKey={stateA} position="right" formatter={(v: number) => `${(v / 1000).toFixed(0)}K`} style={{ fill: chart.axisText, fontSize: 9, fontFamily: 'JetBrains Mono' }} />
            </Bar>
            <Bar dataKey={stateB} fill={colorB} radius={[0, 3, 3, 0]} maxBarSize={16}>
              <LabelList dataKey={stateB} position="right" formatter={(v: number) => `${(v / 1000).toFixed(0)}K`} style={{ fill: chart.axisText, fontSize: 9, fontFamily: 'JetBrains Mono' }} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
        <div className="flex items-center justify-center gap-6 mt-3 text-[11px] font-mono">
          <span style={{ color: colorA }}>{stateA}</span>
          <span style={{ color: colorB }}>{stateB}</span>
        </div>
      </div>
      )}

      {!comboImpossible && (
      <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '160ms' }}>
        <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight mb-4">All States — Ranked</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
          {(allStates || []).map((s: { state_name: string; count: number; share_percent: number }, i: number) => (
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
            </button>
          ))}
        </div>
      </div>
      )}
    </div>
  );
}
