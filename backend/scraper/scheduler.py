import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx

from app.core.database import AsyncSessionLocal
from app.services.scraper_service import run_scraper
from scraper.fada_scraper import discover_releases, parse_release_pdf, persist_oem_sales

logger = logging.getLogger("scheduler")

REFRESH_INTERVAL_HOURS = 5
FADA_CHECK_INTERVAL_HOURS = 24


async def run_scheduler_loop() -> None:
    """Runs run_scraper() once immediately, then every REFRESH_INTERVAL_HOURS forever.
    Intended to be launched as a background asyncio task from the FastAPI lifespan.

    The sleep is measured from when a run *finishes*, not from a fixed clock,
    so this loop can never overlap itself -- there's no separate lock needed
    here. REFRESH_INTERVAL_HOURS=5 only gives a real ~5h cadence now that
    run_scraper() runs its three dimensions concurrently (~1-1.5h wall time);
    at the old sequential ~4.5h runtime this would have meant a ~9.5h cycle
    (scrape time + 5h idle), not 5h.
    """
    while True:
        try:
            await run_scraper()
        except Exception as exc:
            logger.error("Scheduled scrape failed: %s", exc)

        next_run = datetime.now(timezone.utc) + timedelta(hours=REFRESH_INTERVAL_HOURS)
        logger.info("Next scheduled scrape at %s UTC", next_run.isoformat())
        await asyncio.sleep(REFRESH_INTERVAL_HOURS * 3600)


async def run_fada_scheduler_loop() -> None:
    """Checks FADA's archive once a day for a release not yet in
    oem_monthly_sales, and ingests it if found. FADA publishes monthly, not
    continuously, so this runs on its own 24h cadence -- deliberately not
    folded into run_scheduler_loop's 5h VAHAN cadence, since they're
    different sources with no reason to be coupled.
    """
    while True:
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
                    for release in new_releases:
                        resp = await client.get(release["pdf_url"])
                        resp.raise_for_status()
                        rows = parse_release_pdf(resp.content)
                        if rows:
                            await persist_oem_sales(db, rows, source="FADA", source_document=release["title"])
                            await db.commit()
                            logger.info("FADA scheduler: ingested new release %r", release["title"])
        except Exception as exc:
            logger.error("FADA scheduled check failed: %s", exc)

        await asyncio.sleep(FADA_CHECK_INTERVAL_HOURS * 3600)
