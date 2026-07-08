import asyncio
import logging
from datetime import datetime, timedelta

from app.services.scraper_service import run_scraper

logger = logging.getLogger("scheduler")

REFRESH_INTERVAL_HOURS = 24


async def run_scheduler_loop() -> None:
    """Runs run_scraper() once immediately, then every REFRESH_INTERVAL_HOURS forever.
    Intended to be launched as a background asyncio task from the FastAPI lifespan.
    """
    while True:
        try:
            await run_scraper()
        except Exception as exc:
            logger.error("Scheduled scrape failed: %s", exc)

        next_run = datetime.utcnow() + timedelta(hours=REFRESH_INTERVAL_HOURS)
        logger.info("Next scheduled scrape at %s UTC", next_run.isoformat())
        await asyncio.sleep(REFRESH_INTERVAL_HOURS * 3600)
