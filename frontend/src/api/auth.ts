import axios from 'axios';

export interface AuthUser {
  access_token: string;
  token_type: string;
  role: 'admin' | 'analyst' | 'viewer';
  email: string;
  full_name: string | null;
  scope_type: 'national' | 'state' | 'rto';
  scope_state_code: string | null;
  scope_state_name: string | null;
  scope_rto_code: string | null;
  scope_rto_name: string | null;
}

const STORAGE_KEY = 'vahan_auth';

export function getStoredAuth(): AuthUser | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as AuthUser) : null;
  } catch {
    return null;
  }
}

export function setStoredAuth(auth: AuthUser | null) {
  if (auth) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(auth));
  } else {
    localStorage.removeItem(STORAGE_KEY);
  }
}

export async function login(email: string, password: string): Promise<AuthUser> {
  // /auth/login is OAuth2PasswordRequestForm -- form-encoded, not JSON.
  const body = new URLSearchParams({ username: email, password });
  const { data } = await axios.post<AuthUser>('/api/v1/auth/login', body, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  });
  setStoredAuth(data);
  return data;
}

export function logout() {
  setStoredAuth(null);
}
