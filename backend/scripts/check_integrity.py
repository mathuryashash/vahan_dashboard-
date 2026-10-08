"""READ-ONLY data-integrity diagnostics for the two known scrape defects.

1. Class-pass truncation: RTO-months where the vehicle_class pass
   (is_supplementary, maker NULL, fuel NULL) sums to < 95% of the canonical
   maker pass for the same RTO-month. Signature of dropped first pages
   (only the alphabetical tail of classes survived). Evidence: 2017-2024.
2. Maker-pass "PAGE_SIZE fingerprint": RTO-years where maker_category_totals
   knows exactly 25 more distinct makers than the registrations maker pass
   (one dropped 25-row page). Evidence: 34 RTOs in 2025 (CG/HR/JH/MZ).
   LEFT JOIN from maker_category_totals, so an RTO-year that mct knows but
   the maker pass has ZERO rows for is reported too (an inner JOIN silently
   dropped exactly the worst case). Also reports missing_makers >= 25.

Nothing here writes: the session is SET TRANSACTION READ ONLY and every
statement is a SELECT. Prints one line per year.

Usage (from backend/):
    python scripts/check_integrity.py [--from-year 2003] [--to-year 2026]
Connection: DATABASE_URL from app settings (.env), with the same asyncpg
driver the app uses.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.core.config import settings  # noqa: E402

CLASS_PASS_SQL = text("""
WITH m AS (
    SELECT rto_code, month, sum(count) AS maker_total
    FROM registrations
    WHERE year = :y AND is_supplementary IS NOT TRUE
    GROUP BY rto_code, month
), c AS (
    SELECT rto_code, month, sum(count) AS class_total
    FROM registrations
    WHERE year = :y AND is_supplementary IS TRUE AND maker IS NULL AND fuel_type IS NULL
      AND vehicle_class <> 'All'
    GROUP BY rto_code, month
)
SELECT count(*) FILTER (WHERE coalesce(c.class_total, 0) < 0.95 * m.maker_total) AS short_rto_months,
       count(*) AS rto_months,
       coalesce(sum(m.maker_total - coalesce(c.class_total, 0))
                FILTER (WHERE coalesce(c.class_total, 0) < 0.95 * m.maker_total), 0) AS missing_units
FROM m LEFT JOIN c USING (rto_code, month)
WHERE m.maker_total > 0
""")

FINGERPRINT_SQL = text("""
WITH reg AS (
    SELECT rto_code, maker, sum(count) AS n
    FROM registrations
    WHERE year = :y AND is_supplementary IS NOT TRUE AND maker IS NOT NULL
    GROUP BY rto_code, maker
), mct AS (
    SELECT rto_code, state_code, maker, sum(count) AS n
    FROM maker_category_totals
    WHERE year = :y AND rto_code IS NOT NULL
    GROUP BY rto_code, state_code, maker
), r AS (
    SELECT rto_code, count(*) AS makers, sum(n) AS units FROM reg GROUP BY rto_code
), x AS (
    SELECT rto_code, min(state_code) AS state_code, count(*) AS makers, sum(n) AS units
    FROM mct GROUP BY rto_code
), diff AS (
    -- distinct-maker count difference per RTO-year (mct minus maker pass);
    -- units = the volume the maker pass is short by.
    SELECT x.rto_code, x.state_code, x.makers - coalesce(r.makers, 0) AS missing_makers,
           x.units - coalesce(r.units, 0) AS missing_units, r.rto_code IS NULL AS no_maker_pass
    FROM x LEFT JOIN r USING (rto_code)
)
SELECT count(*) FILTER (WHERE missing_makers = 25) AS rto_years_missing_25,
       coalesce(sum(missing_units) FILTER (WHERE missing_makers = 25), 0) AS units,
       coalesce(string_agg(DISTINCT state_code, ',') FILTER (WHERE missing_makers = 25), '') AS states,
       count(*) FILTER (WHERE missing_makers >= 25) AS rto_years_missing_ge25,
       count(*) FILTER (WHERE no_maker_pass) AS rto_years_no_maker_pass,
       coalesce(sum(missing_units) FILTER (WHERE no_maker_pass), 0) AS no_maker_pass_units,
       coalesce(string_agg(DISTINCT state_code, ',') FILTER (WHERE no_maker_pass), '') AS no_maker_pass_states
FROM diff
""")


async def main(from_year: int, to_year: int) -> None:
    engine = create_async_engine(settings.DATABASE_URL)
    t0 = time.perf_counter()
    totals = {"short": 0, "missing": 0, "fp_rtos": 0, "fp_units": 0, "ge25": 0, "nomp": 0, "nomp_units": 0}
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SET TRANSACTION READ ONLY"))
            await conn.execute(text("SET LOCAL statement_timeout = '300s'"))
            print("year | classpass_short_rto_months / rto_months | classpass_missing_units "
                  "| rto_years_missing_exactly_25_makers | their_units | states "
                  "| rto_years_missing_>=25 | rto_years_with_NO_maker_pass | their_units | states")
            for y in range(from_year, to_year + 1):
                short, months, missing = (await conn.execute(CLASS_PASS_SQL, {"y": y})).one()
                (fp_rtos, fp_units, states, ge25, nomp, nomp_units,
                 nomp_states) = (await conn.execute(FINGERPRINT_SQL, {"y": y})).one()
                totals["ge25"] += ge25
                totals["nomp"] += nomp
                totals["nomp_units"] += int(nomp_units)
                totals["short"] += short
                totals["missing"] += int(missing)
                totals["fp_rtos"] += fp_rtos
                totals["fp_units"] += int(fp_units)
                print(f"{y} | {short} / {months} | {int(missing)} | {fp_rtos} | {int(fp_units)} | {states} "
                      f"| {ge25} | {nomp} | {int(nomp_units)} | {nomp_states}")
            await conn.rollback()
    finally:
        await engine.dispose()
    print(f"TOTAL classpass_short_rto_months={totals['short']} classpass_missing_units={totals['missing']} "
          f"rto_years_missing_25={totals['fp_rtos']} their_units={totals['fp_units']} "
          f"rto_years_missing_ge25={totals['ge25']} rto_years_no_maker_pass={totals['nomp']} "
          f"their_units={totals['nomp_units']} "
          f"({time.perf_counter() - t0:.1f}s, read-only)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from-year", type=int, default=2003)
    ap.add_argument("--to-year", type=int, default=2026)
    a = ap.parse_args()
    asyncio.run(main(a.from_year, a.to_year))
