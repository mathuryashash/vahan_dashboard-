"""Targeted re-scrape: exactly the listed RTO-years, nothing else.

For repairing known-bad data without a full-India pass per year, e.g. the 84
maker-pass RTO-years that lost one 25-row page, or the class-pass RTO-years
written by the retired paged path (see vahan_scraper.TABLE_ID's comment).
Every listed RTO is force re-scraped through the normal persist path
(delete-then-insert for that RTO-year-dimension only; an empty answer never
deletes anything). States not in the plan are never requested.

Plan sources (pick one):
  --plan FILE          CSV with header year,state_name,rto_code
  --detect KIND        derive the plan from the DB with a READ-ONLY query:
      maker-fingerprint  maker pass knows >= 25 fewer makers than
                         maker_category_totals for the RTO-year
      class-short        vehicle_class pass < 99.5% of the maker pass for the
                         RTO-year, or any RTO-month < 95%, or the class pass
                         knows >= 20 fewer classes than maker_category_totals
      fuel-short         fuel pass < 99.5% of the maker pass (year or month<95%)
      crosstab-off       (crosstab dimensions) the table's RTO-year total is
                         off the maker pass by > 1% (and >= 5 units), or the
                         RTO-year is missing from the table
      all-rtos           every RTO with maker-pass rows for the year (a full
                         refresh of a crosstab table, split across sessions)

Usage (from backend/):
  python -m scraper.run_targeted_scrape --dimension maker --detect maker-fingerprint \
      --from-year 2003 --to-year 2025 [--dry-run] [--write-plan FILE]
  python -m scraper.run_targeted_scrape --dimension vehicle_class --plan plan.csv --concurrent-states 4
  python -m scraper.run_targeted_scrape --dimension maker_category --plan plan.csv --partitions 4

`--dimension` is a registrations pass (maker | vehicle_class | fuel) or a
crosstab table (maker_category | maker_fuel | fuel_category), or several
comma-separated -- those run concurrently, one plan each, like run_scraper's
three passes. Crosstab runs are serial per session, so --partitions N splits
each plan's states across N concurrent sessions (default 1). Takes the shared
scrape run lock: exits 4 with a message if another scrape is running.
"""
import argparse
import asyncio
import csv
import logging
import sys
from collections import defaultdict

from scraper import pool_sizing

pool_sizing.concurrent_workers()  # before any app.* import: up to dims x partitions sessions at once

from sqlalchemy import text  # noqa: E402

from app.core.database import engine  # noqa: E402
from app.core.scrape_lock import exit_if_run_lock_busy, scrape_run_lock, scrape_write_lock  # noqa: E402
from scraper import run_crosstab_scrape, run_full_scrape  # noqa: E402
from scraper.vahan_scraper import DIMENSIONS  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("run_targeted_scrape")

CROSSTAB_DIMENSIONS = {"maker_category", "maker_fuel", "fuel_category"}

_DETECT_SQL = {
    "maker-fingerprint": """
        WITH reg AS (
            SELECT rto_code, count(DISTINCT maker) AS makers FROM registrations
            WHERE year = :y AND is_supplementary IS NOT TRUE AND maker IS NOT NULL GROUP BY rto_code
        ), x AS (
            SELECT rto_code, min(state_name) AS state_name, count(DISTINCT maker) AS makers
            FROM maker_category_totals WHERE year = :y AND rto_code IS NOT NULL GROUP BY rto_code
        )
        SELECT x.state_name, x.rto_code FROM x LEFT JOIN reg USING (rto_code)
        WHERE x.makers - coalesce(reg.makers, 0) >= 25 ORDER BY 1, 2
    """,
    "class-short": """
        WITH m AS (
            SELECT rto_code, min(state_name) AS state_name, month, sum(count) AS t FROM registrations
            WHERE year = :y AND is_supplementary IS NOT TRUE GROUP BY rto_code, month
        ), c AS (
            SELECT rto_code, month, sum(count) AS t FROM registrations
            WHERE year = :y AND is_supplementary IS TRUE AND fuel_type IS NULL AND vehicle_class <> 'All'
            GROUP BY rto_code, month
        ), j AS (
            SELECT m.rto_code, min(m.state_name) AS state_name, sum(m.t) AS mt, sum(coalesce(c.t, 0)) AS ct,
                   bool_or(coalesce(c.t, 0) < 0.95 * m.t) AS any_short
            FROM m LEFT JOIN c USING (rto_code, month) GROUP BY m.rto_code
        ), k AS (
            SELECT rto_code, count(DISTINCT vehicle_class) AS n FROM registrations
            WHERE year = :y AND is_supplementary IS TRUE AND fuel_type IS NULL GROUP BY rto_code
        ), x AS (
            SELECT rto_code, count(DISTINCT vehicle_class) AS n FROM maker_category_totals
            WHERE year = :y AND rto_code IS NOT NULL GROUP BY rto_code
        )
        SELECT j.state_name, j.rto_code FROM j LEFT JOIN k USING (rto_code) LEFT JOIN x USING (rto_code)
        WHERE j.mt > 0 AND (j.any_short OR j.ct < 0.995 * j.mt OR coalesce(x.n, 0) - coalesce(k.n, 0) >= 20)
        ORDER BY 1, 2
    """,
    "fuel-short": """
        WITH m AS (
            SELECT rto_code, min(state_name) AS state_name, month, sum(count) AS t FROM registrations
            WHERE year = :y AND is_supplementary IS NOT TRUE GROUP BY rto_code, month
        ), f AS (
            SELECT rto_code, month, sum(count) AS t FROM registrations
            WHERE year = :y AND is_supplementary IS TRUE AND fuel_type IS NOT NULL GROUP BY rto_code, month
        ), j AS (
            SELECT m.rto_code, min(m.state_name) AS state_name, sum(m.t) AS mt, sum(coalesce(f.t, 0)) AS ft,
                   bool_or(coalesce(f.t, 0) < 0.95 * m.t) AS any_short
            FROM m LEFT JOIN f USING (rto_code, month) GROUP BY m.rto_code
        )
        SELECT state_name, rto_code FROM j WHERE mt > 0 AND (any_short OR ft < 0.995 * mt) ORDER BY 1, 2
    """,
}

_DETECT_SQL["all-rtos"] = """
    SELECT DISTINCT state_name, rto_code FROM registrations
    WHERE year = :y AND is_supplementary IS NOT TRUE AND rto_code IS NOT NULL ORDER BY 1, 2
"""
_CROSSTAB_OFF_SQL = """
    WITH m AS (
        SELECT rto_code, min(state_name) AS state_name, sum(count) AS t FROM registrations
        WHERE year = :y AND is_supplementary IS NOT TRUE AND rto_code IS NOT NULL GROUP BY rto_code
    ), x AS (
        SELECT rto_code, sum(count) AS t FROM {table} WHERE year = :y GROUP BY rto_code
    )
    SELECT m.state_name, m.rto_code FROM m LEFT JOIN x USING (rto_code)
    WHERE m.t > 0 AND abs(coalesce(x.t, 0) - m.t) > greatest(5, 0.01 * m.t) ORDER BY 1, 2
"""

Plan = dict[int, dict[str, frozenset[str]]]  # year -> state_name -> rto_codes


def _detect_sql(kind: str, dimension: str) -> str:
    if kind == "crosstab-off":
        if dimension not in CROSSTAB_DIMENSIONS:
            raise SystemExit("--detect crosstab-off needs a crosstab --dimension")
        return _CROSSTAB_OFF_SQL.format(table=run_crosstab_scrape._DIMENSIONS[dimension].model.__tablename__)
    return _DETECT_SQL[kind]


async def detect_plan(kind: str, from_year: int, to_year: int, dimension: str = "maker") -> Plan:
    plan: Plan = {}
    sql = _detect_sql(kind, dimension)
    async with engine.connect() as conn:
        await conn.execute(text("SET TRANSACTION READ ONLY"))
        await conn.execute(text("SET LOCAL statement_timeout = '600s'"))
        for y in range(from_year, to_year + 1):
            rows = (await conn.execute(text(sql), {"y": y})).all()
            if rows:
                by_state: dict[str, set[str]] = defaultdict(set)
                for state_name, rto_code in rows:
                    by_state[state_name].add(rto_code)
                plan[y] = {s: frozenset(c) for s, c in by_state.items()}
        await conn.rollback()
    return plan


def read_plan(path: str) -> Plan:
    acc: dict[int, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            acc[int(row["year"])][row["state_name"].strip()].add(row["rto_code"].strip())
    return {y: {s: frozenset(c) for s, c in states.items()} for y, states in acc.items()}


def write_plan(plan: Plan, path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["year", "state_name", "rto_code"])
        for y in sorted(plan):
            for s in sorted(plan[y]):
                for c in sorted(plan[y][s]):
                    w.writerow([y, s, c])


def partition(states: dict[str, frozenset[str]], n: int) -> list[dict[str, frozenset[str]]]:
    """Split states into n groups balanced by RTO count (largest first)."""
    groups: list[dict[str, frozenset[str]]] = [{} for _ in range(max(1, n))]
    loads = [0] * len(groups)
    for s, codes in sorted(states.items(), key=lambda kv: -len(kv[1])):
        i = loads.index(min(loads))
        groups[i][s] = codes
        loads[i] += len(codes)
    return [g for g in groups if g]


async def run(dimension: str, plan: Plan, concurrent_states: int = 1, partitions: int = 1) -> int:
    """Returns the number of year-runs that ended partial."""
    partial_years = 0
    async with scrape_run_lock(engine, f"run_targeted_scrape {dimension}"):
        for year in sorted(plan, reverse=True):
            if not plan[year]:
                continue
            n = sum(len(v) for v in plan[year].values())
            logger.info("=== %s %d: %d RTO(s) across %d state(s) ===", dimension, year, n, len(plan[year]))
            if dimension in CROSSTAB_DIMENSIONS:
                table = run_crosstab_scrape._DIMENSIONS[dimension].model.__tablename__
                async with scrape_write_lock(engine, f"{table}:{year}"):
                    done = await asyncio.gather(*(
                        run_crosstab_scrape._main(dimension, year, True, part, take_write_lock=False)
                        for part in partition(plan[year], partitions)
                    ))
                logger.info("%s %d: %d RTO(s) persisted", dimension, year, sum(done))
            else:
                partial_years += 1 if await run_full_scrape._main(
                    year, dimension, concurrent_states, True, plan[year]) else 0
    return partial_years


async def amain(args) -> int:
    dims = [d.strip() for d in args.dimension.split(",") if d.strip()]
    bad = [d for d in dims if d not in set(DIMENSIONS) | CROSSTAB_DIMENSIONS]
    if bad:
        raise SystemExit(f"unknown dimension(s): {bad}")
    plans: dict[str, Plan] = {}
    for d in dims:
        plans[d] = read_plan(args.plan) if args.plan else await detect_plan(args.detect, args.from_year, args.to_year, d)
        plan = plans[d]
        total = sum(len(c) for y in plan.values() for c in y.values())
        logger.info("Plan %s: %d RTO-year(s) over %d year(s): %s", d, total, len(plan),
                    ", ".join(f"{y}:{sum(len(c) for c in plan[y].values())}" for y in sorted(plan)))
        print(f"PLAN_RTO_YEARS {d}: {total}", flush=True)
        if args.write_plan:
            write_plan(plan, args.write_plan if len(dims) == 1 else args.write_plan.replace(".csv", f".{d}.csv"))
    if args.dry_run:
        return 0
    async with scrape_run_lock(engine, "run_targeted_scrape"):
        results = await asyncio.gather(*(run(d, plans[d], args.concurrent_states, args.partitions)
                                         for d in dims if plans[d]), return_exceptions=True)
    failed = [r for r in results if isinstance(r, BaseException)]
    for r in failed:
        logger.error("dimension run failed: %r", r)
    if failed:
        raise failed[0]
    return sum(results)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dimension", required=True, help="one or more (comma-separated) of: "
                    + ", ".join(sorted(set(DIMENSIONS) | CROSSTAB_DIMENSIONS)))
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--plan")
    src.add_argument("--detect", choices=sorted(set(_DETECT_SQL) | {"crosstab-off"}))
    ap.add_argument("--from-year", type=int, default=2003)
    ap.add_argument("--to-year", type=int, default=2025)
    ap.add_argument("--concurrent-states", type=int, default=1)
    ap.add_argument("--partitions", type=int, default=1, help="crosstab only: concurrent sessions")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--write-plan")
    a = ap.parse_args()
    try:
        partial = asyncio.run(amain(a))
    except Exception as exc:  # a busy run lock exits 4 with a message; anything else re-raises
        exit_if_run_lock_busy(exc)
    sys.exit(run_full_scrape.PARTIAL_EXIT_CODE if partial else 0)
