// frontend/src/pages/YoY.tsx
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  BarChart, Bar, LabelList, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, LineChart, Line, TooltipProps
} from 'recharts';
import { useAppStore } from '../hooks/useAppStore';
import { getYoYMonthly, getYoYSummary } from '../api/vahan';
import { useChartTheme } from '../hooks/useChartTheme';
import { EmptyState } from '../components/EmptyState';
import { ErrorBanner } from '../components/ErrorBanner';
import { LoadingBlock } from '../components/LoadingBlock';
import { formatCompact, NO_VALUE } from '../utils/format';
import { monthWindow, partialMonthProgress, resolvePartialMonth } from '../utils/partialMonth';

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function YoYTooltip({ active, payload, label, chart }: TooltipProps<number, string> & { chart: ReturnType<typeof useChartTheme> }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl px-3 py-2.5" style={{ background: chart.tooltipBg, border: `1px solid ${chart.tooltipBorder}` }}>
      <p className="text-[10px] uppercase tracking-widest mb-2" style={{ color: chart.axisText }}>{label}</p>
      {payload.map((p, i) => (
        <div key={i} className="flex items-center gap-2 mb-1">
          <div className="w-2 h-2 rounded-sm" style={{ background: p.fill }} />
          <span className="text-[11px] font-mono" style={{ color: chart.axisText }}>{p.name}:</span>
          <span className="text-xs font-bold font-mono" style={{ color: chart.tooltipText }}>{p.value?.toLocaleString('en-IN')}</span>
        </div>
      ))}
    </div>
  );
}

const CURRENT_YEAR = new Date().getFullYear();
// VAHAN4's own year selector goes back to 2003; offering the full range here
// too rather than hardcoding to "last year vs this year" -- data may not be
// scraped for every year yet, but the picker shouldn't be the bottleneck.
const SELECTABLE_YEARS = Array.from({ length: CURRENT_YEAR - 2002 }, (_, i) => CURRENT_YEAR - i);

export function YoYPage() {
  const chart = useChartTheme();
  const { comparisonYearA, comparisonYearB, setComparisonYears, selectedCategory, selectedState } = useAppStore();
  // The shared State filter is honoured here (it used to be silently dropped:
  // a user arriving with state=Lakshadweep saw all-India numbers under no
  // geography label). Both /yoy endpoints already accept `state` and clamp it
  // to the account's scope server-side.
  const stateParam = selectedState || undefined;
  // Comparing a year with itself is always 0% and means nothing. The pickers
  // can't produce it (each omits the other side's year); this guards a value
  // arriving from elsewhere.
  const sameYear = comparisonYearA === comparisonYearB;
  // Full year (1-12) by default -- same behavior as before this range picker
  // existed. A custom range (e.g. Apr-Jul) compares that exact window across
  // both selected years instead of the whole year.
  const [startMonth, setStartMonth] = useState(1);
  const [endMonth, setEndMonth] = useState(12);
  const isCustomRange = startMonth !== 1 || endMonth !== 12;

  const { data: monthly, isLoading, isError, refetch } = useQuery({
    queryKey: ['yoy', comparisonYearA, comparisonYearB, startMonth, endMonth, selectedCategory, stateParam ?? null],
    queryFn: () => getYoYMonthly(comparisonYearA, comparisonYearB, stateParam, startMonth, endMonth, selectedCategory),
    enabled: !sameYear,
  });

  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ['yoySummary', comparisonYearA, comparisonYearB, startMonth, endMonth, selectedCategory, stateParam ?? null],
    queryFn: () => getYoYSummary(comparisonYearA, comparisonYearB, startMonth, endMonth, selectedCategory, stateParam),
    enabled: !sameYear,
  });

  // growth_percent is null for months comparisonYearB hasn't reached yet
  // (the API distinguishes "not occurred/scraped" from "zero registrations").
  // Volume charts still show every month so year A's full trend is visible,
  // but growth-rate views should only cover months both years actually have.
  // Months comparisonYearB hasn't reached yet come back as 0, which plots as
  // a real bar labelled "0.0M" beside a full prior-year bar and drops the
  // trend line vertically to zero from the current month on (found in review:
  // an OEM reader sees that as the market collapsing, not as "October hasn't
  // happened yet"). null instead, with connectNulls={false}, so year B's line
  // simply ends at the last month that exists. Year A keeps every month, so
  // its full-year shape is still visible. "Hasn't happened" is read from the
  // data (months after year B's newest non-zero month), not today's date --
  // the data can be weeks behind the calendar.
  type MonthRow = { month: number; growth_percent: number | null; is_partial?: boolean; [key: string]: number | boolean | null | undefined };
  const rows: MonthRow[] = monthly?.data || [];
  const lastBMonth = rows.reduce((mx, d) => (Number(d[`year_${comparisonYearB}`]) > 0 ? Math.max(mx, d.month) : mx), 0);

  // The stored-but-incomplete month. From the API when it says (partial_month
  // + partial_month_year, derived from when the data was scraped); the wall
  // clock is only the fallback for an older backend that sends neither.
  const apiPartial: number | null | undefined = monthly && 'partial_month' in monthly
    ? monthly.partial_month
    : summary && 'partial_month' in summary ? summary.partial_month : undefined;
  const apiPartialYear: number | null | undefined = monthly?.partial_month_year ?? summary?.partial_month_year;
  const partialYear = apiPartial !== undefined && apiPartialYear != null ? apiPartialYear : comparisonYearB;
  const partial = monthly && (partialYear === comparisonYearA || partialYear === comparisonYearB)
    ? resolvePartialMonth(partialYear, apiPartial, { apiPartialYear, scrapedAt: monthly?.data_scraped_at })
    : null;

  const chartData: { name: string; partial: boolean; [key: string]: number | string | boolean | null }[] = rows.map((d) => ({
    name: MONTH_NAMES[d.month - 1],
    partial: !!partial && d.month === partial.month,
    [`${comparisonYearA}`]: (d[`year_${comparisonYearA}`] as number | null) ?? null,
    [`${comparisonYearB}`]: d.month > lastBMonth ? null : ((d[`year_${comparisonYearB}`] as number | null) ?? null),
    growth: d.growth_percent,
  }));
  // The in-progress month is real but not COMPARABLE: a month that's only
  // part-way through is measured against a full month of the prior year, so
  // it always renders as a large fake decline (found live: Sep 2026 showed
  // -38.6% purely because it was 15 days in -- 1,024,868 registrations
  // against a complete Sep 2025's 1,931,043). Excluded from the growth bars
  // and reported separately below with its actual progress, rather than
  // sitting in the chart as a red bar implying the market is collapsing.
  const partialMonthName = partial?.name ?? null;
  const otherYear = partialYear === comparisonYearB ? comparisonYearA : comparisonYearB;

  const growthChartData = chartData
    .filter((d) => d.growth !== null)
    .filter((d) => !d.partial);

  // The window the headline % actually compares: the backend cuts the range
  // at the last COMPLETE month either year has. When that cut falls before
  // the range start (e.g. Oct-Dec while data is complete only through Aug),
  // there is nothing comparable yet -- say so instead of "0 -> 0".
  const compareThrough: number | null = typeof summary?.compare_through_month === 'number' ? summary.compare_through_month : null;
  const noCompleteMonths = compareThrough != null && compareThrough < startMonth;
  const comparedWindow = compareThrough != null && !noCompleteMonths ? monthWindow(startMonth, compareThrough) : null;

  // null (no summary yet / no prior-year volume) renders as a dash, not "+0.0%".
  const growth: number | null = !noCompleteMonths && summary && summary[`total_${comparisonYearA}`] ? (summary.growth_percent ?? null) : null;
  const colorA = chart.seriesColors[4];
  const colorB = chart.seriesColors[0];

  // Selectable years go back to 2003 (matches VAHAN4's own picker), but real
  // scraped data currently starts 2016 -- picking an unscraped year returns
  // an empty `data` array rather than an error, so the charts below would
  // otherwise render with nothing in them and look broken instead of empty.
  const hasNoData = !sameYear && !isLoading && (monthly?.data?.length ?? 0) === 0;

  return (
    <div className="p-3 sm:p-6 space-y-5">
      {isError && (
        <ErrorBanner
          title="Couldn't load year-over-year data"
          description="The request to the server failed. Check your connection and try again."
          action={{ label: 'Retry', onClick: () => refetch() }}
        />
      )}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="animate-entrance min-w-0">
          <h2 className="text-xl font-bold text-[var(--text-primary)] tracking-tight">Year-over-Year Analysis</h2>
          <p className="text-xs text-[var(--text-muted)] mt-0.5 font-mono uppercase tracking-widest">
            {isCustomRange ? `${MONTH_NAMES[startMonth - 1]}-${MONTH_NAMES[endMonth - 1]}` : 'Full Year'} comparison — CY {comparisonYearA} vs CY {comparisonYearB} — {selectedState ?? 'All India'} — {selectedCategory ?? 'All categories'}
          </p>
        </div>
        <div className="flex items-center gap-3 flex-wrap animate-entrance" style={{ animationDelay: '50ms' }}>
          <div className="px-2 py-1.5 rounded-lg border flex items-center gap-1.5 border-[var(--border)] text-[var(--text-secondary)]">
            <span className="text-[10px] uppercase tracking-widest text-[var(--text-muted)]" id="yoy-range-label">Range</span>
            <label htmlFor="yoy-start-month" className="sr-only">Range start month</label>
            <select
              id="yoy-start-month"
              aria-label="Range start month"
              value={startMonth}
              onChange={(e) => {
                const v = Number(e.target.value);
                setStartMonth(v);
                if (v > endMonth) setEndMonth(v);
              }}
              className="bg-[var(--bg-sunken)] text-xs font-mono font-semibold cursor-pointer rounded px-1"
            >
              {MONTH_NAMES.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
            </select>
            <span className="text-[var(--text-muted)]" aria-hidden="true">→</span>
            <label htmlFor="yoy-end-month" className="sr-only">Range end month</label>
            <select
              id="yoy-end-month"
              aria-label="Range end month"
              value={endMonth}
              onChange={(e) => {
                const v = Number(e.target.value);
                setEndMonth(v);
                if (v < startMonth) setStartMonth(v);
              }}
              className="bg-[var(--bg-sunken)] text-xs font-mono font-semibold cursor-pointer rounded px-1"
            >
              {MONTH_NAMES.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
            </select>
          </div>
          <div className="px-2 py-1.5 rounded-lg border flex items-center gap-1.5 border-[var(--border)] text-[var(--text-secondary)]">
            <label htmlFor="yoy-year-a" className="text-[10px] uppercase tracking-widest text-[var(--text-muted)]">Year A</label>
            <select
              id="yoy-year-a"
              aria-label="Year A (baseline calendar year)"
              value={comparisonYearA}
              onChange={(e) => setComparisonYears(Number(e.target.value), comparisonYearB)}
              className="bg-[var(--bg-sunken)] text-xs font-mono font-semibold cursor-pointer rounded px-1"
            >
              {SELECTABLE_YEARS.filter((y) => y !== comparisonYearB).map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
            <span className="text-[var(--text-muted)]" aria-hidden="true">→</span>
            <span className="text-[var(--text-primary)] font-mono text-xs font-semibold">{summaryLoading ? '…' : noCompleteMonths ? NO_VALUE : (summary?.[`total_${comparisonYearA}`] || 0).toLocaleString('en-IN')}</span>
          </div>
          <div className="px-2 py-1.5 rounded-lg border flex items-center gap-1.5" style={{ background: 'var(--bg-sunken)', borderColor: 'var(--border)', color: 'var(--accent)' }}>
            <label htmlFor="yoy-year-b" className="text-[10px] uppercase tracking-widest text-[var(--text-muted)]">Year B</label>
            <select
              id="yoy-year-b"
              aria-label="Year B (comparison calendar year)"
              value={comparisonYearB}
              onChange={(e) => setComparisonYears(comparisonYearA, Number(e.target.value))}
              className="bg-[var(--bg-sunken)] text-xs font-mono font-semibold cursor-pointer rounded px-1"
              style={{ color: 'var(--accent)' }}
            >
              {SELECTABLE_YEARS.filter((y) => y !== comparisonYearA).map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
            <span className="text-[var(--text-muted)]" aria-hidden="true">→</span>
            <span className="text-[var(--text-primary)] font-mono text-xs font-semibold">{summaryLoading ? '…' : noCompleteMonths ? NO_VALUE : (summary?.[`total_${comparisonYearB}`] || 0).toLocaleString('en-IN')}</span>
          </div>
          <div
            className="px-3 py-1.5 rounded-lg text-xs font-bold font-mono border"
            style={{
              background: 'var(--bg-sunken)',
              color: growth == null ? 'var(--text-muted)' : growth >= 0 ? 'var(--success)' : 'var(--danger)',
              borderColor: 'var(--border)',
            }}
            title={noCompleteMonths
              ? 'No complete months in this range yet'
              : growth == null ? `No ${comparisonYearA} volume to compare against`
              : comparedWindow ? `Compares ${comparedWindow} ${comparisonYearB} with ${comparedWindow} ${comparisonYearA}` : undefined}
            data-testid="yoy-growth-pill"
          >
            {growth == null ? NO_VALUE : `${growth >= 0 ? '+' : ''}${growth.toFixed(1)}%`}
            {comparedWindow && growth != null && (
              <span className="ml-1.5 text-[10px] font-semibold text-[var(--text-muted)]" data-testid="yoy-compared-window">
                {comparedWindow} vs {comparedWindow}
              </span>
            )}
          </div>
        </div>
      </div>

      {!sameYear && noCompleteMonths && (
        <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] animate-entrance" data-testid="yoy-no-complete-months">
          <EmptyState
            variant="no-data"
            title="No complete months in this range yet"
            description={`${monthWindow(startMonth, endMonth)} has no fully scraped month in both ${comparisonYearA} and ${comparisonYearB} — the data is complete through ${compareThrough ? MONTH_NAMES[compareThrough - 1] : 'none of this range'}. Pick an earlier range.`}
          />
        </div>
      )}
      {sameYear ? (
        <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] animate-entrance">
          <EmptyState variant="no-selection" title="Pick two different years" description={`Year A and Year B are both ${comparisonYearA}; a year compared with itself is always 0%.`} />
        </div>
      ) : hasNoData ? (
        <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] animate-entrance" style={{ animationDelay: '80ms' }}>
          <EmptyState
            variant="no-data"
            title="No data for these years"
            description={`Neither ${comparisonYearA} nor ${comparisonYearB} has been scraped yet. Try a year between 2016 and ${CURRENT_YEAR}.`}
          />
        </div>
      ) : (
      <>
      <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '80ms' }}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">Monthly Volume Comparison</h3>
          <div className="flex items-center gap-4 text-[11px] font-mono">
            <span className="flex items-center gap-1.5"><span className="w-3 h-0.5 rounded-full inline-block" style={{ background: colorA }} /> {comparisonYearA}</span>
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm inline-block" style={{ background: colorB }} /> {comparisonYearB}</span>
          </div>
        </div>
        {isLoading ? <LoadingBlock className="h-64" /> : (
          <div role="img" aria-label={`Monthly registrations, ${comparisonYearA} vs ${comparisonYearB}: ${chartData.map((d) => `${d.name} ${d[`${comparisonYearA}`] ?? NO_VALUE} vs ${d[`${comparisonYearB}`] ?? NO_VALUE}`).join(', ')}`}>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={chartData} barGap={4} margin={{ top: 20 }}>
              <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} vertical={false} />
              <XAxis dataKey="name" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} tickFormatter={formatCompact} width={40} />
              <Tooltip content={<YoYTooltip chart={chart} />} />
              <Bar dataKey={`${comparisonYearA}`} fill={colorA} radius={[3, 3, 0, 0]} maxBarSize={20}>
                {chartData.map((d) => (
                  <Cell key={d.name} fill={colorA} fillOpacity={d.partial && partialYear === comparisonYearA ? 0.35 : 1} />
                ))}
                <LabelList dataKey={`${comparisonYearA}`} position="top" formatter={formatCompact} style={{ fill: chart.axisText, fontSize: 9, fontFamily: 'JetBrains Mono' }} />
              </Bar>
              <Bar dataKey={`${comparisonYearB}`} fill={colorB} radius={[3, 3, 0, 0]} maxBarSize={20}>
                {/* The in-progress month is drawn faded so it doesn't read as a
                    real decline against a full prior-year month. */}
                {chartData.map((d) => (
                  <Cell key={d.name} fill={colorB} fillOpacity={d.partial && partialYear === comparisonYearB ? 0.35 : 1} />
                ))}
                <LabelList dataKey={`${comparisonYearB}`} position="top" formatter={formatCompact} style={{ fill: chart.axisText, fontSize: 9, fontFamily: 'JetBrains Mono' }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          </div>
        )}
        {partial && chartData.some((d) => d.partial) && (
          <p className="text-[10px] text-[var(--text-muted)] mt-2 font-mono" data-testid="yoy-partial-bar-note">
            Faded bar: {partial.name} {partialYear} is a partial month ({partialMonthProgress(partial)}) — not comparable with a full month.
          </p>
        )}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '130ms' }}>
          <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight mb-4">Month-wise Growth Rate</h3>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={growthChartData} layout="vertical" margin={{ right: 30, left: 10 }}>
              <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} horizontal={false} />
              <XAxis type="number" domain={[-50, 50]} tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${v}%`} />
              <YAxis dataKey="name" type="category" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} width={30} axisLine={false} tickLine={false} />
              <Tooltip formatter={(val: number) => [`${val?.toFixed(1)}%`, 'Growth']} contentStyle={chart.tooltipContentStyle()} {...chart.tooltipTextStyle} />
              <Bar dataKey="growth" radius={[0, 3, 3, 0]} maxBarSize={14}>
                {growthChartData.map((d, i: number) => (
                  <Cell key={i} fill={(d.growth as number) >= 0 ? chart.success : chart.danger} />
                ))}
                <LabelList dataKey="growth" position="right" formatter={(v: number) => `${v.toFixed(1)}%`} style={{ fill: chart.axisText, fontSize: 9, fontFamily: 'JetBrains Mono' }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <div className="flex items-center justify-center gap-4 mt-3 text-[10px] font-mono">
            <span style={{ color: chart.success }}>▲ Positive growth</span>
            <span style={{ color: chart.danger }}>▼ Negative growth</span>
          </div>
          {partial && partialMonthName && (
            <p className="text-[10px] text-[var(--text-muted)] mt-2 text-center leading-relaxed" data-testid="yoy-partial-note">
              {partialMonthName} {partialYear} excluded — {partial.fromData ? 'month only part-scraped' : 'month still in progress'}
              {' '}({partialMonthProgress(partial)}).
              Comparing it against a full {partialMonthName} {otherYear} would show a change that isn't real.
            </p>
          )}
        </div>

        <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '160ms' }}>
          <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight mb-4">Dual-Year Trend Line</h3>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} vertical={false} />
              <XAxis dataKey="name" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} tickFormatter={formatCompact} width={40} />
              <Tooltip formatter={(val: number) => val.toLocaleString('en-IN')} contentStyle={chart.tooltipContentStyle()} {...chart.tooltipTextStyle} />
              <Line type="monotone" dataKey={`${comparisonYearA}`} stroke={colorA} strokeWidth={1.5} dot={{ r: 3, fill: colorA }} />
              <Line type="monotone" dataKey={`${comparisonYearB}`} stroke={colorB} strokeWidth={2.5} dot={{ r: 4, fill: colorB }} activeDot={{ r: 6 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '190ms' }}>
        <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight mb-4">Month-by-Month Breakdown</h3>
        <div className="grid grid-cols-6 gap-3 mb-4 text-[10px] uppercase tracking-widest text-[var(--text-muted)] font-mono px-1">
          <span>Month</span>
          <span>{comparisonYearA}</span>
          <span>{comparisonYearB}</span>
          <span className="col-span-2 text-center">Delta</span>
          <span className="text-right">Growth</span>
        </div>
        <div className="space-y-2">
          {growthChartData.map((d, i: number) => {
            const a = Number(d[`${comparisonYearA}`]) || 0;
            const b = Number(d[`${comparisonYearB}`]) || 0;
            const delta = b - a;
            const pct = Number(d.growth) || 0;
            return (
              <div key={d.name} className="grid grid-cols-6 gap-3 items-center px-1 py-1.5 rounded-lg hover:bg-[var(--bg-card-hover)] transition-colors">
                <span className="text-xs font-mono text-[var(--text-secondary)] font-semibold">{d.name}</span>
                <span className="font-mono text-xs text-[var(--text-muted)]">{a.toLocaleString('en-IN')}</span>
                <span className="font-mono text-xs font-semibold" style={{ color: colorB }}>{b.toLocaleString('en-IN')}</span>
                <div className="col-span-2 flex items-center gap-1">
                  <span className="font-mono text-[11px] font-bold" style={{ color: delta >= 0 ? chart.success : chart.danger }}>
                    {delta >= 0 ? '+' : ''}{delta.toLocaleString('en-IN')}
                  </span>
                  <div className="h-0.5 flex-1 rounded-full overflow-hidden bg-[var(--bg-sunken)]">
                    <div className="h-full rounded-full" style={{ width: `${Math.min(Math.abs(pct), 100)}%`, background: pct >= 0 ? chart.success : chart.danger }} />
                  </div>
                </div>
                <span className="text-right font-mono text-[11px] font-bold" style={{ color: pct >= 0 ? chart.success : chart.danger }}>
                  {pct >= 0 ? '+' : ''}{pct.toFixed(1)}%
                </span>
              </div>
            );
          })}
        </div>
      </div>
      </>
      )}
    </div>
  );
}
