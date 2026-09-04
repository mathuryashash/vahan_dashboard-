// frontend/src/pages/MakersModels.tsx
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import { getTopMakers, getCategories, getMakerCategoryBreakdown, getAvailableYears } from '../api/vahan';
import { useChartTheme } from '../hooks/useChartTheme';
import { TruncatedYAxisTick } from '../components/ChartAxisTick';
import { ExportCsvButton } from '../components/ExportCsvButton';
import { EmptyState } from '../components/EmptyState';

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const CURRENT_YEAR = new Date().getFullYear();

export function MakersModelsPage() {
  const chart = useChartTheme();
  // Deliberately its own year/month, not useAppStore's shared selectedYear --
  // this page's filters shouldn't move the Overview page's filters and vice
  // versa.
  const [year, setYear] = useState<number>(CURRENT_YEAR);
  const [month, setMonth] = useState<number | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);

  const { data: availableYears } = useQuery({ queryKey: ['availableYears'], queryFn: getAvailableYears });
  const { data: categories } = useQuery({
    queryKey: ['categories', year, month],
    queryFn: () => getCategories({ year, month }),
  });

  // When a category is selected, this ranks real makers within it -- the
  // Maker x Vehicle Category cross-tab (year-only, no month breakdown, see
  // docs/superpowers/specs/2026-08-25-maker-category-crosstab-design.md) --
  // instead of the all-category leaderboard. The crosstab has no month
  // column, so `month` only applies to the un-categorized leaderboard.
  const { data: makers, isLoading: makersLoading } = useQuery({
    queryKey: ['makers-full', year, month, selectedCategory],
    queryFn: ({ signal }) => selectedCategory
      ? getMakerCategoryBreakdown({ year, vehicle_category: selectedCategory, limit: 20 }, signal)
      : getTopMakers({ year, month, limit: 20 }, signal),
  });

  const makerChartData = (makers || []).map((m: { maker: string; count: number }) => ({ name: m.maker, count: m.count }));
  const selectClass = "bg-[var(--bg-sunken)] border border-[var(--border)] text-xs font-semibold px-3 py-2 rounded-xl cursor-pointer";

  return (
    <div className="p-6 space-y-6">
      <div className="animate-entrance">
        <h2 className="text-xl font-bold text-[var(--text-primary)] tracking-tight">Makers</h2>
        <p className="text-[10px] text-[var(--text-muted)] mt-0.5 font-mono uppercase tracking-widest">
          Manufacturer leaderboard — FY {year}
        </p>
      </div>

      <div className="flex items-center gap-3 flex-wrap animate-entrance" style={{ animationDelay: '40ms' }}>
        <select value={year} onChange={(e) => setYear(Number(e.target.value))} className={selectClass}>
          {(availableYears || [year]).map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
        <select
          value={month || ''}
          onChange={(e) => setMonth(e.target.value ? Number(e.target.value) : null)}
          disabled={!!selectedCategory}
          title={selectedCategory ? "Category ranking is a year total -- month doesn't apply" : undefined}
          className={`${selectClass} disabled:opacity-40 disabled:cursor-not-allowed`}
        >
          <option value="">All Months</option>
          {MONTH_NAMES.map((name, idx) => (
            <option key={name} value={idx + 1}>{name}</option>
          ))}
        </select>
        <select
          value={selectedCategory || ''}
          onChange={(e) => {
            const value = e.target.value || null;
            setSelectedCategory(value);
            // The month control goes disabled the moment a category is
            // picked (the crosstab it switches to is year-only) -- clearing
            // it too means a disabled "Feb" left over from before doesn't
            // sit there implying it's still in effect.
            if (value) setMonth(null);
          }}
          className={selectClass}
        >
          <option value="">All Categories</option>
          {(categories || []).map((c: { vehicle_category: string }) => (
            <option key={c.vehicle_category} value={c.vehicle_category}>{c.vehicle_category}</option>
          ))}
        </select>
      </div>
      {selectedCategory && (
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl px-4 py-2.5 text-xs text-[var(--text-secondary)] animate-entrance">
          Ranked by <span className="font-semibold text-[var(--accent)]">{selectedCategory}</span> registrations for FY {year} — a year total, no month breakdown available for this view.
        </div>
      )}

      <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '80ms' }}>
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">
            {selectedCategory ? `Top Manufacturers — ${selectedCategory}` : 'Top Manufacturers'}
          </h3>
          <ExportCsvButton filename={`top-makers-fy${year}${selectedCategory ? `-${selectedCategory}` : ''}`} rows={makers} />
        </div>
        {makersLoading ? (
          <div className="h-[420px] rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft" />
        ) : makerChartData.length === 0 ? (
          <EmptyState
            variant="no-data"
            title={`No maker data for FY ${year}${selectedCategory ? ` / ${selectedCategory}` : ''}`}
            description={selectedCategory
              ? `The Maker × Category breakdown has only ever been scraped for the current year -- try clearing the category filter, or switch to FY ${new Date().getFullYear()}.`
              : `Try a different year.`}
          />
        ) : (
          <ResponsiveContainer width="100%" height={Math.max(280, makerChartData.length * 30)}>
            <BarChart data={makerChartData} layout="vertical">
              <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} horizontal={false} />
              <XAxis type="number" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} />
              <YAxis dataKey="name" type="category" tick={(props) => <TruncatedYAxisTick {...props} fill={chart.axisText} />} width={220} />
              <Tooltip
                formatter={(val: number) => [val.toLocaleString('en-IN'), 'Registrations']}
                contentStyle={chart.tooltipContentStyle({ fontSize: 12 })} {...chart.tooltipTextStyle}
              />
              <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                {makerChartData.map((d: { name: string }, i: number) => (
                  <Cell key={i} fill={chart.seriesColor(d.name)} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
