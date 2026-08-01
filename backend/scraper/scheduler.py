import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

import httpx

from app.core.database import AsyncSessionLocal
from app.services.scraper_service import run_scraper
from scraper.fada_scraper import discover_releases, parse_release_pdf, persist_oem_sales

logger = logging.getLogger("scheduler")

REFRESH_INTERVAL_HOURS = 5
FADA_CHECK_INTERVAL_HOURS = 24
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
            await run_scraper()
            logger.info("Scheduled scrape succeeded in %.0fs (after %d prior failures)", time.monotonic() - started, consecutive_failures)
            consecutive_failures = 0
        except Exception as exc:
            consecutive_failures += 1
            logger.error("Scheduled scrape failed after %.0fs (%d consecutive): %s", time.monotonic() - started, consecutive_failures, exc)


async def run_fada_scheduler_loop() -> None:
    """Checks FADA's archive once a day for a release not yet in
    oem_monthly_sales, and ingests it if found. FADA publishes monthly, not
    continuously, so this runs on its own 24h cadence -- deliberately not
    folded into run_scheduler_loop's 5h VAHAN cadence, since they're
    different sources with no reason to be coupled.
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
                    from app.models.models import OEMMonthlySales
                    existing = await db.execute(select(OEMMonthlySales.source_document).distinct())
                    known_titles = {row[0] for row in existing.all()}

                    new_releases = [r for r in releases if r["title"] not in known_titles]
                    # One release failing to fetch/parse must not block every
                    # other new release behind it for the next 24h -- mirrors
                    # backfill_fada.py's per-release try/except.
                    for release in new_releases:
                        try:
                            resp = await client.get(release["pdf_url"])
                            resp.raise_for_status()
                            rows = parse_release_pdf(resp.content)
                            if rows:
                                await persist_oem_sales(db, rows, source="FADA", source_document=release["title"])
                                await db.commit()
                                ingested += 1
                                logger.info("FADA scheduler: ingested new release %r", release["title"])
                        except Exception as exc:
                            logger.error("FADA scheduler: failed processing %r: %s", release["title"], exc)
            logger.info("FADA scheduled check succeeded in %.0fs, ingested %d release(s)", time.monotonic() - started, ingested)
            consecutive_failures = 0
        except Exception as exc:
            consecutive_failures += 1
            logger.error("FADA scheduled check failed after %.0fs (%d consecutive): %s", time.monotonic() - started, consecutive_failures, exc)

        interval_hours = _backoff_hours(FADA_CHECK_INTERVAL_HOURS, consecutive_failures, FADA_MAX_BACKOFF_HOURS)
        await asyncio.sleep(interval_hours * 3600)
