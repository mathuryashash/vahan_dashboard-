import { useQuery } from '@tanstack/react-query';
import { getCategories } from '../api/vahan';

export interface CategoryRow {
  vehicle_category: string;
  total_count: number;
  share_percent: number;
  yoy_growth: number | null;
}

/** The ONE way to read `/categories/` (year, month, state).
 *
 * That endpoint is the slowest in the app (12-19 s cold, all-India). Five
 * call sites used to build their own query key for it -- Overview's Vehicle
 * Mix (`['categories', y, m, s, maker]`) and Category picker
 * (`['categoryOptions', y, m, s]`), FuelCategoryPanel's
 * `categoryMonthlyOnly` / `categoryYearOnly`, Categories/CategoryDetail's
 * `['categories', y, s]` and Comparison's `['categories', y]` -- so the same
 * request went out twice in parallel on every Overview year change, and again
 * on each tab. One key shape means one request per (year, month, state),
 * shared by every card on every page.
 *
 * `month`/`state` are normalised to null so `undefined` vs `null` can't split
 * the cache; axios drops both from the query string identically. */
export function useCategoriesQuery(
  { year, month = null, state = null }: { year: number; month?: number | null; state?: string | null },
  options: { enabled?: boolean } = {},
) {
  return useQuery<CategoryRow[]>({
    queryKey: ['categories', year, month ?? null, state || null] as const,
    queryFn: ({ signal }) => getCategories({ year, month: month ?? null, state: state || null }, signal),
    enabled: options.enabled ?? true,
  });
}
