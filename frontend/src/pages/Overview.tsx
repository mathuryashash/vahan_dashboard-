import { useQuery } from '@tanstack/react-query';
import {
  AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, TooltipProps, ResponsiveContainer
} from 'recharts';
import { TrendingUp, Award, Car, Bike } from '../components/Icons';
import { KPICard } from '../components/KPICard';
import { getKPIs, getTrend, getStateRanking, getCategories, getStates, getTopMakers, getModelBreakdown } from '../api/vahan';
import { useAppStore } from '../hooks/useAppStore';

const COLORS = ['#3B82F6', '#06B6D4', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899', '#F97316'];
const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const VEHICLE_CLASSES = [
  "Two-Wheeler",
  "Motor Car/Jeep/Taxi",
  "Mini Bus",
  "Bus",
  "Three-Wheeler",
  "Light Motor Vehicle",
  "Medium Bus",
  "Medium Truck",
  "Heavy Truck",
  "Tractor",
  "Construction Equipment",
  "Other"
];

function CustomTooltip({ active, payload, label }: TooltipProps<number, string>) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-[#0D1829] border border-[rgba(59,130,246,0.3)] rounded-xl px-3 py-2.5 shadow-[0_8px_30px_rgba(0,0,0,0.5)]">
      <p className="text-[10px] uppercase tracking-widest text-slate-400 mb-1">{label}</p>
      <p className="font-mono text-base font-bold text-white">{payload[0].value?.toLocaleString('en-IN')}</p>
      <p className="text-[10px] text-slate-400">registrations</p>
    </div>
  );
}

export function OverviewPage() {
  const {
    selectedYear,
    selectedMonth,
    selectedState,
    selectedCategory,
    selectedMaker,
    selectedModel,
    setSelectedYear,
    setSelectedMonth,
    setSelectedState,
    setSelectedCategory,
    setSelectedMaker,
    setSelectedModel,
  } = useAppStore();

  // Dynamic filter queries
  const { data: statesList } = useQuery({ queryKey: ['states'], queryFn: getStates });

  const { data: kpis, isLoading: kpisLoading } = useQuery({
    queryKey: ['kpis', selectedYear, selectedMonth, selectedState, selectedCategory, selectedMaker, selectedModel],
    queryFn: () => getKPIs({
      year: selectedYear,
      month: selectedMonth,
      state: selectedState,
      vehicle_class: selectedCategory,
      maker: selectedMaker,
      vehicle_model: selectedModel
    }),
  });

  const { data: trend, isLoading: trendLoading } = useQuery({
    queryKey: ['trend', selectedYear, selectedMonth, selectedState, selectedCategory, selectedMaker, selectedModel],
    queryFn: () => getTrend({
      year: selectedYear,
      month: selectedMonth,
      state: selectedState,
      vehicle_class: selectedCategory,
      maker: selectedMaker,
      vehicle_model: selectedModel
    }),
  });

  const { data: ranking, isLoading: rankingLoading } = useQuery({
    queryKey: ['stateRanking', selectedYear, selectedMonth, selectedState, selectedCategory, selectedMaker, selectedModel],
    queryFn: () => getStateRanking({
      year: selectedYear,
      month: selectedMonth,
      state: selectedState,
      vehicle_class: selectedCategory,
      maker: selectedMaker,
      vehicle_model: selectedModel,
      limit: 10
    }),
  });

  const { data: categories, isLoading: categoriesLoading } = useQuery({
    queryKey: ['categories', selectedYear, selectedMonth, selectedState, selectedMaker, selectedModel],
    queryFn: () => getCategories({
      year: selectedYear,
      month: selectedMonth,
      state: selectedState,
      maker: selectedMaker,
      vehicle_model: selectedModel
    }),
  });

  const { data: makers } = useQuery({
    queryKey: ['makers', selectedCategory, selectedYear, selectedMonth, selectedState],
    queryFn: () => getTopMakers({
      vehicle_class: selectedCategory,
      year: selectedYear,
      month: selectedMonth,
      state: selectedState,
      limit: 30
    }),
  });

  const { data: models, isLoading: modelsLoading } = useQuery({
    queryKey: ['models', selectedCategory, selectedMaker, selectedYear, selectedMonth, selectedState],
    queryFn: () => getModelBreakdown({
      vehicle_class: selectedCategory,
      maker: selectedMaker,
      year: selectedYear,
      month: selectedMonth,
      state: selectedState,
      limit: 15
    }),
  });

  // Map trend data: show Day 1, Day 2 if month is selected. Else show Jan, Feb.
  const chartData = (trend || []).map((d: { month?: number; day?: number; count: number }) => {
    if (selectedMonth) {
      return {
        name: `Day ${d.day}`,
        count: d.count,
      };
    } else {
      return {
        name: d.month ? MONTH_NAMES[d.month - 1] : '',
        count: d.count,
      };
    }
  });

  const pieData = (categories || []).slice(0, 8).map((c: { vehicle_class: string; total_count: number }) => ({
    name: c.vehicle_class,
    value: c.total_count,
  }));

  const activeFiltersCount = [
    selectedState,
    selectedMonth,
    selectedCategory,
    selectedMaker,
    selectedModel
  ].filter(Boolean).length;

  const handleResetFilters = () => {
    setSelectedState(null);
    setSelectedMonth(null);
    setSelectedCategory(null);
    setSelectedMaker(null);
    setSelectedModel(null);
  };

  return (
    <div className="p-6 space-y-6">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div className="animate-entrance">
          <h2 className="text-xl font-bold text-white tracking-tight">
            Mission Control
          </h2>
          <p className="text-xs text-slate-500 mt-0.5 font-mono uppercase tracking-widest">
            India Vehicle Registration Observatory — FY {selectedYear}
          </p>
        </div>
        <div className="flex items-center gap-4 text-[10px] text-slate-500 font-mono">
          {activeFiltersCount > 0 && (
            <button
              onClick={handleResetFilters}
              className="text-xs text-blue-400 hover:text-blue-300 font-semibold transition-colors bg-[rgba(59,130,246,0.1)] border border-[rgba(59,130,246,0.2)] px-2.5 py-1 rounded-lg"
            >
              Reset Filters ({activeFiltersCount})
            </button>
          )}
          <div className="flex items-center gap-1.5">
            <div className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse-glow" />
            <span>LIVE DATA</span>
          </div>
        </div>
      </div>

      {/* Dynamic Filters Row */}
      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-3 bg-[#0D1829]/60 border border-[rgba(255,255,255,0.06)] p-4 rounded-2xl backdrop-blur-md animate-entrance shadow-[0_10px_30px_rgba(0,0,0,0.3)]">
        {/* State Filter */}
        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] uppercase font-mono tracking-widest text-slate-500 font-bold">State</label>
          <select
            value={selectedState || ''}
            onChange={(e) => setSelectedState(e.target.value || null)}
            className="w-full bg-[#0E1B2E] border border-[rgba(255,255,255,0.08)] hover:border-blue-500/50 text-slate-200 text-xs font-semibold px-3 py-2 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500/40 transition-all duration-200 cursor-pointer shadow-[0_4px_15px_rgba(0,0,0,0.2)]"
          >
            <option value="">All States</option>
            {(statesList || []).map((s: { state_name: string }) => (
              <option key={s.state_name} value={s.state_name}>{s.state_name}</option>
            ))}
          </select>
        </div>

        {/* Year Filter */}
        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] uppercase font-mono tracking-widest text-slate-500 font-bold">Year</label>
          <select
            value={selectedYear}
            onChange={(e) => setSelectedYear(Number(e.target.value))}
            className="w-full bg-[#0E1B2E] border border-[rgba(255,255,255,0.08)] hover:border-blue-500/50 text-slate-200 text-xs font-semibold px-3 py-2 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500/40 transition-all duration-200 cursor-pointer shadow-[0_4px_15px_rgba(0,0,0,0.2)]"
          >
            <option value={2024}>2024</option>
            <option value={2025}>2025</option>
            <option value={2026}>2026</option>
          </select>
        </div>

        {/* Month Filter */}
        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] uppercase font-mono tracking-widest text-slate-500 font-bold">Month</label>
          <select
            value={selectedMonth || ''}
            onChange={(e) => setSelectedMonth(e.target.value ? Number(e.target.value) : null)}
            className="w-full bg-[#0E1B2E] border border-[rgba(255,255,255,0.08)] hover:border-blue-500/50 text-slate-200 text-xs font-semibold px-3 py-2 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500/40 transition-all duration-200 cursor-pointer shadow-[0_4px_15px_rgba(0,0,0,0.2)]"
          >
            <option value="">All Months</option>
            {MONTH_NAMES.map((name, idx) => (
              <option key={name} value={idx + 1}>{name}</option>
            ))}
          </select>
        </div>

        {/* Category Filter */}
        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] uppercase font-mono tracking-widest text-slate-500 font-bold">Category</label>
          <select
            value={selectedCategory || ''}
            onChange={(e) => setSelectedCategory(e.target.value || null)}
            className="w-full bg-[#0E1B2E] border border-[rgba(255,255,255,0.08)] hover:border-blue-500/50 text-slate-200 text-xs font-semibold px-3 py-2 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500/40 transition-all duration-200 cursor-pointer shadow-[0_4px_15px_rgba(0,0,0,0.2)]"
          >
            <option value="">All Categories</option>
            {VEHICLE_CLASSES.map((vc) => (
              <option key={vc} value={vc}>{vc}</option>
            ))}
          </select>
        </div>

        {/* OEM/Maker Filter */}
        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] uppercase font-mono tracking-widest text-slate-500 font-bold">OEM / Brand</label>
          <select
            value={selectedMaker || ''}
            onChange={(e) => setSelectedMaker(e.target.value || null)}
            className="w-full bg-[#0E1B2E] border border-[rgba(255,255,255,0.08)] hover:border-blue-500/50 text-slate-200 text-xs font-semibold px-3 py-2 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500/40 transition-all duration-200 cursor-pointer shadow-[0_4px_15px_rgba(0,0,0,0.2)]"
          >
            <option value="">All Brands</option>
            {(makers || []).map((m: { maker: string }) => (
              <option key={m.maker} value={m.maker}>{m.maker}</option>
            ))}
          </select>
        </div>

        {/* Model Filter */}
        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] uppercase font-mono tracking-widest text-slate-500 font-bold">Vehicle Model</label>
          <select
            value={selectedModel || ''}
            onChange={(e) => setSelectedModel(e.target.value || null)}
            disabled={!selectedMaker}
            className="w-full bg-[#0E1B2E] border border-[rgba(255,255,255,0.08)] hover:border-blue-500/50 text-slate-200 text-xs font-semibold px-3 py-2 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500/40 transition-all duration-200 cursor-pointer shadow-[0_4px_15px_rgba(0,0,0,0.2)] disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <option value="">{selectedMaker ? 'All Models' : 'Select OEM first'}</option>
            {selectedMaker && (models || []).map((m: { model: string }) => (
              <option key={m.model} value={m.model}>{m.model}</option>
            ))}
          </select>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <KPICard label="Total Registrations" value={kpis?.total_this_month ?? 0} change={kpis?.yoy_growth_percent} icon={<Car className="w-4 h-4" />} loading={kpisLoading} accent="blue" index={0} />
        <KPICard label="YoY Growth" value={kpis?.yoy_growth_percent ? `${kpis.yoy_growth_percent.toFixed(1)}%` : '—'} change={kpis?.yoy_growth_percent} icon={<TrendingUp className="w-4 h-4" />} loading={kpisLoading} accent="emerald" index={1} />
        <KPICard label="Latest Day Sales" value={kpis?.total_registrations_today ?? 0} icon={<Bike className="w-4 h-4" />} loading={kpisLoading} accent="cyan" index={2} />
        <KPICard label="Top State" value={kpis?.top_state ?? '—'} icon={<Award className="w-4 h-4" />} loading={kpisLoading} accent="amber" index={3} />
      </div>

      {/* Main charts row */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        {/* Registration Trend (Monthly/Daily) */}
        <div className="xl:col-span-2 bg-[#0D1829] rounded-2xl border border-[rgba(255,255,255,0.06)] p-5 animate-entrance" style={{ animationDelay: '200ms' }}>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-sm font-bold text-white tracking-tight">
                {selectedMonth ? `${MONTH_NAMES[selectedMonth - 1]} Registration Trend` : 'Registration Trend'}
              </h3>
              <p className="text-[10px] text-slate-500 font-mono mt-0.5">
                {selectedMonth ? `Daily View — ${MONTH_NAMES[selectedMonth - 1]} ${selectedYear}` : `Monthly View — FY ${selectedYear}`}
              </p>
            </div>
            <span className="text-[10px] text-blue-400 font-mono bg-[rgba(59,130,246,0.1)] px-2 py-1 rounded-md border border-[rgba(59,130,246,0.2)]">
              {selectedMonth ? 'DAILY' : 'MONTHLY'}
            </span>
          </div>
          {trendLoading ? (
            <div className="h-52 rounded-xl bg-[#111D32] animate-pulse" />
          ) : (
            <ResponsiveContainer width="100%" height={208}>
              <AreaChart data={chartData}>
                <defs>
                  <linearGradient id="gradBlue" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#3B82F6" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="#3B82F6" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="1 2" stroke="rgba(255,255,255,0.04)" vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#475569', fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 10, fill: '#475569', fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} tickFormatter={(v: number) => v >= 1000000 ? `${(v/1000000).toFixed(1)}M` : v.toLocaleString('en-IN')} width={45} />
                <Tooltip content={<CustomTooltip />} />
                <Area type="monotone" dataKey="count" stroke="#3B82F6" strokeWidth={2.5} fill="url(#gradBlue)" dot={selectedMonth ? false : { r: 3, fill: '#3B82F6', strokeWidth: 0 }} activeDot={{ r: 5, fill: '#3B82F6', stroke: '#070D1A', strokeWidth: 2 }} />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Category Donut */}
        <div className="bg-[#0D1829] rounded-2xl border border-[rgba(255,255,255,0.06)] p-5 animate-entrance" style={{ animationDelay: '250ms' }}>
          <div className="mb-4">
            <h3 className="text-sm font-bold text-white tracking-tight">Vehicle Mix</h3>
            <p className="text-[10px] text-slate-500 font-mono mt-0.5">by category — {selectedYear}</p>
          </div>
          {categoriesLoading ? (
            <div className="h-52 rounded-xl bg-[#111D32] animate-pulse" />
          ) : (
            <>
              <ResponsiveContainer width="100%" height={160}>
                <PieChart>
                  <Pie data={pieData} cx="50%" cy="50%" innerRadius={45} outerRadius={75} paddingAngle={2} dataKey="value">
                    {pieData.map((_: unknown, i: number) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                  </Pie>
                  <Tooltip formatter={(val: number) => [val.toLocaleString('en-IN'), '']} contentStyle={{ background: '#0D1829', border: '1px solid rgba(59,130,246,0.3)', borderRadius: 8 }} />
                </PieChart>
              </ResponsiveContainer>
              <div className="mt-2 space-y-1.5 max-h-28 overflow-y-auto pr-1">
                {pieData.map((p: { name: string; value: number }, i: number) => (
                  <div key={i} className="flex items-center justify-between text-[11px]">
                    <div className="flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-sm" style={{ backgroundColor: COLORS[i % COLORS.length] }} />
                      <span className="text-slate-400 truncate max-w-[100px]">{p.name}</span>
                    </div>
                    <span className="font-mono text-slate-300 font-semibold">{p.value?.toLocaleString('en-IN')}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>

      {/* State ranking & Model Breakdown side-by-side */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        {/* State ranking */}
        <div className="bg-[#0D1829] rounded-2xl border border-[rgba(255,255,255,0.06)] p-5 animate-entrance" style={{ animationDelay: '300ms' }}>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-sm font-bold text-white tracking-tight">State Ranking</h3>
              <p className="text-[10px] text-slate-500 font-mono mt-0.5">Top 10 by registrations</p>
            </div>
          </div>
          {rankingLoading ? (
            <div className="h-44 rounded-xl bg-[#111D32] animate-pulse" />
          ) : (
            <div className="space-y-3 max-h-96 overflow-y-auto pr-1">
              {(ranking || []).map((s: { state_name: string; total_count: number; share_percent: number }, i: number) => {
                const max = (ranking || [])[0]?.total_count || 1;
                const pct = (s.total_count / max) * 100;
                const color = COLORS[i % COLORS.length];
                return (
                  <div key={s.state_name} className="flex items-center gap-3 group cursor-pointer" onClick={() => setSelectedState(s.state_name)}>
                    <span className="font-mono text-[11px] font-bold text-slate-500 w-4 text-right shrink-0">#{i + 1}</span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs font-semibold text-slate-300 group-hover:text-white transition-colors">{s.state_name}</span>
                        <span className="font-mono text-[11px] text-slate-500">{s.share_percent?.toFixed(1)}%</span>
                      </div>
                      <div className="h-1.5 bg-[#111D32] rounded-full overflow-hidden">
                        <div
                          className="h-full rounded-full transition-all duration-700 ease-out group-hover:shadow-[0_0_8px_var(--color)]"
                          style={{ width: `${pct}%`, backgroundColor: color, ['--color' as string]: color }}
                        />
                      </div>
                    </div>
                    <span className="font-mono text-[11px] font-bold text-slate-300 w-20 text-right shrink-0">
                      {s.total_count?.toLocaleString('en-IN')}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* OEM Vehicle Models Breakdown */}
        <div className="bg-[#0D1829] rounded-2xl border border-[rgba(255,255,255,0.06)] p-5 animate-entrance" style={{ animationDelay: '350ms' }}>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-sm font-bold text-white tracking-tight">Top Vehicle Models</h3>
              <p className="text-[10px] text-slate-500 font-mono mt-0.5">
                {selectedMaker ? `${selectedMaker} Models Breakdown` : 'Top Models Breakdown'}
              </p>
            </div>
            {selectedMaker && (
              <button
                onClick={() => setSelectedMaker(null)}
                className="text-[9px] uppercase font-mono tracking-wider text-blue-400 hover:text-blue-300 transition-colors"
              >
                Clear Brand
              </button>
            )}
          </div>
          {modelsLoading ? (
            <div className="h-44 rounded-xl bg-[#111D32] animate-pulse" />
          ) : (models || []).length === 0 ? (
            <div className="h-44 flex flex-col items-center justify-center text-slate-500 text-xs border border-dashed border-slate-800 rounded-xl">
              <span>No vehicle models match the active filters</span>
              <span className="text-[10px] text-slate-600 mt-1">Try selecting a different OEM or category</span>
            </div>
          ) : (
            <div className="space-y-3 max-h-96 overflow-y-auto pr-1">
              {(models || []).map((m: { model: string; count: number; share_percent: number }, i: number) => {
                const max = (models || [])[0]?.count || 1;
                const pct = (m.count / max) * 100;
                const color = COLORS[(i + 2) % COLORS.length];
                return (
                  <div key={m.model} className="flex items-center gap-3 group cursor-pointer" onClick={() => setSelectedModel(m.model)}>
                    <span className="font-mono text-[11px] font-bold text-slate-500 w-4 text-right shrink-0">#{i + 1}</span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs font-semibold text-slate-300 group-hover:text-white transition-colors">{m.model}</span>
                        <span className="font-mono text-[11px] text-slate-500">{m.share_percent?.toFixed(1)}%</span>
                      </div>
                      <div className="h-1.5 bg-[#111D32] rounded-full overflow-hidden">
                        <div
                          className="h-full rounded-full transition-all duration-700 ease-out group-hover:shadow-[0_0_8px_var(--color)]"
                          style={{ width: `${pct}%`, backgroundColor: color, ['--color' as string]: color }}
                        />
                      </div>
                    </div>
                    <span className="font-mono text-[11px] font-bold text-slate-300 w-20 text-right shrink-0">
                      {m.count?.toLocaleString('en-IN')}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Bottom stats row */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {[
          { label: 'States Active', value: '36 / 36', sub: 'All states reporting', color: '#10B981' },
          { label: 'Avg per State', value: kpis ? Math.round(kpis.total_this_month / 36).toLocaleString('en-IN') : '—', sub: 'registrations per state', color: '#3B82F6' },
          { label: 'Peak Trend Point', value: chartData.length > 0 ? chartData.reduce((a: { count: number }, b: { count: number }) => a.count > b.count ? a : b).name : '—', sub: 'highest volume time point', color: '#F59E0B' },
        ].map((stat, i) => (
          <div key={i} className="bg-[#0D1829] rounded-xl border border-[rgba(255,255,255,0.06)] p-4 flex items-center gap-4 animate-entrance" style={{ animationDelay: `${350 + i * 60}ms` }}>
            <div className="w-1 h-10 rounded-full" style={{ background: stat.color }} />
            <div>
              <p className="text-[10px] uppercase tracking-widest text-slate-500">{stat.label}</p>
              <p className="font-mono text-lg font-bold" style={{ color: stat.color }}>{stat.value}</p>
              <p className="text-[10px] text-slate-600">{stat.sub}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}