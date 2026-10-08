import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { isAxiosError } from 'axios';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, LabelList } from 'recharts';
import { MAKER_FUEL_GROUPS, getLiveMakerLeaderboard, getLiveMakerQuery, getMakerOptions, getStates } from '../api/vahan';
import { useAppStore } from '../hooks/useAppStore';
import { useAuth } from '../contexts/AuthContext';
import { formatCompact } from '../utils/format';
import { useChartTheme } from '../hooks/useChartTheme';
import { TruncatedYAxisTick } from './ChartAxisTick';
import { LabeledSelect } from './LabeledSelect';
import { EmptyState } from './EmptyState';
import { ErrorBanner } from './ErrorBanner';
import { SearchableSelect } from './SearchableSelect';

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

// Six fuel groups instead of VAHAN's ~34 raw labels; the server folds every
// raw label into one of them (backend services/fuel_groups.py), so picking
// "Petrol" sums PETROL, PETROL(E20), PETROL/ETHANOL, ...
const FUEL_GROUP_HINT: Record<string, string> = {
  Petrol: 'Petrol, E20, petrol/ethanol', Diesel: 'Diesel, bio-diesel', 'CNG/LPG': 'CNG, LPG, LNG and bi-fuel',
  Electric: 'Battery EV, fuel cell', Hybrid: 'Strong / plug-in / mild hybrids', Other: 'Ethanol, methanol, solar, n/a',
};

// The backend gives each failure mode a distinct status specifically so the
// caller can explain what actually happened (bad state vs. rate-limited vs.
// the source site being unreachable vs. OCR not ready) -- worth reading
// here rather than collapsing to one generic "request failed" message the
// way cheap DB-query endpoints elsewhere on this page do.
function errorMessageFor(error: unknown): string {
  const status = isAxiosError(error) ? error.response?.status : undefined;
  switch (status) {
    case 404: return 'Unknown state -- pick a different one.';
    case 429: return 'Too many live lookups in a row -- wait a minute and try again.';
    case 502: return 'Could not reach the source site right now. Try again shortly.';
    case 503: return 'Live lookups are temporarily unavailable on the server right now.';
    default: return 'Something went wrong loading this combination.';
  }
}

/** Where a live-query answer came from. Newer backends answer some lookups
 * from data already in our tables (`source: 'stored'`, `as_of` = when that
 * data was scraped) instead of a fresh scrape; showing "live" wording over
 * a stored answer overstated its freshness. Older backends send neither
 * field, which keeps the original live wording. */
export function formatAsOf(asOf: string | null | undefined): string {
  if (!asOf) return 'an earlier scrape';
  const d = new Date(asOf);
  if (Number.isNaN(d.getTime())) return asOf;
  // Date-only strings ("2026-09-30") have no time worth showing.
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(asOf);
  return d.toLocaleString('en-IN', dateOnly
    ? { day: 'numeric', month: 'short', year: 'numeric' }
    : { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function SourceNote({ source, asOf }: { source?: string; asOf?: string | null }) {
  if (source === 'stored') {
    return (
      <p className="text-[10px] font-mono text-[var(--text-muted)] mb-2" data-testid="live-source-note">
        Stored data as of {formatAsOf(asOf)}.
      </p>
    );
  }
  return (
    <p className="text-[10px] font-mono text-[var(--text-muted)] mb-2" data-testid="live-source-note">
      Fetched live{asOf ? ` · ${formatAsOf(asOf)}` : ''}.
    </p>
  );
}

export function LiveMakerQueryPanel({ year, onStateCodeChange, rtoScope }: {
  year: number;
  onStateCodeChange?: (stateCode: string | null) => void;
  // Set by the RTO Analysis page, which has already picked a state AND an
  // RTO: the panel then drops its own State dropdown (that page has one
  // above it -- two would be ambiguous) and scopes every lookup to that one
  // RTO. One prop, not two, so the state and the RTO can't drift apart.
  // Undefined (the Makers page) means the whole state, as before.
  rtoScope?: { stateCode: string; rtoCode: string; rtoName: string };
}) {
  const auth = useAuth();
  const { selectedState, selectedCategory } = useAppStore();
  const { data: states, isLoading: statesLoading } = useQuery({ queryKey: ['states'], queryFn: getStates });

  // This page has no state selector of its own elsewhere (found in review:
  // MakersModels' filter bar is Year/Month/Category/Powertrain only), so a
  // national user landing here directly -- a bookmark, a refresh, a link --
  // would otherwise hit a dead end with nowhere to pick a state. This panel
  // gets its own, defaulted once from the shared selection (Overview/
  // Comparison/RTO Analysis) if one already exists, but editable here after
  // that without fighting the shared store.
  const [localStateCode, setLocalStateCode] = useState('');
  useEffect(() => {
    if (auth.scope_type !== 'national' || localStateCode || !selectedState || !states) return;
    const match = states.find((s: { state_code: string; state_name: string }) => s.state_name === selectedState);
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (match) setLocalStateCode(match.state_code);
  }, [selectedState, states, auth.scope_type, localStateCode]);

  const stateCode = rtoScope ? rtoScope.stateCode : (auth.scope_type !== 'national' ? auth.scope_state_code : (localStateCode || null));

  // Shares this one state selection with the sibling leaderboard panel
  // below -- two independent "State" dropdowns on the same page would be
  // confusing (which one applies to what?), so this is the only one; the
  // parent page passes the resolved code down to the leaderboard panel.
  useEffect(() => {
    onStateCodeChange?.(stateCode);
  }, [stateCode, onStateCodeChange]);

  const [fuel, setFuel] = useState('');
  const [maker, setMaker] = useState('');
  const [submitted, setSubmitted] = useState<{ maker: string; fuel: string; category: string | null } | null>(null);

  // The Maker dropdown lists ONLY makers with stored registrations for this
  // state (+ RTO) + year + fuel group, biggest first, scope-clamped by the
  // server -- so a combination with nothing in it (Karnataka x Hero x
  // Diesel) can't be picked in the first place.
  const { data: makerOptions, isFetching: makerOptionsLoading } = useQuery({
    queryKey: ['makerOptions', stateCode, year, fuel, rtoScope?.rtoCode, selectedCategory],
    queryFn: ({ signal }) => getMakerOptions({
      state_code: stateCode!, year, fuel_group: fuel || null, rto: rtoScope?.rtoCode ?? null,
      vehicle_category: selectedCategory,
    }, signal),
    enabled: !!stateCode,
    staleTime: 5 * 60 * 1000,
  });
  const optionList = makerOptions?.makers ?? [];
  // A maker the new fuel / state / year doesn't carry is dropped, not kept
  // as a stale pick that would come back empty.
  useEffect(() => {
    if (maker && makerOptions && !makerOptions.makers.some((m) => m.maker === maker)) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setMaker('');
    }
  }, [maker, makerOptions]);
  const liveWording = !!makerOptions?.live_fallback;
  // ErrorBanner hides itself on its own Retry click (before the retry's
  // outcome is known), so re-mount it fresh per attempt -- otherwise a
  // second failure in a row (a real case for 502/503/429) shows no banner
  // at all and the Retry button becomes a silent no-op (found in review).
  const [attempt, setAttempt] = useState(0);

  const { data, isFetching, isError, error, refetch } = useQuery({
    queryKey: ['liveMakerQuery', stateCode, year, submitted?.maker, submitted?.fuel, submitted?.category, rtoScope?.rtoCode],
    queryFn: () => getLiveMakerQuery({
      state_code: stateCode!, year, maker: submitted!.maker, fuel_group: submitted!.fuel || null,
      rto: rtoScope?.rtoCode ?? null, vehicle_category: submitted!.category,
    }),
    enabled: !!stateCode && !!submitted,
    retry: false, // a 502/503/429 is a real answer to show, not a transient glitch to silently retry (each retry re-pays the ~7s cost)
  });

  const canSubmit = !!stateCode && maker.length > 0;
  const records = data?.records ?? [];
  const total = records.reduce((sum, r) => sum + r.count, 0);
  // grain 'year' (or any month-0 row) = the stored table only holds a
  // calendar-year total for this combination, so there is no monthly split
  // to show -- render it as one "Full year" row instead of an empty month
  // table (month 0 matched none of 1..12 before).
  const yearGrain = data?.grain === 'year' || records.some((r) => r.month === 0);
  const byMonth = yearGrain
    ? (total > 0 ? [{ name: 'Full year', count: total }] : [])
    : MONTH_NAMES
      .map((name, idx) => ({ name, count: records.filter((r) => r.month === idx + 1).reduce((sum, r) => sum + r.count, 0) }))
      .filter((m) => m.count > 0);
  const unanswerable = data?.unanswerable_reason || null;

  let stateHint: string | null = null;
  if (auth.scope_type !== 'national' && !stateCode) {
    stateHint = 'Your account has no state assigned -- contact an admin.';
  } else if (auth.scope_type === 'national' && !stateCode && statesLoading) {
    stateHint = 'Loading states…';
  } else if (auth.scope_type === 'national' && !stateCode) {
    stateHint = 'Pick a state to look up.';
  }

  return (
    // relative z-20: the entrance animation's transform/opacity gives this
    // card its own stacking context even after it finishes (translateY(0)
    // still counts as "not none" for stacking purposes) -- without an
    // explicit z-index here, the maker-suggestions dropdown's own z-10
    // only ranks within THIS card, so the sibling leaderboard card below
    // (later in DOM, its own stacking context) painted over it regardless
    // (found live: the dropdown rendered visibly behind that section).
    <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance relative z-20" style={{ animationDelay: '120ms' }}>
      <div className="mb-1">
        <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">
          {`${liveWording ? 'Live ' : ''}Maker Lookup${rtoScope ? ` — ${rtoScope.rtoName}` : ''}`}
        </h3>
        <p className="text-[10px] text-[var(--text-muted)] mt-0.5">
          {/* Only claim a live fetch when the backend said so: lookups are now
              answered from stored tables (source 'stored') unless the server
              has the live fallback enabled. */}
          {data?.source === 'live'
            ? 'Look up one manufacturer, optionally by fuel, fetched on demand.'
            : 'Pick a fuel, then a manufacturer — only makers with registrations for that fuel are listed, largest first.'}
          {rtoScope ? ' Scoped to this RTO only, month by month.' : ''}
        </p>
      </div>

      <form
        className="flex items-end gap-3 flex-wrap mt-4"
        onSubmit={(e) => {
          e.preventDefault();
          // The page's category rides along like fuel: captured at submit,
          // since a current-year lookup re-scrapes (a real CAPTCHA) each time.
          if (canSubmit) setSubmitted({ maker, fuel, category: selectedCategory });
        }}
      >
        {rtoScope ? (
          <div className="flex flex-col gap-1.5">
            <span className="text-[10px] uppercase font-mono tracking-widest text-[var(--text-muted)] font-bold">RTO</span>
            <div className="bg-[var(--bg-sunken)] border border-[var(--border)] text-xs font-semibold px-3 py-2 rounded-xl">
              {rtoScope.rtoName}
            </div>
          </div>
        ) : auth.scope_type === 'national' ? (
          <LabeledSelect
            label="State"
            value={localStateCode}
            onChange={(e) => setLocalStateCode(e.target.value)}
            className="bg-[var(--bg-sunken)] border border-[var(--border)] text-xs font-semibold px-3 py-2 rounded-xl cursor-pointer"
          >
            <option value="">Select a state...</option>
            {(states || []).map((s: { state_code: string; state_name: string }) => (
              <option key={s.state_code} value={s.state_code}>{s.state_name}</option>
            ))}
          </LabeledSelect>
        ) : (
          <div className="flex flex-col gap-1.5">
            <span className="text-[10px] uppercase font-mono tracking-widest text-[var(--text-muted)] font-bold">State</span>
            <div className="bg-[var(--bg-sunken)] border border-[var(--border)] text-xs font-semibold px-3 py-2 rounded-xl">
              {auth.scope_state_name || '—'}
            </div>
          </div>
        )}
        <LabeledSelect
          label="Fuel"
          value={fuel}
          onChange={(e) => setFuel(e.target.value)}
          className="bg-[var(--bg-sunken)] border border-[var(--border)] text-xs font-semibold px-3 py-2 rounded-xl cursor-pointer"
        >
          <option value="">Any fuel</option>
          {MAKER_FUEL_GROUPS.map((g) => <option key={g} value={g} title={FUEL_GROUP_HINT[g]}>{g}</option>)}
        </LabeledSelect>
        <div className="w-80" data-testid="maker-lookup-maker">
          <SearchableSelect
            label={makerOptionsLoading ? 'Maker (loading…)' : `Maker (${optionList.length.toLocaleString('en-IN')} with data)`}
            value={maker}
            onChange={setMaker}
            allLabel="Select a manufacturer…"
            options={optionList.map((m) => ({ value: m.maker, label: m.maker, note: `${m.total.toLocaleString('en-IN')} registrations` }))}
          />
        </div>
        <button
          type="submit"
          disabled={!canSubmit || isFetching}
          className="bg-[var(--accent)] text-[var(--accent-contrast)] text-xs font-semibold px-4 py-2 rounded-xl disabled:opacity-40 disabled:cursor-not-allowed transition-opacity"
        >
          {isFetching ? 'Loading…' : 'Look up'}
        </button>
      </form>

      {stateHint && (
        <p className="text-xs text-[var(--text-muted)] mt-3">{stateHint}</p>
      )}
      {stateCode && makerOptions?.unanswerable_reason && (
        <p className="text-xs text-[var(--text-muted)] mt-3" data-testid="maker-options-unanswerable">{makerOptions.unanswerable_reason}</p>
      )}
      {stateCode && makerOptions && !makerOptions.unanswerable_reason && optionList.length === 0 && (
        <p className="text-xs text-[var(--text-muted)] mt-3" data-testid="maker-options-empty">
          No manufacturer has {fuel || 'any'} registrations stored for this {rtoScope ? 'RTO' : 'state'} in {year}.
        </p>
      )}

      {isError && (
        <ErrorBanner
          key={attempt}
          title="Couldn't load this combination"
          description={errorMessageFor(error)}
          action={{ label: 'Retry', onClick: () => { setAttempt((n) => n + 1); refetch(); } }}
          className="mt-4"
        />
      )}

      {isFetching && (
        <div
          role="status"
          aria-live="polite"
          className="mt-4 h-32 rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft flex items-center justify-center text-xs text-[var(--text-muted)] text-center px-6"
        >
          Loading…
        </div>
      )}

      {!isFetching && submitted && data && (
        unanswerable ? (
          <div className="mt-4" role="status" aria-live="polite" data-testid="live-unanswerable">
            <EmptyState
              variant="no-data"
              title="Can't answer this combination from stored data"
              description={`${unanswerable} (${submitted.maker}${submitted.fuel ? ` × ${submitted.fuel}` : ''}${submitted.category ? ` × ${submitted.category}` : ''}, ${year}) — this is not a zero.`}
            />
          </div>
        ) : records.length === 0 ? (
          <div className="mt-4" role="status" aria-live="polite">
            <EmptyState
              variant="no-data"
              title="No registrations found"
              description={`${submitted.maker}${submitted.fuel ? ` × ${submitted.fuel}` : ''}${submitted.category ? ` × ${submitted.category}` : ''} in ${year} — confirmed zero, not a failed lookup.`}
            />
          </div>
        ) : (
          <div className="mt-4" role="status" aria-live="polite">
            <SourceNote source={data.source} asOf={data.as_of} />
            <p className="text-xs text-[var(--text-secondary)] mb-2">
              <span className="font-semibold text-[var(--accent)]">{total.toLocaleString('en-IN')}</span> total registrations
              {submitted.fuel ? <> — <span className="font-semibold">{submitted.fuel}</span></> : null}
              {submitted.category ? <> — <span className="font-semibold">{submitted.category}</span></> : null}, {year}
              {yearGrain ? <span className="text-[var(--text-muted)]"> · calendar-year total only — no monthly split is stored for this combination</span> : null}
            </p>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-[10px] uppercase font-mono tracking-widest text-[var(--text-muted)] border-b border-[var(--border)]">
                    <th className="py-2 pr-4">Month</th>
                    <th className="py-2">Count</th>
                  </tr>
                </thead>
                <tbody>
                  {byMonth.map((m) => (
                    <tr key={m.name} className="border-b border-[var(--border)] last:border-0">
                      <td className="py-1.5 pr-4 text-[var(--text-primary)]">{m.name}</td>
                      <td className="py-1.5 font-mono text-[var(--text-secondary)]">{m.count.toLocaleString('en-IN')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )
      )}
    </div>
  );
}

export function LiveMakerLeaderboardPanel({ year, stateCode }: { year: number; stateCode: string | null }) {
  const chart = useChartTheme();
  const [fuel, setFuel] = useState('');
  const [limit, setLimit] = useState(10);
  // stateCode captured into `submitted`, not read live from the prop in
  // queryKey/queryFn -- otherwise changing the state dropdown in the
  // sibling LiveMakerQueryPanel above (after one leaderboard submission)
  // would silently re-fire this query with the new state, with no button
  // press here. An uncached call costs up to `limit` (20) real CAPTCHA-
  // solves server-side -- that should only ever happen on an explicit
  // "Show Leaderboard" click, same as every other param here.
  const { selectedCategory } = useAppStore();
  const [submitted, setSubmitted] = useState<{ stateCode: string; fuel: string; limit: number; category: string | null } | null>(null);
  const [attempt, setAttempt] = useState(0);

  const { data, isFetching, isError, error, refetch } = useQuery({
    queryKey: ['liveMakerLeaderboard', submitted?.stateCode, year, submitted?.fuel, submitted?.limit, submitted?.category],
    queryFn: () => getLiveMakerLeaderboard({
      state_code: submitted!.stateCode, year, fuel_group: submitted!.fuel || null, limit: submitted!.limit,
      vehicle_category: submitted!.category,
    }),
    enabled: !!submitted,
    retry: false,
  });

  const chartData = (data?.makers ?? []).filter((m) => m.total > 0).map((m) => ({ name: m.maker, count: m.total }));

  return (
    <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '160ms' }}>
      <div className="mb-1">
        <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">{data?.source === 'live' ? 'Live Top Makers' : 'Top Makers'}{fuel ? ` — ${fuel}` : ''}</h3>
        <p className="text-[10px] text-[var(--text-muted)] mt-0.5">
          Real (not modelled) calendar-year ranking of this state's manufacturers, optionally within one fuel group.
        </p>
      </div>

      <form
        className="flex items-end gap-3 flex-wrap mt-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (stateCode) setSubmitted({ stateCode, fuel, limit, category: selectedCategory });
        }}
      >
        <LabeledSelect
          label="Fuel"
          value={fuel}
          onChange={(e) => setFuel(e.target.value)}
          className="bg-[var(--bg-sunken)] border border-[var(--border)] text-xs font-semibold px-3 py-2 rounded-xl cursor-pointer"
        >
          <option value="">Any fuel</option>
          {MAKER_FUEL_GROUPS.map((g) => <option key={g} value={g} title={FUEL_GROUP_HINT[g]}>{g}</option>)}
        </LabeledSelect>
        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] uppercase font-mono tracking-widest text-[var(--text-muted)] font-bold" htmlFor="leaderboard-limit">Top N</label>
          <input
            id="leaderboard-limit"
            type="number"
            min={1}
            max={20}
            value={limit}
            onChange={(e) => setLimit(Math.min(20, Math.max(1, Number(e.target.value) || 1)))}
            className="bg-[var(--bg-sunken)] border border-[var(--border)] text-xs font-semibold px-3 py-2 rounded-xl w-20 focus:outline-none focus:ring-2 focus:ring-[var(--accent)]"
          />
        </div>
        <button
          type="submit"
          disabled={!stateCode || isFetching}
          className="bg-[var(--accent)] text-[var(--accent-contrast)] text-xs font-semibold px-4 py-2 rounded-xl disabled:opacity-40 disabled:cursor-not-allowed transition-opacity"
        >
          {isFetching ? 'Loading…' : 'Show Top Makers'}
        </button>
      </form>

      {!stateCode && (
        <p className="text-xs text-[var(--text-muted)] mt-3">Pick a state in the panel above first.</p>
      )}

      {isError && (
        <ErrorBanner
          key={attempt}
          title="Couldn't load the top makers"
          description={errorMessageFor(error)}
          action={{ label: 'Retry', onClick: () => { setAttempt((n) => n + 1); refetch(); } }}
          className="mt-4"
        />
      )}

      {isFetching && (
        <div
          role="status"
          aria-live="polite"
          className="mt-4 h-32 rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft flex items-center justify-center text-xs text-[var(--text-muted)] text-center px-6"
        >
          Loading the top {submitted?.limit ?? limit} makers…
        </div>
      )}

      {!isFetching && submitted && data && (
        data.unanswerable_reason ? (
          <div className="mt-4" role="status" aria-live="polite" data-testid="leaderboard-unanswerable">
            <EmptyState
              variant="no-data"
              title="Can't answer this combination from stored data"
              description={`${data.unanswerable_reason} (top ${submitted.limit} makers${submitted.fuel ? ` × ${submitted.fuel}` : ''}${submitted.category ? ` × ${submitted.category}` : ''}, ${year}) — this is not a zero.`}
            />
          </div>
        ) : chartData.length === 0 ? (
          <div className="mt-4" role="status" aria-live="polite">
            <EmptyState
              variant="no-data"
              title="No registrations found"
              description={`No real data for the top ${submitted.limit} makers${submitted.fuel ? ` × ${submitted.fuel}` : ''}${submitted.category ? ` × ${submitted.category}` : ''} in ${year}.`}
            />
          </div>
        ) : (
          <div className="mt-4" role="status" aria-live="polite">
            <SourceNote source={data.source} asOf={data.as_of} />
            <div role="figure" aria-label={`Top makers, ${year}: ${chartData.map((d) => `${d.name} ${d.count.toLocaleString('en-IN')}`).join(', ')}`}>
            <ResponsiveContainer width="100%" height={Math.max(220, chartData.length * 38)}>
              <BarChart data={chartData} layout="vertical" margin={{ right: 48 }}>
                <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} tickFormatter={formatCompact} />
                <YAxis dataKey="name" type="category" tick={(props) => <TruncatedYAxisTick {...props} fill={chart.axisText} />} width={220} />
                <Tooltip
                  formatter={(val: number) => [val.toLocaleString('en-IN'), data.source === 'stored' ? 'Registrations (stored)' : 'Registrations (real)']}
                  contentStyle={chart.tooltipContentStyle({ fontSize: 12 })} {...chart.tooltipTextStyle}
                />
                <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                  {chartData.map((d) => <Cell key={d.name} fill={chart.seriesColor(d.name)} />)}
                  <LabelList dataKey="count" position="right" formatter={(v: number) => v.toLocaleString('en-IN')} style={{ fill: chart.axisText, fontSize: 10, fontFamily: 'JetBrains Mono' }} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
            </div>
          </div>
        )
      )}
    </div>
  );
}
