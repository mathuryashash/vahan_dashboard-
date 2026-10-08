// Shared number/label formatting.

/** Compact Indian-style number: 950, 9.5K, 95K, 9.5L, 95L, 9.5Cr.
 *
 * Replaces the hard-coded `(v/1000).toFixed(0)+'K'` and `(v/1e6).toFixed(1)+'M'`
 * axis formatters. Those printed "0K" for every bar of a small state
 * (Lakshadweep, Ladakh: a few hundred a month) and "0.1M" for a small
 * category, so the chart could not be read. Precision adapts to magnitude:
 * one decimal below 10 of a unit, none above it. Values under 1,000 are
 * printed in full. */
export function formatCompact(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  const sign = value < 0 ? '-' : '';
  const v = Math.abs(value);
  const fmt = (n: number, unit: string) => {
    const digits = n < 10 ? 1 : 0;
    // Drop a trailing ".0" so round values read "2K", not "2.0K".
    return `${sign}${n.toFixed(digits).replace(/\.0$/, '')}${unit}`;
  };
  if (v < 1_000) return `${sign}${Math.round(v).toLocaleString('en-IN')}`;
  if (v < 1_00_000) return fmt(v / 1_000, 'K');
  if (v < 1_00_00_000) return fmt(v / 1_00_000, 'L');
  return fmt(v / 1_00_00_000, 'Cr');
}

/** Calendar-year label used on every page except RTO Analysis. These pages
 * filter `Registration.year == year` (Jan-Dec); they used to say "FY 2026",
 * which an Indian reader takes to mean Apr 2025 - Mar 2026. */
export const cyLabel = (year: number) => `CY ${year}`;
export const cyLongLabel = (year: number) => `CY ${year} (Jan–Dec)`;

/** Indian financial year as used by RTO Analysis (backend fy_filter):
 * April `year` through March `year + 1`. */
export const fyLabel = (year: number) => `FY ${year}-${String((year + 1) % 100).padStart(2, '0')}`;
export const fyLongLabel = (year: number) => `${fyLabel(year)} (Apr ${year} – Mar ${year + 1})`;

/** The one dash used for "no value" everywhere (the API's "N/A" included). */
export const NO_VALUE = '—';
export const orDash = (v: string | null | undefined) => (v == null || v === '' || v === 'N/A' ? NO_VALUE : v);
