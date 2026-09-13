import { useEffect, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAppStore } from './useAppStore';

const PARAM_KEYS = ['year', 'month', 'state', 'category', 'fuel', 'maker'] as const;

/** Two-way sync between the shared filter store and the URL's query string,
 * mounted once at the app root. Without this, refreshing the page or
 * sharing a link always lands back on the default (unfiltered) view --
 * every filter selection lived only in the in-memory zustand store.
 *
 * Hydrates once from whatever's in the URL on first mount, then keeps the
 * URL in sync on every subsequent filter change via replaceState (not a
 * new history entry per filter tweak -- the back button should undo page
 * navigation, not every dropdown click). */
export function useUrlSyncedFilters() {
  const [searchParams, setSearchParams] = useSearchParams();
  const hydrated = useRef(false);

  const year = useAppStore((s) => s.selectedYear);
  const month = useAppStore((s) => s.selectedMonth);
  const state = useAppStore((s) => s.selectedState);
  const category = useAppStore((s) => s.selectedCategory);
  const fuelGroup = useAppStore((s) => s.fuelGroup);
  const maker = useAppStore((s) => s.selectedMaker);
  const setSelectedYear = useAppStore((s) => s.setSelectedYear);
  const setSelectedMonth = useAppStore((s) => s.setSelectedMonth);
  const setSelectedState = useAppStore((s) => s.setSelectedState);
  const setSelectedCategory = useAppStore((s) => s.setSelectedCategory);
  const setFuelGroup = useAppStore((s) => s.setFuelGroup);
  const setSelectedMaker = useAppStore((s) => s.setSelectedMaker);

  // Hydrate from the URL once, before anything writes back to it.
  useEffect(() => {
    if (hydrated.current) return;
    hydrated.current = true;
    const yearParam = searchParams.get('year');
    const monthParam = searchParams.get('month');
    if (yearParam) setSelectedYear(Number(yearParam));
    if (monthParam) setSelectedMonth(Number(monthParam));
    if (searchParams.get('state')) setSelectedState(searchParams.get('state'));
    if (searchParams.get('category')) setSelectedCategory(searchParams.get('category'));
    if (searchParams.get('fuel')) setFuelGroup(searchParams.get('fuel'));
    if (searchParams.get('maker')) setSelectedMaker(searchParams.get('maker'));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- URL read only on first mount, intentionally not re-running when searchParams itself changes (that would fight the write-back effect below)
  }, []);

  useEffect(() => {
    if (!hydrated.current) return;
    const next = new URLSearchParams();
    // PARAM_KEYS order kept deliberately, not alphabetical or insertion
    // order of the values below -- a stable, readable URL shape.
    const values: Record<(typeof PARAM_KEYS)[number], string | number | null> = {
      year, month, state, category, fuel: fuelGroup, maker,
    };
    for (const key of PARAM_KEYS) {
      const value = values[key];
      if (value !== null && value !== undefined) next.set(key, String(value));
    }
    setSearchParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- setSearchParams identity is stable per react-router, omitting it avoids an extra effect run it would otherwise trigger
  }, [year, month, state, category, fuelGroup, maker]);
}
