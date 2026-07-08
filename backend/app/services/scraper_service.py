import asyncio
import logging
import sys
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.models import Registration, State

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
    """Launch the full-India live scrape as a separate OS process and await completion.

    Playwright's Chromium subprocess was observed (during manual verification) to crash
    reliably within seconds when driven from an asyncio task sharing uvicorn's event
    loop, but runs cleanly as a fully independent process. See scraper/run_full_scrape.py
    for the actual scrape + persist logic; persist_rto_batch/_state_code_lookup above are
    reused by that script (and covered directly by tests here, without needing a subprocess).
    """
    logger.info("Starting live VAHAN4 scrape (subprocess) at %s", datetime.utcnow())
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "scraper.run_full_scrape",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    if process.stdout is not None:
        async for line in process.stdout:
            logger.info("[scraper] %s", line.decode(errors="replace").rstrip())
    returncode = await process.wait()

    if returncode == 0:
        settings.LAST_UPDATED = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        logger.info("Live VAHAN4 scrape complete.")
    else:
        logger.error("Scraper subprocess exited with code %s", returncode)
