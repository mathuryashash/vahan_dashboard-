import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

import httpx

from app.core.database import AsyncSessionLocal, engine
from app.core.scrape_lock import scrape_write_lock
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


# Floor on the boot catch-up delay: lets init_db / the first page loads finish
# before an overdue scrape starts competing for the pool.
BOOT_CATCHUP_MIN_DELAY_SECONDS = 60


async def _last_success_age_seconds() -> float | None:
    """Age of the last successful scrape according to the DATA (read-only)."""
    from app.services import data_freshness
    async with AsyncSessionLocal() as db:
        return (await data_freshness.get_freshness(db, use_cache=False)).age_seconds()


async def initial_delay_seconds(interval_hours: float = REFRESH_INTERVAL_HOURS) -> float:
    """Seconds until the first scheduled scrape after boot.

    The timer used to start at process start, so every restart reset it and a
    server restarted more often than every 5h never scraped at all. Now the
    first run is due `interval - age` after boot, where age is how long ago
    the last successful scrape finished (from the DB, so it survives
    restarts). Gated by SCRAPE_CATCHUP_ON_BOOT: off = the old full interval.
    No data / unreadable DB = full interval too -- a first-ever full backfill
    is an operator decision, not something a boot should start.
    """
    interval = interval_hours * 3600
    if not settings.SCRAPE_CATCHUP_ON_BOOT:
        return interval
    try:
        age = await _last_success_age_seconds()
    except Exception:
        logger.exception("Could not read last scrape age; using the full interval")
        return interval
    if age is None:
        return interval
    return max(float(BOOT_CATCHUP_MIN_DELAY_SECONDS), interval - age)


async def run_scheduler_loop() -> None:
    """Runs every REFRESH_INTERVAL_HOURS, counted from the last successful
    scrape in the DATA rather than from process start (see
    initial_delay_seconds and SCRAPE_CATCHUP_ON_BOOT).

    Consecutive failures back off exponentially (capped at MAX_BACKOFF_HOURS)
    instead of retrying at the normal 5h cadence forever -- a multi-day site
    outage would otherwise mean dozens of doomed attempts hammering it.
    """
    consecutive_failures = 0
    first = True
    while True:
        if first:
            delay = await initial_delay_seconds(REFRESH_INTERVAL_HOURS)
            first = False
        else:
            delay = _backoff_hours(REFRESH_INTERVAL_HOURS, consecutive_failures, MAX_BACKOFF_HOURS) * 3600
        next_run = datetime.now(timezone.utc) + timedelta(seconds=delay)
        logger.info("Next scheduled scrape at %s UTC (in %.2fh)", next_run.isoformat(), delay / 3600)
        await asyncio.sleep(delay)

        if settings.REFRESH_STATUS == "running":
            logger.info("Scheduled scrape skipped: a scrape is already running")
            continue

        started = time.monotonic()
        try:
            if await run_scraper(concurrent_states=settings.SCRAPER_CONCURRENT_STATES) is False:
                # Busy run lock: nothing ran, so neither a success (no backoff
                # reset, no "succeeded" line) nor a failure to back off on.
                logger.info("Scheduled scrape skipped (another scrape running)")
                continue
            logger.info("Scheduled scrape succeeded in %.0fs (after %d prior failures)", time.monotonic() - started, consecutive_failures)
            consecutive_failures = 0
        except Exception as exc:
            consecutive_failures += 1
            logger.error("Scheduled scrape failed after %.0fs (%d consecutive): %s", time.monotonic() - started, consecutive_failures, exc)


# ---------------------------------------------------------------------------
# NEW site (analytics.parivahan.gov.in): state x month x category (+ fuel).
# ---------------------------------------------------------------------------
# Later than the old loop's 60s floor on purpose: on a catch-up boot the
# old-site scrape takes the shared run lock first, and this one then waits
# its turn (ANALYTICS_BUSY_RETRY_SECONDS) instead of both racing at 60s.
ANALYTICS_BOOT_MIN_DELAY_SECONDS = 15 * 60
ANALYTICS_BUSY_RETRY_SECONDS = 30 * 60
ANALYTICS_MAX_BACKOFF_HOURS = 24 * 4
# run_analytics_refresh.py exit codes (see its docstring).
_ANALYTICS_EXIT_PARTIAL, _ANALYTICS_EXIT_BUSY, _ANALYTICS_EXIT_TESSERACT = 3, 4, 5


def _analytics_last_run_age_seconds() -> float | None:
    """Age of the last completed analytics refresh, from its summary file
    (the crosstab tables carry no timestamp column). None = never ran."""
    from scraper import analytics_refresh
    summary = analytics_refresh.read_last_summary()
    if not summary or not summary.get("finished_at"):
        return None
    finished = datetime.fromisoformat(summary["finished_at"])
    if finished.tzinfo is None:
        finished = finished.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - finished).total_seconds()


def analytics_initial_delay_seconds(interval_hours: float | None = None) -> float:
    """Same shape as initial_delay_seconds: `interval - age` after boot,
    floored at ANALYTICS_BOOT_MIN_DELAY_SECONDS. Never ran = overdue (the
    tables exist from hand-run backfills whose age is unknown). Catch-up off
    = the full interval."""
    interval = (interval_hours or settings.ANALYTICS_REFRESH_INTERVAL_HOURS) * 3600
    if not settings.SCRAPE_CATCHUP_ON_BOOT:
        return interval
    try:
        age = _analytics_last_run_age_seconds()
    except Exception:
        logger.exception("Could not read the last analytics refresh age; treating it as overdue")
        age = None
    if age is None:
        return float(ANALYTICS_BOOT_MIN_DELAY_SECONDS)
    return max(float(ANALYTICS_BOOT_MIN_DELAY_SECONDS), interval - age)


def _run_analytics_refresh_sync(holder: dict) -> tuple[int, list[str]]:
    """Run scraper.run_analytics_refresh as a child process (tesseract is
    driven via asyncio subprocesses, which uvicorn's Windows loop can't
    spawn -- same reason run_scraper uses child processes). Relays the
    child's output to this logger; returns (exit code, marker lines)."""
    import subprocess
    import sys
    proc = subprocess.Popen(
        [sys.executable, "-m", "scraper.run_analytics_refresh"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
    )
    holder["proc"] = proc
    markers = []
    for line in proc.stdout:
        line = line.rstrip()
        if line.startswith(("SUMMARY:", "TESSERACT_UNAVAILABLE:", "SCRAPE_ALREADY_RUNNING:")):
            markers.append(line)
        if " WARNING " in line or " ERROR " in line or line.startswith(("SUMMARY", "TESSERACT", "SCRAPE_")) \
                or "run_analytics_refresh:" in line or "analytics_refresh:" in line:
            logger.info("[analytics] %s", line)
    return proc.wait(), markers


async def run_analytics_refresh_once() -> str:
    """One scheduled analytics refresh. Returns 'ok' | 'partial' | 'busy' |
    'tesseract' | 'failed'. Kills the child if cancelled (app shutdown)."""
    from app.services import source_health
    holder: dict = {}
    try:
        code, markers = await asyncio.to_thread(_run_analytics_refresh_sync, holder)
    except asyncio.CancelledError:
        proc = holder.get("proc")
        if proc is not None and proc.poll() is None:
            proc.kill()  # its DB connection drops, which releases the advisory locks
        raise
    if code == _ANALYTICS_EXIT_BUSY:
        return "busy"
    if code == _ANALYTICS_EXIT_TESSERACT:
        detail = next((m.split(":", 1)[1].strip() for m in markers if m.startswith("TESSERACT")),
                      "tesseract unavailable")
        source_health.record_analytics_scrape(False, f"tesseract unavailable: {detail}")
        return "tesseract"
    if code in (0, _ANALYTICS_EXIT_PARTIAL):
        # The child wrote the crosstabs in another process; this process's
        # response caches still hold pre-refresh numbers for up to 600 s.
        from app.core.cache import TTLCache
        TTLCache.clear_all()
        source_health.record_analytics_scrape(True, "last scheduled refresh completed", load_summary=True)
        return "ok" if code == 0 else "partial"
    source_health.record_analytics_scrape(False, f"refresh process exited with code {code}")
    raise RuntimeError(f"analytics refresh exited with code {code}")


async def run_analytics_scheduler_loop() -> None:
    """Refreshes the analytics crosstabs every ANALYTICS_REFRESH_INTERVAL_HOURS
    (first run from the last run's age, like run_scheduler_loop). Shares the
    one scrape run lock with every other scrape: busy -> 'skipped (another
    scrape running)' and a retry ANALYTICS_BUSY_RETRY_SECONDS later, no
    backoff. Failures (incl. tesseract missing) back off exponentially;
    tesseract missing is logged at ERROR once per streak and marks the
    analytics source unhealthy in source-health. Never raises: a broken
    analytics scraper must not take the app down."""
    consecutive_failures = 0
    tesseract_reported = False
    delay = analytics_initial_delay_seconds()
    while True:
        interval_h = settings.ANALYTICS_REFRESH_INTERVAL_HOURS
        next_run = datetime.now(timezone.utc) + timedelta(seconds=delay)
        logger.info("Next analytics refresh at %s UTC (in %.2fh)", next_run.isoformat(), delay / 3600)
        await asyncio.sleep(delay)
        if settings.REFRESH_STATUS == "running":
            logger.info("Scheduled analytics refresh skipped (another scrape running)")
            delay = ANALYTICS_BUSY_RETRY_SECONDS
            continue
        started = time.monotonic()
        try:
            outcome = await run_analytics_refresh_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            outcome = "failed"
            logger.error("Scheduled analytics refresh failed after %.0fs: %s", time.monotonic() - started, exc)
        if outcome == "busy":
            logger.info("Scheduled analytics refresh skipped (another scrape running)")
            delay = ANALYTICS_BUSY_RETRY_SECONDS
            continue
        if outcome in ("ok", "partial"):
            logger.info("Scheduled analytics refresh %s in %.0fs (after %d prior failures)",
                        "succeeded" if outcome == "ok" else "finished with unrefreshed combos (see summary)",
                        time.monotonic() - started, consecutive_failures)
            consecutive_failures = 0
            tesseract_reported = False
        else:
            consecutive_failures += 1
            if outcome == "tesseract":
                if not tesseract_reported:
                    logger.error("ANALYTICS SCRAPER DISABLED: tesseract OCR is not installed or cannot read "
                                 "CAPTCHAs, so state x month x category tables will go stale. Install "
                                 "tesseract-ocr (see analytics_scraper.TesseractUnavailableError).")
                    tesseract_reported = True
                else:
                    logger.warning("analytics refresh: tesseract still unavailable (%d consecutive)",
                                   consecutive_failures)
        delay = _backoff_hours(interval_h, consecutive_failures, ANALYTICS_MAX_BACKOFF_HOURS) * 3600


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
                # Same lock key as backfill_fada.py so a manual backfill run
                # and this scheduled loop can't overlap on oem_monthly_sales.
                async with scrape_write_lock(engine, "oem_monthly_sales"), AsyncSessionLocal() as db:
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
                            # Without this, a DB-level failure (e.g. the
                            # oem_monthly_sales natural-key constraint) leaves
                            # this shared session's transaction aborted --
                            # every subsequent release in new_releases would
                            # then also fail (PendingRollbackError) and never
                            # get a FadaScrapeAttempt row, so it's retried
                            # forever on the next 24h cycle instead of just
                            # this one release.
                            await db.rollback()
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
            if await run_scraper(concurrent_states=settings.SCRAPER_CONCURRENT_STATES, force=True, year=previous_year) is False:
                logger.info("Previous-year revalidation (%d) skipped (another scrape running)", previous_year)
                continue
            logger.info("Previous-year revalidation (%d) succeeded in %.0fs", previous_year, time.monotonic() - started)
            consecutive_failures = 0
        except Exception as exc:
            consecutive_failures += 1
            logger.error("Previous-year revalidation (%d) failed after %.0fs (%d consecutive): %s", previous_year, time.monotonic() - started, consecutive_failures, exc)
