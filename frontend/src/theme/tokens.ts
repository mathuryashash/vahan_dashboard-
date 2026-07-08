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
  const existingOtherIdx = kept.findIndex((d) => d.name === 'Other');
  if (existingOtherIdx !== -1) {
    const merged = [...kept];
    merged[existingOtherIdx] = { ...merged[existingOtherIdx], value: merged[existingOtherIdx].value + otherValue };
    return merged;
  }
  return [...kept, { name: 'Other', value: otherValue } as T];
}
