import { useQuery } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import { PieChart, Pie, Cell, BarChart, Bar, ResponsiveContainer, XAxis, YAxis, CartesianGrid, Tooltip } from 'recharts';
import { getTopMakers, getFuelBreakdown, getCategories } from '../api/vahan';
import { useAppStore } from '../hooks/useAppStore';
import { ArrowLeft } from '../components/Icons';
import { Link } from 'react-router-dom';

const COLORS = ['#3B82F6', '#06B6D4', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899', '#F97316'];

export function CategoryDetailPage() {
  const { vehicleClass } = useParams<{ vehicleClass: string }>();
  const decoded = decodeURIComponent(vehicleClass || '');
  const { selectedYear } = useAppStore();

  const { data: cats } = useQuery({
    queryKey: ['categories', selectedYear],
    queryFn: () => getCategories(selectedYear),
  });

  const currentCat = (cats || []).find((c: { vehicle_class: string }) => c.vehicle_class === decoded);

  const { data: makers, isLoading: makersLoading } = useQuery({
    queryKey: ['makers', decoded, selectedYear],
    queryFn: () => getTopMakers(decoded, selectedYear),
    enabled: !!decoded,
  });

  const { data: fuel, isLoading: fuelLoading } = useQuery({
    queryKey: ['fuel', decoded, selectedYear],
    queryFn: () => getFuelBreakdown(decoded, selectedYear),
    enabled: !!decoded,
  });

  const totalFuelCount = (fuel || []).reduce((sum: number, f: { count: number }) => sum + f.count, 0);

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="animate-entrance">
        <Link to="/categories" className="inline-flex items-center gap-2 text-[11px] text-slate-500 hover:text-blue-400 font-mono mb-3 transition-colors">
          <ArrowLeft className="w-3.5 h-3.5" />
          Back to Categories
        </Link>
        <div className="flex items-center gap-3">
          <div className="w-1 h-8 rounded-full bg-blue-500" />
          <div>
            <h2 className="text-xl font-bold text-white tracking-tight">{decoded}</h2>
            <p className="text-[10px] text-slate-500 mt-0.5 font-mono uppercase tracking-widest">
              {selectedYear} · {currentCat?.total_count?.toLocaleString('en-IN') || 0} registrations
              {currentCat?.yoy_growth != null && (
                <span className={`ml-2 font-mono font-bold ${(currentCat.yoy_growth as number) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {((currentCat.yoy_growth as number) >= 0 ? '+' : '')}{currentCat.yoy_growth?.toFixed(1)}% YoY
                </span>
              )}
            </p>
          </div>
        </div>
      </div>

      {/* Top Makers Chart */}
      <div className="bg-[#0D1829] rounded-2xl border border-[rgba(255,255,255,0.06)] p-5 animate-entrance" style={{ animationDelay: '100ms' }}>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-sm font-bold text-white tracking-tight">Top Makers</h3>
            <p className="text-[10px] text-slate-500 font-mono mt-0.5">manufacturers leading in {decoded}</p>
          </div>
          <div className="w-2 h-2 rounded-full bg-blue-500 animate-pulse-glow" />
        </div>
        {makersLoading ? (
          <div className="h-[280px] rounded-xl bg-[#111D32] animate-pulse" />
        ) : (
          <>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={(makers || []).map((m: { maker: string; count: number }) => ({ name: m.maker, count: m.count }))} layout="vertical">
                <CartesianGrid strokeDasharray="1 2" stroke="rgba(255,255,255,0.04)" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 10, fill: '#475569', fontFamily: 'JetBrains Mono' }} />
                <YAxis dataKey="name" type="category" tick={{ fontSize: 10, fill: '#64748B', fontFamily: 'JetBrains Mono' }} width={140} />
                <Tooltip
                  formatter={(val: number) => [val.toLocaleString('en-IN'), 'Registrations']}
                  contentStyle={{
                    background: '#0D1829',
                    border: '1px solid rgba(59,130,246,0.3)',
                    borderRadius: 8,
                    fontSize: 12,
                  }}
                />
                <Bar dataKey="count" fill="#3B82F6" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
            {/* Maker stats */}
            <div className="mt-3 flex items-center justify-between">
              <span className="text-[10px] text-slate-600 font-mono">{(makers || []).length} makers tracked</span>
              <span className="text-[10px] text-slate-600 font-mono">
                {(makers || [])[0]?.maker || '—'} leads with {(makers || [])[0]?.count?.toLocaleString('en-IN') || 0}
              </span>
            </div>
          </>
        )}
      </div>

      {/* Fuel Type Distribution */}
      <div className="bg-[#0D1829] rounded-2xl border border-[rgba(255,255,255,0.06)] p-5 animate-entrance" style={{ animationDelay: '150ms' }}>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-sm font-bold text-white tracking-tight">Fuel Type Distribution</h3>
            <p className="text-[10px] text-slate-500 font-mono mt-0.5">powertrain mix for {decoded}</p>
          </div>
          <span className="text-[10px] text-cyan-400 font-mono bg-[rgba(6,182,212,0.1)] px-2 py-1 rounded-md border border-[rgba(6,182,212,0.2)]">
            {totalFuelCount.toLocaleString('en-IN')} total
          </span>
        </div>
        {fuelLoading ? (
          <div className="h-[280px] rounded-xl bg-[#111D32] animate-pulse" />
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
                  {(fuel || []).map((_: unknown, i: number) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  formatter={(val: number) => [val.toLocaleString('en-IN'), 'Registrations']}
                  contentStyle={{
                    background: '#0D1829',
                    border: '1px solid rgba(6,182,212,0.3)',
                    borderRadius: 8,
                    fontSize: 12,
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
            <div className="flex flex-wrap gap-2 mt-3">
              {(fuel || []).map((f: { fuel_type: string; count: number }, i: number) => {
                const share = totalFuelCount > 0 ? ((f.count / totalFuelCount) * 100).toFixed(1) : '0.0';
                return (
                  <div
                    key={i}
                    className="flex items-center gap-2 px-3 py-1.5 rounded-xl border transition-all hover:scale-105"
                    style={{
                      backgroundColor: `${COLORS[i % COLORS.length]}15`,
                      borderColor: `${COLORS[i % COLORS.length]}30`,
                    }}
                  >
                    <span className="w-2 h-2 rounded-sm" style={{ backgroundColor: COLORS[i % COLORS.length] }} />
                    <span className="text-[11px] font-semibold" style={{ color: COLORS[i % COLORS.length] }}>{f.fuel_type}</span>
                    <span className="font-mono text-[10px] text-slate-400">{f.count?.toLocaleString('en-IN')}</span>
                    <span className="font-mono text-[10px] text-slate-600">({share}%)</span>
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