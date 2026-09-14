import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { isAxiosError } from 'axios';
import { getLiveMakerQuery, getStates } from '../api/vahan';
import { useAppStore } from '../hooks/useAppStore';
import { useAuth } from '../contexts/AuthContext';
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

export function LiveMakerQueryPanel({ year }: { year: number }) {
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

  const [makerInput, setMakerInput] = useState('');
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
        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] uppercase font-mono tracking-widest text-[var(--text-muted)] font-bold" htmlFor="live-maker-input">Maker</label>
          <input
            id="live-maker-input"
            value={makerInput}
            onChange={(e) => setMakerInput(e.target.value)}
            placeholder="e.g. HONDA MOTORCYCLE AND SCOOTER INDIA (P) LTD"
            className="bg-[var(--bg-sunken)] border border-[var(--border)] text-xs font-semibold px-3 py-2 rounded-xl w-80 focus:outline-none focus:ring-2 focus:ring-[var(--accent)]"
          />
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
