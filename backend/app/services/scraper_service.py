import asyncio
import logging
import sys
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.query_filters import classify_vehicle
from app.models.models import MakerCategoryTotal, Registration, State
from scraper.vahan_scraper import DIMENSIONS

logger = logging.getLogger("scraper_service")


class ScrapeFailedError(RuntimeError):
    """A completed scraper run that could not refresh the source data."""


def _mark_retry_pending(message: str) -> None:
    settings.REFRESH_STATUS = "retrying"
    settings.REFRESH_ERROR = message


async def persist_rto_batch(db: AsyncSession, batch: dict, state_code: str, dimension: str = "maker") -> None:
    """Replace any existing rows for this (rto_code, year, dimension) with the
    freshly scraped ones. `dimension` is one of 'maker' | 'vehicle_class' | 'fuel'
    (see scraper.vahan_scraper.DIMENSIONS) and controls which column a row's
    `label` maps to:

      - 'maker': the canonical pass. vehicle_class='All' (unknown at this
        granularity), maker=<real>, is_supplementary=False. This is the one
        "total registrations" queries should sum -- see Registration.is_supplementary.
      - 'vehicle_class' / 'fuel': supplementary breakdown passes over the SAME
        underlying registrations already counted by the maker pass. maker=None,
        is_supplementary=True, and the label goes into vehicle_class or
        fuel_type respectively (vehicle_class defaults to 'All' for the fuel
        pass, since it doesn't carry class info either).

    The delete-before-insert is scoped by dimension too (not just rto_code/year):
    re-scraping the vehicle_class pass must not delete fuel-pass rows for the
    same RTO/year, and vice versa -- they coexist as separate rows.
    """
    rto_code = batch["rto_code"]
    is_supplementary = dimension != "maker"
    years = {r["year"] for r in batch["records"]}
    for year in years:
        delete_query = delete(Registration).where(
            Registration.rto_code == rto_code,
            Registration.year == year,
            Registration.is_supplementary == is_supplementary,
        )
        if dimension == "vehicle_class":
            delete_query = delete_query.where(Registration.fuel_type.is_(None))
        elif dimension == "fuel":
            delete_query = delete_query.where(Registration.fuel_type.isnot(None))
        await db.execute(delete_query)

    for record in batch["records"]:
        fields = dict(
            state_code=state_code,
            state_name=batch["state_name"],
            rto_code=rto_code,
            rto_name=batch["rto_name"],
            month=record["month"],
            year=record["year"],
            count=record["count"],
            is_supplementary=is_supplementary,
        )
        if dimension == "maker":
            fields.update(vehicle_class="All", maker=record["label"], fuel_type=None)
        elif dimension == "vehicle_class":
            fields.update(vehicle_class=record["label"], maker=None, fuel_type=None)
        elif dimension == "fuel":
            fields.update(vehicle_class="All", maker=None, fuel_type=record["label"])
        else:
            raise ValueError(f"Unknown dimension: {dimension!r}")
        category, tier = classify_vehicle(fields["vehicle_class"])
        fields.update(vehicle_category=category, commercial_tier=tier)
        db.add(Registration(**fields))


async def persist_maker_category_batch(db: AsyncSession, batch: dict, state_code: str, year: int) -> None:
    """Replace any existing MakerCategoryTotal rows for this (rto_code, year)
    with freshly scraped ones. Separate table, separate delete-before-insert
    scope from persist_rto_batch -- this pivot has no month column and no
    is_supplementary concept, it's a genuinely different shape, not another
    Registration dimension (see docs/superpowers/specs/
    2026-08-25-maker-category-crosstab-design.md)."""
    rto_code = batch["rto_code"]
    await db.execute(
        delete(MakerCategoryTotal).where(
            MakerCategoryTotal.rto_code == rto_code,
            MakerCategoryTotal.year == year,
        )
    )
    for record in batch["records"]:
        category, tier = classify_vehicle(record["vehicle_class"])
        db.add(MakerCategoryTotal(
            state_code=state_code,
            state_name=batch["state_name"],
            rto_code=rto_code,
            rto_name=batch["rto_name"],
            year=year,
            maker=record["maker"],
            vehicle_class=record["vehicle_class"],
            vehicle_category=category,
            commercial_tier=tier,
            count=record["count"],
        ))


async def _state_code_lookup(db: AsyncSession) -> dict[str, str]:
    result = await db.execute(select(State.state_name, State.state_code))
    return {name: code for name, code in result.all()}


def _run_dimension_sync(dimension: str, concurrent_states: int = 1, force: bool = True) -> int:
    import subprocess
    cmd = [sys.executable, "-m", "scraper.run_full_scrape", "--dimension", dimension, "--concurrent-states", str(concurrent_states)]
    if force:
        cmd.append("--force")
    logger.info("Starting scraper subprocess for dimension: %s (concurrent_states=%s, force=%s)", dimension, concurrent_states, force)
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    while True:
        line = proc.stdout.readline()
        if not line and proc.poll() is not None:
            break
        if line:
            logger.info("[scraper:%s] %s", dimension, line.rstrip())
    return proc.wait()


async def run_scraper(concurrent_states: int = 1, force: bool = True) -> None:
    """Launch the full-India live scrape as separate OS processes and await completion.

    Playwright's Chromium subprocess was observed (during manual verification) to crash
    reliably within seconds when driven from an asyncio task sharing uvicorn's event
    loop, but runs cleanly as a fully independent process. We offload execution to a
    background thread using asyncio.to_thread with subprocess.Popen to prevent Uvicorn's
    Windows event loop policy from causing NotImplementedError.

    The three dimensions are independent full-India passes with no shared
    in-memory state (each is its own OS process, its own httpx session, its
    own ViewState) -- there's no correctness reason to run them one after
    another, only a historical one. Running them concurrently cuts wall time
    roughly 3x, bounded by whichever dimension is slowest, without adding any
    load on the target site beyond what already happens serially today (same
    three sessions, same per-RTO throttle each -- just overlapped in time
    instead of laid end to end). The only new risk this introduces is three
    processes writing to PostgreSQL through independent connection pools.

    `concurrent_states` controls how many states are scraped in parallel within
    each dimension process. Each state runs in its own HTTP session with its
    own pacing (1.5s between RTO requests), so N concurrent states means
    N requests every ~1.5s instead of 1.

    `force` (default True): re-scrape every RTO for the current year even if
    it already has data. run_full_scrape.py's --year always defaults to the
    current calendar year, so this never touches historical years -- but
    without it, VAHAN's own late/backfilled registrations for recent months
    never get picked up: any RTO that already has *a* row for this year gets
    silently skipped, so the same stale numbers persist run after run no
    matter how often the scheduler fires.
    """
    settings.REFRESH_STATUS = "running"
    settings.REFRESH_ERROR = None
    settings.LAST_REFRESH_STARTED_AT = datetime.now(timezone.utc)
    logger.info("Starting live VAHAN4 scrape at %s (concurrent_states=%s, force=%s)", settings.LAST_REFRESH_STARTED_AT, concurrent_states, force)

    try:
        results = await asyncio.gather(
            *(asyncio.to_thread(_run_dimension_sync, dimension, concurrent_states, force) for dimension in DIMENSIONS),
            return_exceptions=True,
        )
    except asyncio.CancelledError:
        # A shutdown is not a failed refresh. Leave the next server instance
        # free to schedule its normal run.
        settings.REFRESH_STATUS = "idle"
        raise
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        _mark_retry_pending(message)
        logger.error("Scraper failed: %s", exc)
        raise ScrapeFailedError(message) from exc

    for dimension, result in zip(DIMENSIONS, results):
        if isinstance(result, BaseException):
            message = f"Scraper subprocess for {dimension} raised: {result}"
            _mark_retry_pending(message)
            logger.error(message)
            raise ScrapeFailedError(message) from result
        if result != 0:
            message = f"Scraper subprocess for {dimension} exited with code {result}"
            _mark_retry_pending(message)
            logger.error(message)
            raise ScrapeFailedError(message)

    settings.LAST_UPDATED = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    settings.REFRESH_STATUS = "success"
    logger.info("Live VAHAN4 scrape complete.")
