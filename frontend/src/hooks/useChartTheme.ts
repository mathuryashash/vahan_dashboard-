// frontend/src/hooks/useChartTheme.ts
import { useTheme } from './useTheme';
import { getChartPalette, seriesColor, type ChartPalette } from '../theme/tokens';

export interface ChartThemeApi extends ChartPalette {
  seriesColor: (name: string) => string;
  /** Recharts' <Tooltip contentStyle> never picks up a text color on its own
   * -- every call site across this app set background/border but not color,
   * so the tooltip rendered in whatever default color Recharts falls back to
   * regardless of theme (near-invisible dark-on-dark in the dark theme).
   * Use this for every plain <Tooltip contentStyle={...}> instead of
   * hand-rolling the object per chart. */
  tooltipContentStyle: (extra?: Record<string, unknown>) => Record<string, unknown>;
  /** Recharts colors each tooltip item's text with that series' own `color`
   * field, falling back to literal black if it's undefined -- true for every
   * chart here that colors bars/slices with per-item <Cell> fills instead of
   * a single <Bar>/<Pie> `fill` prop, since Cell fills never populate that
   * field. `contentStyle`'s `color` only styles the tooltip's outer wrapper,
   * not these -- spread this alongside it on every <Tooltip> to force both
   * the item text and the label to the theme's tooltip text color instead. */
  tooltipTextStyle: { itemStyle: Record<string, unknown>; labelStyle: Record<string, unknown> };
}

export function useChartTheme(): ChartThemeApi {
  const theme = useTheme((s) => s.theme);
  const palette = getChartPalette(theme);
  return {
    ...palette,
    seriesColor: (name: string) => seriesColor(palette, name),
    tooltipContentStyle: (extra) => ({
      background: palette.tooltipBg,
      border: `1px solid ${palette.tooltipBorder}`,
      borderRadius: 8,
      color: palette.tooltipText,
      ...extra,
    }),
    tooltipTextStyle: {
      itemStyle: { color: palette.tooltipText },
      labelStyle: { color: palette.tooltipText },
    },
  };
}
