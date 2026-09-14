"""On-demand live scraping for maker(+fuel)-filtered queries against the
new analytics.parivahan.gov.in site -- the piece the bulk backfills
(StateMonthCategoryTotal/StateMonthCategoryFuelTotal) deliberately don't
cover, since maker is an unbounded 7,733-item long tail with no static enum
to loop over. See MakerLiveQueryCache's docstring for the caching design
(confirmed-empty marker row, "ALL" fuel sentinel for a maker-only query).
"""
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.models import MakerCategoryTotal, MakerLiveQueryCache, State
from scraper.analytics_scraper import (
    TesseractUnavailableError, load_session, scrape_state_year, search_makers as _search_makers_site,
    verify_tesseract,
)

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


@dataclass
class _WarmSession:
    client: httpx.AsyncClient
    csrf_token: str


# Reuses a session (cookies + CSRF token) across multiple queries instead of
# paying load_session's GET-the-report-page-and-parse-CSRF cost on every
# single call -- confirmed live this roughly halves per-query latency
# (~2.0s -> ~1.0s on a fresh vs. already-warm session, measured directly).
# The site's own analytics_scraper docstring already established the same
# CSRF token works across many POSTs with no per-request refresh needed;
# this just keeps that session alive across calls instead of discarding it
# after one use. Bounded by _concurrency above (at most 4 sessions can ever
# be checked out at once), so the pool never needs an explicit size cap.
# A session that errors is closed and dropped rather than returned --
# self-healing if the site ever invalidates a session server-side.
_session_pool: list[_WarmSession] = []
_pool_lock = asyncio.Lock()


async def _acquire_session() -> _WarmSession:
    async with _pool_lock:
        if _session_pool:
            return _session_pool.pop()
    client = httpx.AsyncClient(timeout=30)
    try:
        csrf_token = await load_session(client)
    except BaseException:
        # A fresh client that never made it into the pool -- close it here,
        # otherwise it's leaked (not pooled, and the caller's own cleanup
        # never runs since this function hasn't returned a session yet).
        await client.aclose()
        raise
    return _WarmSession(client, csrf_token)


async def _release_session(session: _WarmSession, *, healthy: bool) -> None:
    if not healthy:
        await session.client.aclose()
        return
    async with _pool_lock:
        _session_pool.append(session)


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
                session = await _acquire_session()
                healthy = False
                try:
                    # A bound, not a guess: CAPTCHA_MAX_ATTEMPTS=5 retries x
                    # httpx's own 30s per-request timeout is a real ~150s
                    # worst case for one maker if the site is slow but not
                    # outright erroring (a timeout wouldn't fire on its own).
                    # 90s lets 2-3 genuine retries complete while still
                    # capping how long one bad maker can hold up a request
                    # (especially the leaderboard's up-to-4-at-once fan-out).
                    records = await asyncio.wait_for(
                        scrape_state_year(
                            session.client, tesseract_path, session.csrf_token, state_code, year,
                            maker=maker, fuel=fuel_key if fuel_key != ALL_FUEL_SENTINEL else None,
                        ),
                        timeout=90,
                    )
                    healthy = True
                finally:
                    # finally, not except/else: asyncio.CancelledError is a
                    # BaseException (Python 3.8+), so `except Exception`
                    # never sees it -- a cancelled request (client
                    # disconnect, Starlette request cancellation) would
                    # otherwise leak this session, neither closed nor
                    # returned to the pool.
                    await _release_session(session, healthy=healthy)
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


_LEADERBOARD_LIMIT_CAP = 20

# Bounds how many _one() calls hold an AsyncSessionLocal() open at once,
# separately from _concurrency (which only bounds actual scraping). Without
# this, all `limit` (up to 20) fan-out calls open their DB session upfront
# and hold it for the whole get_or_scrape_maker_query call -- including the
# ones still just waiting their turn on _concurrency, doing nothing with
# the connection. Matches _concurrency's own cap: no more sessions held at
# once than can actually be scraping at once.
_leaderboard_db_gate = asyncio.Semaphore(4)


async def get_top_makers_leaderboard(
    db: AsyncSession, state_code: str, year: int, fuel: str | None = None, limit: int = 10,
) -> list[dict]:
    """Real (not modeled) maker ranking for one state/year, optionally
    scoped to one raw fuel value -- the actual-numbers alternative to
    MakersModels.tsx's log-linear ESTIMATE for a Maker x Fuel x Month
    combo, which has no real data source anywhere in this codebase.

    Which makers to look up is itself real: ranked by each maker's overall
    volume in that state/year from MakerCategoryTotal (real batch-scraped
    data, not modeled), so the shown leaderboard is the state's actual
    biggest players, not an arbitrary or global list. Their FUEL-scoped
    counts are then live-scraped (cached after) via
    get_or_scrape_maker_query -- one real CAPTCHA-solve per uncached maker,
    which is why `limit` is capped: an uncached call to this function pays
    that cost `limit` times (bounded to `_concurrency` at once, not fully
    serial, but still real work, not free)."""
    limit = min(limit, _LEADERBOARD_LIMIT_CAP)
    state_name = (await db.execute(select(State.state_name).where(State.state_code == state_code))).scalar()
    if state_name is None:
        raise UnknownStateCodeError(state_code)

    top_makers = (await db.execute(
        select(MakerCategoryTotal.maker, func.sum(MakerCategoryTotal.count).label("total"))
        .where(MakerCategoryTotal.state_code == state_code, MakerCategoryTotal.year == year)
        .group_by(MakerCategoryTotal.maker)
        .order_by(func.sum(MakerCategoryTotal.count).desc())
        .limit(limit)
    )).all()

    async def _one(maker: str) -> dict | None:
        # Own session, not the caller's `db` -- these run concurrently via
        # gather below, and SQLAlchemy AsyncSessions aren't safe to share
        # across concurrently-running coroutines (same lesson as the batch
        # scrapers' per-worker sessions). Gated separately from
        # _concurrency (see _leaderboard_db_gate) so at most 4 of these
        # hold a DB connection at once, not all `limit`.
        async with _leaderboard_db_gate:
            try:
                async with AsyncSessionLocal() as own_db:
                    records = await get_or_scrape_maker_query(own_db, state_code, year, maker, fuel)
                return {"maker": maker, "total": sum(r["count"] for r in records)}
            except TesseractUnavailableError:
                # A process-wide precondition, not a per-maker transient --
                # every remaining maker would fail identically, so surface
                # it as a real failure (the endpoint returns 503) instead of
                # silently degrading to an incomplete or empty leaderboard.
                raise
            except Exception:
                # A genuinely per-maker failure (that maker's CAPTCHA
                # rejected repeatedly, a one-off network blip) shouldn't
                # discard every other maker's already-succeeded result --
                # same isolation principle as the batch scrapers' per-worker
                # try/except.
                logger.warning("leaderboard: failed to fetch maker=%r state=%s year=%d fuel=%r -- skipping", maker, state_code, year, fuel)
                return None

    results = await asyncio.gather(*(_one(maker) for maker, _ in top_makers))
    ranked = [r for r in results if r is not None]
    return sorted(ranked, key=lambda r: r["total"], reverse=True)


async def search_makers(search_text: str, limit: int = 20) -> list[str]:
    """Real maker names matching `search_text`, straight from the source
    site -- lets a caller offer an actual autocomplete instead of requiring
    exact knowledge of a manufacturer's full legal name up front (confirmed
    live: "HONDA" alone matches nothing in the site's own vehicleMakers
    form field; the real entity is "HONDA MOTORCYCLE AND SCOOTER INDIA (P)
    LTD"). No CAPTCHA needed for this lookup (unlike scrape_state_year), but
    still gated by _concurrency: without it, a burst of concurrent search
    requests (search-as-you-type has no server-side rate limit, only the
    API's blanket 120/minute default) could each independently find the
    pool empty and bootstrap their own session at once -- unbounded
    concurrent hits against the same site the CAPTCHA-gated scrape path is
    otherwise careful to keep to 4 at a time, and _session_pool growing past
    the size every other comment in this file assumes it's capped at
    (found in review)."""
    search_text = search_text.strip()
    if not search_text:
        return []
    async with _concurrency:
        session = await _acquire_session()
        healthy = False
        try:
            results = await asyncio.wait_for(_search_makers_site(session.client, search_text, size=limit), timeout=15)
            healthy = True
            return results
        finally:
            await _release_session(session, healthy=healthy)
