// frontend/src/pages/CategoryDetail.tsx
import { useQuery } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import { PieChart, Pie, Cell, BarChart, Bar, ResponsiveContainer, XAxis, YAxis, CartesianGrid, Tooltip } from 'recharts';
import { getTopMakers, getFuelBreakdown, getCategories } from '../api/vahan';
import { useAppStore } from '../hooks/useAppStore';
import { ArrowLeft } from '../components/Icons';
import { Link } from 'react-router-dom';
import { useChartTheme } from '../hooks/useChartTheme';

export function CategoryDetailPage() {
  const { vehicleClass } = useParams<{ vehicleClass: string }>();
  const decoded = decodeURIComponent(vehicleClass || '');
  const { selectedYear } = useAppStore();
  const chart = useChartTheme();

  const { data: cats } = useQuery({
    queryKey: ['categories', selectedYear],
    queryFn: () => getCategories({ year: selectedYear }),
  });

  const currentCat = (cats || []).find((c: { vehicle_class: string }) => c.vehicle_class === decoded);

  const { data: makers, isLoading: makersLoading } = useQuery({
    queryKey: ['makers', decoded, selectedYear],
    queryFn: () => getTopMakers({ vehicle_class: decoded, year: selectedYear }),
    enabled: !!decoded,
  });

  const { data: fuel, isLoading: fuelLoading } = useQuery({
    queryKey: ['fuel', decoded, selectedYear],
    queryFn: () => getFuelBreakdown({ vehicle_class: decoded, year: selectedYear }),
    enabled: !!decoded,
  });

  const totalFuelCount = (fuel || []).reduce((sum: number, f: { count: number }) => sum + f.count, 0);

  return (
    <div className="p-6 space-y-6">
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
              {selectedYear} · {currentCat?.total_count?.toLocaleString('en-IN') || 0} registrations
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
          <div className="h-[280px] rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft" />
        ) : (
          <>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={(makers || []).map((m: { maker: string; count: number }) => ({ name: m.maker, count: m.count }))} layout="vertical">
                <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} />
                <YAxis dataKey="name" type="category" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} width={140} />
                <Tooltip
                  formatter={(val: number) => [val.toLocaleString('en-IN'), 'Registrations']}
                  contentStyle={{ background: chart.tooltipBg, border: `1px solid ${chart.tooltipBorder}`, borderRadius: 8, fontSize: 12 }}
                />
                <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                  {(makers || []).map((m: { maker: string }, i: number) => (
                    <Cell key={i} fill={chart.seriesColor(m.maker)} />
                  ))}
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
          <div className="h-[280px] rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft" />
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
                >
                  {(fuel || []).map((f: { fuel_type: string }, i: number) => (
                    <Cell key={i} fill={chart.seriesColor(f.fuel_type)} />
                  ))}
                </Pie>
                <Tooltip
                  formatter={(val: number) => [val.toLocaleString('en-IN'), 'Registrations']}
                  contentStyle={{ background: chart.tooltipBg, border: `1px solid ${chart.tooltipBorder}`, borderRadius: 8, fontSize: 12 }}
                />
              </PieChart>
            </ResponsiveContainer>
            <div className="flex flex-wrap gap-2 mt-3">
              {(fuel || []).map((f: { fuel_type: string; count: number }, i: number) => {
                const share = totalFuelCount > 0 ? ((f.count / totalFuelCount) * 100).toFixed(1) : '0.0';
                const color = chart.seriesColor(f.fuel_type);
                return (
                  <div key={i} className="flex items-center gap-2 px-3 py-1.5 rounded-xl border transition-all hover:scale-105" style={{ backgroundColor: `${color}18`, borderColor: `${color}40` }}>
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
