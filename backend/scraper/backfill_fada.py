"""One-time backfill of FADA's full public "Vehicle Retail Data" archive
(confirmed live on 2026-07-15: ~Aug 2021 through present, 5 archive pages)
into oem_monthly_sales. Safe to re-run -- persist_oem_sales is idempotent
per (source, year, month, category).

Usage: python -m scraper.backfill_fada
"""
import asyncio
import logging

import httpx

from app.core.database import AsyncSessionLocal, init_db
from scraper.fada_scraper import discover_releases, parse_release_pdf, persist_oem_sales

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_fada")

REQUEST_DELAY_SECONDS = 2.5


async def main() -> None:
    await init_db()

    async with httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"},
        timeout=30,
        follow_redirects=True,
    ) as client:
        releases = await discover_releases(client)
        logger.info("Found %d Vehicle Retail Data releases", len(releases))

        async with AsyncSessionLocal() as db:
            for release in releases:
                try:
                    resp = await client.get(release["pdf_url"])
                    resp.raise_for_status()
                    rows = parse_release_pdf(resp.content)
                    if not rows:
                        logger.warning("No OEM rows parsed from %r, skipping", release["title"])
                        continue
                    await persist_oem_sales(db, rows, source="FADA", source_document=release["title"])
                    await db.commit()
                    logger.info("Persisted %d rows from %r", len(rows), release["title"])
                except Exception as exc:
                    logger.error("Failed processing %r: %s", release["title"], exc)
                finally:
                    await asyncio.sleep(REQUEST_DELAY_SECONDS)

    logger.info("FADA backfill complete.")


if __name__ == "__main__":
    asyncio.run(main())
