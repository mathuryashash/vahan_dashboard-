// frontend/src/hooks/useIsLiveData.ts
import { useQuery } from '@tanstack/react-query';
import { getScrapeProgress } from '../api/vahan';

/** Tracks the one-time synthetic -> live data migration (run out-of-band via
 * scraper/run_full_scrape.py, not through the refresh button). Shared by
 * App.tsx (feeds the header's migration progress bar) and useIsLiveData
 * (below) so there's one query definition, not two. Stops polling once
 * fully done. */
export function useScrapeProgress() {
  return useQuery({
    queryKey: ['scrapeProgress'],
    queryFn: getScrapeProgress,
    refetchInterval: (query) => (query.state.data && query.state.data.states_done >= query.state.data.states_total ? false : 15000),
  });
}

/** True once every state has been replaced with real scraped data (not
 * necessarily 100% of the analytical views, though — see PRODUCTION_HARDENING.md
 * for the Vehicle Class / Fuel dimensions, which lag the Maker dimension). */
export function useIsLiveData(): boolean {
  const { data } = useScrapeProgress();
  return !!data && data.states_done >= data.states_total;
}
