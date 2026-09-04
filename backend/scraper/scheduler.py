import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

import httpx

from app.core.database import AsyncSessionLocal
from app.services.scraper_service import run_scraper
from scraper.fada_scraper import discover_releases, parse_release_pdf, persist_oem_sales
from app.core.config import settings

logger = logging.getLogger("scheduler")

REFRESH_INTERVAL_HOURS = 5
FADA_CHECK_INTERVAL_HOURS = 24
PREVIOUS_YEAR_REVALIDATION_INTERVAL_HOURS = 24
# Caps how far a failing loop's interval can back off to -- without this, a
# multi-day site outage would otherwise mean a monotonically growing sleep
# that never comes back down to check again in reasonable time.
MAX_BACKOFF_HOURS = 24
FADA_MAX_BACKOFF_HOURS = 24 * 7


def _backoff_hours(base_hours: float, consecutive_failures: int, cap_hours: float) -> float:
    if consecutive_failures == 0:
        return base_hours
    return min(base_hours * (2 ** consecutive_failures), cap_hours)


async def run_scheduler_loop() -> None:
    """Runs every REFRESH_INTERVAL_HOURS without scraping on server startup.

    A restart should make the dashboard available, not immediately trigger a
    multi-hour third-party scrape. Operators can still use the refresh action
    when they explicitly need fresh data.

    Consecutive failures back off exponentially (capped at MAX_BACKOFF_HOURS)
    instead of retrying at the normal 5h cadence forever -- a multi-day site
    outage would otherwise mean dozens of doomed attempts hammering it.
    """
    consecutive_failures = 0
    while True:
        interval_hours = _backoff_hours(REFRESH_INTERVAL_HOURS, consecutive_failures, MAX_BACKOFF_HOURS)
        next_run = datetime.now(timezone.utc) + timedelta(hours=interval_hours)
        logger.info("Next scheduled scrape at %s UTC (interval %.1fh)", next_run.isoformat(), interval_hours)
        await asyncio.sleep(interval_hours * 3600)

        started = time.monotonic()
        try:
            await run_scraper(concurrent_states=settings.SCRAPER_CONCURRENT_STATES)
            logger.info("Scheduled scrape succeeded in %.0fs (after %d prior failures)", time.monotonic() - started, consecutive_failures)
            consecutive_failures = 0
        except Exception as exc:
            consecutive_failures += 1
            logger.error("Scheduled scrape failed after %.0fs (%d consecutive): %s", time.monotonic() - started, consecutive_failures, exc)


async def run_fada_scheduler_loop() -> None:
    """Checks FADA's archive once a day for a release not yet attempted,
    and ingests it if found. FADA publishes monthly, not continuously, so
    this runs on its own 24h cadence -- deliberately not folded into
    run_scheduler_loop's 5h VAHAN cadence, since they're different sources
    with no reason to be coupled.

    "Already attempted" is tracked in FadaScrapeAttempt, not by checking
    OEMMonthlySales.source_document -- a release whose PDF layout defeats
    extraction never gets an OEMMonthlySales row, so that check alone would
    re-fetch and re-parse the same permanently-failing releases every single
    cycle, forever (confirmed live: ~15 pre-2022 releases were being
    re-parsed on every restart before this fix).
    """
    consecutive_failures = 0
    while True:
        started = time.monotonic()
        ingested = 0
        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"},
                timeout=30,
                follow_redirects=True,
            ) as client:
                releases = await discover_releases(client)
                async with AsyncSessionLocal() as db:
                    from sqlalchemy import select
                    from app.models.models import FadaScrapeAttempt, OEMMonthlySales

                    existing = await db.execute(select(FadaScrapeAttempt.source_document))
                    attempted_titles = {row[0] for row in existing.all()}

                    # One-time backfill for the first run after this table was
                    # introduced: without it, every release already sitting in
                    # OEMMonthlySales from before this table existed looks
                    # "never attempted" and gets needlessly re-fetched and
                    # re-parsed in this single cycle (idempotent, but a real
                    # burst of load against FADA's site for no reason -- the
                    # data's already ingested).
                    if not attempted_titles:
                        already_ingested = await db.execute(select(OEMMonthlySales.source_document).distinct())
                        backfill_titles = {row[0] for row in already_ingested.all()}
                        if backfill_titles:
                            db.add_all([
                                FadaScrapeAttempt(source_document=title, status="ingested", row_count=0)
                                for title in backfill_titles
                            ])
                            await db.commit()
                            attempted_titles = backfill_titles
                            logger.info("FADA scheduler: backfilled %d already-ingested titles into FadaScrapeAttempt", len(backfill_titles))

                    new_releases = [r for r in releases if r["title"] not in attempted_titles]
                    # One release failing to fetch/parse must not block every
                    # other new release behind it for the next 24h -- mirrors
                    # backfill_fada.py's per-release try/except.
                    for release in new_releases:
                        try:
                            resp = await client.get(release["pdf_url"])
                            resp.raise_for_status()
                            # pdfplumber is synchronous/CPU-bound -- run off
                            # the event loop so a big PDF (or a long backlog
                            # of them) doesn't stall every concurrent API
                            # request for the whole scan.
                            rows = await asyncio.to_thread(parse_release_pdf, resp.content)
                            if rows:
                                await persist_oem_sales(db, rows, source="FADA", source_document=release["title"])
                                db.add(FadaScrapeAttempt(source_document=release["title"], status="ingested", row_count=len(rows)))
                                await db.commit()
                                ingested += 1
                                logger.info("FADA scheduler: ingested new release %r", release["title"])
                            else:
                                db.add(FadaScrapeAttempt(source_document=release["title"], status="failed_extraction", row_count=0))
                                await db.commit()
                                logger.warning("FADA scheduler: extraction returned 0 rows for %r, marking attempted so it isn't retried every cycle", release["title"])
                        except Exception as exc:
                            logger.error("FADA scheduler: failed processing %r: %s", release["title"], exc)
            logger.info("FADA scheduled check succeeded in %.0fs, ingested %d release(s)", time.monotonic() - started, ingested)
            consecutive_failures = 0
        except Exception as exc:
            consecutive_failures += 1
            logger.error("FADA scheduled check failed after %.0fs (%d consecutive): %s", time.monotonic() - started, consecutive_failures, exc)

        interval_hours = _backoff_hours(FADA_CHECK_INTERVAL_HOURS, consecutive_failures, FADA_MAX_BACKOFF_HOURS)
        await asyncio.sleep(interval_hours * 3600)


async def run_previous_year_revalidation_loop() -> None:
    """Once every 24h, re-scrapes last calendar year (all 3 dimensions,
    force=True) so it isn't frozen the moment the current year rolls over.
    run_scheduler_loop's 5h loop only ever scrapes the current year (see
    run_scraper's `year` param) -- without this, the day 2026 becomes "last
    year" it stops getting re-validated forever, and any stale-page/
    duplicate-row defect present at that moment is permanent.

    This is a genuinely significant recurring load, not a cheap check like
    the FADA loop above: a full previous-year revalidation is the same
    multi-hour, all-India, all-3-dimension scrape a manual Refresh triggers
    -- once a day, indefinitely. It shares run_scraper's REFRESH_STATUS
    guard with the manual Refresh button and the 5h current-year loop, so
    it can't run concurrently with either (it skips its turn and retries
    next cycle if one is already in progress), but it does NOT reduce how
    often VAHAN gets hit overall -- it adds a full extra pass every day.
    If that's not wanted, this loop is safe to not start (see main.py).
    """
    from app.core.config import settings
    from app.services.scraper_service import run_scraper

    consecutive_failures = 0
    while True:
        interval_hours = _backoff_hours(PREVIOUS_YEAR_REVALIDATION_INTERVAL_HOURS, consecutive_failures, MAX_BACKOFF_HOURS)
        await asyncio.sleep(interval_hours * 3600)

        if settings.REFRESH_STATUS == "running":
            logger.info("Previous-year revalidation: a scrape is already running, skipping this cycle")
            continue

        previous_year = datetime.now(timezone.utc).year - 1
        started = time.monotonic()
        try:
            await run_scraper(concurrent_states=settings.SCRAPER_CONCURRENT_STATES, force=True, year=previous_year)
            logger.info("Previous-year revalidation (%d) succeeded in %.0fs", previous_year, time.monotonic() - started)
            consecutive_failures = 0
        except Exception as exc:
            consecutive_failures += 1
            logger.error("Previous-year revalidation (%d) failed after %.0fs (%d consecutive): %s", previous_year, time.monotonic() - started, consecutive_failures, exc)
