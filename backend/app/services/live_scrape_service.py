"""On-demand live scraping for maker(+fuel)-filtered queries against the
new analytics.parivahan.gov.in site -- the piece the bulk backfills
(StateMonthCategoryTotal/StateMonthCategoryFuelTotal) deliberately don't
cover, since maker is an unbounded 7,733-item long tail with no static enum
to loop over. See MakerLiveQueryCache's docstring for the caching design
(confirmed-empty marker row, "ALL" fuel sentinel for a maker-only query).
"""
import asyncio
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import MakerLiveQueryCache, State
from scraper.analytics_scraper import load_session, scrape_state_year, verify_tesseract

logger = logging.getLogger("live_scrape_service")

_EMPTY_MARKER_CATEGORY = "__EMPTY__"
ALL_FUEL_SENTINEL = "ALL"

# Guards against a thundering herd: two concurrent requests for the exact
# same uncached combo shouldn't both pay a live CAPTCHA-solve (several
# seconds each) -- the second one waits for the first's result and reads it
# from cache instead of scraping the same thing twice. Process-local (not
# cross-process like scrape_lock.py's advisory lock): fine for the single
# uvicorn worker this Dockerfile actually runs (no --workers flag); a
# multi-instance deployment would need the DB-level equivalent. Entries are
# popped once the request they were created for finishes (see
# get_or_scrape_maker_query) so this doesn't grow unbounded over the life of
# the process despite maker's long tail.
_locks: dict[tuple, asyncio.Lock] = {}
_tesseract_path: str | None = None

# Caps how many live scrapes run at once, independent of the per-key lock
# above (that only dedupes *identical* keys; maker alone has 7,733 possible
# values, so distinct-key concurrency needs its own bound). Mirrors the
# batch scrapers' own asyncio.Semaphore pattern (run_analytics_scrape.py,
# run_analytics_fuel_scrape.py) rather than leaving this site's load
# entirely up to the API's blanket per-IP rate limit, which was sized for
# cheap DB-scan endpoints, not ~7s external-site round trips.
_concurrency = asyncio.Semaphore(4)


class UnknownStateCodeError(ValueError):
    """state_code isn't in the `states` table -- caught by the API layer
    and turned into a 404 before any live scrape is attempted. National
    users aren't scope-clamped to one state_code (see require_state_code),
    so nothing else validates this is a real state."""


async def _get_tesseract_path() -> str:
    # Verified once per process, not once per request -- verify_tesseract()
    # does a real OCR smoke-test (a network round-trip + a subprocess call),
    # not something to pay on every cache-miss.
    global _tesseract_path
    if _tesseract_path is None:
        _tesseract_path = await verify_tesseract()
    return _tesseract_path


def _normalize(value: str) -> str:
    # Every real maker/fuel string this app has ever seen (both from the
    # site's own vehicleFuels <select> and its /lazy/vehicle-makers search
    # endpoint) is already upper-case -- this just makes stray
    # casing/whitespace from a caller (a hand-built request, a slightly
    # different frontend value) collapse onto the same cache row and lock
    # key instead of silently missing the cache and re-scraping.
    return value.strip().upper()


async def get_or_scrape_maker_query(
    db: AsyncSession, state_code: str, year: int, maker: str, fuel: str | None = None,
) -> list[dict]:
    """Returns [{'month': int, 'category': str, 'count': int}, ...] for this
    (state, year, maker, fuel) combo -- from cache if already scraped,
    otherwise scraped live from the new site and cached for next time.
    Raises UnknownStateCodeError if state_code isn't real, and
    CaptchaSolveError/TesseractUnavailableError on a scrape failure (the
    caller, the API endpoint, translates these to HTTP responses).

    The current year is never served from cache (always re-scraped): unlike
    closed years, it's still filling in, and this codebase already treats
    "current year" specially everywhere else (summary.py/categories.py's
    latest_month_with_data, refresh.py's whole reason for existing) -- a
    March cache entry silently under-counting for the rest of the year
    would be a worse bug than paying the scrape cost more than once."""
    maker = _normalize(maker)
    fuel_key = _normalize(fuel) if fuel else ALL_FUEL_SENTINEL
    is_current_year = year == datetime.now(timezone.utc).year

    if not is_current_year:
        cached = await _read_cache(db, state_code, year, maker, fuel_key)
        if cached is not None:
            return cached

    lock_key = (state_code, year, maker, fuel_key)
    lock = _locks.setdefault(lock_key, asyncio.Lock())
    try:
        async with lock:
            if not is_current_year:
                # Re-check after acquiring the lock: another request may
                # have populated the cache while this one was waiting on it.
                cached = await _read_cache(db, state_code, year, maker, fuel_key)
                if cached is not None:
                    return cached

            state_name = (await db.execute(select(State.state_name).where(State.state_code == state_code))).scalar()
            if state_name is None:
                raise UnknownStateCodeError(state_code)

            async with _concurrency:
                tesseract_path = await _get_tesseract_path()
                async with httpx.AsyncClient(timeout=30) as client:
                    csrf_token = await load_session(client)
                    records = await scrape_state_year(
                        client, tesseract_path, csrf_token, state_code, year,
                        maker=maker, fuel=fuel_key if fuel_key != ALL_FUEL_SENTINEL else None,
                    )
            await _write_cache(db, state_code, state_name, year, maker, fuel_key, records)
            await db.commit()
            logger.info("live-scraped state=%s year=%d maker=%r fuel=%r: %d rows", state_code, year, maker, fuel_key, len(records))
            return records
    finally:
        _locks.pop(lock_key, None)


async def _read_cache(db: AsyncSession, state_code: str, year: int, maker: str, fuel_key: str) -> list[dict] | None:
    rows = (await db.execute(
        select(MakerLiveQueryCache).where(
            MakerLiveQueryCache.state_code == state_code,
            MakerLiveQueryCache.year == year,
            MakerLiveQueryCache.maker == maker,
            MakerLiveQueryCache.fuel == fuel_key,
        )
    )).scalars().all()
    if not rows:
        return None
    if len(rows) == 1 and rows[0].category == _EMPTY_MARKER_CATEGORY:
        return []
    return [{"month": r.month, "category": r.category, "count": r.count} for r in rows]


async def _write_cache(
    db: AsyncSession, state_code: str, state_name: str, year: int, maker: str, fuel_key: str, records: list[dict],
) -> None:
    # Delete-then-insert, not a plain add: the current-year path can call
    # this more than once for the same key (see is_current_year above), and
    # a second plain insert would collide with idx_mlqc_natural_key.
    await db.execute(
        delete(MakerLiveQueryCache).where(
            MakerLiveQueryCache.state_code == state_code,
            MakerLiveQueryCache.year == year,
            MakerLiveQueryCache.maker == maker,
            MakerLiveQueryCache.fuel == fuel_key,
        )
    )
    if not records:
        db.add(MakerLiveQueryCache(
            state_code=state_code, state_name=state_name, year=year, maker=maker, fuel=fuel_key,
            month=0, category=_EMPTY_MARKER_CATEGORY, count=0,
        ))
        return
    for record in records:
        db.add(MakerLiveQueryCache(
            state_code=state_code, state_name=state_name, year=year, maker=maker, fuel=fuel_key,
            month=record["month"], category=record["category"], count=record["count"],
        ))
