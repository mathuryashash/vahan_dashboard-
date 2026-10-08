// frontend/src/pages/Overview.tsx
import { useEffect, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  AreaChart, Area, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, TooltipProps, ResponsiveContainer
} from 'recharts';
import { TrendingUp, Award, Car, Bike } from '../components/Icons';
import { KPICard } from '../components/KPICard';
import { EmptyState } from '../components/EmptyState';
import { ErrorBanner } from '../components/ErrorBanner';
import { insidePieLabel } from '../components/ChartAxisTick';
import { ExportCsvButton } from '../components/ExportCsvButton';
import { LabeledSelect } from '../components/LabeledSelect';
import { SearchableSelect } from '../components/SearchableSelect';
import { PowertrainToggle } from '../components/PowertrainToggle';
import { getKPIs, getTrend, getStateRanking, getStates, getBrandOptions, getMonthDetail, getAvailableYears, getMakerCategoryBreakdown, getFuelCategoryBreakdown, getMakerFuelBreakdown, getCrosstabCoverage, getCrosstabDetail, getFuelBreakdown } from '../api/vahan';
import { useScopeLock } from '../hooks/useScopeLock';
import { useAppStore } from '../hooks/useAppStore';
import { useSettledLayout } from '../hooks/useSettledLayout';
import { useChartTheme } from '../hooks/useChartTheme';
import { capForDonut, distinctSeriesColors } from '../theme/tokens';
import { useAuth } from '../contexts/AuthContext';
import type { MonthDetail } from '../types';
import { useCategoriesQuery } from '../hooks/useCategoriesQuery';
import { LoadingBlock } from '../components/LoadingBlock';
import { formatCompact, cyLabel, cyLongLabel, orDash, NO_VALUE } from '../utils/format';

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
  // The pinning effects these flags used to own now live in useScopeLock,
  // called once from App -- they only ran here, so a scoped account landing
  // directly on another page was never pinned at all.
  const { isStateLocked, isCategoryLocked } = useScopeLock();

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
    queryFn: ({ signal }) => getMakerCategoryBreakdown({ year: selectedYear, vehicle_category: selectedCategory!, maker: selectedMaker!, state: selectedState }, signal),
    // kpiComboImpossible (not exactlyOnePairActive) so this also fires when
    // all 3 filters are set -- real Maker x Category total, independent of
    // whether a Powertrain filter is also active. Matches crosstabFuelCategory's
    // gating below.
    enabled: kpiComboImpossible && !!selectedCategory && !!selectedMaker,
  });
  const { data: crosstabFuelCategory, isLoading: crosstabFuelCategoryLoading } = useQuery({
    queryKey: ['fuelCategoryBreakdown', selectedYear, selectedCategory, fuelGroup, selectedState],
    queryFn: ({ signal }) => getFuelCategoryBreakdown({ year: selectedYear, vehicle_category: selectedCategory!, fuel_group: fuelGroup!, state: selectedState }, signal),
    // kpiComboImpossible (not exactlyOnePairActive) so this also fires when
    // all 3 filters are set -- this query is maker-independent (Category x
    // Fuel only), so it's exactly as valid there; reused below as rCf for
    // the all-3-selected estimate.
    enabled: kpiComboImpossible && !!selectedCategory && !!fuelGroup,
  });
  const { data: crosstabMakerFuel, isLoading: crosstabMakerFuelLoading } = useQuery({
    queryKey: ['makerFuelBreakdown', selectedYear, selectedMaker, fuelGroup, selectedState],
    queryFn: ({ signal }) => getMakerFuelBreakdown({ year: selectedYear, maker: selectedMaker!, fuel_group: fuelGroup!, state: selectedState }, signal),
    // kpiComboImpossible, same reasoning as crosstabMakerCategory above.
    // Never for a category-scoped account: Maker x Fuel has no category
    // column, so the server refuses it ([]) rather than leak other segments.
    enabled: kpiComboImpossible && !!selectedMaker && !!fuelGroup && !isCategoryLocked,
  });

  // /maker-category-breakdown, /fuel-category-breakdown and
  // /maker-fuel-breakdown each key their response by whichever of the two
  // requested dimensions is left unfixed (see categories.py's key_name) --
  // computed unconditionally here (not just when exactlyOnePairActive) so
  // the same three real numbers also feed the all-3-filters KPI row below,
  // instead of a fabricated combined estimate.
  const mcTotal = (crosstabMakerCategory || []).find((r: { vehicle_category: string; count: number }) => r.vehicle_category === selectedCategory)?.count;
  const cfTotal = (crosstabFuelCategory || []).find((r: { vehicle_category: string; count: number }) => r.vehicle_category === selectedCategory)?.count;
  const mfTotal = (crosstabMakerFuel || []).find((r: { maker: string; count: number }) => r.maker === selectedMaker)?.count;

  let crosstabTotal: number | undefined;
  let crosstabLoading = false;
  if (exactlyOnePairActive && selectedCategory && selectedMaker) {
    crosstabTotal = mcTotal;
    crosstabLoading = crosstabMakerCategoryLoading;
  } else if (exactlyOnePairActive && selectedCategory && fuelGroup) {
    crosstabTotal = cfTotal;
    crosstabLoading = crosstabFuelCategoryLoading;
  } else if (exactlyOnePairActive && selectedMaker && fuelGroup) {
    crosstabTotal = mfTotal;
    crosstabLoading = crosstabMakerFuelLoading;
  }
  // Cross-tabs are year totals, no day-level granularity to divide by the
  // actual elapsed days -- 365 is the same coarse approximation the rest of
  // this page already uses elsewhere for a full-year average.
  const crosstabAvgDaily = crosstabTotal !== undefined ? Math.round(crosstabTotal / 365) : undefined;

  // ---- All 3 filters at once: three real pairwise numbers, not a
  // combined estimate ----
  // No VAHAN table pivots on Maker x Category x Fuel together, and there's
  // no real number for that exact combination to show as a single "Total
  // Registrations" -- so instead of modeling one (the previous approach),
  // the KPI row below shows the three real pairwise totals side by side.
  const allThreeActive = kpiComboImpossible && !exactlyOnePairActive;
  // hasYearData signal per pairwise cross-tab -- see MakerCategoryPanel's
  // comment further down for why this (not an empty filtered response)
  // is what tells "not scraped this year" apart from a real zero.
  const mcNoData = allThreeActive && crosstabCoverage ? !crosstabCoverage.maker_category.includes(selectedYear) : false;
  const cfNoData = allThreeActive && crosstabCoverage ? !crosstabCoverage.fuel_category.includes(selectedYear) : false;
  const mfNoData = allThreeActive && crosstabCoverage ? !crosstabCoverage.maker_fuel.includes(selectedYear) : false;

  // YoY Growth and Top State for the same combo -- only became answerable
  // once the crosstab tables got multi-year (2003+), per-state history;
  // before that backfill this really was a permanent '--'.
  const { data: crosstabDetail } = useQuery({
    queryKey: ['crosstabDetail', selectedYear, selectedCategory, selectedMaker, fuelGroup, selectedState],
    queryFn: ({ signal }) => getCrosstabDetail({
      year: selectedYear,
      vehicle_category: selectedCategory,
      maker: selectedMaker,
      fuel_group: fuelGroup,
      state: selectedState,
    }, signal),
    enabled: exactlyOnePairActive,
  });

  const { data: kpis, isLoading: kpisLoading, isError: kpisError, refetch: refetchKpis } = useQuery<{
    total_registrations_today: number;
    total_this_month: number;
    yoy_growth_percent: number | null;
    top_state: string | null;
    top_state_count: number;
  }>({
    queryKey: ['kpis', selectedYear, selectedMonth, selectedState, selectedCategory, fuelGroup, selectedMaker],
    queryFn: ({ signal }) => getKPIs({
      year: selectedYear,
      month: selectedMonth,
      state: selectedState,
      vehicle_category: selectedCategory,
      fuel_group: fuelGroup,
      maker: selectedMaker,
    }, signal),
    enabled: !kpiComboImpossible,
  });

  // /summary/kpis reports yoy_growth_percent = 0.0 both for "exactly flat"
  // and for "no prior-year data at all" (it divides only when the prior total
  // is > 0). The card used to show a green "▲ 0.0%" for 2003 or Ladakh x EV,
  // which reads as "flat" when the truth is "unknown". A null from a newer
  // backend is unambiguous; an exact 0 is checked against the prior year's
  // own total (one cheap request, and only in that rare case).
  const yoyRaw = kpis?.yoy_growth_percent;
  const priorYearListed = availableYears ? availableYears.includes(selectedYear - 1) : true;
  const { data: priorKpis, isLoading: priorKpisLoading } = useQuery<{ total_this_month: number }>({
    queryKey: ['kpis', selectedYear - 1, selectedMonth, selectedState, selectedCategory, fuelGroup, selectedMaker],
    queryFn: ({ signal }) => getKPIs({
      year: selectedYear - 1,
      month: selectedMonth,
      state: selectedState,
      vehicle_category: selectedCategory,
      fuel_group: fuelGroup,
      maker: selectedMaker,
    }, signal),
    enabled: !kpiComboImpossible && yoyRaw === 0 && priorYearListed,
  });
  const noPriorYearData =
    !kpiComboImpossible && !!kpis && (
      yoyRaw == null || !priorYearListed || (yoyRaw === 0 && !!priorKpis && !priorKpis.total_this_month)
    );
  const yoyKnown = !kpiComboImpossible && !!kpis && !noPriorYearData && !(yoyRaw === 0 && priorKpisLoading);

  const { data: trend, isLoading: trendLoading, isError: trendError, refetch: refetchTrend } = useQuery({
    queryKey: ['trend', selectedYear, selectedState, selectedCategory, fuelGroup, selectedMaker],
    queryFn: ({ signal }) => getTrend({
      year: selectedYear,
      state: selectedState,
      vehicle_category: selectedCategory,
      fuel_group: fuelGroup,
      maker: selectedMaker,
    }, signal),
    enabled: !kpiComboImpossible,
  });

  const { data: ranking, isLoading: rankingLoading, isError: rankingError, refetch: refetchRanking } = useQuery({
    queryKey: ['stateRanking', selectedYear, selectedMonth, selectedState, selectedCategory, fuelGroup, selectedMaker],
    queryFn: ({ signal }) => getStateRanking({
      year: selectedYear,
      month: selectedMonth,
      state: selectedState,
      vehicle_category: selectedCategory,
      fuel_group: fuelGroup,
      maker: selectedMaker,
      limit: 10
    }, signal),
    enabled: !kpiComboImpossible,
  });

  // A failed request (network error, 500) rendered identically to a
  // legitimate empty result -- both just showed "no data"/"0" -- which
  // undermines the honest-empty-state pattern the rest of this page relies
  // on: a user can't tell "the API is down" from "VAHAN never scraped
  // this" (found by frontend review). One banner covers the three main
  // queries; a page-specific failure buried in a lower panel still shows
  // via that panel's own empty state.
  const hasLoadError = kpisError || trendError || rankingError;

  // ONE /categories/ request per (year, month, state) feeds both the Vehicle
  // Mix donut and the Category picker below (B2: they used to be two query
  // keys -- ['categories',...,maker] and ['categoryOptions',...] -- so the
  // slowest endpoint in the app went out twice in parallel on every year
  // change). The maker param was dropped from the request: maker and a real
  // category never coexist on a Registration row, so the maker-filtered call
  // was guaranteed empty and Vehicle Mix already switches to
  // makerCategoryMix whenever a maker is selected.
  const {
    data: categories,
    isLoading: categoriesLoading,
    isError: categoriesError,
    refetch: refetchCategories,
  } = useCategoriesQuery({ year: selectedYear, month: selectedMonth, state: selectedState });

  // Real per-maker category mix, from the same Maker x Vehicle Class
  // cross-tab MakerCategoryPanel uses (year-only, no month breakdown) --
  // passing only `maker` (no vehicle_category) groups by vehicle_category,
  // giving this one maker's full category split. Used instead of `categories`
  // above whenever a maker is selected, since that query is structurally
  // guaranteed empty in that case (see its own comment).
  const { data: makerCategoryMix, isLoading: makerCategoryMixLoading } = useQuery({
    queryKey: ['makerCategoryMix', selectedYear, selectedMaker, selectedState],
    queryFn: ({ signal }) => getMakerCategoryBreakdown({ year: selectedYear, maker: selectedMaker!, state: selectedState }, signal),
    enabled: !!selectedMaker,
  });

  // Separate from `categories` above (which drives the Vehicle Mix pie and
  // is deliberately maker-filtered -- correctly empty whenever a maker's
  // selected, same reason the KPI cards go "--"). The Category <select>'s
  // OPTION LIST needs the maker-independent list instead: maker and a real
  // category never coexist on the same Registration row (see MakersModels.tsx's
  // matching comment on its own maker dropdown), so filtering this by
  // selectedMaker made the option list empty the moment a maker was picked --
  // the browser then silently fell back to showing "All Categories" since
  // the <option> matching the actual selectedCategory value no longer
  // existed, even though selectedCategory itself was untouched (found live:
  // dropdown showed "All Categories" while every panel below still said
  // "Two-Wheeler", reading selectedCategory directly as a prop).
  // Same cache entry as `categories` above -- no second request.
  const categoryOptions = categories;

  // The complete OEM/Brand list, built server-side (get_brand_options in
  // backend categories.py). It replaces two limits the old client-side list
  // had: "All Brands" was a top-30, so VinFast -- 17th in Four-Wheeler for
  // 2026 -- was unreachable; and category membership was a 1%-of-own-volume
  // share rule, which put Mercedes-Benz (72 units) under Two-Wheeler while
  // genuine bike makers like BMW and Piaggio have lower shares than that
  // noise. Membership is now national volume, and the list is searchable.
  const { data: brandRows } = useQuery({
    queryKey: ['brandOptions', selectedYear, selectedCategory, selectedState],
    queryFn: ({ signal }) => getBrandOptions({ year: selectedYear, vehicle_category: selectedCategory, state: selectedState }, signal),
  });
  const brandOptions = useMemo(
    () => (brandRows || []).map((b) => ({ value: b.maker, label: b.maker, note: b.note })),
    [brandRows],
  );

  // A maker picked under one category can fall outside another's list --
  // clear it rather than keep filtering by a brand the picker no longer
  // offers. Only once the list has loaded, so a refetch can't clear it.
  useEffect(() => {
    if (brandRows && selectedCategory && selectedMaker && !brandRows.some((b) => b.maker === selectedMaker)) {
      setSelectedMaker(null);
    }
  }, [brandRows, selectedCategory, selectedMaker, setSelectedMaker]);

  // The live VAHAN4 site has no day-level granularity at all -- its finest
  // X-axis option is "Month Wise" (confirmed against the live site's own
  // axis-selector options). A specific-date picker was built against that
  // assumption before this was known; it's replaced with a month + YTD
  // detail driven by the Year/Month filters above, since a real month total
  // (and year-to-date through it) is the finest granularity this data source
  // can ever supply.
  const { data: monthDetail, isLoading: monthDetailLoading, isError: monthDetailError } = useQuery<MonthDetail>({
    queryKey: ['monthDetail', selectedYear, selectedMonth, selectedState, selectedCategory, fuelGroup, selectedMaker],
    queryFn: ({ signal }) => getMonthDetail({
      year: selectedYear,
      month: selectedMonth!,
      state: selectedState,
      vehicle_category: selectedCategory,
      fuel_group: fuelGroup,
      maker: selectedMaker,
    }, signal),
    enabled: selectedMonth != null && !kpiComboImpossible,
  });

  // The current month is still filling in, so plotting it drops the line off
  // a cliff and reads as a collapsing market. YoY.tsx already guards this and
  // documents the incident behind it (September 2026 showed -38.6% purely
  // because it was 15 days old); this is that guard, on the landing page's
  // flagship chart, which had none.
  const _now = new Date();
  const trendPartialMonth =
    selectedYear === _now.getFullYear() && selectedMonth == null ? _now.getMonth() + 1 : null;
  const trendPartialName = trendPartialMonth ? MONTH_NAMES[trendPartialMonth - 1] : null;
  const trendPartialProgress = trendPartialMonth
    ? Math.round((_now.getDate() / new Date(_now.getFullYear(), trendPartialMonth, 0).getDate()) * 100)
    : null;

  const chartData = (trend || [])
    // Only when viewing the whole year. If the user has explicitly picked
    // this month, hiding it would leave an empty chart.
    .filter((d: { month?: number }) => !trendPartialMonth || d.month !== trendPartialMonth)
    .map((d: { month?: number; count: number }) => ({
      name: d.month ? MONTH_NAMES[d.month - 1] : '',
      count: d.count,
    }));

  // These cards fall back to the cross-tab YEAR total for impossible combos,
  // so their value is identical for every month -- which reads as stale or
  // broken data when the user switches months and nothing moves (found live:
  // reported as "exact same data for both months"). The banner above the
  // cards already said this; saying it on the card itself is what actually
  // lands, since the card is where the unchanging number is.
  const kpiPeriodSuffix = kpiComboImpossible && selectedMonth != null ? ' · year total' : '';

  const pieData = capForDonut(
    selectedMaker
      ? (makerCategoryMix || []).map((c: { vehicle_category: string; count: number }) => ({ name: c.vehicle_category, value: c.count }))
      : (categories || []).map((c) => ({ name: c.vehicle_category, value: c.total_count }))
  );
  const pieColors = distinctSeriesColors(chart, pieData.map((p) => p.name));
  const vehicleMixLoading = selectedMaker ? makerCategoryMixLoading : categoriesLoading;
  const vehicleMixReady = useSettledLayout(vehicleMixLoading);
  // See MakerCategoryPanel's comment further down -- hasYearData (not an
  // empty filtered response) tells "not scraped this year" apart from a
  // real zero, same distinction applies to this maker's category mix.
  const vehicleMixNoData = selectedMaker && crosstabCoverage ? !crosstabCoverage.maker_category.includes(selectedYear) : false;

  // A state/RTO-scoped analyst can't do anything about missing data (no
  // access to /refresh/, it's admin-only) -- an empty card telling them to
  // "run a sync" or a bare "couldn't load" is just noise they can't act on.
  // National users keep the existing empty/error states since they're the
  // ones who could actually trigger a scrape. isStateLocked already covers
  // both state- and RTO-scoped accounts (scope_type !== 'national').
  // kpiComboImpossible hides these outright rather than rendering an
  // explanatory empty state in each: for these combos the trend, the state
  // ranking and the month detail are ALL unanswerable at once, so spelling
  // that out three times filled the page with "no data" blocks and made the
  // dashboard look broken. The single banner above the KPI cards carries the
  // explanation instead; the dead sections just collapse.
  const showTrendCard = !kpiComboImpossible && (!isStateLocked || trendLoading || chartData.length > 0);
  // A segment account's vehicle mix is by definition one slice at 100% --
  // an honest chart, but it reads as a rendering bug, so drop the card
  // rather than ship a pie of one.
  const showVehicleMixCard = !isCategoryLocked && (!isStateLocked || vehicleMixLoading || !vehicleMixReady || pieData.length > 0);
  const monthDetailUnavailable = selectedMonth != null && !monthDetailLoading && (monthDetailError || !monthDetail);
  const showMonthDetailCard = !kpiComboImpossible && (!isStateLocked || !monthDetailUnavailable);
  const showStateRankingCard = !kpiComboImpossible;

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
    // Only clear axes this account actually controls. Clearing a locked one
    // flashed unscoped data for a frame before the scope lock put it back,
    // which reads as the filter breaking.
    if (!isStateLocked) setSelectedState(null);
    if (!isCategoryLocked) setSelectedCategory(null);
    setSelectedMonth(null);
    setFuelGroup(null);
    setSelectedMaker(null);
  };

  const selectClass = "w-full bg-[var(--bg-sunken)] border border-[var(--border)] hover:border-[var(--border-strong)] text-[var(--text-primary)] text-xs font-semibold px-3 py-2 rounded-xl focus:outline-none focus:ring-2 focus:ring-[var(--accent)] transition-all duration-200 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed";

  return (
    <div className="p-3 sm:p-6 space-y-6">
      {hasLoadError && (
        <ErrorBanner
          title="Couldn't load dashboard data"
          description="The request to the server failed -- this is different from a real empty result. Check your connection and try again."
          action={{ label: 'Retry', onClick: () => { refetchKpis(); refetchTrend(); refetchRanking(); } }}
        />
      )}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="animate-entrance min-w-0">
          <h2 className="text-xl font-bold text-[var(--text-primary)] tracking-tight">
            Overview
          </h2>
          <p className="text-xs text-[var(--text-muted)] mt-0.5 font-mono uppercase tracking-widest">
            India Vehicle Registration Observatory — {cyLongLabel(selectedYear)}
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

      {/* relative z-20: animate-entrance leaves this card with its own
          stacking context, so the brand picker's dropdown z-index would only
          rank inside it and the charts below would paint over the list --
          the same bug LiveMakerQueryPanel hit and fixed this way. */}
      <div className="grid grid-cols-1 min-[480px]:grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-3 bg-[var(--bg-card)] border border-[var(--border)] p-4 rounded-2xl animate-entrance relative z-20">
        {isStateLocked ? (
          <div className="flex flex-col gap-1.5">
            <span className="text-[10px] uppercase font-mono tracking-widest text-[var(--text-muted)] font-bold">State</span>
            <div className={`${selectClass} cursor-default hover:border-[var(--border)]`}>{auth.scope_state_name}</div>
          </div>
        ) : (
          <LabeledSelect label="State" value={selectedState || ''} onChange={(e) => setSelectedState(e.target.value || null)} className={selectClass}>
            <option value="">All States</option>
            {(statesList || []).map((s: { state_name: string }) => (
              <option key={s.state_name} value={s.state_name}>{s.state_name}</option>
            ))}
          </LabeledSelect>
        )}

        <LabeledSelect label="Year (calendar)" title="Calendar year, Jan–Dec. RTO Analysis reads the same year as the financial year starting that April." value={selectedYear} onChange={(e) => setSelectedYear(Number(e.target.value))} className={selectClass}>
          {(availableYears || [selectedYear]).map((y) => <option key={y} value={y}>{cyLabel(y)}</option>)}
        </LabeledSelect>

        <LabeledSelect label="Month" value={selectedMonth || ''} onChange={(e) => setSelectedMonth(e.target.value ? Number(e.target.value) : null)} className={selectClass}>
          <option value="">All Months</option>
          {MONTH_NAMES.map((name, idx) => (
            <option key={name} value={idx + 1}>{name}</option>
          ))}
        </LabeledSelect>

        {isCategoryLocked ? (
          <div className="flex flex-col gap-1.5">
            <span className="text-[10px] uppercase font-mono tracking-widest text-[var(--text-muted)] font-bold">Category</span>
            <div className={`${selectClass} cursor-default hover:border-[var(--border)]`}>{auth.scope_vehicle_category}</div>
          </div>
        ) : (
          <LabeledSelect label="Category" value={selectedCategory || ''} onChange={(e) => setSelectedCategory(e.target.value || null)} className={selectClass}>
            <option value="">All Categories</option>
            {/* Still filtering even when this period/state lists no such
                category -- show it rather than "All" over its zeros. */}
            {selectedCategory && !(categoryOptions || []).some((c: { vehicle_category: string }) => c.vehicle_category === selectedCategory) && (
              <option value={selectedCategory}>{selectedCategory}</option>
            )}
            {(categoryOptions || []).map((c: { vehicle_category: string }) => (
              <option key={c.vehicle_category} value={c.vehicle_category}>{c.vehicle_category}</option>
            ))}
          </LabeledSelect>
        )}

        <div className="flex flex-col gap-1.5">
          {/* span, not label: PowertrainToggle is a button group, not a
              single form control a <label> can associate with -- its own
              aria-label carries the accessible name instead. */}
          <span className="text-[10px] uppercase font-mono tracking-widest text-[var(--text-muted)] font-bold">Powertrain</span>
          <PowertrainToggle value={fuelGroup} onChange={setFuelGroup} />
        </div>

        <div className="flex flex-col gap-1.5">
          <SearchableSelect
            label="OEM / Brand"
            value={selectedMaker || ''}
            onChange={(maker) => setSelectedMaker(maker || null)}
            options={brandOptions}
            allLabel="All Brands"
          />
          {fuelGroup && (
            <p className="text-[9px] text-[var(--text-muted)] font-mono leading-tight">
              not scoped to {fuelGroup} — VAHAN can't cross maker × fuel here, see panel below
            </p>
          )}
        </div>
      </div>

      {exactlyOnePairActive && impossibleCrossFilter && (
        <MakerCategoryPanel
          year={selectedYear}
          category={selectedCategory!}
          maker={selectedMaker!}
          month={selectedMonth}
          state={selectedState}
          hasYearData={crosstabCoverage ? crosstabCoverage.maker_category.includes(selectedYear) : true}
        />
      )}

      {exactlyOnePairActive && impossibleFuelCategoryFilter && (
        <FuelCategoryPanel
          year={selectedYear}
          category={selectedCategory!}
          fuelGroup={fuelGroup!}
          month={selectedMonth}
          state={selectedState}
          hasYearData={crosstabCoverage ? crosstabCoverage.fuel_category.includes(selectedYear) : true}
        />
      )}

      {exactlyOnePairActive && impossibleMakerFuelFilter && (
        <MakerFuelPanel
          year={selectedYear}
          maker={selectedMaker!}
          fuelGroup={fuelGroup!}
          month={selectedMonth}
          hasYearData={crosstabCoverage ? crosstabCoverage.maker_fuel.includes(selectedYear) : true}
          state={selectedState}
        />
      )}

      {exactlyOnePairActive && (
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl px-4 py-2.5 text-xs text-[var(--text-secondary)] animate-entrance">
          All four cards below are sourced from the cross-tab panel (a <span className="font-semibold text-[var(--accent)]">year total</span>, not this month) since VAHAN has no single table for this combination.
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        {allThreeActive ? (
          <>
            <KPICard
              label="Maker × Category"
              value={mcNoData ? 'Not scraped' : (mcTotal ?? 0)}
              icon={<Car className="w-4 h-4" />}
              loading={crosstabMakerCategoryLoading}
              index={0}
            />
            <KPICard
              label="Maker × Powertrain"
              value={isCategoryLocked ? '—' : mfNoData ? 'Not scraped' : (mfTotal ?? 0)}
              icon={<Bike className="w-4 h-4" />}
              loading={crosstabMakerFuelLoading}
              index={1}
            />
            <KPICard
              label="Category × Powertrain"
              value={cfNoData ? 'Not scraped' : (cfTotal ?? 0)}
              icon={<TrendingUp className="w-4 h-4" />}
              loading={crosstabFuelCategoryLoading}
              index={2}
            />
            <KPICard
              label="Top State"
              value={selectedState ?? '—'}
              icon={<Award className="w-4 h-4" />}
              index={3}
            />
          </>
        ) : (
          <>
            {/* Total carries the volume only. The YoY % used to sit on BOTH
                this card's badge and the YoY card below it -- the same number
                twice. It now lives on the YoY card alone. */}
            <KPICard
              label={`Total Registrations${kpiPeriodSuffix}`}
              value={kpiComboImpossible ? (crosstabTotal ?? NO_VALUE) : (kpis?.total_this_month ?? 0)}
              sub={kpiComboImpossible ? undefined : `${cyLabel(selectedYear)}${selectedMonth ? ` · ${MONTH_NAMES[selectedMonth - 1]}` : ' · year to date'}`}
              icon={<Car className="w-4 h-4" />}
              loading={kpiComboImpossible ? crosstabLoading : kpisLoading}
              index={0}
            />
            {(() => {
              // One source of truth for the YoY card: a % with its arrow, or
              // a dash + "no prior-year data" -- never "— " over "▲ 0.0%".
              const yoy = kpiComboImpossible
                ? (exactlyOnePairActive ? crosstabDetail?.yoy_growth_percent ?? null : null)
                : (yoyKnown ? (yoyRaw ?? null) : null);
              const loading = kpiComboImpossible ? crosstabLoading : (kpisLoading || (yoyRaw === 0 && priorKpisLoading));
              return (
                <KPICard
                  label={`YoY Growth${kpiPeriodSuffix}`}
                  value={yoy == null ? NO_VALUE : `${yoy >= 0 ? '+' : ''}${yoy.toFixed(1)}%`}
                  sub={yoy == null ? undefined : `vs ${cyLabel(selectedYear - 1)}, same months`}
                  change={yoy == null ? null : undefined}
                  icon={<TrendingUp className="w-4 h-4" />}
                  loading={loading}
                  index={1}
                />
              );
            })()}
            <KPICard
              label={`Avg Daily Registrations${kpiPeriodSuffix}`}
              value={kpiComboImpossible
                ? (crosstabTotal === undefined ? NO_VALUE : crosstabTotal > 0 && crosstabAvgDaily === 0 ? '< 1' : (crosstabAvgDaily ?? NO_VALUE))
                : (kpis?.total_registrations_today ?? 0)}
              icon={<Bike className="w-4 h-4" />}
              loading={kpiComboImpossible ? crosstabLoading : kpisLoading}
              index={2}
            />
            {auth.scope_type === 'rto' ? (
              // A single-RTO account's "top state" is by definition its own
              // state -- a card that can never say anything else. Show the
              // RTO the numbers are scoped to instead.
              <KPICard
                label="Your RTO"
                value={auth.scope_rto_code ?? NO_VALUE}
                sub={auth.scope_rto_name ?? undefined}
                icon={<Award className="w-4 h-4" />}
                index={3}
              />
            ) : (
              <KPICard
                label="Top State"
                value={orDash(kpiComboImpossible ? (exactlyOnePairActive ? crosstabDetail?.top_state : null) : kpis?.top_state)}
                icon={<Award className="w-4 h-4" />}
                loading={kpiComboImpossible ? crosstabLoading : kpisLoading}
                index={3}
              />
            )}
          </>
        )}
      </div>

      {(showTrendCard || showVehicleMixCard) && (
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        {showTrendCard && (
        <div className="xl:col-span-2 bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '200ms' }}>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">Registration Trend</h3>
              <p className="text-[10px] text-[var(--text-muted)] font-mono mt-0.5">
                Monthly View — {cyLabel(selectedYear)}
                {trendPartialName && (
                  // Said out loud rather than quietly dropped: a reader who
                  // counts the months should know why the latest one is
                  // absent, not wonder whether the data is stale.
                  <> · {trendPartialName} excluded, month {trendPartialProgress}% elapsed</>
                )}
              </p>
            </div>
            <span className="text-[10px] font-mono px-2 py-1 rounded-md" style={{ color: chart.seriesColors[0], background: 'var(--bg-sunken)' }}>
              MONTHLY
            </span>
          </div>
          {trendLoading ? (
            <LoadingBlock className="h-52" />
          ) : (
            <div
              role="img"
              aria-label={chartData.length
                ? `Monthly registrations, ${cyLabel(selectedYear)}: ${chartData.map((d: { name: string; count: number }) => `${d.name} ${d.count.toLocaleString('en-IN')}`).join(', ')}`
                : `No monthly registrations for ${cyLabel(selectedYear)}`}
            >
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
                <YAxis tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} tickFormatter={formatCompact} width={45} />
                <Tooltip content={<CustomTooltip chart={chart} />} />
                <Area type="monotone" dataKey="count" stroke={chart.seriesColors[0]} strokeWidth={2.5} fill="url(#gradAccent)" dot={{ r: 3, fill: chart.seriesColors[0], strokeWidth: 0 }} activeDot={{ r: 5, fill: chart.seriesColors[0] }} />
              </AreaChart>
            </ResponsiveContainer>
            </div>
          )}
        </div>
        )}

        {showVehicleMixCard && (
        <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '250ms' }}>
          <div className="mb-4">
            <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">Vehicle Mix</h3>
            <p className="text-[10px] text-[var(--text-muted)] font-mono mt-0.5">
              by category — {cyLabel(selectedYear)}{selectedMonth && !selectedMaker ? ` · ${MONTH_NAMES[selectedMonth - 1]}` : ''}{selectedState ? ` · ${selectedState}` : ''}{selectedMaker && <>, {selectedMaker} (year total, no month breakdown)</>}
            </p>
          </div>
          {vehicleMixLoading || !vehicleMixReady ? (
            <LoadingBlock className="h-52" />
          ) : !selectedMaker && categoriesError ? (
            <EmptyState
              title="Couldn't load vehicle mix"
              description="The category query failed or timed out -- this is not an empty result."
              variant="error"
              className="py-8"
              action={{ label: 'Retry', onClick: () => { refetchCategories(); } }}
            />
          ) : pieData.length === 0 ? (
            <EmptyState
              title="No Category Data"
              description={
                vehicleMixNoData
                  ? `Not scraped for ${cyLabel(selectedYear)} yet.`
                  : selectedMaker
                  ? `${selectedMaker} has no registrations in any category for ${cyLabel(selectedYear)}.`
                  : "Run a sync for 'vehicle_class' to load category breakdowns."
              }
              variant="no-data"
              className="py-8"
            />
          ) : (
            <>
              <div role="img" aria-label={`Vehicle mix: ${pieData.map((p) => `${p.name} ${p.value.toLocaleString('en-IN')}`).join(', ')}`}>
              <ResponsiveContainer width="100%" height={160}>
                <PieChart>
                  <Pie
                    data={pieData} cx="50%" cy="50%" innerRadius={45} outerRadius={75} paddingAngle={2} dataKey="value"
                    label={insidePieLabel}
                    labelLine={false}
                  >
                    {pieData.map((p: { name: string }, i: number) => <Cell key={i} fill={pieColors.get(p.name)} />)}
                  </Pie>
                  <Tooltip formatter={(val: number) => [val.toLocaleString('en-IN'), '']} contentStyle={chart.tooltipContentStyle()} {...chart.tooltipTextStyle} />
                </PieChart>
              </ResponsiveContainer>
              </div>
              <div className="mt-2 space-y-1.5 max-h-28 overflow-y-auto pr-1">
                {pieData.map((p: { name: string; value: number }, i: number) => (
                  <div key={p.name} className="flex items-center justify-between text-[11px]">
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
        )}
      </div>
      )}

      {/* Always rendered (not just once a month happens to be selected) so this
          feature is discoverable rather than silently absent. Driven by the
          Year/Month filters above rather than its own date picker: VAHAN4 has
          no day-level granularity at all (confirmed against the live site's
          own axis-selector options — its finest is "Month Wise"), so a
          real month total and year-to-date through it are the finest detail
          this data source can ever supply. */}
      {showMonthDetailCard && (
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
          <LoadingBlock className="h-24" />
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
      )}

      {showStateRankingCard && (
      <div className="grid grid-cols-1 gap-4">
        <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '300ms' }}>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">State Ranking</h3>
              <p className="text-[10px] text-[var(--text-muted)] font-mono mt-0.5">Top 10 by registrations — {cyLabel(selectedYear)}</p>
            </div>
            <ExportCsvButton filename={`state-ranking-cy${selectedYear}`} rows={ranking} />
          </div>
          {rankingLoading ? (
            <LoadingBlock className="h-44" />
          ) : (
            <div className="space-y-3 max-h-96 overflow-y-auto pr-1">
              {(ranking || []).map((s: { state_name: string; total_count: number; share_percent: number }, i: number) => {
                const max = (ranking || [])[0]?.total_count || 1;
                const pct = (s.total_count / max) * 100;
                const color = chart.seriesColor(s.state_name);
                return (
                  <button
                    key={s.state_name} type="button"
                    // A state-locked account can't switch states, so this row
                    // is a read-only bar for them -- clicking it only bounced
                    // off the scope lock.
                    disabled={isStateLocked}
                    className={`w-full flex items-center gap-3 group text-left ${isStateLocked ? 'cursor-default' : 'cursor-pointer'}`}
                    onClick={() => setSelectedState(s.state_name)}
                  >
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
                  </button>
                );
              })}
            </div>
          )}
        </div>

      </div>
      )}

      <div className={`grid grid-cols-1 gap-4 ${selectedState ? '' : 'md:grid-cols-2'}`}>
        {[
          // "States Active 36 / 36 -- All states reporting" used to sit here
          // as a hardcoded string. It claimed full national coverage no
          // matter what the data actually held, which is exactly the kind of
          // fabricated reassurance this product cannot afford. There is no
          // cheap real source for it (the ranking query is capped at 10
          // rows), so it is gone rather than guessed.
          // Only meaningful for an all-India view: with a state selected it
          // divided ONE state's total by 36 (Maharashtra Jun 2025 showed
          // 6,072 = 218,587 / 36), a number that means nothing.
          ...(selectedState ? [] : [
            { label: 'Avg per State / UT', value: kpis ? Math.round(kpis.total_this_month / 36).toLocaleString('en-IN') : NO_VALUE, sub: 'total ÷ 36 states & UTs', colorIdx: 0 },
          ]),
          { label: 'Peak Trend Point', value: chartData.length > 0 ? chartData.reduce((a: { count: number }, b: { count: number }) => a.count > b.count ? a : b).name : NO_VALUE, sub: 'highest volume time point', colorIdx: 5 },
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
    queryFn: ({ signal }) => getMakerCategoryBreakdown({ year, vehicle_category: category, maker, state }, signal),
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
  // /maker-category-breakdown returns one row keyed by "vehicle_category"
  // (not "maker") when both maker and vehicle_category are passed together
  // -- same "both given" response shape as its sibling endpoint, see
  // MakerFuelPanel's comment below for the identical bug already found and
  // fixed there. Searching for r.maker here (a field this response shape
  // never has) always returned undefined -- silently showing 0 regardless
  // of real data (confirmed live: Honda's real Two-Wheeler total in Bihar
  // FY2025 is 275,614, this card showed 0).
  const count = (data || []).find((r: { vehicle_category: string; count: number }) => r.vehicle_category === category)?.count ?? 0;

  return (
    // Standard card shell, same as Registration Trend / Vehicle Mix / State
    // Ranking. It used to be an accent-outlined callout box, which read as a
    // warning or an anomaly rather than as ordinary data (reported live: the
    // highlighted box gave a wrong impression about the numbers in it).
    <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance">
      <div className="mb-4">
        <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">{maker} in {category}</h3>
        <p className="text-[10px] text-[var(--text-muted)] font-mono mt-0.5">
          {cyLabel(year)}{state && <> · {state}</>} — year total
        </p>
      </div>
      <div className="flex items-center justify-between flex-wrap gap-2 text-xs text-[var(--text-secondary)]">
        <span>Registrations</span>
        {isLoading ? (
          <span className="font-mono text-sm font-bold animate-pulse-soft">···</span>
        ) : noDataForYear ? (
          <span className="font-mono text-xs text-[var(--text-muted)]">not scraped for {cyLabel(year)}</span>
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
  // A category-scoped account can't get a fuel figure across all categories
  // (the server pins its category, and category + month is a 400 there), so
  // those rows would sit on "···" forever. They're left out instead.
  const { isCategoryLocked } = useScopeLock();
  const { data, isLoading } = useQuery({
    queryKey: ['fuelCategoryBreakdown', year, category, fuelGroup, state],
    queryFn: ({ signal }) => getFuelCategoryBreakdown({ year, vehicle_category: category, fuel_group: fuelGroup, state }, signal),
  });

  // The exact combo (e.g. "EV Two-Wheelers in March") only exists as a year
  // total -- but each half of it, taken alone, IS real month-level data
  // (Category alone from the vehicle_class-dimension pass, Fuel alone from
  // the fuel-dimension pass -- see Registration.is_supplementary). Surfacing
  // both next to the year total gives an honest closest answer instead of
  // just explaining why the exact number isn't available (found: users
  // expect a month number here and don't know a narrower single-filter
  // query would actually give them one).
  // Shared key with Overview's own /categories/ query (same year/month/
  // state) -- this used to be a separate 'categoryMonthlyOnly' key that
  // re-sent the identical request.
  const { data: categoryMonthly } = useCategoriesQuery({ year, month, state }, { enabled: !!month });
  const categoryMonthlyCount = (categoryMonthly || []).find((c) => c.vehicle_category === category)?.total_count;

  const { data: fuelMonthly } = useQuery({
    queryKey: ['fuelMonthlyOnly', year, month, state],
    queryFn: () => getFuelBreakdown({ year, month, state }),
    enabled: !!month && !isCategoryLocked,
  });
  const fuelMonthlyCount = (fuelMonthly || []).find(
    (f: { fuel_type: string; count: number }) => f.fuel_type === fuelGroup
  )?.count;

  // Two ESTIMATES (not real data) for the exact combo-by-month, built by
  // prorating the real year-total crosstab down using each side's own real
  // monthly curve -- e.g. "category X was 7% of its FY total in this month,
  // so assume the combo was too." Two valid bases (category's curve vs
  // fuel's curve) can disagree meaningfully (confirmed live: 20% apart on a
  // real example) since there's no real month-level combo data anywhere to
  // check either against -- shown side by side, clearly marked as modeled,
  // specifically so that disagreement stays visible rather than picking one
  // and presenting it as settled.
  // Year-only: same cache entry Categories/CategoryDetail use for this
  // year+state (was its own 'categoryYearOnly' key).
  const { data: categoryYearly } = useCategoriesQuery({ year, month: null, state }, { enabled: !!month });
  const categoryYearCount = (categoryYearly || []).find((c) => c.vehicle_category === category)?.total_count;

  const { data: fuelYearly } = useQuery({
    queryKey: ['fuelYearOnly', year, state],
    queryFn: () => getFuelBreakdown({ year, month: null, state }),
    enabled: !!month && !isCategoryLocked,
  });
  const fuelYearCount = (fuelYearly || []).find(
    (f: { fuel_type: string; count: number }) => f.fuel_type === fuelGroup
  )?.count;

  // See MakerCategoryPanel's comment above -- hasYearData (not an empty
  // filtered response) tells "not scraped this year" apart from a real zero.
  const noDataForYear = !hasYearData;
  const count = (data || []).find((r: { vehicle_category: string; count: number }) => r.vehicle_category === category)?.count ?? 0;

  // noDataForYear-gated: `count` falls back to 0 when the crosstab simply
  // hasn't been scraped for this year/state (see the comment on
  // noDataForYear above) -- without this guard, an unscraped combo would
  // estimate to a confident-looking "~0" instead of the "unknown" that it
  // actually is (found in review: categoryMonthlyCount/fuelMonthlyCount
  // come from separate, independently-scraped endpoints and can be real
  // even when the crosstab itself has nothing for this year).
  const estimateByCategoryCurve = (!noDataForYear && categoryYearCount && categoryMonthlyCount != null)
    ? count * (categoryMonthlyCount / categoryYearCount)
    : undefined;
  const estimateByFuelCurve = (!noDataForYear && fuelYearCount && fuelMonthlyCount != null)
    ? count * (fuelMonthlyCount / fuelYearCount)
    : undefined;

  return (
    // Standard card shell -- see MakerCategoryPanel's comment above.
    <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance">
      <div className="mb-4">
        <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">{fuelGroup} {category}</h3>
        <p className="text-[10px] text-[var(--text-muted)] font-mono mt-0.5">
          {cyLabel(year)}{state && <> · {state}</>} — year total
        </p>
      </div>
      <div className="flex items-center justify-between flex-wrap gap-2 text-xs text-[var(--text-secondary)]">
        <span>Registrations</span>
        {isLoading ? (
          <span className="font-mono text-sm font-bold animate-pulse-soft">···</span>
        ) : noDataForYear ? (
          <span className="font-mono text-xs text-[var(--text-muted)]">not scraped for {cyLabel(year)}</span>
        ) : (
          <span className="font-mono text-sm font-bold text-[var(--text-primary)]">{count.toLocaleString('en-IN')}</span>
        )}
      </div>
      {month && (
        <>
          <p className="text-[10px] text-[var(--text-muted)] mt-1">
            This is a year total — the underlying data has no month breakdown, so the Month filter doesn't apply here.
          </p>
          <div className="mt-2 pt-2 border-t border-[var(--border)] flex flex-col gap-1">
            <p className="text-[10px] text-[var(--text-muted)]">Closest real numbers for {MONTH_NAMES[month - 1]} {year} (each alone, not combined):</p>
            <div className="flex items-center justify-between text-[11px]">
              <span>{category} (all powertrains)</span>
              <span className="font-mono font-semibold text-[var(--text-primary)]">
                {categoryMonthlyCount != null ? categoryMonthlyCount.toLocaleString('en-IN') : '···'}
              </span>
            </div>
            {!isCategoryLocked && (
              <div className="flex items-center justify-between text-[11px]">
                <span>{fuelGroup} (all categories)</span>
                <span className="font-mono font-semibold text-[var(--text-primary)]">
                  {fuelMonthlyCount != null ? fuelMonthlyCount.toLocaleString('en-IN') : '···'}
                </span>
              </div>
            )}
          </div>
          <div className="mt-2 pt-2 border-t border-dashed border-[var(--border)] flex flex-col gap-1">
            <p className="text-[10px] text-[var(--text-muted)]">
              Estimated {fuelGroup} {category} for {MONTH_NAMES[month - 1]} {year} — modeled from the year total above, not observed. VAHAN has no real month-level data for this combo; the two methods below can disagree.
            </p>
            <div className="flex items-center justify-between text-[11px]">
              <span>~ by {category}'s monthly pattern</span>
              <span className="font-mono font-semibold text-[var(--accent)]">
                {estimateByCategoryCurve != null ? `~${Math.round(estimateByCategoryCurve).toLocaleString('en-IN')}` : '···'}
              </span>
            </div>
            {!isCategoryLocked && (
              <div className="flex items-center justify-between text-[11px]">
                <span>~ by {fuelGroup}'s monthly pattern</span>
                <span className="font-mono font-semibold text-[var(--accent)]">
                  {estimateByFuelCurve != null ? `~${Math.round(estimateByFuelCurve).toLocaleString('en-IN')}` : '···'}
                </span>
              </div>
            )}
          </div>
        </>
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
    queryFn: ({ signal }) => getMakerFuelBreakdown({ year, maker, fuel_group: fuelGroup, state }, signal),
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
    // Standard card shell -- see MakerCategoryPanel's comment above.
    <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance">
      <div className="mb-4">
        <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">{maker} — {fuelGroup}</h3>
        <p className="text-[10px] text-[var(--text-muted)] font-mono mt-0.5">
          {cyLabel(year)}{state && <> · {state}</>} — year total
        </p>
      </div>
      <div className="flex items-center justify-between flex-wrap gap-2 text-xs text-[var(--text-secondary)]">
        <span>Registrations</span>
        {isLoading ? (
          <span className="font-mono text-sm font-bold animate-pulse-soft">···</span>
        ) : noDataForYear ? (
          <span className="font-mono text-xs text-[var(--text-muted)]">not scraped for {cyLabel(year)}</span>
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
