// frontend/src/utils/tripleEstimate.ts
//
// Estimates Maker x Category x Fuel cells -- VAHAN has no table that pivots
// on all three at once, only the three pairwise cross-tabs (Maker x
// Category, Maker x Fuel, Category x Fuel, each year-only). Used by
// MakersModels.tsx (every maker, for a ranking) when a user has Category,
// Maker, and Powertrain all selected together.
//
// Method: the "no three-factor interaction" log-linear model gives a prior
// share per maker, raw(m) = r_mc(m) * r_mf(m) / m_total(m) (the
// N/category-total/fuel-total terms all cancel once rescaled against the
// one real total we have, r_cf -- verified in code review). A naive single
// rescale (multiply every raw(m) by rCf/sum(raw)) can push a maker's
// estimate ABOVE its own real ceiling -- a fuel-only slice can never
// exceed either the maker's real Category total (all fuels) or its real
// Fuel total (all categories), so ceiling(m) = min(r_mc(m), r_mf(m)) is a
// hard bound every estimate must respect. A single rescale-then-clamp
// breaks that: confirmed live, it left a 279-unit shortfall against the
// real total on a real example (6597 vs 6876) because capped makers'
// excess was simply discarded instead of redistributed.
//
// This instead does iterative capped redistribution (a bounded transport /
// RAS-style proportional-fitting step): rescale the remaining
// (not-yet-capped) makers to make up the current shortfall, cap anyone who
// still exceeds their ceiling, and repeat. Confirmed live: sums exactly to
// the real total instead of falling short, and gives every maker still
// under its ceiling a fair share of what capped makers couldn't take.
// Terminates in at most one iteration per maker (each iteration caps at
// least one more).

export interface MakerCount {
  maker: string;
  count: number;
}

// A maker's real Category count can be genuinely nonzero (VAHAN's own
// registration data, not invented) even when that category is a rounding
// error for them -- e.g. a two-wheeler maker with a handful of real
// Four-Wheeler registrations nationally. Excluding those from a
// category-scoped ranking isn't correcting bad data, it's just not
// surfacing a maker's noise-level presence in a category dominated by
// someone else. 1% is a judgment call, not derived from anything.
export const MIN_CATEGORY_SHARE = 0.01;

export interface TripleEstimateInputs {
  /** Maker x Category, all makers, real counts -- category already fixed by the caller's query. */
  mcList: MakerCount[];
  /** Maker x Fuel, all makers, real counts -- fuel already fixed by the caller's query. */
  mfList: MakerCount[];
  /** Maker alone, all makers, real year totals (no category/fuel filter). */
  myList: MakerCount[];
  /** The one real number available for the full combo: Category x Fuel total across all makers. */
  rCf: number;
}

export function estimateTripleCells({ mcList, mfList, myList, rCf }: TripleEstimateInputs): Map<string, number> {
  const mfMap = new Map<string, number>(mfList.map((x) => [x.maker, x.count]));
  const myMap = new Map<string, number>(myList.map((x) => [x.maker, x.count]));

  type Candidate = { maker: string; raw: number; ceiling: number };
  let pool: Candidate[] = mcList
    .map((row): Candidate | null => {
      const rMf = mfMap.get(row.maker);
      const mTotal = myMap.get(row.maker);
      if (!rMf || !mTotal) return null;
      if (row.count / mTotal < MIN_CATEGORY_SHARE) return null;
      return { maker: row.maker, raw: (row.count * rMf) / mTotal, ceiling: Math.min(row.count, rMf) };
    })
    .filter((x): x is Candidate => x !== null);

  const result = new Map<string, number>();
  let target = rCf;

  // Bound captured up front, NOT re-read from `pool` each pass. The loop
  // removes capped makers, so `iter <= pool.length` was a limit that fell as
  // the counter rose: each pass costs one iteration and removes at least one
  // maker, so the two meet at N/2 and the loop can stop with the pool still
  // holding uncapped makers, never reaching the `over.length === 0` branch
  // that assigns them. Those makers would get no value at all and the
  // estimates would sum below the real total.
  //
  // Latent, not observed: checked against the real FY2026 Two-Wheeler x EV
  // inputs and both bounds give an identical result summing to exactly the
  // anchor, because that case converges in far fewer than N/2 rounds. It
  // needs a distribution where more than half the makers cap in separate
  // rounds. Each pass caps at least one maker, so the initial size is a
  // sufficient bound.
  const maxIters = pool.length;
  for (let iter = 0; iter <= maxIters && pool.length > 0; iter++) {
    const rawSum = pool.reduce((s, c) => s + c.raw, 0);
    if (rawSum <= 0) break;
    const scale = target / rawSum;
    const over = pool.filter((c) => c.raw * scale > c.ceiling);
    if (over.length === 0) {
      for (const c of pool) result.set(c.maker, c.raw * scale);
      break;
    }
    for (const c of over) {
      result.set(c.maker, c.ceiling);
      target -= c.ceiling;
    }
    pool = pool.filter((c) => !over.includes(c));
  }
  return result;
}
