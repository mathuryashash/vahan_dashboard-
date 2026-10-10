"""Scheduled refresh of the NEW analytics.parivahan.gov.in crosstabs.

One run refreshes, for every state, ``state_month_category_totals`` (one
query per state-year) and ``state_month_category_fuel_totals`` (one query per
state-year-fuel, all 34 fuels) for the years ``plan_years`` picks: always the
current year, plus the previous year early in a month (late revisions to last
year's final months land for a while after they close).

How this differs from the hand-run runners (run_analytics_scrape.py,
run_analytics_fuel_scrape.py):

* No resume-by-natural-key. Those runners skip a state that already has ANY
  row for the year, which for the current year means the partial month is
  never refreshed after the first run. Here every combo is fetched every run.
* Upsert in place, never delete-then-insert. A combo whose fetch fails, whose
  table fails the parser's integrity checks, or whose fresh data would shrink
  the stored scope (see ``shrink_problem``) leaves the stored rows untouched.
  Cells that disappeared from a GOOD fetch are deleted (the site revised them
  to zero) -- only after the scope passed every check.
* Every failed / rejected combo is retried once with a fresh HTTP session
  (each fetch opens its own client, so a retry is a new JSESSIONID/_csrf),
  then reported in the run summary. Nothing is dropped silently.
* After the writes, ``reconcile`` compares, per touched state-year,
  smct vs smcft and smct vs the old site's canonical registrations total for
  the same complete months, flagging anything more than 1% off.

The CLI wrapper is scraper/run_analytics_refresh.py; the in-app scheduler
(scraper/scheduler.py, run_analytics_scheduler_loop) launches that wrapper as
a child process -- Tesseract is driven through asyncio subprocesses, which
uvicorn's Windows event loop cannot create.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
from sqlalchemy import delete, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.core.scrape_lock import scrape_write_lock
from app.models.models import State, StateMonthCategoryFuelTotal, StateMonthCategoryTotal
from scraper.analytics_scraper import (
    FUEL_VALUES,
    SITE_CATEGORIES,
    CaptchaSolveError,
    UnexpectedPageError,
    load_session,
    scrape_state_year,
)

logger = logging.getLogger("analytics_refresh")

IST = timezone(timedelta(hours=5, minutes=30))  # India has no DST; no tzdata on Windows
SUMMARY_FILENAME = "analytics_refresh_last.json"
RECONCILE_FLAG_PCT = 1.0
# A fresh fetch that would cut a stored scope's year total by more than this
# (or empty a month that held SHRINK_MONTH_MIN_UNITS+) is rejected, not
# written: the site's registrations only grow, so a big drop is a bad page.
SHRINK_MAX_DROP_PCT = 2.0
SHRINK_MIN_UNITS = 100
SHRINK_MONTH_MIN_UNITS = 50


class CategoryAxisError(UnexpectedPageError):
    """A parsed table named a category outside the site's 17-category axis."""


class ShrinkRejected(RuntimeError):
    """The fresh data would shrink what is stored -- kept the stored rows."""


def today_ist() -> date:
    return datetime.now(IST).date()


def plan_years(today: date, window_days: int | None = None) -> list[int]:
    """Current year always; the previous year too during the first
    `window_days` of a month, and always in January (December only closes
    once January has started)."""
    window = settings.ANALYTICS_PREVIOUS_YEAR_WINDOW_DAYS if window_days is None else window_days
    years = [today.year]
    if today.month == 1 or today.day <= window:
        years.insert(0, today.year - 1)
    return years


def summary_path() -> Path:
    return Path(settings.SCRAPER_DATA_DIR) / SUMMARY_FILENAME


def read_last_summary(path: Path | None = None) -> dict | None:
    p = path or summary_path()
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_summary(summary: dict, path: Path | None = None) -> Path:
    p = path or summary_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8", newline="\n")
    tmp.replace(p)
    return p


def check_categories(records: list[dict]) -> None:
    bad = sorted({r["category"] for r in records} - set(SITE_CATEGORIES))
    if bad:
        raise CategoryAxisError(f"categories outside the site's 17-category axis: {bad}")


def shrink_problem(old: dict[tuple[int, str], int], new: dict[tuple[int, str], int]) -> str | None:
    old_total, new_total = sum(old.values()), sum(new.values())
    if old_total >= SHRINK_MIN_UNITS and new_total < old_total * (1 - SHRINK_MAX_DROP_PCT / 100):
        return f"year total would drop {old_total} -> {new_total}"
    new_months: dict[int, int] = defaultdict(int)
    for (m, _), n in new.items():
        new_months[m] += n
    old_months: dict[int, int] = defaultdict(int)
    for (m, _), n in old.items():
        old_months[m] += n
    for m, n in sorted(old_months.items()):
        if n >= SHRINK_MONTH_MIN_UNITS and not new_months.get(m):
            return f"month {m} ({n} units stored) is empty in the fresh fetch"
    return None


def _model_and_key(fuel: str | None):
    if fuel is None:
        return StateMonthCategoryTotal, ["state_code", "year", "month", "category"]
    return StateMonthCategoryFuelTotal, ["state_code", "year", "fuel", "month", "category"]


async def upsert_scope(db, state_code: str, state_name: str, year: int, fuel: str | None,
                       records: list[dict], *, allow_shrink: bool = False) -> dict:
    """Bring one (state, year[, fuel]) scope in line with `records`, in place.

    Raises ShrinkRejected (nothing written) when the fresh data would shrink
    the stored scope; the caller rolls back and reports it."""
    model, key = _model_and_key(fuel)
    conds = [model.state_code == state_code, model.year == year]
    if fuel is not None:
        conds.append(model.fuel == fuel)
    old = {(m, c): n for m, c, n in (await db.execute(
        select(model.month, model.category, model.count).where(*conds))).all()}
    new: dict[tuple[int, str], int] = {}
    for r in records:
        k = (r["month"], r["category"])
        if k in new:
            raise UnexpectedPageError(f"duplicate cell {k} in one parsed table")
        new[k] = r["count"]
    if not allow_shrink:
        problem = shrink_problem(old, new)
        if problem:
            raise ShrinkRejected(problem)
    changed = {k: n for k, n in new.items() if old.get(k) != n}
    if changed:
        base = {"state_code": state_code, "state_name": state_name, "year": year}
        if fuel is not None:
            base["fuel"] = fuel
        rows = [{**base, "month": m, "category": c, "count": n} for (m, c), n in changed.items()]
        stmt = pg_insert(model).values(rows)
        await db.execute(stmt.on_conflict_do_update(
            index_elements=key,
            set_={"count": stmt.excluded.count, "state_name": stmt.excluded.state_name},
        ))
    stale = [k for k in old if k not in new]
    if stale:
        await db.execute(delete(model).where(*conds, tuple_(model.month, model.category).in_(stale)))
    return {
        "inserted": sum(1 for k in changed if k not in old),
        "updated": sum(1 for k in changed if k in old),
        "deleted": len(stale),
        "units_before": sum(old.values()),
        "units_after": sum(new.values()),
    }


async def fetch_combo(tesseract_path: str, state_code: str, year: int, fuel: str | None,
                      counter: dict) -> list[dict]:
    """One fresh HTTP session per call, so a retry never reuses a bad one."""
    async def count(_request):
        counter["requests"] += 1

    async with httpx.AsyncClient(timeout=30, event_hooks={"request": [count]}) as client:
        csrf = await load_session(client)
        records = await scrape_state_year(client, tesseract_path, csrf, state_code, year, fuel=fuel)
    check_categories(records)
    return records


async def _states() -> list[tuple[str, str]]:
    async with AsyncSessionLocal() as db:
        return [tuple(r) for r in (await db.execute(
            select(State.state_code, State.state_name).order_by(State.state_code))).all()]


async def run_refresh(years: list[int], *, tesseract_path: str, concurrent: int = 6,
                      states: list[tuple[str, str]] | None = None, fuels: list[str] | None = None,
                      allow_shrink: bool = False, fetch=fetch_combo) -> dict:
    """Fetch + upsert every (year, state, [fuel]) combo, retry failures once,
    reconcile, and return the run summary (also the scheduler's record)."""
    started_at = datetime.now(timezone.utc)
    t0 = time.monotonic()
    states = states if states is not None else await _states()
    fuels = list(FUEL_VALUES) if fuels is None else fuels
    combos = [(y, code, name, fuel) for y in years for code, name in states for fuel in [None, *fuels]]
    counter = {"requests": 0}
    sem = asyncio.Semaphore(concurrent)
    totals = defaultdict(int)

    async def attempt(combo) -> tuple[str, str | None]:
        y, code, name, fuel = combo
        async with sem:
            try:
                records = await fetch(tesseract_path, code, y, fuel, counter)
                async with AsyncSessionLocal() as db:
                    try:
                        stats = await upsert_scope(db, code, name, y, fuel, records, allow_shrink=allow_shrink)
                        await db.commit()
                    except BaseException:
                        await db.rollback()
                        raise
            except ShrinkRejected as e:
                return "rejected", str(e)
            except (CaptchaSolveError, UnexpectedPageError, httpx.HTTPError) as e:
                return "failed", f"{type(e).__name__}: {e}"
            except Exception as e:  # one bad combo must not abort the other ~2,500
                logger.exception("year=%d state=%s fuel=%s: unexpected failure", y, code, fuel)
                return "failed", f"{type(e).__name__}: {e}"
        for k, v in stats.items():
            totals[k] += v
        return "ok", None

    async with contextlib.AsyncExitStack() as stack:
        for y in years:  # same per-table-year keys the hand-run runners take
            await stack.enter_async_context(scrape_write_lock(engine, f"state_month_category_totals:{y}"))
            await stack.enter_async_context(scrape_write_lock(engine, f"state_month_category_fuel_totals:{y}"))
        first = await asyncio.gather(*(attempt(c) for c in combos))
        bad = [(c, r) for c, r in zip(combos, first) if r[0] != "ok"]
        logger.info("first pass: %d/%d combos ok, %d to retry", len(combos) - len(bad), len(combos), len(bad))
        retried = await asyncio.gather(*(attempt(c) for c, _ in bad))

    failures = []
    for (combo, (status1, reason1)), (status2, reason2) in zip(bad, retried):
        if status2 == "ok":
            continue
        y, code, _, fuel = combo
        failures.append({"year": y, "state": code, "fuel": fuel, "table": "smct" if fuel is None else "smcft",
                         "status": status2, "reason": reason2, "first_reason": reason1})
        logger.warning("NOT refreshed after retry: year=%d state=%s fuel=%s (%s: %s) -- stored rows kept",
                       y, code, fuel, status2, reason2)

    today = today_ist()
    touched = sorted({(y, code) for y, code, _, _ in combos})
    async with AsyncSessionLocal() as db:
        recon = await reconcile(db, touched, today)
    flagged = [r for r in recon if r["flagged"]]
    for r in flagged:
        logger.warning("RECONCILE >%.0f%% off: %s %d smct=%s smcft=%s reg=%s (fuel %s%%, reg %s%%)",
                       RECONCILE_FLAG_PCT, r["state"], r["year"], r["smct"], r["smcft"], r["registrations"],
                       r["pct_fuel_vs_smct"], r["pct_smct_vs_reg"])
    return {
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(time.monotonic() - t0, 1),
        "years": years,
        "combos": len(combos),
        "ok_first_pass": len(combos) - len(bad),
        "retried": len(bad),
        "recovered_on_retry": len(bad) - len(failures),
        "failed": sum(1 for f in failures if f["status"] == "failed"),
        "rejected": sum(1 for f in failures if f["status"] == "rejected"),
        "failures": failures,
        "requests": counter["requests"],
        "rows": dict(totals),
        "reconciliation": recon,
        "flagged_state_years": len(flagged),
    }


_RECON_SQL = text("""
WITH a AS (SELECT state_code, month, sum(count) AS n FROM state_month_category_totals
           WHERE year = :y GROUP BY 1, 2),
     f AS (SELECT state_code, month, sum(count) AS n FROM state_month_category_fuel_totals
           WHERE year = :y GROUP BY 1, 2),
     r AS (SELECT state_code, month, sum(count) AS n FROM registrations
           WHERE year = :y AND is_supplementary IS NOT TRUE GROUP BY 1, 2)
SELECT state_code, month, a.n, f.n, r.n
FROM a FULL JOIN f USING (state_code, month) FULL JOIN r USING (state_code, month)
""")


def _pct(x: int, base: int) -> float | None:
    return round((x - base) * 100.0 / base, 3) if base else None


def reconcile_rows(rows, state_years: list[tuple[int, str]], today: date) -> list[dict]:
    """Pure part of `reconcile`: rows are (year, state, month, smct, smcft, reg).

    Compared over COMPLETE months only (all of a past year; months before the
    current one for this year) -- the partial month is scraped at different
    moments by the two sites and is reported separately, never flagged."""
    want = set(state_years)
    agg: dict[tuple[int, str], dict] = {}
    for y, code, month, a, f, r in rows:
        if (y, code) not in want:
            continue
        s = agg.setdefault((y, code), {"smct": 0, "smcft": 0, "registrations": 0, "partial": None})
        if y == today.year and month >= today.month:
            if month == today.month:
                s["partial"] = {"month": month, "smct": a or 0, "smcft": f or 0, "registrations": r or 0}
            continue
        s["smct"] += a or 0
        s["smcft"] += f or 0
        s["registrations"] += r or 0
    out = []
    for (y, code) in sorted(want):
        s = agg.get((y, code), {"smct": 0, "smcft": 0, "registrations": 0, "partial": None})
        pf, pr = _pct(s["smcft"], s["smct"]), _pct(s["smct"], s["registrations"])
        flagged = any(p is not None and abs(p) > RECONCILE_FLAG_PCT for p in (pf, pr)) or (
            s["smct"] == 0 and (s["smcft"] or s["registrations"]))
        out.append({"year": y, "state": code, **s, "pct_fuel_vs_smct": pf, "pct_smct_vs_reg": pr,
                    "flagged": bool(flagged)})
    return out


async def reconcile(db, state_years: list[tuple[int, str]], today: date) -> list[dict]:
    rows = []
    for y in sorted({y for y, _ in state_years}):
        rows += [(y, *r) for r in (await db.execute(_RECON_SQL, {"y": y})).all()]
    return reconcile_rows(rows, state_years, today)
