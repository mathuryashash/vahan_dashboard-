// frontend/src/pages/YoY.tsx
import { useQuery } from '@tanstack/react-query';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, LineChart, Line, TooltipProps
} from 'recharts';
import { useAppStore } from '../hooks/useAppStore';
import { getYoYMonthly, getYoYSummary } from '../api/vahan';
import { useChartTheme } from '../hooks/useChartTheme';
import { EmptyState } from '../components/EmptyState';

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
  const { comparisonYearA, comparisonYearB, setComparisonYears } = useAppStore();

  const { data: monthly, isLoading } = useQuery({
    queryKey: ['yoy', comparisonYearA, comparisonYearB],
    queryFn: () => getYoYMonthly(comparisonYearA, comparisonYearB),
  });

  const { data: summary } = useQuery({
    queryKey: ['yoySummary', comparisonYearA, comparisonYearB],
    queryFn: () => getYoYSummary(comparisonYearA, comparisonYearB),
  });

  // growth_percent is null for months comparisonYearB hasn't reached yet
  // (the API distinguishes "not occurred/scraped" from "zero registrations").
  // Volume charts still show every month so year A's full trend is visible,
  // but growth-rate views should only cover months both years actually have.
  const chartData: { name: string; [key: string]: number | string | null }[] = (monthly?.data || []).map((d: { month: number; [key: string]: number | null }) => ({
    name: MONTH_NAMES[d.month - 1],
    [`${comparisonYearA}`]: d[`year_${comparisonYearA}`],
    [`${comparisonYearB}`]: d[`year_${comparisonYearB}`],
    growth: d.growth_percent,
  }));
  const growthChartData = chartData.filter((d) => d.growth !== null);

  const growth = summary?.growth_percent ?? 0;
  const colorA = chart.seriesColors[4];
  const colorB = chart.seriesColors[0];

  // Selectable years go back to 2003 (matches VAHAN4's own picker), but real
  // scraped data currently starts 2016 -- picking an unscraped year returns
  // an empty `data` array rather than an error, so the charts below would
  // otherwise render with nothing in them and look broken instead of empty.
  const hasNoData = !isLoading && (monthly?.data?.length ?? 0) === 0;

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div className="animate-entrance">
          <h2 className="text-xl font-bold text-[var(--text-primary)] tracking-tight">Year-over-Year Analysis</h2>
          <p className="text-xs text-[var(--text-muted)] mt-0.5 font-mono uppercase tracking-widest">
            Temporal comparison — {comparisonYearA} vs {comparisonYearB}
          </p>
        </div>
        <div className="flex items-center gap-3 animate-entrance" style={{ animationDelay: '50ms' }}>
          <div className="px-2 py-1.5 rounded-lg border flex items-center gap-1.5 border-[var(--border)] text-[var(--text-secondary)]">
            <select
              value={comparisonYearA}
              onChange={(e) => setComparisonYears(Number(e.target.value), comparisonYearB)}
              className="bg-[var(--bg-sunken)] text-xs font-mono font-semibold focus:outline-none cursor-pointer rounded px-1"
            >
              {SELECTABLE_YEARS.map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
            <span className="text-[var(--text-muted)]">→</span>
            <span className="text-[var(--text-primary)] font-mono text-xs font-semibold">{(summary?.[`total_${comparisonYearA}`] || 0).toLocaleString('en-IN')}</span>
          </div>
          <div className="px-2 py-1.5 rounded-lg border flex items-center gap-1.5" style={{ background: 'var(--bg-sunken)', borderColor: 'var(--border)', color: 'var(--accent)' }}>
            <select
              value={comparisonYearB}
              onChange={(e) => setComparisonYears(comparisonYearA, Number(e.target.value))}
              className="bg-[var(--bg-sunken)] text-xs font-mono font-semibold focus:outline-none cursor-pointer rounded px-1"
              style={{ color: 'var(--accent)' }}
            >
              {SELECTABLE_YEARS.map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
            <span className="text-[var(--text-muted)]">→</span>
            <span className="text-[var(--text-primary)] font-mono text-xs font-semibold">{(summary?.[`total_${comparisonYearB}`] || 0).toLocaleString('en-IN')}</span>
          </div>
          <div
            className="px-3 py-1.5 rounded-lg text-xs font-bold font-mono border"
            style={{
              background: 'var(--bg-sunken)',
              color: growth >= 0 ? 'var(--success)' : 'var(--danger)',
              borderColor: 'var(--border)',
            }}
          >
            {growth >= 0 ? '+' : ''}{growth.toFixed(1)}%
          </div>
        </div>
      </div>

      {hasNoData ? (
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
        {isLoading ? <div className="h-64 rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft" /> : (
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={chartData} barGap={4}>
              <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} vertical={false} />
              <XAxis dataKey="name" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${(v/1000000).toFixed(1)}M`} width={40} />
              <Tooltip content={<YoYTooltip chart={chart} />} />
              <Bar dataKey={`${comparisonYearA}`} fill={colorA} radius={[3, 3, 0, 0]} maxBarSize={20} />
              <Bar dataKey={`${comparisonYearB}`} fill={colorB} radius={[3, 3, 0, 0]} maxBarSize={20} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '130ms' }}>
          <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight mb-4">Month-wise Growth Rate</h3>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={growthChartData} layout="vertical">
              <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} horizontal={false} />
              <XAxis type="number" domain={[-50, 50]} tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${v}%`} />
              <YAxis dataKey="name" type="category" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} width={30} axisLine={false} tickLine={false} />
              <Tooltip formatter={(val: number) => [`${val?.toFixed(1)}%`, 'Growth']} contentStyle={chart.tooltipContentStyle()} {...chart.tooltipTextStyle} />
              <Bar dataKey="growth" radius={[0, 3, 3, 0]} maxBarSize={14}>
                {growthChartData.map((d, i: number) => (
                  <Cell key={i} fill={(d.growth as number) >= 0 ? chart.success : chart.danger} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <div className="flex items-center justify-center gap-4 mt-3 text-[10px] font-mono">
            <span style={{ color: chart.success }}>▲ Positive growth</span>
            <span style={{ color: chart.danger }}>▼ Negative growth</span>
          </div>
        </div>

        <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '160ms' }}>
          <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight mb-4">Dual-Year Trend Line</h3>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} vertical={false} />
              <XAxis dataKey="name" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${(v/1000000).toFixed(1)}M`} width={40} />
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
              <div key={i} className="grid grid-cols-6 gap-3 items-center px-1 py-1.5 rounded-lg hover:bg-[var(--bg-card-hover)] transition-colors">
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
