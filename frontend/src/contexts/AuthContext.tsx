import { createContext, useContext } from 'react';
import type { AuthUser } from '../api/auth';

export const AuthContext = createContext<AuthUser | null>(null);

// Only ever rendered inside App.tsx once `auth` is non-null (App shows the
// login page otherwise), so pages can assume this is always populated.
export function useAuth(): AuthUser {
  const auth = useContext(AuthContext);
  if (!auth) {
    throw new Error('useAuth() called outside an authenticated session');
  }
  return auth;
}
