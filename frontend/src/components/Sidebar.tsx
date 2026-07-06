import { NavLink } from 'react-router-dom';
import { LayoutDashboard, Map, TrendingUp, BarChart3, ChevronLeft, ChevronRight } from './Icons';
import clsx from 'clsx';
import { useAppStore } from '../hooks/useAppStore';

const navItems = [
  { to: '/', icon: LayoutDashboard, label: 'Overview' },
  { to: '/comparison', icon: Map, label: 'State Comparison' },
  { to: '/yoy', icon: TrendingUp, label: 'Year-over-Year' },
  { to: '/categories', icon: BarChart3, label: 'Categories' },
];

function NavItem({ to, icon: Icon, label, collapsed }: { to: string; icon: React.FC<{ className?: string }>; label: string; collapsed: boolean }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }: { isActive: boolean }) =>
        clsx(
          'flex items-center gap-3 text-sm font-medium transition-all duration-200 relative group',
          isActive ? 'text-white' : 'text-slate-500 hover:text-slate-300',
          collapsed ? 'justify-center px-3 py-2.5' : 'px-4 py-2.5'
        )
      }
    >
      {({ isActive }: { isActive: boolean }) => (
        <>
          {isActive && (
            <div
              className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-5 rounded-r-full"
              style={{ background: 'linear-gradient(180deg, #3B82F6, #06B6D4)' }}
            />
          )}
          <Icon className="w-4 h-4 shrink-0" />
          {!collapsed && <span className="text-xs tracking-wide">{label}</span>}
          {isActive && !collapsed && (
            <div className="ml-auto flex items-center gap-1">
              <div className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse-glow" />
            </div>
          )}
        </>
      )}
    </NavLink>
  );
}

export function Sidebar() {
  const { sidebarCollapsed, toggleSidebar } = useAppStore();

  return (
    <aside
      className={clsx(
        'flex flex-col transition-all duration-300 shrink-0',
        sidebarCollapsed ? 'w-14' : 'w-52'
      )}
      style={{ background: '#070D1A', borderRight: '1px solid rgba(255,255,255,0.05)' }}
    >
      <div className="px-4 py-5 border-b border-[rgba(255,255,255,0.05)]">
        {!sidebarCollapsed && (
          <div className="animate-entrance">
            <p className="text-[10px] uppercase tracking-[0.2em] text-slate-500 font-mono mb-0.5">Ministry of Road Transport</p>
            <p className="text-sm font-bold text-white tracking-tight">VAHAN SEWA</p>
          </div>
        )}
        {sidebarCollapsed && (
          <div className="w-6 h-6 rounded-md bg-gradient-to-br from-blue-500 to-cyan-400 mx-auto" />
        )}
      </div>

      <nav className="flex-1 py-3">
        {navItems.map(({ to, icon: Icon, label }) => (
          <NavItem key={to} to={to} icon={Icon} label={label} collapsed={sidebarCollapsed} />
        ))}
      </nav>

      <div className="px-3 py-3 border-t border-[rgba(255,255,255,0.05)]">
        <button
          onClick={toggleSidebar}
          className="w-full flex items-center justify-center py-1.5 text-slate-500 hover:text-slate-300 transition-colors rounded-lg hover:bg-[rgba(255,255,255,0.04)]"
        >
          {sidebarCollapsed ? (
            <ChevronRight className="w-4 h-4" />
          ) : (
            <div className="flex items-center gap-2 text-[11px] font-mono text-slate-600">
              <ChevronLeft className="w-4 h-4" />
              <span>COLLAPSE</span>
            </div>
          )}
        </button>
      </div>
    </aside>
  );
}