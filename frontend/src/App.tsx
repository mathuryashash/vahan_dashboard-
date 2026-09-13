import { useState, useEffect, lazy, Suspense } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
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
const IndustrySalesPage = lazy(() => import('./pages/IndustrySales').then((m) => ({ default: m.IndustrySalesPage })));
const RtoAnalysisPage = lazy(() => import('./pages/RtoAnalysis').then((m) => ({ default: m.RtoAnalysisPage })));
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { getRefreshStatus } from './api/vahan';
import { useScrapeProgress } from './hooks/useIsLiveData';
import { fetchCurrentUser, logout } from './api/auth';
import type { AuthUser } from './api/auth';
import { AuthContext } from './contexts/AuthContext';

export default function App() {
  // undefined = still checking the httpOnly session cookie via GET /me;
  // null = confirmed logged out. Can't know synchronously anymore since the
  // token itself is never readable from JS (see api/auth.ts).
  const [auth, setAuth] = useState<AuthUser | null | undefined>(undefined);
  const queryClient = useQueryClient();

  useEffect(() => {
    fetchCurrentUser().then(setAuth);
  }, []);

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
    return <LoginPage onLogin={setAuth} />;
  }

  const handleLogout = async () => {
    await logout();
    queryClient.clear();
    setAuth(null);
  };

  return (
    <AuthContext.Provider value={auth}>
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
                <Route path="/industry-sales" element={<IndustrySalesPage />} />
                <Route path="/rto-analysis" element={<RtoAnalysisPage />} />
              </Routes>
            </Suspense>
          </main>
        </div>
      </div>
    </AuthContext.Provider>
  );
}