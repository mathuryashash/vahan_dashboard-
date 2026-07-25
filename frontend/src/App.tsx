import { Routes, Route } from 'react-router-dom';
import { Sidebar } from './components/Sidebar';
import { Header } from './components/Header';
import { OverviewPage } from './pages/Overview';
import { ComparisonPage } from './pages/Comparison';
import { YoYPage } from './pages/YoY';
import { CategoriesPage } from './pages/Categories';
import { CategoryDetailPage } from './pages/CategoryDetail';
import { MakersModelsPage } from './pages/MakersModels';
import { IndustrySalesPage } from './pages/IndustrySales';
import { RtoAnalysisPage } from './pages/RtoAnalysis';
import { useQuery } from '@tanstack/react-query';
import { getRefreshStatus } from './api/vahan';
import { useScrapeProgress } from './hooks/useIsLiveData';

export default function App() {
  const { data, dataUpdatedAt } = useQuery({
    queryKey: ['refreshStatus'],
    queryFn: getRefreshStatus,
    // Poll quickly while a scrape is running so the header reflects real
    // progress; fall back to a slow poll otherwise.
    refetchInterval: (query) => (query.state.data?.status === 'running' ? 5000 : 120000),
  });

  const { data: scrapeProgress } = useScrapeProgress();

  return (
    <div className="flex h-screen overflow-hidden bg-[var(--bg-app)]">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden bg-[var(--bg-surface)]">
        <Header refreshStatus={data ?? null} statusUpdatedAt={dataUpdatedAt} scrapeProgress={scrapeProgress ?? null} />
        <main className="flex-1 overflow-y-auto">
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
        </main>
      </div>
    </div>
  );
}