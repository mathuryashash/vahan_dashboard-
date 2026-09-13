import axios from 'axios';

export interface AuthUser {
  role: 'admin' | 'analyst' | 'viewer';
  email: string;
  full_name: string | null;
  scope_type: 'national' | 'state' | 'rto';
  scope_state_code: string | null;
  scope_state_name: string | null;
  scope_rto_code: string | null;
  scope_rto_name: string | null;
}

// The JWT itself lives only in an httpOnly cookie the backend sets on login
// (see auth.py) -- JS never sees or stores it, closing the XSS-can-steal-
// the-token gap a localStorage-held token had. Session state is rehydrated
// by asking the backend (the cookie, if any, goes along automatically),
// not by reading anything client-side.
export async function fetchCurrentUser(): Promise<AuthUser | null> {
  try {
    const { data } = await axios.get<AuthUser>('/api/v1/auth/me', { withCredentials: true });
    return data;
  } catch {
    return null;
  }
}

export async function login(email: string, password: string): Promise<AuthUser> {
  // /auth/login is OAuth2PasswordRequestForm -- form-encoded, not JSON.
  const body = new URLSearchParams({ username: email, password });
  const { data } = await axios.post<AuthUser>('/api/v1/auth/login', body, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    withCredentials: true,
  });
  return data;
}

export async function logout(): Promise<void> {
  // JS can't delete an httpOnly cookie itself -- only the backend can.
  await axios.post('/api/v1/auth/logout', null, { withCredentials: true }).catch(() => {});
}
