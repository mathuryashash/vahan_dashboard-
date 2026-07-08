// frontend/src/pages/MakersModels.tsx
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import { getTopMakers, getModelBreakdown } from '../api/vahan';
import { useAppStore } from '../hooks/useAppStore';
import { useChartTheme } from '../hooks/useChartTheme';

export function MakersModelsPage() {
  const chart = useChartTheme();
  const { selectedYear } = useAppStore();
  const [selectedMaker, setSelectedMaker] = useState<string | null>(null);

  const { data: makers, isLoading: makersLoading } = useQuery({
    queryKey: ['makers-full', selectedYear],
    queryFn: () => getTopMakers({ year: selectedYear, limit: 20 }),
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

      <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '80ms' }}>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">Top Manufacturers</h3>
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
              <YAxis dataKey="name" type="category" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} width={190} />
              <Tooltip
                formatter={(val: number) => [val.toLocaleString('en-IN'), 'Registrations']}
                contentStyle={{ background: chart.tooltipBg, border: `1px solid ${chart.tooltipBorder}`, borderRadius: 8, fontSize: 12 }}
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
              <YAxis dataKey="name" type="category" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} width={150} />
              <Tooltip
                formatter={(val: number) => [val.toLocaleString('en-IN'), 'Registrations']}
                contentStyle={{ background: chart.tooltipBg, border: `1px solid ${chart.tooltipBorder}`, borderRadius: 8, fontSize: 12 }}
              />
              <Bar dataKey="count" fill={chart.seriesColor(selectedMaker)} radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
