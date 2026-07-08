"""Standalone entrypoint for a full-India live scrape. Run as its own OS process
(never as an in-process asyncio task inside the FastAPI/uvicorn server) — Playwright's
Chromium subprocess was observed to crash reliably within seconds when driven from a
background task sharing uvicorn's event loop, but runs cleanly as an independent process.
See app.services.scraper_service.run_scraper(), which launches this via subprocess.
"""
import asyncio
import logging
from datetime import datetime

from app.core.database import AsyncSessionLocal
from app.services.scraper_service import persist_rto_batch, _state_code_lookup
from scraper.vahan_scraper import scrape_all_india

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("run_full_scrape")


async def main() -> None:
    logger.info("Starting live VAHAN4 scrape at %s", datetime.utcnow())
    year = datetime.now().year

    async with AsyncSessionLocal() as db:
        state_codes = await _state_code_lookup(db)

        rto_count = 0
        async for batch in scrape_all_india(year=year):
            code = state_codes.get(batch["state_name"])
            if code is None:
                logger.warning("No state_code found for '%s', skipping batch", batch["state_name"])
                continue
            await persist_rto_batch(db, batch, state_code=code)
            await db.commit()
            rto_count += 1
            if rto_count % 25 == 0:
                logger.info("Scraped %d RTOs so far...", rto_count)

    logger.info("Live VAHAN4 scrape complete. %d RTOs processed.", rto_count)


if __name__ == "__main__":
    asyncio.run(main())
