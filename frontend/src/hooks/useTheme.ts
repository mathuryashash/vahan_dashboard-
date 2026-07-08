// frontend/src/hooks/useTheme.ts
import { create } from 'zustand';

export type Theme = 'dark' | 'light';

const STORAGE_KEY = 'vahan-theme';

function applyThemeToDocument(theme: Theme) {
  if (theme === 'light') {
    document.documentElement.setAttribute('data-theme', 'light');
  } else {
    document.documentElement.removeAttribute('data-theme');
  }
}

function getInitialTheme(): Theme {
  const stored = localStorage.getItem(STORAGE_KEY);
  return stored === 'light' ? 'light' : 'dark';
}

interface ThemeState {
  theme: Theme;
  toggleTheme: () => void;
  setTheme: (theme: Theme) => void;
}

export const useTheme = create<ThemeState>((set, get) => ({
  theme: getInitialTheme(),
  toggleTheme: () => {
    const next: Theme = get().theme === 'dark' ? 'light' : 'dark';
    localStorage.setItem(STORAGE_KEY, next);
    applyThemeToDocument(next);
    set({ theme: next });
  },
  setTheme: (theme) => {
    localStorage.setItem(STORAGE_KEY, theme);
    applyThemeToDocument(theme);
    set({ theme });
  },
}));

// Apply immediately on module load so the correct theme is set before first paint.
applyThemeToDocument(getInitialTheme());
