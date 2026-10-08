// Shared helpers for the "partial month" and "compared window" labels on the
// Overview and YoY pages. Newer backends say which stored month was still in
// progress when it was scraped (`partial_month`) and how far a YoY comparison
// actually runs (`compare_through_month`). Those come from the DATA, so they
// stay right when the data is weeks old; today's date does not (it named Oct
// as the excluded month while the data actually ended 19 Sep). The wall clock
// is only the fallback for older backends that send neither field.

export const MONTH_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** "Jan–Aug", or just "Aug" for a one-month window. */
export function monthWindow(start: number, end: number): string {
  const s = MONTH_SHORT[start - 1];
  const e = MONTH_SHORT[end - 1];
  if (!s || !e) return '';
  return start === end ? e : `${s}–${e}`;
}

export interface PartialMonthInfo {
  /** 1-12 */
  month: number;
  name: string;
  /** Day of the month the data runs through, when known. */
  throughDay: number | null;
  /** Days in that month. */
  daysInMonth: number;
  /** true = taken from the backend, false = guessed from today's date. */
  fromData: boolean;
}

/** Day-of-month from a scrape timestamp ("2026-09-19 21:01 UTC" or ISO),
 * only if it falls in (year, month). */
function dayIfInMonth(stamp: string | null | undefined, year: number, month: number): number | null {
  if (!stamp) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(stamp);
  if (!m) return null;
  if (Number(m[1]) !== year || Number(m[2]) !== month) return null;
  return Number(m[3]);
}

/**
 * Resolve the in-progress month of `year`.
 * - `apiPartial === undefined` (field absent: older backend) -> wall clock.
 * - `apiPartial === null` (backend says no partial month) -> null.
 * - a number -> that month (only if it belongs to `year` when
 *   `apiPartialYear` is given).
 */
export function resolvePartialMonth(
  year: number,
  apiPartial: number | null | undefined,
  opts: { apiPartialYear?: number | null; scrapedAt?: string | null } = {},
): PartialMonthInfo | null {
  if (apiPartial !== undefined) {
    if (apiPartial == null || apiPartial < 1 || apiPartial > 12) return null;
    if (opts.apiPartialYear != null && opts.apiPartialYear !== year) return null;
    const daysInMonth = new Date(year, apiPartial, 0).getDate();
    return {
      month: apiPartial,
      name: MONTH_SHORT[apiPartial - 1],
      throughDay: dayIfInMonth(opts.scrapedAt, year, apiPartial),
      daysInMonth,
      fromData: true,
    };
  }
  const now = new Date();
  if (year !== now.getFullYear()) return null;
  const month = now.getMonth() + 1;
  return {
    month,
    name: MONTH_SHORT[month - 1],
    throughDay: now.getDate(),
    daysInMonth: new Date(year, month, 0).getDate(),
    fromData: false,
  };
}

/** "data through 19 Sep (61% of the month)" / "month 26% elapsed". */
export function partialMonthProgress(p: PartialMonthInfo): string {
  if (p.throughDay == null) return p.fromData ? 'month only part-scraped' : 'month in progress';
  const pct = Math.round((p.throughDay / p.daysInMonth) * 100);
  return p.fromData
    ? `data through ${p.throughDay} ${p.name}, ${pct}% of the month`
    : `${p.throughDay} of ${p.daysInMonth} days, ${pct}%`;
}
