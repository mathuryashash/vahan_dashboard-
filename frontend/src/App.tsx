import { useState, lazy, Suspense } from 'react';
import { Routes, Route } from 'react-router-dom';
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
import { getStoredAuth, logout } from './api/auth';
import type { AuthUser } from './api/auth';
import { AuthContext } from './contexts/AuthContext';

export default function App() {
  const [auth, setAuth] = useState<AuthUser | null>(getStoredAuth());
  const queryClient = useQueryClient();

  const { data, dataUpdatedAt } = useQuery({
    queryKey: ['refreshStatus'],
    queryFn: getRefreshStatus,
    // Poll quickly while a scrape is running so the header reflects real
    // progress; fall back to a slow poll otherwise.
    refetchInterval: (query) => (query.state.data?.status === 'running' ? 5000 : 120000),
    enabled: !!auth,
  });

  const { data: scrapeProgress } = useScrapeProgress(!!auth);

  if (!auth) {
    return <LoginPage onLogin={setAuth} />;
  }

  const handleLogout = () => {
    logout();
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
                <Route path="/comparison" element={<ComparisonPage />} />
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