// frontend/src/pages/IndustrySales.tsx
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { getOemCategories, getOemMonthly, getOemTrend } from '../api/vahan';
import { useChartTheme } from '../hooks/useChartTheme';
import { useAppStore } from '../hooks/useAppStore';
import { TruncatedYAxisTick } from '../components/ChartAxisTick';

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export function IndustrySalesPage() {
  const chart = useChartTheme();
  const { selectedYear } = useAppStore();
  // FADA data has no reason to share Overview's month filter -- a month
  // picked there would silently make this page's leaderboard query a
  // single (likely empty) month instead of the intended year-to-date view.
  // Always a year-to-date leaderboard here, independent of that filter.
  const selectedMonth = null;
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [selectedMaker, setSelectedMaker] = useState<string | null>(null);

  const { data: categories } = useQuery({ queryKey: ['oemCategories'], queryFn: getOemCategories });
  const category = selectedCategory ?? categories?.[0] ?? null;

  const { data: monthly, isLoading: monthlyLoading } = useQuery({
    queryKey: ['oemMonthly', category, selectedYear, selectedMonth],
    queryFn: () => getOemMonthly({ category: category!, year: selectedYear, month: selectedMonth }),
    enabled: !!category,
  });

  const { data: trend } = useQuery({
    queryKey: ['oemTrend', selectedMaker, category],
    queryFn: () => getOemTrend({ maker: selectedMaker!, category: category! }),
    enabled: !!selectedMaker && !!category,
  });

  const barData = (monthly || []).map((m: { maker: string; count: number }) => ({ name: m.maker, count: m.count }));
  const trendData = (trend || []).map((t: { year: number; month: number | null; count: number }) => ({
    name: t.month ? `${MONTH_NAMES[t.month - 1]} ${t.year}` : `FY${t.year}`,
    count: t.count,
  }));

  return (
    <div className="p-6 space-y-6">
      <div className="animate-entrance">
        <h2 className="text-xl font-bold text-[var(--text-primary)] tracking-tight">Industry Sales</h2>
        <p className="text-[10px] text-[var(--text-muted)] mt-0.5 font-mono uppercase tracking-widest">
          Maker-wise vehicle retail data — sourced from FADA, real registrations
        </p>
      </div>

      <div className="flex flex-col gap-1.5 max-w-xs">
        <label className="text-[10px] uppercase font-mono tracking-widest text-[var(--text-muted)] font-bold">Category</label>
        <select
          value={category || ''}
          onChange={(e) => { setSelectedCategory(e.target.value); setSelectedMaker(null); }}
          className="w-full bg-[var(--bg-sunken)] border border-[var(--border)] text-[var(--text-primary)] text-xs font-semibold px-3 py-2 rounded-xl focus:outline-none focus:ring-2 focus:ring-[var(--accent)]"
        >
          {(categories || []).map((c: string) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>

      <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance">
        <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight mb-4">Maker Leaderboard</h3>
        {monthlyLoading ? (
          <div className="h-[400px] rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft" />
        ) : (
          <ResponsiveContainer width="100%" height={Math.max(280, barData.length * 26)}>
            <BarChart data={barData} layout="vertical">
              <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} horizontal={false} />
              <XAxis type="number" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} />
              <YAxis dataKey="name" type="category" tick={(props) => <TruncatedYAxisTick {...props} fill={chart.axisText} />} width={210} />
              <Tooltip
                formatter={(val: number) => [val.toLocaleString('en-IN'), 'Registrations']}
                contentStyle={chart.tooltipContentStyle({ fontSize: 12 })}
              />
              <Bar
                dataKey="count"
                fill={chart.seriesColors[0]}
                radius={[0, 4, 4, 0]}
                onClick={(data: { name?: string }) => data?.name && setSelectedMaker(data.name)}
                cursor="pointer"
              />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      {selectedMaker && (
        <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance">
          <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight mb-4">{selectedMaker} — Trend</h3>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={trendData}>
              <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} vertical={false} />
              <XAxis dataKey="name" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} />
              <Tooltip formatter={(val: number) => val.toLocaleString('en-IN')} contentStyle={chart.tooltipContentStyle()} />
              <Line type="monotone" dataKey="count" stroke={chart.seriesColors[0]} strokeWidth={2.5} dot={{ r: 3, fill: chart.seriesColors[0] }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
