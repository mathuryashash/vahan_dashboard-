// frontend/src/pages/MakersModels.tsx
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import { getTopMakers, getModelBreakdown, getCategories, getMakerCategoryBreakdown } from '../api/vahan';
import { useAppStore } from '../hooks/useAppStore';
import { useChartTheme } from '../hooks/useChartTheme';
import { TruncatedYAxisTick } from '../components/ChartAxisTick';

export function MakersModelsPage() {
  const chart = useChartTheme();
  const { selectedYear } = useAppStore();
  const [selectedMaker, setSelectedMaker] = useState<string | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);

  const { data: categories } = useQuery({
    queryKey: ['categories', selectedYear],
    queryFn: () => getCategories({ year: selectedYear }),
  });

  // When a category is selected, this ranks real makers within it -- the
  // Maker x Vehicle Category cross-tab (year-only, no month breakdown, see
  // docs/superpowers/specs/2026-08-25-maker-category-crosstab-design.md) --
  // instead of the all-category leaderboard.
  const { data: makers, isLoading: makersLoading } = useQuery({
    queryKey: ['makers-full', selectedYear, selectedCategory],
    // Switching the Category filter changes queryKey, so this and the
    // previous key's request can both be briefly in flight -- forwarding
    // React Query's abort signal to axios lets it actually cancel the
    // abandoned one instead of leaving it to resolve on its own time and
    // race the current selection (found by live click-through QA: the
    // unfiltered top-makers call is slow enough that a quick category
    // click could still see it land after the filtered one).
    queryFn: ({ signal }) => selectedCategory
      ? getMakerCategoryBreakdown({ year: selectedYear, vehicle_category: selectedCategory, limit: 20 }, signal)
      : getTopMakers({ year: selectedYear, limit: 20 }, signal),
  });

  const { data: models, isLoading: modelsLoading } = useQuery({
    queryKey: ['models-full', selectedMaker, selectedYear],
    queryFn: () => getModelBreakdown({ maker: selectedMaker, year: selectedYear, limit: 20 }),
    enabled: !!selectedMaker,
  });

  const makerChartData = (makers || []).map((m: { maker: string; count: number }) => ({ name: m.maker, count: m.count }));
  const modelChartData = (models || []).map((m: { model: string; count: number }) => ({ name: m.model, count: m.count }));

  return (
    <div className="p-6 space-y-6">
      <div className="animate-entrance">
        <h2 className="text-xl font-bold text-[var(--text-primary)] tracking-tight">Makers & Models</h2>
        <p className="text-[10px] text-[var(--text-muted)] mt-0.5 font-mono uppercase tracking-widest">
          Manufacturer and model leaderboard — FY {selectedYear}
        </p>
      </div>

      <div className="flex items-center gap-3 animate-entrance" style={{ animationDelay: '40ms' }}>
        <select
          value={selectedCategory || ''}
          onChange={(e) => setSelectedCategory(e.target.value || null)}
          className="bg-[var(--bg-sunken)] border border-[var(--border)] text-xs font-semibold px-3 py-2 rounded-xl"
        >
          <option value="">All Categories</option>
          {(categories || []).map((c: { vehicle_category: string }) => (
            <option key={c.vehicle_category} value={c.vehicle_category}>{c.vehicle_category}</option>
          ))}
        </select>
      </div>
      {selectedCategory && (
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl px-4 py-2.5 text-xs text-[var(--text-secondary)] animate-entrance">
          Ranked by <span className="font-semibold text-[var(--accent)]">{selectedCategory}</span> registrations for FY {selectedYear} — a year total, no month breakdown available for this view.
        </div>
      )}

      <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '80ms' }}>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">
              {selectedCategory ? `Top Manufacturers — ${selectedCategory}` : 'Top Manufacturers'}
            </h3>
            <p className="text-[10px] text-[var(--text-muted)] font-mono mt-0.5">click a maker to see its model breakdown below</p>
          </div>
          {selectedMaker && (
            <button onClick={() => setSelectedMaker(null)} className="text-[9px] uppercase font-mono tracking-wider text-[var(--accent)] hover:opacity-80 transition-opacity">
              Clear Selection
            </button>
          )}
        </div>
        {makersLoading ? (
          <div className="h-[420px] rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft" />
        ) : (
          <ResponsiveContainer width="100%" height={Math.max(280, makerChartData.length * 22)}>
            <BarChart data={makerChartData} layout="vertical">
              <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} horizontal={false} />
              <XAxis type="number" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} />
              <YAxis dataKey="name" type="category" tick={(props) => <TruncatedYAxisTick {...props} fill={chart.axisText} />} width={210} />
              <Tooltip
                formatter={(val: number) => [val.toLocaleString('en-IN'), 'Registrations']}
                contentStyle={chart.tooltipContentStyle({ fontSize: 12 })} {...chart.tooltipTextStyle}
              />
              <Bar
                dataKey="count"
                radius={[0, 4, 4, 0]}
                onClick={(data: { name?: string }) => data?.name && setSelectedMaker(data.name)}
                cursor="pointer"
              >
                {makerChartData.map((d: { name: string }, i: number) => (
                  <Cell
                    key={i}
                    fill={chart.seriesColor(d.name)}
                    fillOpacity={selectedMaker && selectedMaker !== d.name ? 0.35 : 1}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '140ms' }}>
        <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight mb-1">Model Breakdown</h3>
        <p className="text-[10px] text-[var(--text-muted)] font-mono mb-4">
          {selectedMaker ? `Models from ${selectedMaker}` : 'Select a manufacturer above to see its individual models'}
        </p>
        {!selectedMaker ? (
          <div className="h-44 flex flex-col items-center justify-center text-[var(--text-muted)] text-xs border border-dashed border-[var(--border)] rounded-xl">
            <span>No manufacturer selected</span>
            <span className="text-[10px] mt-1">Click a bar above to drill into its models</span>
          </div>
        ) : modelsLoading ? (
          <div className="h-[300px] rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft" />
        ) : modelChartData.length === 0 ? (
          <div className="h-44 flex flex-col items-center justify-center text-[var(--text-muted)] text-xs border border-dashed border-[var(--border)] rounded-xl">
            <span>No model-level data for {selectedMaker}</span>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={Math.max(220, modelChartData.length * 24)}>
            <BarChart data={modelChartData} layout="vertical">
              <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} horizontal={false} />
              <XAxis type="number" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} />
              <YAxis dataKey="name" type="category" tick={(props) => <TruncatedYAxisTick {...props} fill={chart.axisText} />} width={170} />
              <Tooltip
                formatter={(val: number) => [val.toLocaleString('en-IN'), 'Registrations']}
                contentStyle={chart.tooltipContentStyle({ fontSize: 12 })} {...chart.tooltipTextStyle}
              />
              <Bar dataKey="count" fill={chart.seriesColor(selectedMaker)} radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
