"""READ-ONLY: per state-year reconciliation of the analytics crosstabs.

Compares, for complete months, state_month_category_totals (smct) against
state_month_category_fuel_totals (smcft) and against the old site's canonical
registrations pass -- the same check the scheduled refresh runs after every
run (scraper/analytics_refresh.reconcile). Flags anything more than 1% off.

Usage (from backend/):
    python scripts/analytics_reconcile.py --year 2026 [--json out.json]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper import pool_sizing  # noqa: E402

pool_sizing.serial()

from sqlalchemy import select, text  # noqa: E402

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.models import State  # noqa: E402
from scraper.analytics_refresh import reconcile, today_ist  # noqa: E402


async def main(years: list[int], out: str | None) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        codes = (await db.execute(select(State.state_code).order_by(State.state_code))).scalars().all()
        rows = await reconcile(db, [(y, c) for y in years for c in codes], today_ist())
    print(f"{'year':>4} {'st':<3} {'smct':>10} {'smcft':>10} {'reg':>10} {'fuel%':>8} {'reg%':>8}  partial(smct/smcft/reg)")
    for r in rows:
        p = r["partial"]
        ptxt = f"{p['smct']}/{p['smcft']}/{p['registrations']}" if p else ""
        print(f"{r['year']:>4} {r['state']:<3} {r['smct']:>10} {r['smcft']:>10} {r['registrations']:>10} "
              f"{r['pct_fuel_vs_smct']!s:>8} {r['pct_smct_vs_reg']!s:>8}  {ptxt}{'  <-- >1%' if r['flagged'] else ''}")
    for y in years:
        yr = [r for r in rows if r["year"] == y]
        a, f, g = (sum(r[k] for r in yr) for k in ("smct", "smcft", "registrations"))
        print(f"TOTAL {y}: smct={a} smcft={f} reg={g} flagged={sum(r['flagged'] for r in yr)}")
    if out:
        Path(out).write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, action="append", required=True)
    ap.add_argument("--json")
    a = ap.parse_args()
    asyncio.run(main(a.year, a.json))
