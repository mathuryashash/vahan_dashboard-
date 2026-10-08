// frontend/src/components/Sidebar.tsx
import { useEffect } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
// Award went with the hidden Industry Sales entry below -- re-add it here
// when restoring that page.
import { LayoutDashboard, Map, TrendingUp, BarChart3, Car, Building, ChevronLeft, ChevronRight, Close } from './Icons';
import clsx from 'clsx';
import { useAppStore } from '../hooks/useAppStore';
import { useAuth } from '../contexts/AuthContext';

const navItems = [
  { to: '/', icon: LayoutDashboard, label: 'Overview' },
  // Comparing states only makes sense nationally -- a state/RTO-scoped
  // account is locked to one state, so there's nothing to compare against
  // (see App.tsx's route guard, which also blocks direct URL navigation).
  { to: '/comparison', icon: Map, label: 'State Comparison', nationalOnly: true },
  { to: '/yoy', icon: TrendingUp, label: 'Year over Year' },
  { to: '/categories', icon: BarChart3, label: 'Categories & Fuel' },
  { to: '/makers', icon: Car, label: 'Makers' },
  // Industry Sales is hidden: it is the only page sourced from FADA's
  // dealer-retail PDFs rather than VAHAN, and this deployment presents
  // VAHAN registration data only. The page and its endpoints still exist --
  // restore this line (and the route in App.tsx) to bring it back.
  { to: '/rto-analysis', icon: Building, label: 'RTO Analysis' },
];

function NavItem({ to, icon: Icon, label, collapsed }: { to: string; icon: React.FC<{ className?: string }>; label: string; collapsed: boolean }) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      // B13: icon-only when collapsed -- give it an accessible name and a
      // hover tooltip. (Harmless when expanded: the name matches the text.)
      aria-label={label}
      title={collapsed ? label : undefined}
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
      <Icon className="w-4 h-4 shrink-0" aria-hidden="true" />
      {!collapsed && <span className="text-xs tracking-wide">{label}</span>}
    </NavLink>
  );
}

export function Sidebar() {
  const { sidebarCollapsed: desktopCollapsed, toggleSidebar, mobileNavOpen, setMobileNavOpen } = useAppStore();
  const auth = useAuth();
  const visibleNavItems = navItems.filter((item) => !item.nationalOnly || auth.scope_type === 'national');
  const location = useLocation();

  // B5: below md the sidebar is an off-canvas drawer (opened from the
  // header's menu button) instead of a fixed 224 px column that squeezed
  // <main> to ~166 px at 390 px. Close it on navigation and on Escape.
  useEffect(() => { setMobileNavOpen(false); }, [location.pathname, setMobileNavOpen]);
  useEffect(() => {
    if (!mobileNavOpen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setMobileNavOpen(false); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [mobileNavOpen, setMobileNavOpen]);
  // The drawer always shows labels; the collapse toggle is desktop-only.
  const sidebarCollapsed = desktopCollapsed && !mobileNavOpen;

  return (
    <>
    {mobileNavOpen && (
      <div
        className="fixed inset-0 z-40 bg-black/40 md:hidden"
        aria-hidden="true"
        onClick={() => setMobileNavOpen(false)}
      />
    )}
    <aside
      id="app-sidebar"
      aria-label="Main navigation"
      className={clsx(
        'flex flex-col transition-all duration-300 shrink-0 bg-[var(--bg-app)] border-r border-[var(--border)]',
        // Mobile: fixed drawer, hidden unless open. md+: in-flow column.
        'fixed inset-y-0 left-0 z-50 w-64 md:static md:z-auto',
        mobileNavOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0',
        sidebarCollapsed ? 'md:w-14' : 'md:w-56'
      )}
    >
      <div className="px-4 py-5 border-b border-[var(--border)] flex items-center justify-between">
        {!sidebarCollapsed && (
          <div className="animate-entrance">
            <p className="text-sm font-bold text-[var(--text-primary)] tracking-tight">GRYDENCE</p>
          </div>
        )}
        {sidebarCollapsed && (
          <img src="/company-logo.png" alt="Grydence" className="w-8 h-8 rounded-lg object-cover mx-auto" />
        )}
        {mobileNavOpen && (
          <button
            type="button"
            onClick={() => setMobileNavOpen(false)}
            aria-label="Close navigation"
            className="md:hidden p-1 rounded-lg text-[var(--text-muted)] hover:text-[var(--text-primary)]"
          >
            <Close className="w-4 h-4" />
          </button>
        )}
      </div>

      <nav className="flex-1 py-3 space-y-1">
        {visibleNavItems.map(({ to, icon: Icon, label }) => (
          <NavItem key={to} to={to} icon={Icon} label={label} collapsed={sidebarCollapsed} />
        ))}
      </nav>

      <div className="px-3 py-3 border-t border-[var(--border)] hidden md:block">
        <button
          onClick={toggleSidebar}
          aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
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
    </>
  );
}
