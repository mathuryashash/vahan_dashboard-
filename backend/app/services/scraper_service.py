import logging
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.config import settings
from app.models.models import Registration, State
from scraper.vahan_scraper import scrape_all_india

logger = logging.getLogger("scraper_service")


async def persist_rto_batch(db: AsyncSession, batch: dict, state_code: str) -> None:
    """Replace any existing rows for this (rto_code, year) with the freshly scraped ones."""
    rto_code = batch["rto_code"]
    years = {r["year"] for r in batch["records"]}
    for year in years:
        await db.execute(
            delete(Registration).where(
                Registration.rto_code == rto_code, Registration.year == year
            )
        )
    for record in batch["records"]:
        db.add(
            Registration(
                state_code=state_code,
                state_name=batch["state_name"],
                rto_code=rto_code,
                rto_name=batch["rto_name"],
                month=record["month"],
                year=record["year"],
                vehicle_class="All",
                maker=record["maker"],
                count=record["count"],
            )
        )


async def _state_code_lookup(db: AsyncSession) -> dict[str, str]:
    result = await db.execute(select(State.state_name, State.state_code))
    return {name: code for name, code in result.all()}


async def run_scraper() -> None:
    """Full-India live scrape: iterate every state/RTO on vahan4dashboard and persist results.
    Designed to run as a long-lived background task (can take over an hour for all of India).
    """
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

    settings.LAST_UPDATED = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    logger.info("Live VAHAN4 scrape complete. %d RTOs processed.", rto_count)
