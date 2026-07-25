# Dashboard Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current "sci-fi HUD" dark-only dashboard (neon glow shadows, pulsing dots, hardcoded hex colors) with a calm, professional "Automotive Editorial" design — charcoal/warm-white surfaces with a single amber accent, a real light/dark theme system, a 5-section sidebar, and a new Makers & Models page. Presentation-layer only: no backend changes, no new API endpoints, no changes to data-fetching logic.

**Architecture:** A CSS-variable theme (`:root` = dark defaults, `:root[data-theme="light"]` = overrides) drives all Tailwind arbitrary-value classes (`bg-[var(--bg-card)]` etc.) across every component. A small Zustand `useTheme` store toggles `data-theme` on `<html>` and persists the choice to `localStorage`. Because Recharts needs real hex strings (not CSS var references) for reliable SVG rendering, a parallel `theme/tokens.ts` JS module mirrors the CSS palette, and a `useChartTheme()` hook resolves the right one plus a deterministic per-series color function so the same maker/category is always the same color on every chart. Existing pages keep their exact data-fetching (`useQuery` + `api/vahan.ts` calls) — only markup, class names, and chart color props change.

**Tech Stack:** React 19, Tailwind CSS (arbitrary-value classes referencing CSS custom properties), Recharts, Zustand, existing `clsx`/`lucide`-free custom `Icons.tsx`.

**Confirmed decisions from brainstorming:**
- Visual direction: **Automotive Editorial** (charcoal `#1C1C1E` base, warm amber `#E0A458` accent) — not navy/neon, not light-first SaaS.
- 5 sidebar sections: **Overview · State Comparison · Year over Year · Categories & Fuel · Makers & Models**. The last is a new page; the other 4 map 1:1 to existing pages/routes.
- Default theme on first load: **dark**. Toggle lives in the top bar, persists to `localStorage`.
- No glow/box-shadow/neon effects, no decorative pulsing dots. Functional pulse (loading skeletons, a genuine "live" status dot) is kept — it's a real UX signal, not decoration.
- Chart conventions: trends = area/line, rankings = **horizontal** bar (not vertical — long maker/state names need the room), category/fuel share = donut capped at ~6 slices + "Other", state-vs-state = grouped horizontal bars.
- Every chart uses the same color for the same series name everywhere it appears (deterministic hash → palette index), replacing today's `COLORS[i % n]` index-based coloring which gives "Honda" a different color on every page.

---

## Task 1: Theme CSS foundation

**Files:**
- Modify: `frontend/src/index.css` (full rewrite)
- Modify: `frontend/index.html:7-10` (font tags + title)

Replaces the current single dark-only `:root` block and removes the glow/dot decorative utility classes (`.glow-text`, `.glow-card`, `.glow-card-primary`, `.bg-dots`, `.gradient-border`, `.bg-grid`) per the "no neon" design decision. Keeps `.animate-entrance` (functional entrance transition) and `.animate-pulse-glow` (renamed `.animate-pulse-soft`, used only for genuine live/loading indicators, not decoration).

- [ ] **Step 1: Rewrite `frontend/src/index.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

* { margin: 0; padding: 0; box-sizing: border-box; }

:root {
  /* Dark theme (default) — Automotive Editorial */
  --bg-app: #161618;
  --bg-surface: #1C1C1E;
  --bg-card: #242426;
  --bg-card-hover: #2C2C2E;
  --bg-sunken: #18181A;
  --border: rgba(255,255,255,0.08);
  --border-strong: rgba(255,255,255,0.16);
  --text-primary: #F5F5F7;
  --text-secondary: #A1A1A6;
  --text-muted: #8E8E93;
  --accent: #E0A458;
  --accent-strong: #F0C48A;
  --accent-contrast: #1C1C1E;
  --success: #6FCF97;
  --danger: #E5707A;
  --chart-1: #E0A458;
  --chart-2: #5FA8A3;
  --chart-3: #C97B84;
  --chart-4: #8FA37E;
  --chart-5: #7C93B3;
  --chart-6: #D9B44A;
}

:root[data-theme="light"] {
  --bg-app: #F4F1EC;
  --bg-surface: #FAF9F7;
  --bg-card: #FFFFFF;
  --bg-card-hover: #F4F1EC;
  --bg-sunken: #EFECE6;
  --border: rgba(28,28,30,0.10);
  --border-strong: rgba(28,28,30,0.18);
  --text-primary: #1C1C1E;
  --text-secondary: #4B4B4D;
  --text-muted: #7A7A7C;
  --accent: #B8681F;
  --accent-strong: #96551A;
  --accent-contrast: #FFFFFF;
  --success: #1F8A4C;
  --danger: #B83A46;
  --chart-1: #B8681F;
  --chart-2: #3E7A76;
  --chart-3: #A0525C;
  --chart-4: #5C7550;
  --chart-5: #4C6690;
  --chart-6: #A3811E;
}

body {
  font-family: 'Inter', system-ui, sans-serif;
  background-color: var(--bg-app);
  color: var(--text-primary);
  -webkit-font-smoothing: antialiased;
  transition: background-color 0.15s ease, color 0.15s ease;
}

::selection {
  background: var(--accent);
  color: var(--accent-contrast);
}

::-webkit-scrollbar {
  width: 5px;
  height: 5px;
}
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
  background: var(--border-strong);
  border-radius: 999px;
}
::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }

.animate-entrance {
  animation: entrance 0.4s ease-out forwards;
  opacity: 0;
}

@keyframes entrance {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

.animate-pulse-soft {
  animation: pulseSoft 2.5s ease-in-out infinite;
}

@keyframes pulseSoft {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 1; }
}

.number-display {
  font-family: 'JetBrains Mono', monospace;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.01em;
}

@layer utilities {
  .font-mono {
    font-family: 'JetBrains Mono', monospace;
  }
}
```

- [ ] **Step 2: Update page title in `frontend/index.html`**

Find:
```html
    <title>VAHAN Dashboard — Vehicle Analytics</title>
```
Replace with (unchanged — already accurate, no edit needed; confirm it still reads this on inspection). No change required for this file — font links already load Inter + JetBrains Mono correctly, which Step 1 now actually uses (previously `body` referenced `'Space Grotesk'`, a font that was never loaded by the `<link>` tag and was silently falling back to system-ui the whole time).

- [ ] **Step 3: Verify no build errors**

Run: `cd frontend && npm run build`
Expected: build succeeds (no components reference the removed `.glow-*`/`.bg-dots`/`.bg-grid`/`.animate-pulse-glow` classes yet — those references get removed in later tasks, so expect this to still succeed since Tailwind doesn't fail on unknown custom classes, only on invalid arbitrary-value syntax).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/index.css
git commit -m "feat: replace dark-only glow theme with dark/light CSS variable system"
```

---

## Task 2: Theme store, chart color tokens, and theme toggle

**Files:**
- Create: `frontend/src/hooks/useTheme.ts`
- Create: `frontend/src/theme/tokens.ts`
- Create: `frontend/src/hooks/useChartTheme.ts`
- Create: `frontend/src/components/ThemeToggle.tsx`
- Modify: `frontend/src/components/Icons.tsx` (add Sun/Moon icons)

- [ ] **Step 1: Create the theme store**

```typescript
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
```

- [ ] **Step 2: Create the JS-side color tokens (for Recharts, which needs real hex strings, not CSS var references)**

```typescript
// frontend/src/theme/tokens.ts
import type { Theme } from '../hooks/useTheme';

export interface ChartPalette {
  grid: string;
  axisText: string;
  tooltipBg: string;
  tooltipBorder: string;
  tooltipText: string;
  seriesColors: string[];
  success: string;
  danger: string;
}

const DARK: ChartPalette = {
  grid: 'rgba(255,255,255,0.06)',
  axisText: '#8E8E93',
  tooltipBg: '#242426',
  tooltipBorder: 'rgba(255,255,255,0.12)',
  tooltipText: '#F5F5F7',
  seriesColors: ['#E0A458', '#5FA8A3', '#C97B84', '#8FA37E', '#7C93B3', '#D9B44A'],
  success: '#6FCF97',
  danger: '#E5707A',
};

const LIGHT: ChartPalette = {
  grid: 'rgba(28,28,30,0.08)',
  axisText: '#7A7A7C',
  tooltipBg: '#FFFFFF',
  tooltipBorder: 'rgba(28,28,30,0.14)',
  tooltipText: '#1C1C1E',
  seriesColors: ['#B8681F', '#3E7A76', '#A0525C', '#5C7550', '#4C6690', '#A3811E'],
  success: '#1F8A4C',
  danger: '#B83A46',
};

export function getChartPalette(theme: Theme): ChartPalette {
  return theme === 'light' ? LIGHT : DARK;
}

/** Deterministic string hash -> stable palette index, so "Honda" is always
 * the same color on every chart it appears on, regardless of sort order. */
export function seriesColor(palette: ChartPalette, name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  }
  return palette.seriesColors[hash % palette.seriesColors.length];
}

/** Caps a donut/pie dataset at maxSlices, folding the remainder into an "Other"
 * slice — a 12-slice pie is unreadable regardless of theme. Assumes input is
 * already sorted descending by value (true for every category/fuel endpoint here). */
export function capForDonut<T extends { name: string; value: number }>(data: T[], maxSlices = 6): T[] {
  if (data.length <= maxSlices) return data;
  const kept = data.slice(0, maxSlices - 1);
  const rest = data.slice(maxSlices - 1);
  const otherValue = rest.reduce((sum, d) => sum + d.value, 0);
  return [...kept, { name: 'Other', value: otherValue } as T];
}
```

- [ ] **Step 3: Create the chart theme hook**

```typescript
// frontend/src/hooks/useChartTheme.ts
import { useTheme } from './useTheme';
import { getChartPalette, seriesColor, type ChartPalette } from '../theme/tokens';

export function useChartTheme(): ChartPalette & { seriesColor: (name: string) => string } {
  const theme = useTheme((s) => s.theme);
  const palette = getChartPalette(theme);
  return { ...palette, seriesColor: (name: string) => seriesColor(palette, name) };
}
```

- [ ] **Step 4: Add Sun/Moon icons**

Append to `frontend/src/components/Icons.tsx` (after the existing `ArrowLeft` export, keeping the same style):

```typescript
export function Sun({ className = 'w-5 h-5' }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="4"/>
      <line x1="12" y1="2" x2="12" y2="4"/>
      <line x1="12" y1="20" x2="12" y2="22"/>
      <line x1="4.93" y1="4.93" x2="6.34" y2="6.34"/>
      <line x1="17.66" y1="17.66" x2="19.07" y2="19.07"/>
      <line x1="2" y1="12" x2="4" y2="12"/>
      <line x1="20" y1="12" x2="22" y2="12"/>
      <line x1="4.93" y1="19.07" x2="6.34" y2="17.66"/>
      <line x1="17.66" y1="6.34" x2="19.07" y2="4.93"/>
    </svg>
  );
}

export function Moon({ className = 'w-5 h-5' }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
    </svg>
  );
}
```

- [ ] **Step 5: Create the ThemeToggle component**

```tsx
// frontend/src/components/ThemeToggle.tsx
import { useTheme } from '../hooks/useTheme';
import { Sun, Moon } from './Icons';

export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === 'dark';

  return (
    <button
      onClick={toggleTheme}
      aria-label={`Switch to ${isDark ? 'light' : 'dark'} mode`}
      className="w-8 h-8 rounded-lg flex items-center justify-center transition-colors hover:bg-[var(--bg-card-hover)] text-[var(--text-secondary)]"
    >
      {isDark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
    </button>
  );
}
```

- [ ] **Step 6: Verify build**

Run: `cd frontend && npm run build`
Expected: succeeds — these are new, unreferenced-yet files plus an additive change to `Icons.tsx`, so nothing existing breaks.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/hooks/useTheme.ts frontend/src/theme/tokens.ts frontend/src/hooks/useChartTheme.ts frontend/src/components/ThemeToggle.tsx frontend/src/components/Icons.tsx
git commit -m "feat: add theme store, chart color tokens, and theme toggle component"
```

---

## Task 3: Rebuild Sidebar (5 sections)

**Files:**
- Modify: `frontend/src/components/Sidebar.tsx` (full rewrite)

- [ ] **Step 1: Rewrite the sidebar with 5 nav sections and theme tokens**

```tsx
// frontend/src/components/Sidebar.tsx
import { NavLink } from 'react-router-dom';
import { LayoutDashboard, Map, TrendingUp, BarChart3, Car, ChevronLeft, ChevronRight } from './Icons';
import clsx from 'clsx';
import { useAppStore } from '../hooks/useAppStore';

const navItems = [
  { to: '/', icon: LayoutDashboard, label: 'Overview' },
  { to: '/comparison', icon: Map, label: 'State Comparison' },
  { to: '/yoy', icon: TrendingUp, label: 'Year over Year' },
  { to: '/categories', icon: BarChart3, label: 'Categories & Fuel' },
  { to: '/makers', icon: Car, label: 'Makers & Models' },
];

function NavItem({ to, icon: Icon, label, collapsed }: { to: string; icon: React.FC<{ className?: string }>; label: string; collapsed: boolean }) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      className={({ isActive }: { isActive: boolean }) =>
        clsx(
          'flex items-center gap-3 text-sm font-medium transition-all duration-150 relative rounded-lg mx-2',
          isActive
            ? 'bg-[var(--accent)] text-[var(--accent-contrast)]'
            : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-card-hover)]',
          collapsed ? 'justify-center px-2 py-2.5' : 'px-3 py-2.5'
        )
      }
    >
      <Icon className="w-4 h-4 shrink-0" />
      {!collapsed && <span className="text-xs tracking-wide">{label}</span>}
    </NavLink>
  );
}

export function Sidebar() {
  const { sidebarCollapsed, toggleSidebar } = useAppStore();

  return (
    <aside
      className={clsx(
        'flex flex-col transition-all duration-300 shrink-0 bg-[var(--bg-app)] border-r border-[var(--border)]',
        sidebarCollapsed ? 'w-14' : 'w-56'
      )}
    >
      <div className="px-4 py-5 border-b border-[var(--border)]">
        {!sidebarCollapsed && (
          <div className="animate-entrance">
            <p className="text-[10px] uppercase tracking-[0.2em] text-[var(--text-muted)] font-mono mb-0.5">Ministry of Road Transport</p>
            <p className="text-sm font-bold text-[var(--text-primary)] tracking-tight">VAHAN SEWA</p>
          </div>
        )}
        {sidebarCollapsed && (
          <div className="w-6 h-6 rounded-md bg-[var(--accent)] mx-auto" />
        )}
      </div>

      <nav className="flex-1 py-3 space-y-1">
        {navItems.map(({ to, icon: Icon, label }) => (
          <NavItem key={to} to={to} icon={Icon} label={label} collapsed={sidebarCollapsed} />
        ))}
      </nav>

      <div className="px-3 py-3 border-t border-[var(--border)]">
        <button
          onClick={toggleSidebar}
          className="w-full flex items-center justify-center py-1.5 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors rounded-lg hover:bg-[var(--bg-card-hover)]"
        >
          {sidebarCollapsed ? (
            <ChevronRight className="w-4 h-4" />
          ) : (
            <div className="flex items-center gap-2 text-[11px] font-mono text-[var(--text-muted)]">
              <ChevronLeft className="w-4 h-4" />
              <span>COLLAPSE</span>
            </div>
          )}
        </button>
      </div>
    </aside>
  );
}
```

Note: `Car` icon already exists in `Icons.tsx` from the original file — reused here for Makers & Models, no new icon needed for it.

- [ ] **Step 2: Verify build**

Run: `cd frontend && npm run build`
Expected: fails only if `/makers` route doesn't exist yet — that's fine, `NavLink` doesn't require the route to exist to render; TypeScript/Vite build should still succeed since this is just a `to` string prop.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Sidebar.tsx
git commit -m "feat: rebuild sidebar with 5 sections and theme tokens"
```

---

## Task 4: Rebuild Header (add theme toggle)

**Files:**
- Modify: `frontend/src/components/Header.tsx` (full rewrite)

- [ ] **Step 1: Rewrite the header**

```tsx
// frontend/src/components/Header.tsx
import { useQueryClient } from '@tanstack/react-query';
import { triggerRefresh } from '../api/vahan';
import { useState } from 'react';
import { ThemeToggle } from './ThemeToggle';

interface HeaderProps {
  lastUpdated: string | null;
}

export function Header({ lastUpdated }: HeaderProps) {
  const queryClient = useQueryClient();
  const [refreshing, setRefreshing] = useState(false);

  const handleRefresh = async () => {
    setRefreshing(true);
    await triggerRefresh();
    setTimeout(() => {
      queryClient.invalidateQueries();
      setRefreshing(false);
    }, 2000);
  };

  return (
    <header className="h-14 border-b border-[var(--border)] bg-[var(--bg-surface)] flex items-center justify-between px-6 shrink-0">
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-[var(--accent)] flex items-center justify-center">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--accent-contrast)" strokeWidth="2.5" strokeLinecap="round">
            <circle cx="12" cy="12" r="10" />
            <line x1="2" y1="12" x2="22" y2="12" />
            <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
          </svg>
        </div>
        <div>
          <h1 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">VAHAN SEWA</h1>
          <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest">Vehicle Analytics Observatory</p>
        </div>
      </div>

      <div className="flex items-center gap-3">
        {lastUpdated && (
          <div className="flex items-center gap-1.5 text-[11px] text-[var(--text-muted)] font-mono">
            <div className="w-1.5 h-1.5 rounded-full bg-[var(--success)] animate-pulse-soft" />
            <span>SYNC {lastUpdated}</span>
          </div>
        )}

        <button
          onClick={handleRefresh}
          disabled={refreshing}
          className="flex items-center gap-2 px-3 py-1.5 bg-[var(--bg-card)] hover:bg-[var(--bg-card-hover)] border border-[var(--border)] text-[var(--text-secondary)] text-xs font-semibold rounded-lg transition-all duration-200 disabled:opacity-50"
        >
          <svg
            className={refreshing ? 'animate-spin' : ''}
            width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"
          >
            <path d="M21 12a9 9 0 0 1-9 9m0 0a9 9 0 0 1-9-9m9 9v-4m0-8H5a4 4 0 0 0-4 4v4a4 4 0 0 0 4 4h4" />
          </svg>
          {refreshing ? 'SYNCING...' : 'REFRESH'}
        </button>

        <div className="w-px h-5 bg-[var(--border)]" />

        <ThemeToggle />
      </div>
    </header>
  );
}
```

- [ ] **Step 2: Remove the now-unused `bg-grid` wrapper class in `App.tsx`**

Read `frontend/src/App.tsx` (current content shown below for reference) and make the one-line change:

Find:
```tsx
      <div className="flex-1 flex flex-col overflow-hidden bg-grid">
```
Replace with:
```tsx
      <div className="flex-1 flex flex-col overflow-hidden bg-[var(--bg-surface)]">
```

Also find:
```tsx
    <div className="flex h-screen overflow-hidden bg-[#070D1A]">
```
Replace with:
```tsx
    <div className="flex h-screen overflow-hidden bg-[var(--bg-app)]">
```

- [ ] **Step 3: Verify build**

Run: `cd frontend && npm run build`
Expected: succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Header.tsx frontend/src/App.tsx
git commit -m "feat: add theme toggle to header, migrate App shell to theme tokens"
```

---

## Task 5: Migrate KPICard, delete dead KPICardEnhanced

**Files:**
- Modify: `frontend/src/components/KPICard.tsx` (full rewrite)
- Delete: `frontend/src/components/KPICardEnhanced.tsx`

`KPICardEnhanced.tsx` is unused dead code (confirmed via `grep` — no file imports it; only `KPICard.tsx` is actually used, from `Overview.tsx`). Rather than maintaining two divergent card components, this deletes the duplicate and upgrades the one that's actually used.

- [ ] **Step 1: Delete the unused duplicate**

```bash
git rm frontend/src/components/KPICardEnhanced.tsx
```

- [ ] **Step 2: Rewrite `KPICard.tsx` with theme tokens**

```tsx
// frontend/src/components/KPICard.tsx
import clsx from 'clsx';

interface KPICardProps {
  label: string;
  value: number | string;
  change?: number;
  icon?: React.ReactNode;
  loading?: boolean;
  index?: number;
}

export function KPICard({ label, value, change, icon, loading, index = 0 }: KPICardProps) {
  if (loading) {
    return (
      <div
        className="bg-[var(--bg-card)] rounded-2xl p-5 border border-[var(--border)] animate-entrance"
        style={{ animationDelay: `${index * 80}ms` }}
      >
        <div className="h-3 w-20 rounded bg-[var(--bg-sunken)] mb-4 animate-pulse-soft" />
        <div className="h-9 w-32 rounded bg-[var(--bg-sunken)] mb-3 animate-pulse-soft" />
        <div className="h-3 w-16 rounded bg-[var(--bg-sunken)] animate-pulse-soft" />
      </div>
    );
  }

  return (
    <div
      className="bg-[var(--bg-card)] rounded-2xl p-5 border border-[var(--border)] group animate-entrance transition-colors duration-200 hover:border-[var(--border-strong)]"
      style={{ animationDelay: `${index * 80}ms` }}
    >
      <div className="flex items-center justify-between mb-4">
        <span className="text-[11px] uppercase tracking-[0.15em] font-semibold text-[var(--text-muted)]">{label}</span>
        {icon && (
          <div className="w-9 h-9 rounded-xl flex items-center justify-center bg-[var(--bg-sunken)] text-[var(--accent)]">
            {icon}
          </div>
        )}
      </div>
      <div className="number-display text-3xl font-bold text-[var(--text-primary)] mb-2">
        {typeof value === 'number' ? value.toLocaleString('en-IN') : value}
      </div>
      {change !== undefined && (
        <div
          className="text-xs font-semibold px-2.5 py-1 rounded-lg inline-flex items-center gap-1 font-mono"
          style={{
            background: change >= 0 ? 'color-mix(in srgb, var(--success) 15%, transparent)' : 'color-mix(in srgb, var(--danger) 15%, transparent)',
            color: change >= 0 ? 'var(--success)' : 'var(--danger)',
          }}
        >
          <span className="text-[10px]">{change >= 0 ? '▲' : '▼'}</span>
          {Math.abs(change).toFixed(1)}%
        </div>
      )}
    </div>
  );
}
```

Note: `color-mix()` has broad modern browser support (Chrome/Edge 111+, Firefox 113+, Safari 16.4+) and lets a themed color get a translucent background without a second set of pre-mixed CSS variables. If the project needs older-browser support, replace the two `color-mix(...)` values with two extra CSS variables (`--success-bg`, `--danger-bg`) defined alongside `--success`/`--danger` in `index.css` instead — flag this to the user if `npm run build`'s browserslist warns about it.

- [ ] **Step 3: Verify build**

Run: `cd frontend && npm run build`
Expected: succeeds. `Overview.tsx` still passes an `accent` prop to `KPICard` at this point (Task 8 removes it) — TypeScript will error on the extra prop since it's no longer in `KPICardProps`. If so, this step's build failure is expected and resolved by Task 8; note it and continue, or reorder to do Task 8 immediately after this task if running sequentially without stopping.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/KPICard.tsx
git commit -m "feat: migrate KPICard to theme tokens, delete unused KPICardEnhanced duplicate"
```

---

## Task 6: Migrate EmptyState and ErrorBanner to theme tokens

**Files:**
- Modify: `frontend/src/components/EmptyState.tsx`
- Modify: `frontend/src/components/ErrorBanner.tsx`

Both are currently unused but light-theme-hardcoded (`bg-white`, `text-slate-900`, etc.) — kept as reusable components (their prop APIs are already reasonable) but converted to theme tokens so they're consistent and usable if/when a page needs them (e.g. "no data for this filter combination").

- [ ] **Step 1: Update `EmptyState.tsx`'s variant styles**

Find (in `getVariantStyles`):
```typescript
      case 'error':
        return {
          iconColor: 'text-rose-600',
          titleColor: 'text-slate-900',
          descColor: 'text-slate-600',
        };
      case 'no-data':
        return {
          iconColor: 'text-amber-600',
          titleColor: 'text-slate-900',
          descColor: 'text-slate-600',
        };
      case 'search':
        return {
          iconColor: 'text-blue-400',
          titleColor: 'text-slate-900',
          descColor: 'text-slate-600',
        };
      case 'no-selection':
        return {
          iconColor: 'text-gray-400',
          titleColor: 'text-slate-900',
          descColor: 'text-slate-600',
        };
      default:
        return {
          iconColor: 'text-slate-400',
          titleColor: 'text-slate-900',
          descColor: 'text-slate-600',
        };
```
Replace with:
```typescript
      case 'error':
        return {
          iconColor: 'text-[var(--danger)]',
          titleColor: 'text-[var(--text-primary)]',
          descColor: 'text-[var(--text-secondary)]',
        };
      case 'no-data':
        return {
          iconColor: 'text-[var(--accent)]',
          titleColor: 'text-[var(--text-primary)]',
          descColor: 'text-[var(--text-secondary)]',
        };
      case 'search':
        return {
          iconColor: 'text-[var(--accent)]',
          titleColor: 'text-[var(--text-primary)]',
          descColor: 'text-[var(--text-secondary)]',
        };
      case 'no-selection':
        return {
          iconColor: 'text-[var(--text-muted)]',
          titleColor: 'text-[var(--text-primary)]',
          descColor: 'text-[var(--text-secondary)]',
        };
      default:
        return {
          iconColor: 'text-[var(--text-muted)]',
          titleColor: 'text-[var(--text-primary)]',
          descColor: 'text-[var(--text-secondary)]',
        };
```

- [ ] **Step 2: Update the two action buttons in `EmptyState.tsx`**

Find:
```tsx
              className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg font-medium text-sm hover:bg-blue-700 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
```
Replace with:
```tsx
              className="inline-flex items-center gap-2 px-4 py-2 bg-[var(--accent)] text-[var(--accent-contrast)] rounded-lg font-medium text-sm hover:opacity-90 transition-opacity focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
```

Find:
```tsx
              className="inline-flex items-center gap-2 px-4 py-2 border border-slate-300 text-slate-700 rounded-lg font-medium text-sm hover:bg-slate-50 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500"
```
Replace with:
```tsx
              className="inline-flex items-center gap-2 px-4 py-2 border border-[var(--border-strong)] text-[var(--text-secondary)] rounded-lg font-medium text-sm hover:bg-[var(--bg-card-hover)] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--border-strong)]"
```

- [ ] **Step 3: Update `ErrorBanner.tsx`'s severity styles**

Find the entire `getStyles` function body (all four `case` blocks plus `default`):
```typescript
    switch (severity) {
      case 'error':
        return {
          bg: 'bg-rose-50',
          border: 'border-rose-200',
          borderLeft: 'border-l-4 border-l-rose-600',
          icon: 'text-rose-600',
          title: 'text-rose-900',
          desc: 'text-rose-700',
          button: 'hover:bg-rose-100 focus-visible:ring-rose-500',
        };
      case 'warning':
        return {
          bg: 'bg-amber-50',
          border: 'border-amber-200',
          borderLeft: 'border-l-4 border-l-amber-600',
          icon: 'text-amber-600',
          title: 'text-amber-900',
          desc: 'text-amber-700',
          button: 'hover:bg-amber-100 focus-visible:ring-amber-500',
        };
      case 'info':
        return {
          bg: 'bg-blue-50',
          border: 'border-blue-200',
          borderLeft: 'border-l-4 border-l-blue-600',
          icon: 'text-blue-600',
          title: 'text-blue-900',
          desc: 'text-blue-700',
          button: 'hover:bg-blue-100 focus-visible:ring-blue-500',
        };
      case 'success':
        return {
          bg: 'bg-emerald-50',
          border: 'border-emerald-200',
          borderLeft: 'border-l-4 border-l-emerald-600',
          icon: 'text-emerald-600',
          title: 'text-emerald-900',
          desc: 'text-emerald-700',
          button: 'hover:bg-emerald-100 focus-visible:ring-emerald-500',
        };
      default:
        return {
          bg: 'bg-slate-50',
          border: 'border-slate-200',
          borderLeft: 'border-l-4 border-l-slate-600',
          icon: 'text-slate-600',
          title: 'text-slate-900',
          desc: 'text-slate-700',
          button: 'hover:bg-slate-100 focus-visible:ring-slate-500',
        };
    }
```
Replace with:
```typescript
    switch (severity) {
      case 'error':
        return {
          bg: 'bg-[var(--bg-card)]',
          border: 'border-[var(--border)]',
          borderLeft: 'border-l-4',
          borderLeftColor: { borderLeftColor: 'var(--danger)' },
          icon: 'text-[var(--danger)]',
          title: 'text-[var(--text-primary)]',
          desc: 'text-[var(--text-secondary)]',
          button: 'hover:bg-[var(--bg-card-hover)] focus-visible:ring-[var(--danger)]',
        };
      case 'warning':
        return {
          bg: 'bg-[var(--bg-card)]',
          border: 'border-[var(--border)]',
          borderLeft: 'border-l-4',
          borderLeftColor: { borderLeftColor: 'var(--accent)' },
          icon: 'text-[var(--accent)]',
          title: 'text-[var(--text-primary)]',
          desc: 'text-[var(--text-secondary)]',
          button: 'hover:bg-[var(--bg-card-hover)] focus-visible:ring-[var(--accent)]',
        };
      case 'info':
        return {
          bg: 'bg-[var(--bg-card)]',
          border: 'border-[var(--border)]',
          borderLeft: 'border-l-4',
          borderLeftColor: { borderLeftColor: 'var(--chart-5)' },
          icon: 'text-[var(--text-secondary)]',
          title: 'text-[var(--text-primary)]',
          desc: 'text-[var(--text-secondary)]',
          button: 'hover:bg-[var(--bg-card-hover)] focus-visible:ring-[var(--border-strong)]',
        };
      case 'success':
        return {
          bg: 'bg-[var(--bg-card)]',
          border: 'border-[var(--border)]',
          borderLeft: 'border-l-4',
          borderLeftColor: { borderLeftColor: 'var(--success)' },
          icon: 'text-[var(--success)]',
          title: 'text-[var(--text-primary)]',
          desc: 'text-[var(--text-secondary)]',
          button: 'hover:bg-[var(--bg-card-hover)] focus-visible:ring-[var(--success)]',
        };
      default:
        return {
          bg: 'bg-[var(--bg-card)]',
          border: 'border-[var(--border)]',
          borderLeft: 'border-l-4',
          borderLeftColor: { borderLeftColor: 'var(--text-muted)' },
          icon: 'text-[var(--text-muted)]',
          title: 'text-[var(--text-primary)]',
          desc: 'text-[var(--text-secondary)]',
          button: 'hover:bg-[var(--bg-card-hover)] focus-visible:ring-[var(--border-strong)]',
        };
    }
```

- [ ] **Step 4: Apply the new `borderLeftColor` inline style on the root element**

Find:
```tsx
      className={clsx(
        'animate-slideUp',
        styles.bg,
        styles.border,
        'border rounded-lg p-4 mb-4',
        className
      )}
      role="alert"
      aria-live="assertive"
      aria-label={`${severity}: ${title}`}
    >
```
Replace with:
```tsx
      className={clsx(
        'animate-entrance',
        styles.bg,
        styles.border,
        styles.borderLeft,
        'border rounded-lg p-4 mb-4',
        className
      )}
      style={styles.borderLeftColor}
      role="alert"
      aria-live="assertive"
      aria-label={`${severity}: ${title}`}
    >
```

Note: this also fixes a pre-existing bug — `animate-slideUp` was referenced but never defined anywhere in `index.css` (dead class reference); replaced with the real `animate-entrance` utility that Task 1 keeps.

- [ ] **Step 5: Verify build**

Run: `cd frontend && npm run build`
Expected: succeeds.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/EmptyState.tsx frontend/src/components/ErrorBanner.tsx
git commit -m "fix: migrate EmptyState/ErrorBanner to theme tokens, fix dead animate-slideUp reference"
```

---

## Task 7: Migrate Overview page

**Files:**
- Modify: `frontend/src/pages/Overview.tsx` (full rewrite)

Converts all hardcoded colors to theme tokens, switches chart colors to `useChartTheme()`, removes the decorative pulsing "LIVE DATA" dot's glow (keeps a plain static dot — the pulse is reserved for genuinely-loading states per the design decision), and removes the `accent`/gradient-glow props from `KPICard` usage to match Task 5's simplified API.

- [ ] **Step 1: Rewrite `frontend/src/pages/Overview.tsx`**

```tsx
// frontend/src/pages/Overview.tsx
import { useQuery } from '@tanstack/react-query';
import {
  AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, TooltipProps, ResponsiveContainer
} from 'recharts';
import { TrendingUp, Award, Car, Bike } from '../components/Icons';
import { KPICard } from '../components/KPICard';
import { getKPIs, getTrend, getStateRanking, getCategories, getStates, getTopMakers, getModelBreakdown } from '../api/vahan';
import { useAppStore } from '../hooks/useAppStore';
import { useChartTheme } from '../hooks/useChartTheme';
import { capForDonut } from '../theme/tokens';

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const VEHICLE_CLASSES = [
  "Two-Wheeler",
  "Motor Car/Jeep/Taxi",
  "Mini Bus",
  "Bus",
  "Three-Wheeler",
  "Light Motor Vehicle",
  "Medium Bus",
  "Medium Truck",
  "Heavy Truck",
  "Tractor",
  "Construction Equipment",
  "Other"
];

function CustomTooltip({ active, payload, label, chart }: TooltipProps<number, string> & { chart: ReturnType<typeof useChartTheme> }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl px-3 py-2.5" style={{ background: chart.tooltipBg, border: `1px solid ${chart.tooltipBorder}` }}>
      <p className="text-[10px] uppercase tracking-widest mb-1" style={{ color: chart.axisText }}>{label}</p>
      <p className="font-mono text-base font-bold" style={{ color: chart.tooltipText }}>{payload[0].value?.toLocaleString('en-IN')}</p>
      <p className="text-[10px]" style={{ color: chart.axisText }}>registrations</p>
    </div>
  );
}

export function OverviewPage() {
  const chart = useChartTheme();
  const {
    selectedYear,
    selectedMonth,
    selectedState,
    selectedCategory,
    selectedMaker,
    selectedModel,
    setSelectedYear,
    setSelectedMonth,
    setSelectedState,
    setSelectedCategory,
    setSelectedMaker,
    setSelectedModel,
  } = useAppStore();

  const { data: statesList } = useQuery({ queryKey: ['states'], queryFn: getStates });

  const { data: kpis, isLoading: kpisLoading } = useQuery({
    queryKey: ['kpis', selectedYear, selectedMonth, selectedState, selectedCategory, selectedMaker, selectedModel],
    queryFn: () => getKPIs({
      year: selectedYear,
      month: selectedMonth,
      state: selectedState,
      vehicle_class: selectedCategory,
      maker: selectedMaker,
      vehicle_model: selectedModel
    }),
  });

  const { data: trend, isLoading: trendLoading } = useQuery({
    queryKey: ['trend', selectedYear, selectedMonth, selectedState, selectedCategory, selectedMaker, selectedModel],
    queryFn: () => getTrend({
      year: selectedYear,
      month: selectedMonth,
      state: selectedState,
      vehicle_class: selectedCategory,
      maker: selectedMaker,
      vehicle_model: selectedModel
    }),
  });

  const { data: ranking, isLoading: rankingLoading } = useQuery({
    queryKey: ['stateRanking', selectedYear, selectedMonth, selectedState, selectedCategory, selectedMaker, selectedModel],
    queryFn: () => getStateRanking({
      year: selectedYear,
      month: selectedMonth,
      state: selectedState,
      vehicle_class: selectedCategory,
      maker: selectedMaker,
      vehicle_model: selectedModel,
      limit: 10
    }),
  });

  const { data: categories, isLoading: categoriesLoading } = useQuery({
    queryKey: ['categories', selectedYear, selectedMonth, selectedState, selectedMaker, selectedModel],
    queryFn: () => getCategories({
      year: selectedYear,
      month: selectedMonth,
      state: selectedState,
      maker: selectedMaker,
      vehicle_model: selectedModel
    }),
  });

  const { data: makers } = useQuery({
    queryKey: ['makers', selectedCategory, selectedYear, selectedMonth, selectedState],
    queryFn: () => getTopMakers({
      vehicle_class: selectedCategory,
      year: selectedYear,
      month: selectedMonth,
      state: selectedState,
      limit: 30
    }),
  });

  const { data: models, isLoading: modelsLoading } = useQuery({
    queryKey: ['models', selectedCategory, selectedMaker, selectedYear, selectedMonth, selectedState],
    queryFn: () => getModelBreakdown({
      vehicle_class: selectedCategory,
      maker: selectedMaker,
      year: selectedYear,
      month: selectedMonth,
      state: selectedState,
      limit: 15
    }),
  });

  const chartData = (trend || []).map((d: { month?: number; day?: number; count: number }) => {
    if (selectedMonth) {
      return { name: `Day ${d.day}`, count: d.count };
    }
    return { name: d.month ? MONTH_NAMES[d.month - 1] : '', count: d.count };
  });

  const pieData = capForDonut((categories || []).map((c: { vehicle_class: string; total_count: number }) => ({
    name: c.vehicle_class,
    value: c.total_count,
  })));

  const activeFiltersCount = [
    selectedState,
    selectedMonth,
    selectedCategory,
    selectedMaker,
    selectedModel
  ].filter(Boolean).length;

  const handleResetFilters = () => {
    setSelectedState(null);
    setSelectedMonth(null);
    setSelectedCategory(null);
    setSelectedMaker(null);
    setSelectedModel(null);
  };

  const selectClass = "w-full bg-[var(--bg-sunken)] border border-[var(--border)] hover:border-[var(--border-strong)] text-[var(--text-primary)] text-xs font-semibold px-3 py-2 rounded-xl focus:outline-none focus:ring-2 focus:ring-[var(--accent)] transition-all duration-200 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed";

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div className="animate-entrance">
          <h2 className="text-xl font-bold text-[var(--text-primary)] tracking-tight">
            Overview
          </h2>
          <p className="text-xs text-[var(--text-muted)] mt-0.5 font-mono uppercase tracking-widest">
            India Vehicle Registration Observatory — FY {selectedYear}
          </p>
        </div>
        <div className="flex items-center gap-4 text-[10px] text-[var(--text-muted)] font-mono">
          {activeFiltersCount > 0 && (
            <button
              onClick={handleResetFilters}
              className="text-xs text-[var(--accent)] hover:opacity-80 font-semibold transition-opacity bg-[var(--bg-card)] border border-[var(--border)] px-2.5 py-1 rounded-lg"
            >
              Reset Filters ({activeFiltersCount})
            </button>
          )}
          <div className="flex items-center gap-1.5">
            <div className="w-1.5 h-1.5 rounded-full bg-[var(--success)]" />
            <span>LIVE DATA</span>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-3 bg-[var(--bg-card)] border border-[var(--border)] p-4 rounded-2xl animate-entrance">
        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] uppercase font-mono tracking-widest text-[var(--text-muted)] font-bold">State</label>
          <select value={selectedState || ''} onChange={(e) => setSelectedState(e.target.value || null)} className={selectClass}>
            <option value="">All States</option>
            {(statesList || []).map((s: { state_name: string }) => (
              <option key={s.state_name} value={s.state_name}>{s.state_name}</option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] uppercase font-mono tracking-widest text-[var(--text-muted)] font-bold">Year</label>
          <select value={selectedYear} onChange={(e) => setSelectedYear(Number(e.target.value))} className={selectClass}>
            <option value={2024}>2024</option>
            <option value={2025}>2025</option>
            <option value={2026}>2026</option>
          </select>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] uppercase font-mono tracking-widest text-[var(--text-muted)] font-bold">Month</label>
          <select value={selectedMonth || ''} onChange={(e) => setSelectedMonth(e.target.value ? Number(e.target.value) : null)} className={selectClass}>
            <option value="">All Months</option>
            {MONTH_NAMES.map((name, idx) => (
              <option key={name} value={idx + 1}>{name}</option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] uppercase font-mono tracking-widest text-[var(--text-muted)] font-bold">Category</label>
          <select value={selectedCategory || ''} onChange={(e) => setSelectedCategory(e.target.value || null)} className={selectClass}>
            <option value="">All Categories</option>
            {VEHICLE_CLASSES.map((vc) => (
              <option key={vc} value={vc}>{vc}</option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] uppercase font-mono tracking-widest text-[var(--text-muted)] font-bold">OEM / Brand</label>
          <select value={selectedMaker || ''} onChange={(e) => setSelectedMaker(e.target.value || null)} className={selectClass}>
            <option value="">All Brands</option>
            {(makers || []).map((m: { maker: string }) => (
              <option key={m.maker} value={m.maker}>{m.maker}</option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] uppercase font-mono tracking-widest text-[var(--text-muted)] font-bold">Vehicle Model</label>
          <select value={selectedModel || ''} onChange={(e) => setSelectedModel(e.target.value || null)} disabled={!selectedMaker} className={selectClass}>
            <option value="">{selectedMaker ? 'All Models' : 'Select OEM first'}</option>
            {selectedMaker && (models || []).map((m: { model: string }) => (
              <option key={m.model} value={m.model}>{m.model}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <KPICard label="Total Registrations" value={kpis?.total_this_month ?? 0} change={kpis?.yoy_growth_percent} icon={<Car className="w-4 h-4" />} loading={kpisLoading} index={0} />
        <KPICard label="YoY Growth" value={kpis?.yoy_growth_percent ? `${kpis.yoy_growth_percent.toFixed(1)}%` : '—'} change={kpis?.yoy_growth_percent} icon={<TrendingUp className="w-4 h-4" />} loading={kpisLoading} index={1} />
        <KPICard label="Latest Day Sales" value={kpis?.total_registrations_today ?? 0} icon={<Bike className="w-4 h-4" />} loading={kpisLoading} index={2} />
        <KPICard label="Top State" value={kpis?.top_state ?? '—'} icon={<Award className="w-4 h-4" />} loading={kpisLoading} index={3} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div className="xl:col-span-2 bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '200ms' }}>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">
                {selectedMonth ? `${MONTH_NAMES[selectedMonth - 1]} Registration Trend` : 'Registration Trend'}
              </h3>
              <p className="text-[10px] text-[var(--text-muted)] font-mono mt-0.5">
                {selectedMonth ? `Daily View — ${MONTH_NAMES[selectedMonth - 1]} ${selectedYear}` : `Monthly View — FY ${selectedYear}`}
              </p>
            </div>
            <span className="text-[10px] font-mono px-2 py-1 rounded-md" style={{ color: chart.seriesColors[0], background: 'var(--bg-sunken)' }}>
              {selectedMonth ? 'DAILY' : 'MONTHLY'}
            </span>
          </div>
          {trendLoading ? (
            <div className="h-52 rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft" />
          ) : (
            <ResponsiveContainer width="100%" height={208}>
              <AreaChart data={chartData}>
                <defs>
                  <linearGradient id="gradAccent" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={chart.seriesColors[0]} stopOpacity={0.25} />
                    <stop offset="95%" stopColor={chart.seriesColors[0]} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} tickFormatter={(v: number) => v >= 1000000 ? `${(v/1000000).toFixed(1)}M` : v.toLocaleString('en-IN')} width={45} />
                <Tooltip content={<CustomTooltip chart={chart} />} />
                <Area type="monotone" dataKey="count" stroke={chart.seriesColors[0]} strokeWidth={2.5} fill="url(#gradAccent)" dot={selectedMonth ? false : { r: 3, fill: chart.seriesColors[0], strokeWidth: 0 }} activeDot={{ r: 5, fill: chart.seriesColors[0] }} />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '250ms' }}>
          <div className="mb-4">
            <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">Vehicle Mix</h3>
            <p className="text-[10px] text-[var(--text-muted)] font-mono mt-0.5">by category — {selectedYear}</p>
          </div>
          {categoriesLoading ? (
            <div className="h-52 rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft" />
          ) : (
            <>
              <ResponsiveContainer width="100%" height={160}>
                <PieChart>
                  <Pie data={pieData} cx="50%" cy="50%" innerRadius={45} outerRadius={75} paddingAngle={2} dataKey="value">
                    {pieData.map((p: { name: string }, i: number) => <Cell key={i} fill={chart.seriesColor(p.name)} />)}
                  </Pie>
                  <Tooltip formatter={(val: number) => [val.toLocaleString('en-IN'), '']} contentStyle={{ background: chart.tooltipBg, border: `1px solid ${chart.tooltipBorder}`, borderRadius: 8 }} />
                </PieChart>
              </ResponsiveContainer>
              <div className="mt-2 space-y-1.5 max-h-28 overflow-y-auto pr-1">
                {pieData.map((p: { name: string; value: number }, i: number) => (
                  <div key={i} className="flex items-center justify-between text-[11px]">
                    <div className="flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-sm" style={{ backgroundColor: chart.seriesColor(p.name) }} />
                      <span className="text-[var(--text-secondary)] truncate max-w-[100px]">{p.name}</span>
                    </div>
                    <span className="font-mono text-[var(--text-secondary)] font-semibold">{p.value?.toLocaleString('en-IN')}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '300ms' }}>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">State Ranking</h3>
              <p className="text-[10px] text-[var(--text-muted)] font-mono mt-0.5">Top 10 by registrations</p>
            </div>
          </div>
          {rankingLoading ? (
            <div className="h-44 rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft" />
          ) : (
            <div className="space-y-3 max-h-96 overflow-y-auto pr-1">
              {(ranking || []).map((s: { state_name: string; total_count: number; share_percent: number }, i: number) => {
                const max = (ranking || [])[0]?.total_count || 1;
                const pct = (s.total_count / max) * 100;
                const color = chart.seriesColor(s.state_name);
                return (
                  <div key={s.state_name} className="flex items-center gap-3 group cursor-pointer" onClick={() => setSelectedState(s.state_name)}>
                    <span className="font-mono text-[11px] font-bold text-[var(--text-muted)] w-4 text-right shrink-0">#{i + 1}</span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs font-semibold text-[var(--text-secondary)] group-hover:text-[var(--text-primary)] transition-colors">{s.state_name}</span>
                        <span className="font-mono text-[11px] text-[var(--text-muted)]">{s.share_percent?.toFixed(1)}%</span>
                      </div>
                      <div className="h-1.5 bg-[var(--bg-sunken)] rounded-full overflow-hidden">
                        <div className="h-full rounded-full transition-all duration-700 ease-out" style={{ width: `${pct}%`, backgroundColor: color }} />
                      </div>
                    </div>
                    <span className="font-mono text-[11px] font-bold text-[var(--text-secondary)] w-20 text-right shrink-0">
                      {s.total_count?.toLocaleString('en-IN')}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '350ms' }}>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">Top Vehicle Models</h3>
              <p className="text-[10px] text-[var(--text-muted)] font-mono mt-0.5">
                {selectedMaker ? `${selectedMaker} Models Breakdown` : 'Top Models Breakdown'}
              </p>
            </div>
            {selectedMaker && (
              <button onClick={() => setSelectedMaker(null)} className="text-[9px] uppercase font-mono tracking-wider text-[var(--accent)] hover:opacity-80 transition-opacity">
                Clear Brand
              </button>
            )}
          </div>
          {modelsLoading ? (
            <div className="h-44 rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft" />
          ) : (models || []).length === 0 ? (
            <div className="h-44 flex flex-col items-center justify-center text-[var(--text-muted)] text-xs border border-dashed border-[var(--border)] rounded-xl">
              <span>No vehicle models match the active filters</span>
              <span className="text-[10px] mt-1">Try selecting a different OEM or category</span>
            </div>
          ) : (
            <div className="space-y-3 max-h-96 overflow-y-auto pr-1">
              {(models || []).map((m: { model: string; count: number; share_percent: number }, i: number) => {
                const max = (models || [])[0]?.count || 1;
                const pct = (m.count / max) * 100;
                const color = chart.seriesColor(m.model);
                return (
                  <div key={m.model} className="flex items-center gap-3 group cursor-pointer" onClick={() => setSelectedModel(m.model)}>
                    <span className="font-mono text-[11px] font-bold text-[var(--text-muted)] w-4 text-right shrink-0">#{i + 1}</span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs font-semibold text-[var(--text-secondary)] group-hover:text-[var(--text-primary)] transition-colors">{m.model}</span>
                        <span className="font-mono text-[11px] text-[var(--text-muted)]">{m.share_percent?.toFixed(1)}%</span>
                      </div>
                      <div className="h-1.5 bg-[var(--bg-sunken)] rounded-full overflow-hidden">
                        <div className="h-full rounded-full transition-all duration-700 ease-out" style={{ width: `${pct}%`, backgroundColor: color }} />
                      </div>
                    </div>
                    <span className="font-mono text-[11px] font-bold text-[var(--text-secondary)] w-20 text-right shrink-0">
                      {m.count?.toLocaleString('en-IN')}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {[
          { label: 'States Active', value: '36 / 36', sub: 'All states reporting', colorIdx: 3 },
          { label: 'Avg per State', value: kpis ? Math.round(kpis.total_this_month / 36).toLocaleString('en-IN') : '—', sub: 'registrations per state', colorIdx: 0 },
          { label: 'Peak Trend Point', value: chartData.length > 0 ? chartData.reduce((a: { count: number }, b: { count: number }) => a.count > b.count ? a : b).name : '—', sub: 'highest volume time point', colorIdx: 5 },
        ].map((stat, i) => (
          <div key={i} className="bg-[var(--bg-card)] rounded-xl border border-[var(--border)] p-4 flex items-center gap-4 animate-entrance" style={{ animationDelay: `${350 + i * 60}ms` }}>
            <div className="w-1 h-10 rounded-full" style={{ background: chart.seriesColors[stat.colorIdx] }} />
            <div>
              <p className="text-[10px] uppercase tracking-widest text-[var(--text-muted)]">{stat.label}</p>
              <p className="font-mono text-lg font-bold" style={{ color: chart.seriesColors[stat.colorIdx] }}>{stat.value}</p>
              <p className="text-[10px] text-[var(--text-muted)]">{stat.sub}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

Run: `cd frontend && npm run build`
Expected: succeeds (this resolves the `KPICard` prop-mismatch flagged as expected in Task 5 Step 3).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/Overview.tsx
git commit -m "feat: migrate Overview page to theme tokens and consistent chart colors"
```

---

## Task 8: Migrate Comparison page

**Files:**
- Modify: `frontend/src/pages/Comparison.tsx` (full rewrite)

Per the "Chart conventions" design decision, State A/B now use `chart.seriesColor(stateName)` (deterministic, same color as that state gets anywhere else it's charted) instead of hardcoded blue/amber — since amber is now the primary accent color and would visually clash/confuse if reused as a plain series color here.

- [ ] **Step 1: Rewrite `frontend/src/pages/Comparison.tsx`**

```tsx
// frontend/src/pages/Comparison.tsx
import { useQuery } from '@tanstack/react-query';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, TooltipProps } from 'recharts';
import { useState } from 'react';
import { getStatesComparison, compareStates } from '../api/vahan';
import { useAppStore } from '../hooks/useAppStore';
import { useChartTheme } from '../hooks/useChartTheme';

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function StateTooltip({ active, payload, label, chart }: TooltipProps<number, string> & { chart: ReturnType<typeof useChartTheme> }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl px-3 py-2.5" style={{ background: chart.tooltipBg, border: `1px solid ${chart.tooltipBorder}` }}>
      <p className="text-[10px] uppercase tracking-widest mb-1" style={{ color: chart.axisText }}>{label}</p>
      {payload.map((p, i) => (
        <div key={i} className="flex items-center gap-2">
          <span className="text-[10px]" style={{ color: chart.axisText }}>{p.name}:</span>
          <span className="text-xs font-bold font-mono" style={{ color: chart.tooltipText }}>{p.value?.toLocaleString('en-IN')}</span>
        </div>
      ))}
    </div>
  );
}

export function ComparisonPage() {
  const chart = useChartTheme();
  const { selectedYear } = useAppStore();
  const [stateA, setStateA] = useState('Maharashtra');
  const [stateB, setStateB] = useState('Gujarat');
  const [focusState, setFocusState] = useState<string | null>(null);

  const { data: allStates } = useQuery({
    queryKey: ['states', selectedYear],
    queryFn: () => getStatesComparison(selectedYear, 36),
  });

  const { data: comparison } = useQuery({
    queryKey: ['compare', stateA, stateB, selectedYear],
    queryFn: () => compareStates(stateA, stateB, selectedYear),
    enabled: !!stateA,
  });

  const stateOptions = (allStates || []).map((s: { state_name: string }) => s.state_name);
  const aData = (comparison?.state_a_data || []).map((d: { month: number; count: number }) => ({ name: MONTH_NAMES[d.month - 1], [stateA]: d.count }));
  const bData = (comparison?.state_b_data || []).map((d: { month: number; count: number }) => ({ name: MONTH_NAMES[d.month - 1], [stateB]: d.count }));

  const merged = aData.map((d, i) => ({ ...d, ...(bData[i] || {}) }));

  const totalA = (comparison?.state_a_data || []).reduce((s: number, d: { count: number }) => s + d.count, 0);
  const totalB = (comparison?.state_b_data || []).reduce((s: number, d: { count: number }) => s + d.count, 0);

  const colorA = chart.seriesColor(stateA);
  const colorB = chart.seriesColor(stateB);

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div className="animate-entrance">
          <h2 className="text-xl font-bold text-[var(--text-primary)] tracking-tight">State Comparison</h2>
          <p className="text-xs text-[var(--text-muted)] mt-0.5 font-mono uppercase tracking-widest">
            Cross-state registration analysis — FY {selectedYear}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 animate-entrance" style={{ animationDelay: '40ms' }}>
        {[{ label: 'State A', value: stateA, setter: setStateA, color: colorA },
          { label: 'State B', value: stateB, setter: setStateB, color: colorB },
          { label: 'States Active', value: `${stateOptions.length || 0} / 36`, setter: () => {}, color: 'var(--success)' }
        ].map((s, i) => (
          <div key={i} className="bg-[var(--bg-card)] rounded-xl border border-[var(--border)] p-4">
            <p className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] font-mono mb-2">{s.label}</p>
            {i < 2 ? (
              <select
                value={s.value}
                onChange={(e) => s.setter(e.target.value)}
                className="w-full bg-[var(--bg-sunken)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm font-semibold text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)] transition-colors"
              >
                {stateOptions.map((opt: string) => <option key={opt} value={opt}>{opt}</option>)}
              </select>
            ) : (
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full" style={{ background: s.color }} />
                <span className="font-mono text-[var(--text-primary)] font-bold">{s.value}</span>
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 animate-entrance" style={{ animationDelay: '80ms' }}>
        {[{
          label: stateA, total: totalA, color: colorA,
        }, {
          label: stateB, total: totalB, color: colorB,
        }].map((card, i) => (
          <div key={i} className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5">
            <div className="flex items-center gap-3 mb-3">
              <div className="w-3 h-3 rounded-full" style={{ background: card.color }} />
              <span className="text-xs font-semibold text-[var(--text-secondary)]">{card.label}</span>
            </div>
            <div className="number-display text-2xl font-bold text-[var(--text-primary)] mb-1">{card.total?.toLocaleString('en-IN') || 0}</div>
            <p className="text-[11px] text-[var(--text-muted)] font-mono">
              Total registrations FY {selectedYear}
            </p>
          </div>
        ))}
      </div>

      <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '120ms' }}>
        <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight mb-4">{stateA} vs {stateB} — Monthly</h3>
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={merged} layout="vertical" barGap={6}>
            <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} horizontal={false} />
            <XAxis type="number" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${(v/1000).toFixed(0)}K`} />
            <YAxis dataKey="name" type="category" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} width={36} />
            <Tooltip content={<StateTooltip chart={chart} />} />
            <Bar dataKey={stateA} fill={colorA} radius={[0, 3, 3, 0]} maxBarSize={16} />
            <Bar dataKey={stateB} fill={colorB} radius={[0, 3, 3, 0]} maxBarSize={16} />
          </BarChart>
        </ResponsiveContainer>
        <div className="flex items-center justify-center gap-6 mt-3 text-[11px] font-mono">
          <span style={{ color: colorA }}>{stateA}</span>
          <span style={{ color: colorB }}>{stateB}</span>
        </div>
      </div>

      <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '160ms' }}>
        <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight mb-4">All States — Ranked</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
          {(allStates || []).map((s: { state_name: string; count: number; share_percent: number }, i: number) => (
            <div
              key={s.state_name}
              onClick={() => { setStateA(s.state_name); setFocusState(s.state_name); }}
              className="bg-[var(--bg-sunken)] rounded-lg px-3 py-2 cursor-pointer transition-all hover:bg-[var(--bg-card-hover)] border"
              style={{ borderColor: focusState === s.state_name ? 'var(--accent)' : 'transparent' }}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[10px] text-[var(--text-muted)] font-bold w-4">#{i + 1}</span>
                  <span className="text-xs text-[var(--text-secondary)]">{s.state_name}</span>
                </div>
                <div className="text-right">
                  <span className="font-mono text-[11px] font-bold text-[var(--text-primary)]">{s.count?.toLocaleString('en-IN')}</span>
                  <span className="font-mono text-[10px] text-[var(--text-muted)] ml-1">{s.share_percent?.toFixed(1)}%</span>
                </div>
              </div>
              <div className="mt-1.5 h-0.5 bg-[var(--bg-card)] rounded-full overflow-hidden">
                <div className="h-full rounded-full" style={{ width: `${s.share_percent}%`, background: chart.seriesColor(s.state_name) }} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
```

Note: the comparison bar chart switched from vertical to horizontal layout per the "rankings/comparisons read better horizontal" convention from the design.

- [ ] **Step 2: Verify build**

Run: `cd frontend && npm run build`
Expected: succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/Comparison.tsx
git commit -m "feat: migrate Comparison page to theme tokens and horizontal chart layout"
```

---

## Task 9: Migrate Year-over-Year page

**Files:**
- Modify: `frontend/src/pages/YoY.tsx` (full rewrite)

- [ ] **Step 1: Rewrite `frontend/src/pages/YoY.tsx`**

```tsx
// frontend/src/pages/YoY.tsx
import { useQuery } from '@tanstack/react-query';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, LineChart, Line, TooltipProps
} from 'recharts';
import { useAppStore } from '../hooks/useAppStore';
import { getYoYMonthly, getYoYSummary } from '../api/vahan';
import { useChartTheme } from '../hooks/useChartTheme';

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function YoYTooltip({ active, payload, label, chart }: TooltipProps<number, string> & { chart: ReturnType<typeof useChartTheme> }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl px-3 py-2.5" style={{ background: chart.tooltipBg, border: `1px solid ${chart.tooltipBorder}` }}>
      <p className="text-[10px] uppercase tracking-widest mb-2" style={{ color: chart.axisText }}>{label}</p>
      {payload.map((p, i) => (
        <div key={i} className="flex items-center gap-2 mb-1">
          <div className="w-2 h-2 rounded-sm" style={{ background: p.fill }} />
          <span className="text-[11px] font-mono" style={{ color: chart.axisText }}>{p.name}:</span>
          <span className="text-xs font-bold font-mono" style={{ color: chart.tooltipText }}>{p.value?.toLocaleString('en-IN')}</span>
        </div>
      ))}
    </div>
  );
}

export function YoYPage() {
  const chart = useChartTheme();
  const { comparisonYearA, comparisonYearB } = useAppStore();

  const { data: monthly, isLoading } = useQuery({
    queryKey: ['yoy', comparisonYearA, comparisonYearB],
    queryFn: () => getYoYMonthly(comparisonYearA, comparisonYearB),
  });

  const { data: summary } = useQuery({
    queryKey: ['yoySummary', comparisonYearA, comparisonYearB],
    queryFn: () => getYoYSummary(comparisonYearA, comparisonYearB),
  });

  const chartData = (monthly?.data || []).map((d: { month: number; [key: string]: number }) => ({
    name: MONTH_NAMES[d.month - 1],
    [`${comparisonYearA}`]: d[`year_${comparisonYearA}`],
    [`${comparisonYearB}`]: d[`year_${comparisonYearB}`],
    growth: d.growth_percent,
  }));

  const growth = summary?.growth_percent ?? 0;
  const colorA = chart.seriesColors[4];
  const colorB = chart.seriesColors[0];

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div className="animate-entrance">
          <h2 className="text-xl font-bold text-[var(--text-primary)] tracking-tight">Year-over-Year Analysis</h2>
          <p className="text-xs text-[var(--text-muted)] mt-0.5 font-mono uppercase tracking-widest">
            Temporal comparison — {comparisonYearA} vs {comparisonYearB}
          </p>
        </div>
        <div className="flex items-center gap-3 animate-entrance" style={{ animationDelay: '50ms' }}>
          <div className="px-3 py-1.5 rounded-lg border text-xs font-mono font-semibold border-[var(--border)] text-[var(--text-secondary)]">
            {comparisonYearA} <span className="text-[var(--text-muted)] mx-1">→</span>
            <span className="text-[var(--text-primary)] font-mono">{(summary?.[`total_${comparisonYearA}`] || 0).toLocaleString('en-IN')}</span>
          </div>
          <div className="px-3 py-1.5 rounded-lg border text-xs font-mono font-semibold" style={{ background: 'var(--bg-sunken)', borderColor: 'var(--border)', color: 'var(--accent)' }}>
            {comparisonYearB} <span className="text-[var(--text-muted)] mx-1">→</span>
            <span className="text-[var(--text-primary)] font-mono">{(summary?.[`total_${comparisonYearB}`] || 0).toLocaleString('en-IN')}</span>
          </div>
          <div
            className="px-3 py-1.5 rounded-lg text-xs font-bold font-mono border"
            style={{
              background: 'var(--bg-sunken)',
              color: growth >= 0 ? 'var(--success)' : 'var(--danger)',
              borderColor: 'var(--border)',
            }}
          >
            {growth >= 0 ? '+' : ''}{growth.toFixed(1)}%
          </div>
        </div>
      </div>

      <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '80ms' }}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">Monthly Volume Comparison</h3>
          <div className="flex items-center gap-4 text-[11px] font-mono">
            <span className="flex items-center gap-1.5"><span className="w-3 h-0.5 rounded-full inline-block" style={{ background: colorA }} /> {comparisonYearA}</span>
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm inline-block" style={{ background: colorB }} /> {comparisonYearB}</span>
          </div>
        </div>
        {isLoading ? <div className="h-64 rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft" /> : (
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={chartData} barGap={4}>
              <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} vertical={false} />
              <XAxis dataKey="name" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${(v/1000000).toFixed(1)}M`} width={40} />
              <Tooltip content={<YoYTooltip chart={chart} />} />
              <Bar dataKey={`${comparisonYearA}`} fill={colorA} radius={[3, 3, 0, 0]} maxBarSize={20} />
              <Bar dataKey={`${comparisonYearB}`} fill={colorB} radius={[3, 3, 0, 0]} maxBarSize={20} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '130ms' }}>
          <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight mb-4">Month-wise Growth Rate</h3>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={chartData} layout="vertical">
              <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} horizontal={false} />
              <XAxis type="number" domain={[-50, 50]} tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${v}%`} />
              <YAxis dataKey="name" type="category" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} width={30} axisLine={false} tickLine={false} />
              <Tooltip formatter={(val: number) => [`${val?.toFixed(1)}%`, 'Growth']} contentStyle={{ background: chart.tooltipBg, border: `1px solid ${chart.tooltipBorder}`, borderRadius: 8 }} />
              <Bar dataKey="growth" radius={[0, 3, 3, 0]} maxBarSize={14}>
                {chartData.map((d: { growth: number }, i: number) => (
                  <Cell key={i} fill={d.growth >= 0 ? chart.success : chart.danger} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <div className="flex items-center justify-center gap-4 mt-3 text-[10px] font-mono">
            <span style={{ color: chart.success }}>▲ Positive growth</span>
            <span style={{ color: chart.danger }}>▼ Negative growth</span>
          </div>
        </div>

        <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '160ms' }}>
          <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight mb-4">Dual-Year Trend Line</h3>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} vertical={false} />
              <XAxis dataKey="name" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${(v/1000000).toFixed(1)}M`} width={40} />
              <Tooltip formatter={(val: number) => val.toLocaleString('en-IN')} contentStyle={{ background: chart.tooltipBg, border: `1px solid ${chart.tooltipBorder}`, borderRadius: 8 }} />
              <Line type="monotone" dataKey={`${comparisonYearA}`} stroke={colorA} strokeWidth={1.5} dot={{ r: 3, fill: colorA }} />
              <Line type="monotone" dataKey={`${comparisonYearB}`} stroke={colorB} strokeWidth={2.5} dot={{ r: 4, fill: colorB }} activeDot={{ r: 6 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '190ms' }}>
        <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight mb-4">Month-by-Month Breakdown</h3>
        <div className="grid grid-cols-6 gap-3 mb-4 text-[10px] uppercase tracking-widest text-[var(--text-muted)] font-mono px-1">
          <span>Month</span>
          <span>{comparisonYearA}</span>
          <span>{comparisonYearB}</span>
          <span className="col-span-2 text-center">Delta</span>
          <span className="text-right">Growth</span>
        </div>
        <div className="space-y-2">
          {chartData.map((d: { name: string; [key: string]: number }, i: number) => {
            const a = d[`year_${comparisonYearA}`] || 0;
            const b = d[`year_${comparisonYearB}`] || 0;
            const delta = b - a;
            const pct = d.growth || 0;
            return (
              <div key={i} className="grid grid-cols-6 gap-3 items-center px-1 py-1.5 rounded-lg hover:bg-[var(--bg-card-hover)] transition-colors">
                <span className="text-xs font-mono text-[var(--text-secondary)] font-semibold">{d.name}</span>
                <span className="font-mono text-xs text-[var(--text-muted)]">{a.toLocaleString('en-IN')}</span>
                <span className="font-mono text-xs font-semibold" style={{ color: colorB }}>{b.toLocaleString('en-IN')}</span>
                <div className="col-span-2 flex items-center gap-1">
                  <span className="font-mono text-[11px] font-bold" style={{ color: delta >= 0 ? chart.success : chart.danger }}>
                    {delta >= 0 ? '+' : ''}{delta.toLocaleString('en-IN')}
                  </span>
                  <div className="h-0.5 flex-1 rounded-full overflow-hidden bg-[var(--bg-sunken)]">
                    <div className="h-full rounded-full" style={{ width: `${Math.min(Math.abs(pct), 100)}%`, background: pct >= 0 ? chart.success : chart.danger }} />
                  </div>
                </div>
                <span className="text-right font-mono text-[11px] font-bold" style={{ color: pct >= 0 ? chart.success : chart.danger }}>
                  {pct >= 0 ? '+' : ''}{pct.toFixed(1)}%
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

Run: `cd frontend && npm run build`
Expected: succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/YoY.tsx
git commit -m "feat: migrate Year-over-Year page to theme tokens"
```

---

## Task 10: Migrate Categories & Fuel page

**Files:**
- Modify: `frontend/src/pages/Categories.tsx` (full rewrite)

Renames the on-page title to "Categories & Fuel" to match the new sidebar label, and moves the maker breakdown chart to horizontal orientation.

- [ ] **Step 1: Rewrite `frontend/src/pages/Categories.tsx`**

```tsx
// frontend/src/pages/Categories.tsx
import { useQuery } from '@tanstack/react-query';
import {
  PieChart, Pie, Cell, BarChart, Bar, ResponsiveContainer, XAxis, YAxis, CartesianGrid, Tooltip
} from 'recharts';
import { useNavigate } from 'react-router-dom';
import { getCategories, getTopMakers, getFuelBreakdown } from '../api/vahan';
import { useAppStore } from '../hooks/useAppStore';
import { useChartTheme } from '../hooks/useChartTheme';
import { capForDonut } from '../theme/tokens';

export function CategoriesPage() {
  const navigate = useNavigate();
  const chart = useChartTheme();
  const { selectedYear } = useAppStore();

  const { data: categories, isLoading } = useQuery({
    queryKey: ['categories', selectedYear],
    queryFn: () => getCategories(selectedYear),
  });

  const pieData = capForDonut((categories || []).map((c: { vehicle_class: string; total_count: number }) => ({
    name: c.vehicle_class,
    value: c.total_count,
  })));

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between animate-entrance">
        <div>
          <h2 className="text-xl font-bold text-[var(--text-primary)] tracking-tight">Categories & Fuel</h2>
          <p className="text-[10px] text-[var(--text-muted)] mt-0.5 font-mono uppercase tracking-widest">
            Vehicle category and powertrain breakdown — FY {selectedYear}
          </p>
        </div>
        <div className="flex items-center gap-2 text-[10px] text-[var(--text-muted)] font-mono">
          <div className="w-1.5 h-1.5 rounded-full bg-[var(--success)]" />
          LIVE DATA
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div className="xl:col-span-1 bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '100ms' }}>
          <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight mb-4">Category Share</h3>
          {isLoading ? (
            <div className="h-[300px] rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft" />
          ) : (
            <>
              <ResponsiveContainer width="100%" height={240}>
                <PieChart>
                  <Pie
                    data={pieData}
                    cx="50%"
                    cy="50%"
                    innerRadius={70}
                    outerRadius={110}
                    paddingAngle={1}
                    dataKey="value"
                  >
                    {pieData.map((p: { name: string }, i: number) => (
                      <Cell key={i} fill={chart.seriesColor(p.name)} />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(val: number) => [val.toLocaleString('en-IN'), 'Registrations']}
                    contentStyle={{ background: chart.tooltipBg, border: `1px solid ${chart.tooltipBorder}`, borderRadius: 8, fontSize: 12 }}
                  />
                </PieChart>
              </ResponsiveContainer>
              <div className="mt-3 space-y-1.5 max-h-44 overflow-y-auto pr-1">
                {pieData.map((p: { name: string; value: number }, i: number) => (
                  <div key={i} className="flex items-center justify-between text-[11px]">
                    <div className="flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-sm" style={{ backgroundColor: chart.seriesColor(p.name) }} />
                      <span className="text-[var(--text-secondary)] truncate max-w-[110px]">{p.name}</span>
                    </div>
                    <span className="font-mono text-[var(--text-secondary)] font-semibold">{p.value?.toLocaleString('en-IN')}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        <div className="xl:col-span-2 bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '150ms' }}>
          <div className="mb-4">
            <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">Category Breakdown</h3>
            <p className="text-[10px] text-[var(--text-muted)] font-mono mt-0.5">Click any category to explore makers & fuel</p>
          </div>
          <div className="space-y-3">
            {(categories || []).map((c: { vehicle_class: string; total_count: number; share_percent: number; yoy_growth: number }, i: number) => (
              <div
                key={i}
                onClick={() => navigate(`/categories/${encodeURIComponent(c.vehicle_class)}`)}
                className="flex items-center gap-4 p-3 rounded-xl cursor-pointer transition-all duration-200 border border-transparent hover:border-[var(--border-strong)] hover:bg-[var(--bg-card-hover)] group"
              >
                <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ backgroundColor: chart.seriesColor(c.vehicle_class) }} />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-semibold text-[var(--text-secondary)] group-hover:text-[var(--text-primary)] transition-colors truncate">{c.vehicle_class}</div>
                  <div className="w-full bg-[var(--bg-sunken)] rounded-full h-1.5 mt-1.5">
                    <div className="h-1.5 rounded-full transition-all duration-500" style={{ width: `${c.share_percent}%`, backgroundColor: chart.seriesColor(c.vehicle_class) }} />
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="font-mono text-sm font-bold text-[var(--text-primary)]">{c.total_count?.toLocaleString('en-IN')}</div>
                  <div className="flex items-center gap-2 justify-end mt-0.5">
                    <span className="text-[10px] font-mono font-bold" style={{ color: c.yoy_growth >= 0 ? chart.success : chart.danger }}>
                      {c.yoy_growth >= 0 ? '+' : ''}{c.yoy_growth?.toFixed(1)}%
                    </span>
                    <span className="text-[10px] text-[var(--text-muted)] font-mono">{c.share_percent?.toFixed(1)}%</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <CategoryChart title="Top Makers — All Categories" queryKey="makers" fn={() => getTopMakers(undefined, selectedYear)} year={selectedYear} chart={chart} index={0} />
        <CategoryChart title="Fuel Type Breakdown — All Categories" queryKey="fuel" fn={() => getFuelBreakdown(undefined, selectedYear)} year={selectedYear} chart={chart} index={1} />
      </div>
    </div>
  );
}

function CategoryChart({ title, queryKey, fn, year, chart, index }: { title: string; queryKey: string; fn: () => Promise<unknown>; year: number; chart: ReturnType<typeof useChartTheme>; index: number }) {
  const { data, isLoading } = useQuery({ queryKey: [queryKey, year], queryFn: fn });

  const chartData = (data || []).map((d: { maker?: string; fuel_type?: string; count: number }) => ({
    name: d.maker || d.fuel_type || '',
    count: d.count,
  }));

  return (
    <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: `${250 + index * 80}ms` }}>
      <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight mb-4">{title}</h3>
      {isLoading ? (
        <div className="h-[220px] rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft" />
      ) : (
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={chartData} layout="vertical">
            <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} horizontal={false} />
            <XAxis type="number" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} />
            <YAxis dataKey="name" type="category" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} width={110} />
            <Tooltip
              formatter={(val: number) => [val.toLocaleString('en-IN'), 'Count']}
              contentStyle={{ background: chart.tooltipBg, border: `1px solid ${chart.tooltipBorder}`, borderRadius: 8, fontSize: 12 }}
            />
            <Bar dataKey="count" radius={[0, 4, 4, 0]}>
              {chartData.map((d: { name: string }, i: number) => (
                <Cell key={i} fill={chart.seriesColor(d.name)} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

Run: `cd frontend && npm run build`
Expected: succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/Categories.tsx
git commit -m "feat: migrate Categories page to theme tokens, rename to Categories & Fuel"
```

---

## Task 11: Migrate Category Detail page

**Files:**
- Modify: `frontend/src/pages/CategoryDetail.tsx` (full rewrite)

- [ ] **Step 1: Rewrite `frontend/src/pages/CategoryDetail.tsx`**

```tsx
// frontend/src/pages/CategoryDetail.tsx
import { useQuery } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import { PieChart, Pie, Cell, BarChart, Bar, ResponsiveContainer, XAxis, YAxis, CartesianGrid, Tooltip } from 'recharts';
import { getTopMakers, getFuelBreakdown, getCategories } from '../api/vahan';
import { useAppStore } from '../hooks/useAppStore';
import { ArrowLeft } from '../components/Icons';
import { Link } from 'react-router-dom';
import { useChartTheme } from '../hooks/useChartTheme';

export function CategoryDetailPage() {
  const { vehicleClass } = useParams<{ vehicleClass: string }>();
  const decoded = decodeURIComponent(vehicleClass || '');
  const { selectedYear } = useAppStore();
  const chart = useChartTheme();

  const { data: cats } = useQuery({
    queryKey: ['categories', selectedYear],
    queryFn: () => getCategories(selectedYear),
  });

  const currentCat = (cats || []).find((c: { vehicle_class: string }) => c.vehicle_class === decoded);

  const { data: makers, isLoading: makersLoading } = useQuery({
    queryKey: ['makers', decoded, selectedYear],
    queryFn: () => getTopMakers(decoded, selectedYear),
    enabled: !!decoded,
  });

  const { data: fuel, isLoading: fuelLoading } = useQuery({
    queryKey: ['fuel', decoded, selectedYear],
    queryFn: () => getFuelBreakdown(decoded, selectedYear),
    enabled: !!decoded,
  });

  const totalFuelCount = (fuel || []).reduce((sum: number, f: { count: number }) => sum + f.count, 0);

  return (
    <div className="p-6 space-y-6">
      <div className="animate-entrance">
        <Link to="/categories" className="inline-flex items-center gap-2 text-[11px] text-[var(--text-muted)] hover:text-[var(--accent)] font-mono mb-3 transition-colors">
          <ArrowLeft className="w-3.5 h-3.5" />
          Back to Categories
        </Link>
        <div className="flex items-center gap-3">
          <div className="w-1 h-8 rounded-full" style={{ background: chart.seriesColor(decoded) }} />
          <div>
            <h2 className="text-xl font-bold text-[var(--text-primary)] tracking-tight">{decoded}</h2>
            <p className="text-[10px] text-[var(--text-muted)] mt-0.5 font-mono uppercase tracking-widest">
              {selectedYear} · {currentCat?.total_count?.toLocaleString('en-IN') || 0} registrations
              {currentCat?.yoy_growth != null && (
                <span className="ml-2 font-mono font-bold" style={{ color: (currentCat.yoy_growth as number) >= 0 ? chart.success : chart.danger }}>
                  {((currentCat.yoy_growth as number) >= 0 ? '+' : '')}{currentCat.yoy_growth?.toFixed(1)}% YoY
                </span>
              )}
            </p>
          </div>
        </div>
      </div>

      <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '100ms' }}>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">Top Makers</h3>
            <p className="text-[10px] text-[var(--text-muted)] font-mono mt-0.5">manufacturers leading in {decoded}</p>
          </div>
        </div>
        {makersLoading ? (
          <div className="h-[280px] rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft" />
        ) : (
          <>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={(makers || []).map((m: { maker: string; count: number }) => ({ name: m.maker, count: m.count }))} layout="vertical">
                <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} />
                <YAxis dataKey="name" type="category" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} width={140} />
                <Tooltip
                  formatter={(val: number) => [val.toLocaleString('en-IN'), 'Registrations']}
                  contentStyle={{ background: chart.tooltipBg, border: `1px solid ${chart.tooltipBorder}`, borderRadius: 8, fontSize: 12 }}
                />
                <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                  {(makers || []).map((m: { maker: string }, i: number) => (
                    <Cell key={i} fill={chart.seriesColor(m.maker)} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
            <div className="mt-3 flex items-center justify-between">
              <span className="text-[10px] text-[var(--text-muted)] font-mono">{(makers || []).length} makers tracked</span>
              <span className="text-[10px] text-[var(--text-muted)] font-mono">
                {(makers || [])[0]?.maker || '—'} leads with {(makers || [])[0]?.count?.toLocaleString('en-IN') || 0}
              </span>
            </div>
          </>
        )}
      </div>

      <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '150ms' }}>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">Fuel Type Distribution</h3>
            <p className="text-[10px] text-[var(--text-muted)] font-mono mt-0.5">powertrain mix for {decoded}</p>
          </div>
          <span className="text-[10px] font-mono px-2 py-1 rounded-md" style={{ color: chart.seriesColors[1], background: 'var(--bg-sunken)' }}>
            {totalFuelCount.toLocaleString('en-IN')} total
          </span>
        </div>
        {fuelLoading ? (
          <div className="h-[280px] rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft" />
        ) : (
          <>
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie
                  data={(fuel || []).map((f: { fuel_type: string; count: number }) => ({ name: f.fuel_type, value: f.count }))}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={100}
                  paddingAngle={2}
                  dataKey="value"
                >
                  {(fuel || []).map((f: { fuel_type: string }, i: number) => (
                    <Cell key={i} fill={chart.seriesColor(f.fuel_type)} />
                  ))}
                </Pie>
                <Tooltip
                  formatter={(val: number) => [val.toLocaleString('en-IN'), 'Registrations']}
                  contentStyle={{ background: chart.tooltipBg, border: `1px solid ${chart.tooltipBorder}`, borderRadius: 8, fontSize: 12 }}
                />
              </PieChart>
            </ResponsiveContainer>
            <div className="flex flex-wrap gap-2 mt-3">
              {(fuel || []).map((f: { fuel_type: string; count: number }, i: number) => {
                const share = totalFuelCount > 0 ? ((f.count / totalFuelCount) * 100).toFixed(1) : '0.0';
                const color = chart.seriesColor(f.fuel_type);
                return (
                  <div key={i} className="flex items-center gap-2 px-3 py-1.5 rounded-xl border transition-all hover:scale-105" style={{ backgroundColor: `${color}18`, borderColor: `${color}40` }}>
                    <span className="w-2 h-2 rounded-sm" style={{ backgroundColor: color }} />
                    <span className="text-[11px] font-semibold" style={{ color }}>{f.fuel_type}</span>
                    <span className="font-mono text-[10px] text-[var(--text-muted)]">{f.count?.toLocaleString('en-IN')}</span>
                    <span className="font-mono text-[10px] text-[var(--text-muted)]">({share}%)</span>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

Run: `cd frontend && npm run build`
Expected: succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/CategoryDetail.tsx
git commit -m "feat: migrate CategoryDetail page to theme tokens"
```

---

## Task 12: New Makers & Models page

**Files:**
- Create: `frontend/src/pages/MakersModels.tsx`
- Modify: `frontend/src/App.tsx` (add route)

Promotes the maker/model leaderboard that was cramped into Overview's bottom row into its own full page, reusing the exact same `getTopMakers`/`getModelBreakdown` endpoints already used elsewhere — no backend changes.

- [ ] **Step 1: Create `frontend/src/pages/MakersModels.tsx`**

```tsx
// frontend/src/pages/MakersModels.tsx
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import { getTopMakers, getModelBreakdown } from '../api/vahan';
import { useAppStore } from '../hooks/useAppStore';
import { useChartTheme } from '../hooks/useChartTheme';

export function MakersModelsPage() {
  const chart = useChartTheme();
  const { selectedYear } = useAppStore();
  const [selectedMaker, setSelectedMaker] = useState<string | null>(null);

  const { data: makers, isLoading: makersLoading } = useQuery({
    queryKey: ['makers-full', selectedYear],
    queryFn: () => getTopMakers({ year: selectedYear, limit: 20 }),
  });

  const { data: models, isLoading: modelsLoading } = useQuery({
    queryKey: ['models-full', selectedMaker, selectedYear],
    queryFn: () => getModelBreakdown({ maker: selectedMaker, year: selectedYear, limit: 20 }),
    enabled: !!selectedMaker,
  });

  const makerChartData = (makers || []).map((m: { maker: string; count: number }) => ({ name: m.maker, count: m.count }));
  const modelChartData = (models || []).map((m: { model: string; count: number }) => ({ name: m.model, count: m.count }));

  return (
    <div className="p-6 space-y-6">
      <div className="animate-entrance">
        <h2 className="text-xl font-bold text-[var(--text-primary)] tracking-tight">Makers & Models</h2>
        <p className="text-[10px] text-[var(--text-muted)] mt-0.5 font-mono uppercase tracking-widest">
          Manufacturer and model leaderboard — FY {selectedYear}
        </p>
      </div>

      <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '80ms' }}>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">Top Manufacturers</h3>
            <p className="text-[10px] text-[var(--text-muted)] font-mono mt-0.5">click a maker to see its model breakdown below</p>
          </div>
          {selectedMaker && (
            <button onClick={() => setSelectedMaker(null)} className="text-[9px] uppercase font-mono tracking-wider text-[var(--accent)] hover:opacity-80 transition-opacity">
              Clear Selection
            </button>
          )}
        </div>
        {makersLoading ? (
          <div className="h-[420px] rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft" />
        ) : (
          <ResponsiveContainer width="100%" height={Math.max(280, makerChartData.length * 22)}>
            <BarChart data={makerChartData} layout="vertical">
              <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} horizontal={false} />
              <XAxis type="number" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} />
              <YAxis dataKey="name" type="category" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} width={190} />
              <Tooltip
                formatter={(val: number) => [val.toLocaleString('en-IN'), 'Registrations']}
                contentStyle={{ background: chart.tooltipBg, border: `1px solid ${chart.tooltipBorder}`, borderRadius: 8, fontSize: 12 }}
              />
              <Bar
                dataKey="count"
                radius={[0, 4, 4, 0]}
                onClick={(data: { name?: string }) => data?.name && setSelectedMaker(data.name)}
                cursor="pointer"
              >
                {makerChartData.map((d: { name: string }, i: number) => (
                  <Cell
                    key={i}
                    fill={chart.seriesColor(d.name)}
                    fillOpacity={selectedMaker && selectedMaker !== d.name ? 0.35 : 1}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: '140ms' }}>
        <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight mb-1">Model Breakdown</h3>
        <p className="text-[10px] text-[var(--text-muted)] font-mono mb-4">
          {selectedMaker ? `Models from ${selectedMaker}` : 'Select a manufacturer above to see its individual models'}
        </p>
        {!selectedMaker ? (
          <div className="h-44 flex flex-col items-center justify-center text-[var(--text-muted)] text-xs border border-dashed border-[var(--border)] rounded-xl">
            <span>No manufacturer selected</span>
            <span className="text-[10px] mt-1">Click a bar above to drill into its models</span>
          </div>
        ) : modelsLoading ? (
          <div className="h-[300px] rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft" />
        ) : modelChartData.length === 0 ? (
          <div className="h-44 flex flex-col items-center justify-center text-[var(--text-muted)] text-xs border border-dashed border-[var(--border)] rounded-xl">
            <span>No model-level data for {selectedMaker}</span>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={Math.max(220, modelChartData.length * 24)}>
            <BarChart data={modelChartData} layout="vertical">
              <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} horizontal={false} />
              <XAxis type="number" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} />
              <YAxis dataKey="name" type="category" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} width={150} />
              <Tooltip
                formatter={(val: number) => [val.toLocaleString('en-IN'), 'Registrations']}
                contentStyle={{ background: chart.tooltipBg, border: `1px solid ${chart.tooltipBorder}`, borderRadius: 8, fontSize: 12 }}
              />
              <Bar dataKey="count" fill={chart.seriesColor(selectedMaker)} radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Add the route in `frontend/src/App.tsx`**

Find:
```tsx
import { CategoryDetailPage } from './pages/CategoryDetail';
import { useQuery } from '@tanstack/react-query';
```
Replace with:
```tsx
import { CategoryDetailPage } from './pages/CategoryDetail';
import { MakersModelsPage } from './pages/MakersModels';
import { useQuery } from '@tanstack/react-query';
```

Find:
```tsx
            <Route path="/categories/:vehicleClass" element={<CategoryDetailPage />} />
          </Routes>
```
Replace with:
```tsx
            <Route path="/categories/:vehicleClass" element={<CategoryDetailPage />} />
            <Route path="/makers" element={<MakersModelsPage />} />
          </Routes>
```

- [ ] **Step 3: Verify build**

Run: `cd frontend && npm run build`
Expected: succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/MakersModels.tsx frontend/src/App.tsx
git commit -m "feat: add dedicated Makers & Models page with drill-down"
```

---

## Task 13: Manual verification

**Files:** none (verification only)

- [ ] **Step 1: Start the dev server**

```bash
cd frontend && npm run dev
```

- [ ] **Step 2: Visual check — dark mode (default)**

Open the dev server URL. Confirm:
- Page loads in dark mode (charcoal `#1C1C1E`-family surfaces, amber accent) with no flash of the old blue/navy theme
- No visual trace of glow/box-shadow effects or pulsing dots outside the loading skeletons and the header's sync indicator
- All 5 sidebar sections are present and navigable: Overview, State Comparison, Year over Year, Categories & Fuel, Makers & Models
- Overview's filters (State/Year/Month/Category/OEM/Model) still work and update the KPI cards/charts
- Makers & Models: clicking a maker bar loads its model breakdown below

- [ ] **Step 3: Visual check — light mode**

Click the theme toggle in the top bar. Confirm:
- Surfaces switch to the warm off-white palette, text stays readable (dark text on light background), the accent color darkens for contrast
- No components are left showing hardcoded dark colors (would appear as dark boxes/text on the new light background — scan every page)
- Reload the page — theme choice persists (still light, read from `localStorage`)

- [ ] **Step 4: Chart color consistency check**

On Overview, note the color of a specific top state or maker in the ranking list. Navigate to State Comparison or Makers & Models and confirm that same state/maker uses the identical color there too (verifies `seriesColor()` determinism).

- [ ] **Step 5: Run existing backend tests to confirm no accidental backend changes**

```bash
cd ../backend && python -m pytest -v
```
Expected: 32 passed (unchanged from before this plan — this work is frontend-only).

---

## Known follow-ups (not in this plan's scope)

- The Zone → State → District → RTO drill-down UI (backend built in an earlier session) is explicitly deferred — user confirmed "we will add in the UI later." Nothing in this plan touches routing/nav space reserved for it.
- `color-mix()` in `KPICard.tsx` (Task 5) needs a browserslist check — flagged inline in that task with a fallback (two extra CSS variables) if older-browser support turns out to be required.
- No new automated frontend tests are added — this project has no frontend test runner configured yet (only Playwright is set up, for the backend scraper). Verification here is manual (Task 13), matching how the rest of the frontend has been verified to date.
