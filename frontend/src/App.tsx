import { useState, useEffect, lazy, Suspense } from 'react';
import { Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { Sidebar } from './components/Sidebar';
import { Header } from './components/Header';
import { LoginPage } from './pages/Login';

// Route-level code splitting -- every page (Recharts included) used to ship
// in one bundle regardless of which single page a visit actually lands on
// (found by frontend review). Login stays eager: it's the only thing an
// unauthenticated visit ever renders.
const OverviewPage = lazy(() => import('./pages/Overview').then((m) => ({ default: m.OverviewPage })));
const ComparisonPage = lazy(() => import('./pages/Comparison').then((m) => ({ default: m.ComparisonPage })));
const YoYPage = lazy(() => import('./pages/YoY').then((m) => ({ default: m.YoYPage })));
const CategoriesPage = lazy(() => import('./pages/Categories').then((m) => ({ default: m.CategoriesPage })));
const CategoryDetailPage = lazy(() => import('./pages/CategoryDetail').then((m) => ({ default: m.CategoryDetailPage })));
const MakersModelsPage = lazy(() => import('./pages/MakersModels').then((m) => ({ default: m.MakersModelsPage })));
// IndustrySales' lazy import is intentionally absent -- the route below
// redirects while the FADA-sourced page is hidden, and keeping the import
// would still ship its chunk. Restore both together.
const RtoAnalysisPage = lazy(() => import('./pages/RtoAnalysis').then((m) => ({ default: m.RtoAnalysisPage })));
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { getRefreshStatus } from './api/vahan';
import { useScrapeProgress } from './hooks/useIsLiveData';
import { useUrlSyncedFilters } from './hooks/useUrlSyncedFilters';
import { fetchCurrentUser, logout } from './api/auth';
import type { AuthUser } from './api/auth';
import { AuthContext } from './contexts/AuthContext';
import { useScopeLock, applyScopeToStore } from './hooks/useScopeLock';
import { ErrorBoundary } from './components/ErrorBoundary';

/** Renders nothing -- exists only so useScopeLock runs under the auth
 *  provider on every route. */
function ScopeLock() {
  useScopeLock();
  return null;
}

export default function App() {
  // undefined = still checking the httpOnly session cookie via GET /me;
  // null = confirmed logged out. Can't know synchronously anymore since the
  // token itself is never readable from JS (see api/auth.ts).
  const [auth, setAuth] = useState<AuthUser | null | undefined>(undefined);
  const queryClient = useQueryClient();
  const location = useLocation();

  // applyScopeToStore before setAuth, not after: setAuth is what first
  // mounts the pages, and their queries fire from that very first commit.
  // Pinning afterwards (in <ScopeLock />'s effect) would already be one
  // wasted out-of-scope request per query too late.
  useEffect(() => {
    fetchCurrentUser().then((user) => {
      if (user) applyScopeToStore(user);
      setAuth(user);
    });
  }, []);

  const handleLogin = (user: AuthUser) => {
    applyScopeToStore(user);
    setAuth(user);
  };

  // Called unconditionally (Rules of Hooks) even though its effect is only
  // meaningful once auth resolves and the filter bar renders -- see its own
  // docstring for why this needs to live at the app root, not per-page.
  useUrlSyncedFilters();

  // Overview ("/") is the one page every post-login visit hits immediately --
  // prefetching its chunk during idle time (works whether auth is already
  // set or the user is still on the login screen) removes that fetch from
  // the critical path instead of paying for it only once the route mounts.
  // Hashed chunk filenames rule out a static <link rel="modulepreload">.
  useEffect(() => {
    const idle = window.requestIdleCallback ?? ((cb: () => void) => setTimeout(cb, 200));
    idle(() => { import('./pages/Overview'); });
  }, []);

  const { data, dataUpdatedAt } = useQuery({
    queryKey: ['refreshStatus'],
    queryFn: getRefreshStatus,
    // Poll quickly while a scrape is running so the header reflects real
    // progress; fall back to a slow poll otherwise.
    refetchInterval: (query) => (query.state.data?.status === 'running' ? 5000 : 120000),
    enabled: !!auth,
  });

  const { data: scrapeProgress } = useScrapeProgress(!!auth);

  if (auth === undefined) {
    return <div className="h-screen flex items-center justify-center bg-[var(--bg-app)]" />;
  }
  if (auth === null) {
    return <LoginPage onLogin={handleLogin} />;
  }

  const handleLogout = async () => {
    await logout();
    queryClient.clear();
    setAuth(null);
  };

  return (
    <AuthContext.Provider value={auth}>
      {/* Must sit INSIDE the provider (it reads auth) and outside the Routes,
          so a scoped account is pinned on whichever page it lands on first --
          not just Overview, which is where these effects used to live. */}
      <ScopeLock />
      <div className="flex h-screen overflow-hidden bg-[var(--bg-app)]">
        <Sidebar />
        <div className="flex-1 flex flex-col overflow-hidden bg-[var(--bg-surface)]">
          <Header
            refreshStatus={data ?? null}
            statusUpdatedAt={dataUpdatedAt}
            scrapeProgress={scrapeProgress ?? null}
            auth={auth}
            onLogout={handleLogout}
          />
          <main className="flex-1 overflow-y-auto">
            {/* Keyed on the path so the boundary resets when you navigate --
                otherwise one page throwing would leave every later route
                stuck on the fallback. Sits inside the chrome, so a broken
                page keeps the Sidebar and Header usable instead of blanking
                the whole dashboard (the root boundary in main.tsx stays as
                the last resort). */}
            <ErrorBoundary key={location.pathname}>
            <Suspense fallback={<div className="p-6"><div className="h-40 rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft" /></div>}>
              <Routes>
                <Route path="/" element={<OverviewPage />} />
                {/* Comparing states only makes sense for a national viewer -- a
                    state/RTO-scoped account is locked to one state anyway (see
                    comparison.py's scope clamp), so the page would just show
                    their own state with nothing to compare against. Blocks
                    direct URL navigation, not just the Sidebar link below. */}
                <Route path="/comparison" element={auth.scope_type === 'national' ? <ComparisonPage /> : <Navigate to="/" replace />} />
                <Route path="/yoy" element={<YoYPage />} />
                <Route path="/categories" element={<CategoriesPage />} />
                <Route path="/categories/:vehicleClass" element={<CategoryDetailPage />} />
                <Route path="/makers" element={<MakersModelsPage />} />
                {/* FADA-sourced; hidden while this deployment presents VAHAN
                    data only (see Sidebar). Redirects rather than 404s so an
                    old bookmark still lands somewhere sensible. Swap back to
                    <IndustrySalesPage /> to restore it. */}
                <Route path="/industry-sales" element={<Navigate to="/" replace />} />
                <Route path="/rto-analysis" element={<RtoAnalysisPage />} />
              </Routes>
            </Suspense>
            </ErrorBoundary>
          </main>
        </div>
      </div>
    </AuthContext.Provider>
  );
}