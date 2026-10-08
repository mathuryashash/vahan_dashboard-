// frontend/src/pages/CategoryDetail.tsx
import { useQuery } from '@tanstack/react-query';
import { Navigate, useLocation, useNavigate, useParams } from 'react-router-dom';
import { PieChart, Pie, Cell, BarChart, Bar, LabelList, ResponsiveContainer, XAxis, YAxis, CartesianGrid, Tooltip } from 'recharts';
import { getTopMakers, getFuelBreakdown } from '../api/vahan';
import { useCategoriesQuery } from '../hooks/useCategoriesQuery';
import { LoadingBlock } from '../components/LoadingBlock';
import { cyLongLabel, formatCompact } from '../utils/format';
import { useAppStore } from '../hooks/useAppStore';
import { useScopeLock } from '../hooks/useScopeLock';
import { ArrowLeft } from '../components/Icons';
import { Link } from 'react-router-dom';
import { useChartTheme } from '../hooks/useChartTheme';
import { EmptyState } from '../components/EmptyState';
import { ErrorBanner } from '../components/ErrorBanner';
import { insidePieLabel, TruncatedYAxisTick } from '../components/ChartAxisTick';

// The live VAHAN4 site can only pivot on one Y-axis dimension per visit, so
// the scraper's maker-pass and fuel-pass rows are never tagged with a real
// vehicle_class (they store 'All' -- see Registration.is_supplementary and
// scraper_service.persist_rto_batch). There is no cross-tab of maker/fuel by
// vehicle class in the source data for live-scraped years, so this is a real
// data-source gap, not a bug to route around with estimated numbers.
// The stored vehicle_category values (full words, see query_filters.py).
// A slug outside this set (and outside whatever /categories/ returned) is a
// typo or a stale link, not a category with no data.
export const KNOWN_CATEGORIES = ['Two-Wheeler', 'Three-Wheeler', 'Four-Wheeler', 'Commercial Vehicle', 'Other'];

const NO_CROSS_TAB_MESSAGE =
  "VAHAN's live reports can't cross-tabulate this against a vehicle category in one export -- this breakdown isn't available for this category yet.";

export function CategoryDetailPage() {
  const { vehicleClass } = useParams<{ vehicleClass: string }>();
  const decoded = decodeURIComponent(vehicleClass || '');
  const { selectedYear, selectedState } = useAppStore();
  const location = useLocation();
  const navigate = useNavigate();
  const { lockedCategory } = useScopeLock();
  const chart = useChartTheme();

  // Same shared-filter fix as Categories.tsx -- these three queries ignored
  // selectedState, so drilling into a category after picking a state showed
  // national numbers under a state-filtered header.
  // Not fired for a locked account on the wrong segment: it is redirected below,
  // and the unmount would abort this request only for the new page to resend it.
  const { data: cats, isLoading: catsLoading } = useCategoriesQuery(
    { year: selectedYear, state: selectedState },
    { enabled: !(lockedCategory && decoded !== lockedCategory) },
  );

  const currentCat = (cats || []).find((c) => c.vehicle_category === decoded);
  const isKnownCategory = KNOWN_CATEGORIES.includes(decoded) || (cats || []).some((c) => c.vehicle_category === decoded);

  const { data: makers, isLoading: makersLoading, isError: makersError, refetch: refetchMakers } = useQuery({
    queryKey: ['makers', decoded, selectedYear, selectedState],
    queryFn: () => getTopMakers({ vehicle_category: decoded, year: selectedYear, state: selectedState || undefined }),
    enabled: !!decoded && isKnownCategory && !(lockedCategory && decoded !== lockedCategory),
  });

  const { data: fuel, isLoading: fuelLoading } = useQuery({
    queryKey: ['fuel', decoded, selectedYear, selectedState],
    queryFn: () => getFuelBreakdown({ vehicle_category: decoded, year: selectedYear, state: selectedState || undefined }),
    enabled: !!decoded && isKnownCategory && !(lockedCategory && decoded !== lockedCategory),
  });

  const totalFuelCount = (fuel || []).reduce((sum: number, f: { count: number }) => sum + f.count, 0);

  // The server answers a scoped account with its OWN segment whatever the
  // URL says, which rendered one segment's data under another's heading.
  // A category-scoped account asking for another segment: the server would
  // answer with its OWN segment's data (scope clamp), which rendered one
  // segment's numbers under another's heading. Send it to its own category,
  // carrying a flag so the destination can say why.
  if (lockedCategory && decoded !== lockedCategory) {
    return (
      <Navigate
        to={`/categories/${encodeURIComponent(lockedCategory)}${location.search}`}
        replace
        state={{ notInPlan: decoded }}
      />
    );
  }

  // B11: an unknown slug used to render an empty detail page that looked
  // like a real category with no data.
  if (!isKnownCategory) {
    return (
      <div className="p-3 sm:p-6">
        <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] animate-entrance" data-testid="category-not-found">
          <EmptyState
            variant="search"
            title="Unknown category"
            description={`"${decoded}" isn't a vehicle category in this dashboard. Categories are: ${KNOWN_CATEGORIES.join(', ')}.`}
            action={{ label: 'Back to Categories', onClick: () => navigate(`/categories${location.search}`) }}
          />
        </div>
      </div>
    );
  }

  const notInPlan = (location.state as { notInPlan?: string } | null)?.notInPlan;

  return (
    <div className="p-3 sm:p-6 space-y-6">
      {makersError && (
        <ErrorBanner
          title="Couldn't load maker data"
          description="The request to the server failed. Check your connection and try again."
          action={{ label: 'Retry', onClick: () => refetchMakers() }}
        />
      )}
      {notInPlan && (
        <div role="status" className="bg-[var(--bg-card)] rounded-xl border border-[var(--border)] px-4 py-3 text-xs text-[var(--text-secondary)]" data-testid="not-in-plan">
          <span className="font-semibold">{notInPlan}</span> is not in your plan — your account covers {lockedCategory} only, shown below.
        </div>
      )}
      <div className="animate-entrance">
        <Link to="/categories" className="inline-flex items-center gap-2 text-[11px] text-[var(--text-muted)] hover:text-[var(--accent)] font-mono mb-3 transition-colors">
          <ArrowLeft className="w-3.5 h-3.5" />
          Back to Categories
        </Link>
        <div className="flex items-center gap-3">
          <div className="w-1 h-8 rounded-full" style={{ background: chart.seriesColor(decoded) }} />
          <div>
            <h2 className="text-xl font-bold text-[var(--text-primary)] tracking-tight">{decoded}</h2>
            <p className="text-[10px] text-[var(--text-muted)] mt-0.5 font-mono uppercase tracking-widest">
              {cyLongLabel(selectedYear)}{selectedState ? ` · ${selectedState}` : ' · All India'} · {catsLoading ? '…' : (currentCat?.total_count ?? 0).toLocaleString('en-IN')} registrations
              {currentCat?.yoy_growth != null && (
                <span className="ml-2 font-mono font-bold" style={{ color: (currentCat.yoy_growth as number) >= 0 ? chart.success : chart.danger }}>
                  {((currentCat.yoy_growth as number) >= 0 ? '+' : '')}{currentCat.yoy_growth?.toFixed(1)}% YoY
                </span>
              )}
            </p>
          </div>
        </div>
      </div>

      <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '100ms' }}>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">Top Makers</h3>
            <p className="text-[10px] text-[var(--text-muted)] font-mono mt-0.5">manufacturers leading in {decoded}</p>
          </div>
        </div>
        {makersLoading ? (
          <LoadingBlock className="h-[280px]" slowMessage="Per-category maker and fuel breakdowns can take several seconds." />
        ) : (makers || []).length === 0 ? (
          <EmptyState title="No Maker Breakdown" description={NO_CROSS_TAB_MESSAGE} variant="no-data" className="py-8" />
        ) : (
          <>
            {/* Height scales with row count, matching every other maker chart.
                Fixed 280px made Recharts drop every other tick, leaving half
                the bars (including the top one) unlabeled. */}
            <ResponsiveContainer width="100%" height={Math.max(280, (makers || []).length * 38)}>
              <BarChart data={(makers || []).map((m: { maker: string; count: number }) => ({ name: m.maker, count: m.count }))} layout="vertical" margin={{ right: 48 }}>
                <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} tickFormatter={formatCompact} />
                <YAxis dataKey="name" type="category" tick={(props) => <TruncatedYAxisTick {...props} fill={chart.axisText} />} width={220} interval={0} />
                <Tooltip
                  formatter={(val: number) => [val.toLocaleString('en-IN'), 'Registrations']}
                  contentStyle={chart.tooltipContentStyle({ fontSize: 12 })} {...chart.tooltipTextStyle}
                />
                <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                  {(makers || []).map((m: { maker: string }, i: number) => (
                    <Cell key={i} fill={chart.seriesColor(m.maker)} />
                  ))}
                  <LabelList dataKey="count" position="right" formatter={(v: number) => v.toLocaleString('en-IN')} style={{ fill: chart.axisText, fontSize: 10, fontFamily: 'JetBrains Mono' }} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
            <div className="mt-3 flex items-center justify-between">
              <span className="text-[10px] text-[var(--text-muted)] font-mono">{(makers || []).length} makers tracked</span>
              <span className="text-[10px] text-[var(--text-muted)] font-mono">
                {(makers || [])[0]?.maker || '—'} leads with {(makers || [])[0]?.count?.toLocaleString('en-IN') || 0}
              </span>
            </div>
          </>
        )}
      </div>

      <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '150ms' }}>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">Fuel Type Distribution</h3>
            <p className="text-[10px] text-[var(--text-muted)] font-mono mt-0.5">powertrain mix for {decoded}</p>
          </div>
          <span className="text-[10px] font-mono px-2 py-1 rounded-md" style={{ color: chart.seriesColors[1], background: 'var(--bg-sunken)' }}>
            {totalFuelCount.toLocaleString('en-IN')} total
          </span>
        </div>
        {fuelLoading ? (
          <LoadingBlock className="h-[280px]" slowMessage="Per-category maker and fuel breakdowns can take several seconds." />
        ) : (fuel || []).length === 0 ? (
          <EmptyState title="No Fuel Breakdown" description={NO_CROSS_TAB_MESSAGE} variant="no-data" className="py-8" />
        ) : (
          <>
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie
                  data={(fuel || []).map((f: { fuel_type: string; count: number }) => ({ name: f.fuel_type, value: f.count }))}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={100}
                  paddingAngle={2}
                  dataKey="value"
                  label={insidePieLabel}
                  labelLine={false}
                >
                  {(fuel || []).map((f: { fuel_type: string }, i: number) => (
                    <Cell key={i} fill={chart.seriesColor(f.fuel_type)} />
                  ))}
                </Pie>
                <Tooltip
                  formatter={(val: number) => [val.toLocaleString('en-IN'), 'Registrations']}
                  contentStyle={chart.tooltipContentStyle({ fontSize: 12 })} {...chart.tooltipTextStyle}
                />
              </PieChart>
            </ResponsiveContainer>
            <div className="flex flex-wrap gap-2 mt-3">
              {(fuel || []).map((f: { fuel_type: string; count: number }, i: number) => {
                const share = totalFuelCount > 0 ? ((f.count / totalFuelCount) * 100).toFixed(1) : '0.0';
                const color = chart.seriesColor(f.fuel_type);
                return (
                  <div key={f.fuel_type} className="flex items-center gap-2 px-3 py-1.5 rounded-xl border transition-all hover:scale-105" style={{ backgroundColor: `${color}18`, borderColor: `${color}40` }}>
                    <span className="w-2 h-2 rounded-sm" style={{ backgroundColor: color }} />
                    <span className="text-[11px] font-semibold" style={{ color }}>{f.fuel_type}</span>
                    <span className="font-mono text-[10px] text-[var(--text-muted)]">{f.count?.toLocaleString('en-IN')}</span>
                    <span className="font-mono text-[10px] text-[var(--text-muted)]">({share}%)</span>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
