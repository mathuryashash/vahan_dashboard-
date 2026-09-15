import { useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { useAppStore } from './useAppStore';

/** Pins the shared filter store to whatever this account is scoped to.
 *
 * Both axes are enforced server-side regardless (app/core/scope.py's
 * get_effective_state / get_effective_category), so this is purely about the
 * UI telling the truth: a control offering a choice the account doesn't have
 * reads as broken, and a stale filter value left in the store makes the page
 * look like it's showing something it isn't.
 *
 * Lives here rather than inside a page because it used to run only on
 * Overview -- a scoped user who landed on /makers directly (deep link,
 * refresh, or just clicking the sidebar first) never got locked at all, and
 * saw an editable "All Categories" dropdown sitting over segment-scoped data.
 * Called once from App so it applies on every route.
 *
 * The two axes are independent: an account can be locked to a state, to a
 * segment, to both, or to neither.
 */
export function useScopeLock() {
  const auth = useAuth();
  const { selectedState, setSelectedState, selectedCategory, setSelectedCategory } = useAppStore();

  const isStateLocked = auth.scope_type !== 'national';
  const isCategoryLocked = !!auth.scope_vehicle_category;

  useEffect(() => {
    if (isStateLocked && selectedState !== auth.scope_state_name) {
      setSelectedState(auth.scope_state_name);
    }
  }, [isStateLocked, auth.scope_state_name, selectedState, setSelectedState]);

  useEffect(() => {
    if (isCategoryLocked && selectedCategory !== auth.scope_vehicle_category) {
      setSelectedCategory(auth.scope_vehicle_category);
    }
  }, [isCategoryLocked, auth.scope_vehicle_category, selectedCategory, setSelectedCategory]);

  return { isStateLocked, isCategoryLocked, lockedCategory: auth.scope_vehicle_category };
}
