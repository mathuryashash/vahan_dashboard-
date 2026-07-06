import { useQuery } from '@tanstack/react-query';
import {
  PieChart, Pie, Cell, BarChart, Bar, ResponsiveContainer, XAxis, YAxis, CartesianGrid, Tooltip
} from 'recharts';
import { useNavigate } from 'react-router-dom';
import { getCategories, getTopMakers, getFuelBreakdown } from '../api/vahan';
import { useAppStore } from '../hooks/useAppStore';

const COLORS = ['#3B82F6', '#06B6D4', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899', '#F97316', '#14B8A6', '#A855F7', '#EAB308', '#84CC16'];

export function CategoriesPage() {
  const navigate = useNavigate();
  const { selectedYear } = useAppStore();

  const { data: categories, isLoading } = useQuery({
    queryKey: ['categories', selectedYear],
    queryFn: () => getCategories(selectedYear),
  });

  const pieData = (categories || []).map((c: { vehicle_class: string; total_count: number }) => ({
    name: c.vehicle_class,
    value: c.total_count,
  }));

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between animate-entrance">
        <div>
          <h2 className="text-xl font-bold text-white tracking-tight">Vehicle Categories</h2>
          <p className="text-[10px] text-slate-500 mt-0.5 font-mono uppercase tracking-widest">
            Category breakdown — FY {selectedYear}
          </p>
        </div>
        <div className="flex items-center gap-2 text-[10px] text-slate-500 font-mono">
          <div className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse-glow" />
          LIVE DATA
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        {/* Pie Chart */}
        <div className="xl:col-span-1 bg-[#0D1829] rounded-2xl border border-[rgba(255,255,255,0.06)] p-5 animate-entrance" style={{ animationDelay: '100ms' }}>
          <h3 className="text-sm font-bold text-white tracking-tight mb-4">Category Share</h3>
          {isLoading ? (
            <div className="h-[300px] rounded-xl bg-[#111D32] animate-pulse" />
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
                    {pieData.map((_: unknown, i: number) => (
                      <Cell key={i} fill={COLORS[i % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(val: number) => [val.toLocaleString('en-IN'), 'Registrations']}
                    contentStyle={{
                      background: '#0D1829',
                      border: '1px solid rgba(59,130,246,0.3)',
                      borderRadius: 8,
                      fontSize: 12,
                    }}
                  />
                </PieChart>
              </ResponsiveContainer>
              <div className="mt-3 space-y-1.5 max-h-44 overflow-y-auto pr-1">
                {pieData.map((p: { name: string; value: number }, i: number) => (
                  <div key={i} className="flex items-center justify-between text-[11px]">
                    <div className="flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-sm" style={{ backgroundColor: COLORS[i % COLORS.length] }} />
                      <span className="text-slate-400 truncate max-w-[110px]">{p.name}</span>
                    </div>
                    <span className="font-mono text-slate-300 font-semibold">{p.value?.toLocaleString('en-IN')}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        {/* Category Breakdown List */}
        <div className="xl:col-span-2 bg-[#0D1829] rounded-2xl border border-[rgba(255,255,255,0.06)] p-5 animate-entrance" style={{ animationDelay: '150ms' }}>
          <div className="mb-4">
            <h3 className="text-sm font-bold text-white tracking-tight">Category Breakdown</h3>
            <p className="text-[10px] text-slate-500 font-mono mt-0.5">Click any category to explore makers & fuel</p>
          </div>
          <div className="space-y-3">
            {(categories || []).map((c: { vehicle_class: string; total_count: number; share_percent: number; yoy_growth: number }, i: number) => (
              <div
                key={i}
                onClick={() => navigate(`/categories/${encodeURIComponent(c.vehicle_class)}`)}
                className="flex items-center gap-4 p-3 rounded-xl cursor-pointer transition-all duration-200 border border-transparent hover:border-[rgba(59,130,246,0.2)] hover:bg-[rgba(59,130,246,0.04)] group"
              >
                <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ backgroundColor: COLORS[i % COLORS.length] }} />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-semibold text-slate-300 group-hover:text-white transition-colors truncate">{c.vehicle_class}</div>
                  <div className="w-full bg-[#111D32] rounded-full h-1.5 mt-1.5">
                    <div
                      className="h-1.5 rounded-full transition-all duration-500"
                      style={{ width: `${c.share_percent}%`, backgroundColor: COLORS[i % COLORS.length] }}
                    />
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="font-mono text-sm font-bold text-white">{c.total_count?.toLocaleString('en-IN')}</div>
                  <div className="flex items-center gap-2 justify-end mt-0.5">
                    <span className={`text-[10px] font-mono font-bold ${c.yoy_growth >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {c.yoy_growth >= 0 ? '+' : ''}{c.yoy_growth?.toFixed(1)}%
                    </span>
                    <span className="text-[10px] text-slate-600 font-mono">{c.share_percent?.toFixed(1)}%</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <CategoryChart title="Top Makers — All Categories" queryKey="makers" fn={() => getTopMakers(undefined, selectedYear)} year={selectedYear} accent="#3B82F6" index={0} />
        <CategoryChart title="Fuel Type Breakdown — All Categories" queryKey="fuel" fn={() => getFuelBreakdown(undefined, selectedYear)} year={selectedYear} accent="#06B6D4" index={1} />
      </div>
    </div>
  );
}

function CategoryChart({ title, queryKey, fn, year, accent, index }: { title: string; queryKey: string; fn: () => Promise<unknown>; year: number; accent: string; index: number }) {
  const { data, isLoading } = useQuery({ queryKey: [queryKey, year], queryFn: fn });

  const chartData = (data || []).map((d: { maker?: string; fuel_type?: string; count: number }) => ({
    name: d.maker || d.fuel_type || '',
    count: d.count,
  }));

  return (
    <div className="bg-[#0D1829] rounded-2xl border border-[rgba(255,255,255,0.06)] p-5 animate-entrance" style={{ animationDelay: `${250 + index * 80}ms` }}>
      <h3 className="text-sm font-bold text-white tracking-tight mb-4">{title}</h3>
      {isLoading ? (
        <div className="h-[220px] rounded-xl bg-[#111D32] animate-pulse" />
      ) : (
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={chartData} layout="vertical">
            <CartesianGrid strokeDasharray="1 2" stroke="rgba(255,255,255,0.04)" horizontal={false} />
            <XAxis type="number" tick={{ fontSize: 10, fill: '#475569', fontFamily: 'JetBrains Mono' }} />
            <YAxis dataKey="name" type="category" tick={{ fontSize: 10, fill: '#64748B', fontFamily: 'JetBrains Mono' }} width={110} />
            <Tooltip
              formatter={(val: number) => [val.toLocaleString('en-IN'), 'Count']}
              contentStyle={{
                background: '#0D1829',
                border: '1px solid rgba(59,130,246,0.3)',
                borderRadius: 8,
                fontSize: 12,
              }}
            />
            <Bar dataKey="count" fill={accent} radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}