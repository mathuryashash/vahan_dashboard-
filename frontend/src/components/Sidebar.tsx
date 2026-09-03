// frontend/src/components/Sidebar.tsx
import { NavLink } from 'react-router-dom';
import { LayoutDashboard, Map, TrendingUp, BarChart3, Car, Award, Building, ChevronLeft, ChevronRight } from './Icons';
import clsx from 'clsx';
import { useAppStore } from '../hooks/useAppStore';

const navItems = [
  { to: '/', icon: LayoutDashboard, label: 'Overview' },
  { to: '/comparison', icon: Map, label: 'State Comparison' },
  { to: '/yoy', icon: TrendingUp, label: 'Year over Year' },
  { to: '/categories', icon: BarChart3, label: 'Categories & Fuel' },
  { to: '/makers', icon: Car, label: 'Makers' },
  { to: '/industry-sales', icon: Award, label: 'Industry Sales' },
  { to: '/rto-analysis', icon: Building, label: 'RTO Analysis' },
];

function NavItem({ to, icon: Icon, label, collapsed }: { to: string; icon: React.FC<{ className?: string }>; label: string; collapsed: boolean }) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      className={({ isActive }: { isActive: boolean }) =>
        clsx(
          'flex items-center gap-3 text-sm font-medium transition-all duration-150 relative rounded-lg mx-2',
          isActive
            ? 'bg-[var(--accent)] text-[var(--accent-contrast)]'
            : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-card-hover)]',
          collapsed ? 'justify-center px-2 py-2.5' : 'px-3 py-2.5'
        )
      }
    >
      <Icon className="w-4 h-4 shrink-0" />
      {!collapsed && <span className="text-xs tracking-wide">{label}</span>}
    </NavLink>
  );
}

export function Sidebar() {
  const { sidebarCollapsed, toggleSidebar } = useAppStore();

  return (
    <aside
      className={clsx(
        'flex flex-col transition-all duration-300 shrink-0 bg-[var(--bg-app)] border-r border-[var(--border)]',
        sidebarCollapsed ? 'w-14' : 'w-56'
      )}
    >
      <div className="px-4 py-5 border-b border-[var(--border)]">
        {!sidebarCollapsed && (
          <div className="animate-entrance">
            <p className="text-sm font-bold text-[var(--text-primary)] tracking-tight">VAHAN SEWA</p>
          </div>
        )}
        {sidebarCollapsed && (
          <img src="/company-logo.png" alt="Logo" className="w-8 h-8 rounded-lg object-cover mx-auto" />
        )}
      </div>

      <nav className="flex-1 py-3 space-y-1">
        {navItems.map(({ to, icon: Icon, label }) => (
          <NavItem key={to} to={to} icon={Icon} label={label} collapsed={sidebarCollapsed} />
        ))}
      </nav>

      <div className="px-3 py-3 border-t border-[var(--border)]">
        <button
          onClick={toggleSidebar}
          className="w-full flex items-center justify-center py-1.5 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors rounded-lg hover:bg-[var(--bg-card-hover)]"
        >
          {sidebarCollapsed ? (
            <ChevronRight className="w-4 h-4" />
          ) : (
            <div className="flex items-center gap-2 text-[11px] font-mono text-[var(--text-muted)]">
              <ChevronLeft className="w-4 h-4" />
              <span>COLLAPSE</span>
            </div>
          )}
        </button>
      </div>
    </aside>
  );
}
