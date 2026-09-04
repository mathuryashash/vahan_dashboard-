// frontend/src/pages/Categories.tsx
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  PieChart, Pie, Cell, BarChart, Bar, ResponsiveContainer, XAxis, YAxis, CartesianGrid, Tooltip
} from 'recharts';
import { useNavigate } from 'react-router-dom';
import { getCategories, getTopMakers, getFuelBreakdown } from '../api/vahan';
import { useAppStore } from '../hooks/useAppStore';
import { useChartTheme } from '../hooks/useChartTheme';
import { capForDonut, distinctSeriesColors } from '../theme/tokens';
import { TruncatedYAxisTick } from '../components/ChartAxisTick';
import { useSettledLayout } from '../hooks/useSettledLayout';
import { ExportCsvButton } from '../components/ExportCsvButton';

export function CategoriesPage() {
  const navigate = useNavigate();
  const chart = useChartTheme();
  const { selectedYear } = useAppStore();

  const { data: categories, isLoading } = useQuery({
    queryKey: ['categories', selectedYear],
    queryFn: () => getCategories({ year: selectedYear }),
  });

  const pieData = capForDonut((categories || []).map((c: { vehicle_category: string; total_count: number }) => ({
    name: c.vehicle_category,
    value: c.total_count,
  })));
  const pieColors = distinctSeriesColors(chart, pieData.map((p) => p.name));
  const shareReady = useSettledLayout(isLoading);

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between animate-entrance">
        <div>
          <h2 className="text-xl font-bold text-[var(--text-primary)] tracking-tight">Categories & Fuel</h2>
          <p className="text-[10px] text-[var(--text-muted)] mt-0.5 font-mono uppercase tracking-widest">
            Vehicle category and powertrain breakdown — FY {selectedYear}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div className="xl:col-span-1 bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '100ms' }}>
          <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight mb-4">Category Share</h3>
          {isLoading || !shareReady ? (
            <div className="h-[300px] rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft" />
          ) : (
            <>
              <ResponsiveContainer width="100%" height={240}>
                <PieChart>
                  <Pie
                    data={pieData}
                    cx="50%"
                    cy="50%"
                    innerRadius={70}
                    outerRadius={110}
                    paddingAngle={1}
                    dataKey="value"
                  >
                    {pieData.map((p: { name: string }, i: number) => (
                      <Cell key={i} fill={pieColors.get(p.name)} />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(val: number) => [val.toLocaleString('en-IN'), 'Registrations']}
                    contentStyle={chart.tooltipContentStyle({ fontSize: 12 })} {...chart.tooltipTextStyle}
                  />
                </PieChart>
              </ResponsiveContainer>
              <div className="mt-3 space-y-1.5 max-h-44 overflow-y-auto pr-1">
                {pieData.map((p: { name: string; value: number }, i: number) => (
                  <div key={i} className="flex items-center justify-between text-[11px]">
                    <div className="flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-sm" style={{ backgroundColor: pieColors.get(p.name) }} />
                      <span className="text-[var(--text-secondary)] truncate max-w-[110px]">{p.name}</span>
                    </div>
                    <span className="font-mono text-[var(--text-secondary)] font-semibold">{p.value?.toLocaleString('en-IN')}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        <div className="xl:col-span-2 bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '150ms' }}>
          <div className="mb-4">
            <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">Category Breakdown</h3>
            <p className="text-[10px] text-[var(--text-muted)] font-mono mt-0.5">Click any category to explore makers & fuel</p>
          </div>
          <div className="space-y-3">
            {(categories || []).map((c: { vehicle_category: string; total_count: number; share_percent: number; yoy_growth: number }, i: number) => (
              <div
                key={i}
                onClick={() => navigate(`/categories/${encodeURIComponent(c.vehicle_category)}`)}
                className="flex items-center gap-4 p-3 rounded-xl cursor-pointer transition-all duration-200 border border-transparent hover:border-[var(--border-strong)] hover:bg-[var(--bg-card-hover)] group"
              >
                <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ backgroundColor: chart.seriesColor(c.vehicle_category) }} />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-semibold text-[var(--text-secondary)] group-hover:text-[var(--text-primary)] transition-colors truncate">{c.vehicle_category}</div>
                  <div className="w-full bg-[var(--bg-sunken)] rounded-full h-1.5 mt-1.5">
                    <div className="h-1.5 rounded-full transition-all duration-500" style={{ width: `${c.share_percent}%`, backgroundColor: chart.seriesColor(c.vehicle_category) }} />
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="font-mono text-sm font-bold text-[var(--text-primary)]">{c.total_count?.toLocaleString('en-IN')}</div>
                  <div className="flex items-center gap-2 justify-end mt-0.5">
                    <span className="text-[10px] font-mono font-bold" style={{ color: c.yoy_growth >= 0 ? chart.success : chart.danger }}>
                      {c.yoy_growth >= 0 ? '+' : ''}{c.yoy_growth?.toFixed(1)}%
                    </span>
                    <span className="text-[10px] text-[var(--text-muted)] font-mono">{c.share_percent?.toFixed(1)}%</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <CategoryChart title="Top Makers — All Categories" queryKey="makers" fn={() => getTopMakers({ year: selectedYear })} year={selectedYear} chart={chart} index={0} />
        <FuelBreakdownChart title="Fuel Type Breakdown — All Categories" year={selectedYear} chart={chart} index={1} />
      </div>
    </div>
  );
}

function FuelBreakdownChart({ title, year, chart, index }: { title: string; year: number; chart: ReturnType<typeof useChartTheme>; index: number }) {
  const [fuelGroup, setFuelGroup] = useState<string | null>(null);
  const { data, isLoading } = useQuery({
    queryKey: ['fuel', year, fuelGroup],
    queryFn: () => getFuelBreakdown({ year, fuel_group: fuelGroup }),
  });

  const chartData = ((data as { fuel_type?: string; count: number }[]) || []).map((d) => ({
    name: d.fuel_type || '',
    count: d.count,
  }));

  return (
    <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: `${250 + index * 80}ms` }}>
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">{title}</h3>
        <div className="flex rounded-lg border border-[var(--border)] overflow-hidden">
          {(['ICE', 'Hybrid', 'EV'] as const).map((group) => (
            <button
              key={group}
              onClick={() => setFuelGroup(fuelGroup === group ? null : group)}
              className={`px-2.5 py-1 text-[10px] font-semibold transition-colors ${
                fuelGroup === group
                  ? 'bg-[var(--accent)] text-[var(--accent-contrast)]'
                  : 'bg-[var(--bg-sunken)] text-[var(--text-secondary)] hover:bg-[var(--bg-card-hover)]'
              }`}
            >
              {group}
            </button>
          ))}
        </div>
      </div>
      {isLoading ? (
        <div className="h-[220px] rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft" />
      ) : (
        <ResponsiveContainer width="100%" height={Math.max(220, chartData.length * 30)}>
          <BarChart data={chartData} layout="vertical">
            <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} horizontal={false} />
            <XAxis type="number" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} />
            <YAxis dataKey="name" type="category" tick={(props) => <TruncatedYAxisTick {...props} fill={chart.axisText} />} width={190} />
            <Tooltip
              formatter={(val: number) => [val.toLocaleString('en-IN'), 'Count']}
              contentStyle={chart.tooltipContentStyle({ fontSize: 12 })} {...chart.tooltipTextStyle}
            />
            <Bar dataKey="count" radius={[0, 4, 4, 0]}>
              {chartData.map((d: { name: string }, i: number) => (
                <Cell key={i} fill={chart.seriesColor(d.name)} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

function CategoryChart({ title, queryKey, fn, year, chart, index }: { title: string; queryKey: string; fn: () => Promise<unknown>; year: number; chart: ReturnType<typeof useChartTheme>; index: number }) {
  const { data, isLoading } = useQuery({ queryKey: [queryKey, year], queryFn: fn });

  const chartData = ((data as { maker?: string; fuel_type?: string; count: number }[]) || []).map((d) => ({
    name: d.maker || d.fuel_type || '',
    count: d.count,
  }));

  return (
    <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: `${250 + index * 80}ms` }}>
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">{title}</h3>
        <ExportCsvButton filename={`${title.toLowerCase().replace(/\s+/g, '-')}-fy${year}`} rows={data as Record<string, unknown>[] | undefined} />
      </div>
      {isLoading ? (
        <div className="h-[220px] rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft" />
      ) : (
        <ResponsiveContainer width="100%" height={Math.max(220, chartData.length * 30)}>
          <BarChart data={chartData} layout="vertical">
            <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} horizontal={false} />
            <XAxis type="number" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} />
            <YAxis dataKey="name" type="category" tick={(props) => <TruncatedYAxisTick {...props} fill={chart.axisText} />} width={190} />
            <Tooltip
              formatter={(val: number) => [val.toLocaleString('en-IN'), 'Count']}
              contentStyle={chart.tooltipContentStyle({ fontSize: 12 })} {...chart.tooltipTextStyle}
            />
            <Bar dataKey="count" radius={[0, 4, 4, 0]}>
              {chartData.map((d: { name: string }, i: number) => (
                <Cell key={i} fill={chart.seriesColor(d.name)} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
