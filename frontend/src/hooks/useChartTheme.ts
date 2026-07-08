// frontend/src/hooks/useChartTheme.ts
import { useTheme } from './useTheme';
import { getChartPalette, seriesColor, type ChartPalette } from '../theme/tokens';

export function useChartTheme(): ChartPalette & { seriesColor: (name: string) => string } {
  const theme = useTheme((s) => s.theme);
  const palette = getChartPalette(theme);
  return { ...palette, seriesColor: (name: string) => seriesColor(palette, name) };
}
