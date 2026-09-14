import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { isAxiosError } from 'axios';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, LabelList } from 'recharts';
import { getLiveMakerLeaderboard, getLiveMakerQuery, getStates, searchLiveMakers } from '../api/vahan';
import { useAppStore } from '../hooks/useAppStore';
import { useAuth } from '../contexts/AuthContext';
import { useChartTheme } from '../hooks/useChartTheme';
import { TruncatedYAxisTick } from './ChartAxisTick';
import { LabeledSelect } from './LabeledSelect';
import { EmptyState } from './EmptyState';
import { ErrorBanner } from './ErrorBanner';

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

// The source site's own static fuel enum (see backend/scraper/
// analytics_scraper.py's FUEL_VALUES) -- a small, rarely-changing list kept
// in sync by hand rather than adding a round trip just to fetch 34 strings.
const FUEL_VALUES = [
  'BIO-CNG/BIO-GAS', 'CNG ONLY', 'DI-METHYL ETHER', 'DIESEL', 'DIESEL/HYBRID',
  'DUAL DIESEL/BIO CNG', 'DUAL DIESEL/CNG', 'DUAL DIESEL/LNG', 'ELECTRIC(BOV)',
  'ETHANOL(E100)', 'FLEX-FUEL(BIO-DIESEL)', 'FLEX-FUEL(ETHANOL)', 'FUEL CELL HYDROGEN',
  'HCNG', 'HYDROGEN(ICE)', 'LNG', 'LPG ONLY', 'METHANOL', 'NOT APPLICABLE', 'PETROL',
  'PETROL(E20)', 'PETROL(E20)/CNG', 'PETROL(E20)/HYBRID', 'PETROL(E20)/HYBRID/CNG',
  'PETROL(E20)/LPG', 'PETROL/CNG', 'PETROL/HYBRID', 'PETROL/HYBRID/CNG', 'PETROL/LPG',
  'PETROL/METHANOL', 'PLUG-IN HYBRID EV', 'PURE EV', 'SOLAR', 'STRONG HYBRID EV',
];

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
    default: return 'Something went wrong fetching this combination.';
  }
}

export function LiveMakerQueryPanel({ year, onStateCodeChange }: { year: number; onStateCodeChange?: (stateCode: string | null) => void }) {
  const auth = useAuth();
  const { selectedState } = useAppStore();
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

  const stateCode = auth.scope_type !== 'national' ? auth.scope_state_code : (localStateCode || null);

  // Shares this one state selection with the sibling leaderboard panel
  // below -- two independent "State" dropdowns on the same page would be
  // confusing (which one applies to what?), so this is the only one; the
  // parent page passes the resolved code down to the leaderboard panel.
  useEffect(() => {
    onStateCodeChange?.(stateCode);
  }, [stateCode, onStateCodeChange]);

  // Free text alone lets a user submit "honda" and get a real, genuinely-
  // empty result back (confirmed live) -- the source site's maker field
  // needs the EXACT full legal name ("HONDA MOTORCYCLE AND SCOOTER INDIA
  // (P) LTD"), indistinguishable in the response from a real zero. This
  // debounced search-as-you-type against the site's own maker lookup lets
  // a user find and pick a real name instead of guessing one.
  const [makerInput, setMakerInput] = useState('');
  const [debouncedMaker, setDebouncedMaker] = useState('');
  const [showSuggestions, setShowSuggestions] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setDebouncedMaker(makerInput.trim()), 300);
    return () => clearTimeout(t);
  }, [makerInput]);
  const { data: makerSuggestions } = useQuery({
    queryKey: ['makerSearch', debouncedMaker],
    queryFn: ({ signal }) => searchLiveMakers(debouncedMaker, signal),
    enabled: debouncedMaker.length >= 2,
  });

  const [fuel, setFuel] = useState('');
  const [submitted, setSubmitted] = useState<{ maker: string; fuel: string } | null>(null);
  // ErrorBanner hides itself on its own Retry click (before the retry's
  // outcome is known), so re-mount it fresh per attempt -- otherwise a
  // second failure in a row (a real case for 502/503/429) shows no banner
  // at all and the Retry button becomes a silent no-op (found in review).
  const [attempt, setAttempt] = useState(0);

  const { data, isFetching, isError, error, refetch } = useQuery({
    queryKey: ['liveMakerQuery', stateCode, year, submitted?.maker, submitted?.fuel],
    queryFn: () => getLiveMakerQuery({ state_code: stateCode!, year, maker: submitted!.maker, fuel: submitted!.fuel || null }),
    enabled: !!stateCode && !!submitted,
    retry: false, // a 502/503/429 is a real answer to show, not a transient glitch to silently retry (each retry re-pays the ~7s cost)
  });

  const canSubmit = !!stateCode && makerInput.trim().length > 0;
  const records = data?.records ?? [];
  const total = records.reduce((sum, r) => sum + r.count, 0);
  const byMonth = MONTH_NAMES
    .map((name, idx) => ({ name, count: records.filter((r) => r.month === idx + 1).reduce((sum, r) => sum + r.count, 0) }))
    .filter((m) => m.count > 0);

  let stateHint: string | null = null;
  if (auth.scope_type !== 'national' && !stateCode) {
    stateHint = 'Your account has no state assigned -- contact an admin.';
  } else if (auth.scope_type === 'national' && !stateCode && statesLoading) {
    stateHint = 'Loading states…';
  } else if (auth.scope_type === 'national' && !stateCode) {
    stateHint = 'Pick a state to look up.';
  }

  return (
    <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '120ms' }}>
      <div className="mb-1">
        <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">Live Maker Lookup</h3>
        <p className="text-[10px] text-[var(--text-muted)] mt-0.5">
          Look up one manufacturer, optionally by fuel type, directly from the source site — not pre-loaded, fetched on demand.
        </p>
      </div>

      <form
        className="flex items-end gap-3 flex-wrap mt-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (canSubmit) setSubmitted({ maker: makerInput.trim(), fuel });
        }}
      >
        {auth.scope_type === 'national' ? (
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
        <div className="flex flex-col gap-1.5 relative">
          <label className="text-[10px] uppercase font-mono tracking-widest text-[var(--text-muted)] font-bold" htmlFor="live-maker-input">Maker</label>
          <input
            id="live-maker-input"
            value={makerInput}
            onChange={(e) => { setMakerInput(e.target.value); setShowSuggestions(true); }}
            onFocus={() => setShowSuggestions(true)}
            // Delayed so a click on a suggestion below registers before the
            // list disappears -- a plain onBlur closing immediately would
            // eat the click.
            onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
            placeholder="Start typing a manufacturer, e.g. Honda"
            autoComplete="off"
            role="combobox"
            aria-expanded={showSuggestions && !!makerSuggestions?.length}
            aria-controls="live-maker-suggestions"
            aria-autocomplete="list"
            className="bg-[var(--bg-sunken)] border border-[var(--border)] text-xs font-semibold px-3 py-2 rounded-xl w-80 focus:outline-none focus:ring-2 focus:ring-[var(--accent)]"
          />
          {showSuggestions && debouncedMaker.length >= 2 && (
            <ul
              id="live-maker-suggestions"
              role="listbox"
              className="absolute top-full mt-1 left-0 w-80 max-h-56 overflow-y-auto bg-[var(--bg-card)] border border-[var(--border)] rounded-xl shadow-lg z-10 text-xs"
            >
              {makerSuggestions === undefined ? (
                <li className="px-3 py-2 text-[var(--text-muted)]">Searching…</li>
              ) : makerSuggestions.length === 0 ? (
                <li className="px-3 py-2 text-[var(--text-muted)]">No manufacturer matches "{debouncedMaker}" -- the source site needs the exact full legal name.</li>
              ) : (
                makerSuggestions.map((name) => (
                  <li key={name}>
                    <button
                      type="button"
                      // onMouseDown, not onClick: fires before the input's
                      // onBlur (which runs on the input losing focus first),
                      // so the selected value lands after blur's delayed
                      // close instead of racing it.
                      onMouseDown={() => { setMakerInput(name); setShowSuggestions(false); }}
                      className="w-full text-left px-3 py-2 hover:bg-[var(--bg-card-hover)] text-[var(--text-primary)]"
                    >
                      {name}
                    </button>
                  </li>
                ))
              )}
            </ul>
          )}
        </div>
        <LabeledSelect
          label="Fuel"
          value={fuel}
          onChange={(e) => setFuel(e.target.value)}
          className="bg-[var(--bg-sunken)] border border-[var(--border)] text-xs font-semibold px-3 py-2 rounded-xl cursor-pointer"
        >
          <option value="">Any fuel</option>
          {FUEL_VALUES.map((f) => <option key={f} value={f}>{f}</option>)}
        </LabeledSelect>
        <button
          type="submit"
          disabled={!canSubmit || isFetching}
          className="bg-[var(--accent)] text-[var(--accent-contrast)] text-xs font-semibold px-4 py-2 rounded-xl disabled:opacity-40 disabled:cursor-not-allowed transition-opacity"
        >
          {isFetching ? 'Fetching…' : 'Fetch'}
        </button>
      </form>

      {stateHint && (
        <p className="text-xs text-[var(--text-muted)] mt-3">{stateHint}</p>
      )}

      {isError && (
        <ErrorBanner
          key={attempt}
          title="Couldn't fetch this combination"
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
          Fetching… (first lookup for a new combination takes a few real seconds — a live CAPTCHA solve against the source site)
        </div>
      )}

      {!isFetching && submitted && data && (
        records.length === 0 ? (
          <div className="mt-4" role="status" aria-live="polite">
            <EmptyState
              variant="no-data"
              title="No registrations found"
              description={`${submitted.maker}${submitted.fuel ? ` × ${submitted.fuel}` : ''} in ${year} — confirmed zero, not a failed lookup.`}
            />
          </div>
        ) : (
          <div className="mt-4" role="status" aria-live="polite">
            <p className="text-xs text-[var(--text-secondary)] mb-2">
              <span className="font-semibold text-[var(--accent)]">{total.toLocaleString('en-IN')}</span> total registrations
              {submitted.fuel ? <> — <span className="font-semibold">{submitted.fuel}</span></> : null}, {year}
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
  const [submitted, setSubmitted] = useState<{ stateCode: string; fuel: string; limit: number } | null>(null);
  const [attempt, setAttempt] = useState(0);

  const { data, isFetching, isError, error, refetch } = useQuery({
    queryKey: ['liveMakerLeaderboard', submitted?.stateCode, year, submitted?.fuel, submitted?.limit],
    queryFn: () => getLiveMakerLeaderboard({ state_code: submitted!.stateCode, year, fuel: submitted!.fuel || null, limit: submitted!.limit }),
    enabled: !!submitted,
    retry: false,
  });

  const chartData = (data?.makers ?? []).filter((m) => m.total > 0).map((m) => ({ name: m.maker, count: m.total }));

  return (
    <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '160ms' }}>
      <div className="mb-1">
        <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">Live Top Makers — real numbers</h3>
        <p className="text-[10px] text-[var(--text-muted)] mt-0.5">
          The actual (not modeled) fuel-scoped ranking for this state's real biggest manufacturers — the real-data counterpart to the estimated chart above when a fuel filter alone has no month-level real data.
        </p>
      </div>

      <form
        className="flex items-end gap-3 flex-wrap mt-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (stateCode) setSubmitted({ stateCode, fuel, limit });
        }}
      >
        <LabeledSelect
          label="Fuel"
          value={fuel}
          onChange={(e) => setFuel(e.target.value)}
          className="bg-[var(--bg-sunken)] border border-[var(--border)] text-xs font-semibold px-3 py-2 rounded-xl cursor-pointer"
        >
          <option value="">Any fuel</option>
          {FUEL_VALUES.map((f) => <option key={f} value={f}>{f}</option>)}
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
          {isFetching ? 'Fetching…' : 'Show Leaderboard'}
        </button>
      </form>

      {!stateCode && (
        <p className="text-xs text-[var(--text-muted)] mt-3">Pick a state in the panel above first.</p>
      )}

      {isError && (
        <ErrorBanner
          key={attempt}
          title="Couldn't fetch this leaderboard"
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
          Fetching up to {submitted?.limit ?? limit} makers live — cached makers are instant, new ones take a few real seconds each (run concurrently, not one at a time).
        </div>
      )}

      {!isFetching && submitted && data && (
        chartData.length === 0 ? (
          <div className="mt-4" role="status" aria-live="polite">
            <EmptyState
              variant="no-data"
              title="No registrations found"
              description={`No real data for the top ${submitted.limit} makers${submitted.fuel ? ` × ${submitted.fuel}` : ''} in ${year}.`}
            />
          </div>
        ) : (
          <div className="mt-4" role="status" aria-live="polite">
            <ResponsiveContainer width="100%" height={Math.max(220, chartData.length * 38)}>
              <BarChart data={chartData} layout="vertical" margin={{ right: 48 }}>
                <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} />
                <YAxis dataKey="name" type="category" tick={(props) => <TruncatedYAxisTick {...props} fill={chart.axisText} />} width={220} />
                <Tooltip
                  formatter={(val: number) => [val.toLocaleString('en-IN'), 'Registrations (real)']}
                  contentStyle={chart.tooltipContentStyle({ fontSize: 12 })} {...chart.tooltipTextStyle}
                />
                <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                  {chartData.map((d) => <Cell key={d.name} fill={chart.seriesColor(d.name)} />)}
                  <LabelList dataKey="count" position="right" formatter={(v: number) => v.toLocaleString('en-IN')} style={{ fill: chart.axisText, fontSize: 10, fontFamily: 'JetBrains Mono' }} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )
      )}
    </div>
  );
}
