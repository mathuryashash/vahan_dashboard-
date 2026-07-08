import { Routes, Route } from 'react-router-dom';
import { Sidebar } from './components/Sidebar';
import { Header } from './components/Header';
import { OverviewPage } from './pages/Overview';
import { ComparisonPage } from './pages/Comparison';
import { YoYPage } from './pages/YoY';
import { CategoriesPage } from './pages/Categories';
import { CategoryDetailPage } from './pages/CategoryDetail';
import { MakersModelsPage } from './pages/MakersModels';
import { useQuery } from '@tanstack/react-query';
import { getRefreshStatus } from './api/vahan';

export default function App() {
  const { data } = useQuery({
    queryKey: ['refreshStatus'],
    queryFn: getRefreshStatus,
    refetchInterval: 120000,
  });

  return (
    <div className="flex h-screen overflow-hidden bg-[var(--bg-app)]">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden bg-[var(--bg-surface)]">
        <Header lastUpdated={data?.last_updated || null} />
        <main className="flex-1 overflow-y-auto">
          <Routes>
            <Route path="/" element={<OverviewPage />} />
            <Route path="/comparison" element={<ComparisonPage />} />
            <Route path="/yoy" element={<YoYPage />} />
            <Route path="/categories" element={<CategoriesPage />} />
            <Route path="/categories/:vehicleClass" element={<CategoryDetailPage />} />
            <Route path="/makers" element={<MakersModelsPage />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}