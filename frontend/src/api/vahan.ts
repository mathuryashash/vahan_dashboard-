import axios from 'axios';

// The session lives in an httpOnly cookie (see api/auth.ts) -- withCredentials
// makes the browser attach it automatically; there's no token for JS to read
// or attach as a header anymore.
const api = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  withCredentials: true,
});

// A rejected/expired session means every subsequent call would also 401 --
// reload so App.tsx's auth check (GET /auth/me) falls back to the login
// page, instead of every widget on the page silently failing one by one.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      window.location.reload();
    }
    return Promise.reject(error);
  }
);

export interface FilterParams {
  year?: number;
  month?: number | null;
  state?: string | null;
  vehicle_class?: string | null;
  vehicle_category?: string | null;
  commercial_tier?: string | null;
  fuel_group?: string | null;
  maker?: string | null;
  vehicle_model?: string | null;
}

export const getKPIs = (params?: FilterParams, signal?: AbortSignal) => api.get('/summary/kpis', { params, signal }).then(r => r.data);
export const getTrend = (params?: Omit<FilterParams, 'month'>, signal?: AbortSignal) =>
  api.get('/summary/trend', { params, signal }).then(r => r.data);
export const getStateRanking = (params?: FilterParams & { limit?: number }, signal?: AbortSignal) =>
  api.get('/summary/state-ranking', { params, signal }).then(r => r.data);
export const getStates = () => api.get('/states/').then(r => r.data);
export const getStatesComparison = (year: number, limit?: number, vehicle_category?: string | null, fuel_group?: string | null) =>
  api.get('/comparison/all-states', { params: { year, limit, vehicle_category, fuel_group } }).then(r => r.data);
export const compareStates = (state_a: string, state_b?: string, year?: number, vehicle_category?: string | null, fuel_group?: string | null) =>
  api.get('/comparison/states', { params: { state_a, state_b, year, vehicle_category, fuel_group } }).then(r => r.data);
export const getYoYMonthly = (year_a: number, year_b: number, state?: string, start_month?: number, end_month?: number, vehicle_category?: string | null) =>
  api.get('/yoy/monthly', { params: { year_a, year_b, state, start_month, end_month, vehicle_category } }).then(r => r.data);
export const getYoYSummary = (year_a: number, year_b: number, start_month?: number, end_month?: number, vehicle_category?: string | null, state?: string) =>
  api.get('/yoy/summary', { params: { year_a, year_b, start_month, end_month, vehicle_category, state } }).then(r => r.data);
// /categories/ is the one known-slow aggregate (12-19 s cold all-India, see
// docs/review). 30 s cut it off right at the edge, after which the old retry
// policy fired it again from scratch; 60 s lets the first request finish.
export const getCategories = (params?: FilterParams, signal?: AbortSignal) =>
  api.get('/categories/', { params, signal, timeout: 60000 }).then(r => r.data);
export const getTopMakers = (params?: FilterParams & { limit?: number }, signal?: AbortSignal) =>
  api.get('/categories/top-makers', { params, signal }).then(r => r.data);
export const getFuelBreakdown = (params?: FilterParams) =>
  api.get('/categories/fuel-breakdown', { params }).then(r => r.data);
export const triggerRefresh = () => api.post('/refresh/').then(r => r.data);
export const getRefreshStatus = () => api.get('/refresh/status').then(r => r.data);
export const getMonthDetail = (params: { year: number; month: number } & Omit<FilterParams, 'year' | 'month'>, signal?: AbortSignal) =>
  api.get('/summary/month-detail', { params, signal }).then(r => r.data);
export const getAvailableYears = (): Promise<number[]> => api.get('/summary/available-years').then(r => r.data);
export const getScrapeProgress = () => api.get('/refresh/scrape-progress').then(r => r.data);
export interface SourceStatus {
  ok: boolean;
  detail: string;
  checked_at: string;
  down_since: string | null;
  // Newer backends retry a failed probe before calling a source down and
  // report how many checks in a row failed. Optional: older ones omit it.
  consecutive_failures?: number;
}
// Admin-only hourly check of both VAHAN sites -- backend app/services/source_health.py.
export const getSourceHealth = () =>
  api.get('/refresh/source-health').then(r => r.data as Record<string, SourceStatus>);
export const getDataQuality = (): Promise<{
  level: 'green' | 'amber' | 'red';
  scrape_fresh: boolean;
  last_updated: string | null;
  quality_check: { year: number; cells_checked: number; cells_clean: number; pct_clean: number | null };
  fada_last_ingested_at: string | null;
}> => api.get('/refresh/data-quality').then(r => r.data);

export const getOemStatus = (): Promise<{ last_ingested_at: string | null; days_stale: number | null; is_stale: boolean }> =>
  api.get('/oem-sales/status').then(r => r.data);
export const getOemCategories = (year?: number): Promise<string[]> =>
  api.get('/oem-sales/categories', { params: { year } }).then(r => r.data);
export const getOemMonthly = (params: { category: string; year: number; month?: number | null }) =>
  api.get('/oem-sales/monthly', { params }).then(r => r.data);
export const getOemTrend = (params: { maker: string; category: string }) =>
  api.get('/oem-sales/trend', { params }).then(r => r.data);

// The OEM/Brand picker's complete list, scoped and category-filtered server
// side -- see get_brand_options in backend categories.py.
export const getBrandOptions = (params: { year: number; vehicle_category?: string | null; state?: string | null }, signal?: AbortSignal) =>
  api.get('/categories/brand-options', { params, signal }).then(r => r.data as { maker: string; count: number; note: string | null }[]);
export const getMakerCategoryBreakdown = (params: { year: number; state?: string | null; vehicle_category?: string | null; maker?: string | null; limit?: number }, signal?: AbortSignal) =>
  api.get('/categories/maker-category-breakdown', { params, signal }).then(r => r.data);

export const getFuelCategoryBreakdown = (params: { year: number; state?: string | null; vehicle_category?: string | null; fuel_group?: string | null }, signal?: AbortSignal) =>
  api.get('/categories/fuel-category-breakdown', { params, signal }).then(r => r.data);

export const getCrosstabCoverage = (): Promise<{ maker_category: number[]; fuel_category: number[]; maker_fuel: number[] }> =>
  api.get('/categories/crosstab-coverage').then(r => r.data);

export const getMakerFuelBreakdown = (params: { year: number; state?: string | null; maker?: string | null; fuel_group?: string | null; limit?: number }, signal?: AbortSignal) =>
  api.get('/categories/maker-fuel-breakdown', { params, signal }).then(r => r.data);

export const getCrosstabDetail = (params: { year: number; state?: string | null; vehicle_category?: string | null; maker?: string | null; fuel_group?: string | null }, signal?: AbortSignal): Promise<{
  total: number | null;
  top_state: string | null;
  yoy_growth_percent: number | null;
}> => api.get('/categories/crosstab-detail', { params, signal }).then(r => r.data);

// Maker is a 7,733-item long tail with no crosstab table (see backend's
// MakerLiveQueryCache docstring) -- this hits the live-scrape endpoint
// instead: instant if already cached, a real ~7s wait (CAPTCHA solve
// against the source site) on a genuine first request for this exact
// (state, year, maker, fuel) combo. No AbortSignal: an in-flight live
// scrape shouldn't be cancelled by a stray unmount/refetch the way a cheap
// DB-query request can be -- it'd waste the CAPTCHA-solve that already ran.
export const getLiveMakerQuery = (params: { state_code: string; year: number; maker: string; fuel?: string | null; fuel_group?: string | null; rto?: string | null; vehicle_category?: string | null }) =>
  api.get('/live-query/maker', { params, timeout: 30000 }).then(r => r.data as {
    state_code: string;
    year: number;
    maker: string;
    fuel: string | null;
    fuel_group?: string | null;
    rto: string | null;
    records: { month: number; category: string; count: number }[];
    // 'live' = scraped from the source site just now / from the live cache;
    // 'stored' = answered from data already in our tables (as_of = when that
    // data was scraped). Both optional: older backends send neither.
    source?: 'live' | 'stored' | string;
    as_of?: string | null;
    // 'month' = records carry month 1..12; 'year' = one calendar-year row per
    // category with month 0 (the stored table has no monthly split).
    grain?: 'month' | 'year' | string;
    // Set when the stored tables cannot answer this combination (e.g. maker x
    // fuel x vehicle category). records is then empty but that is NOT a zero.
    unanswerable_reason?: string | null;
  });

// Our own rto_codes the source site actually lists for this state -- only
// these can be RTO-scoped in getLiveMakerQuery. Confirmed live for Delhi: we
// hold 27 RTOs and the site lists 23, of which only 16 are in common, so the
// UI has to ask rather than assume every RTO has a live option.
export const getLiveRtos = (stateCode: string): Promise<string[]> =>
  api.get('/live-query/rtos', { params: { state_code: stateCode } }).then(r => r.data);

// Real ranking of the state's actual biggest makers (from MakerCategoryTotal,
// not modeled) by their live-scraped fuel-scoped total. Longer timeout than
// getLiveMakerQuery -- an uncached call here pays up to `limit` real
// CAPTCHA-solves, not one, even though they run concurrently server-side.
export const getLiveMakerLeaderboard = (params: { state_code: string; year: number; fuel?: string | null; fuel_group?: string | null; limit?: number; vehicle_category?: string | null }) =>
  api.get('/live-query/leaderboard', { params, timeout: 60000 }).then(r => r.data as {
    state_code: string;
    year: number;
    fuel: string | null;
    makers: { maker: string; total: number }[];
    source?: 'live' | 'stored' | string;
    as_of?: string | null;
    grain?: 'month' | 'year' | string;
    unanswerable_reason?: string | null;
  });

// Real maker names matching `q`, straight from the source site -- lets the
// UI offer an actual autocomplete instead of requiring the exact full legal
// manufacturer name up front (found live: "honda" alone matches nothing;
// the real entity is "HONDA MOTORCYCLE AND SCOOTER INDIA (P) LTD").
export const searchLiveMakers = (q: string, signal?: AbortSignal): Promise<string[]> =>
  api.get('/live-query/makers/search', { params: { q }, signal }).then(r => r.data);

// The six fuel groups the Maker Lookup / Top Makers offer, mapped from raw
// VAHAN fuel labels server-side (backend services/fuel_groups.py).
export const MAKER_FUEL_GROUPS = ['Petrol', 'Diesel', 'CNG/LPG', 'Electric', 'Hybrid', 'Other'] as const;
export type MakerFuelGroup = typeof MAKER_FUEL_GROUPS[number];

// Makers with stored registrations for this state (+ RTO) + year (+ fuel group),
// largest first, scope-clamped server-side -- the Maker Lookup's dropdown.
export const getMakerOptions = (params: { state_code: string; year: number; fuel_group?: string | null; rto?: string | null; vehicle_category?: string | null }, signal?: AbortSignal) =>
  api.get('/live-query/maker-options', { params, signal }).then(r => r.data as {
    state_code: string;
    year: number;
    fuel_group: string | null;
    rto: string | null;
    makers: { maker: string; total: number }[];
    unanswerable_reason?: string | null;
    live_fallback?: boolean;
  });

// Category x powertrain per state (calendar year) from fuel_category_totals.
export const getCategoryFuelComparison = (params: { year: number; vehicle_category: string; fuel_group: string }) =>
  api.get('/comparison/category-fuel', { params }).then(r => r.data as {
    year: number;
    vehicle_category: string | null;
    fuel_group: string;
    source: string;
    grain: 'year';
    available: boolean;
    unanswerable_reason: string | null;
    coverage_pct_off: number | null;
    coverage_incomplete: boolean;
    total: number;
    states: { state_name: string; count: number; share_percent: number; coverage_pct_off: number | null; incomplete: boolean }[];
  });

// Real month figure for Category x Powertrain, when the monthly source agrees
// with the year crosstab for that scope; otherwise available=false + reason.
export const getCategoryFuelMonth = (params: { year: number; month: number; vehicle_category: string; fuel_group: string; state?: string | null }, signal?: AbortSignal) =>
  api.get('/categories/category-fuel-month', { params, signal }).then(r => r.data as {
    available: boolean;
    count: number | null;
    coverage_pct_off: number | null;
    unanswerable_reason: string | null;
    source: string;
  });

export const getRtosForState = (stateCode: string, year: number, vehicle_category?: string | null) =>
  api.get(`/rto/${stateCode}/list`, { params: { year, vehicle_category } }).then(r => r.data);
// With a year, the server returns only districts that resolve to registration
// data in that FY -- see get_districts_in_state in backend geo.py for why a
// third of districts would otherwise dead-end.
export const getDistrictsForState = (stateCode: string, year?: number) =>
  api.get(`/geo/states/${stateCode}/districts`, { params: { year } }).then(r => r.data);
export const getRtosForDistrict = (districtCode: string) =>
  api.get(`/geo/districts/${districtCode}/rtos`).then(r => r.data);
export const getRtoAnalysis = (rtoCode: string, year: number, vehicle_category?: string | null) =>
  api.get(`/rto/${rtoCode}/analysis`, { params: { year, vehicle_category } }).then(r => r.data);