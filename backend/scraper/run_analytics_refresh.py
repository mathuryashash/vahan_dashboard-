"""CLI / child-process entrypoint for the scheduled analytics refresh.

    python -m scraper.run_analytics_refresh                 # the scheduled plan (plan_years)
    python -m scraper.run_analytics_refresh --year 2026     # one explicit year
    python -m scraper.run_analytics_refresh --wait-for-lock # queue behind a running scrape

Exit codes: 0 every combo refreshed; 3 finished but some combos failed /
were rejected after their retry (see the summary); 4 another scrape holds the
shared run lock (nothing ran); 5 tesseract unavailable (nothing ran);
1 crash. The run summary is written to SCRAPER_DATA_DIR/analytics_refresh_last.json
and its path printed as ``SUMMARY: <path>``.
"""
import argparse
import asyncio
import logging
import sys

from scraper import pool_sizing

pool_sizing.concurrent_workers()  # before any app.* import -- see that module's docstring

from app.core.config import settings  # noqa: E402
from app.core.database import engine, init_db  # noqa: E402
from app.core.scrape_lock import (  # noqa: E402
    SCRAPE_BUSY_EXIT_CODE, ScrapeAlreadyRunningError, ScrapeRunLockBusyError, scrape_run_lock,
)
from scraper import analytics_refresh  # noqa: E402
from scraper.analytics_scraper import TesseractUnavailableError, verify_tesseract  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("run_analytics_refresh")

TESSERACT_EXIT_CODE = 5
PARTIAL_EXIT_CODE = 3
LOCK_POLL_SECONDS = 60


async def _hold_run_lock(wait: bool):
    while True:
        try:
            cm = scrape_run_lock(engine, "run_analytics_refresh")
            await cm.__aenter__()
            return cm
        except ScrapeRunLockBusyError:
            if not wait:
                raise
            logger.info("another scrape holds the run lock; waiting %ds", LOCK_POLL_SECONDS)
            await asyncio.sleep(LOCK_POLL_SECONDS)


async def main(years: list[int] | None, concurrent: int, wait: bool, states: frozenset[str] | None,
               only_failures: bool = False) -> int:
    await init_db()
    try:
        tesseract_path = await verify_tesseract()
    except TesseractUnavailableError as exc:
        print(f"TESSERACT_UNAVAILABLE: {exc}", flush=True)
        return TESSERACT_EXIT_CODE
    only = None
    if only_failures:
        last = analytics_refresh.read_last_summary() or {}
        only = [(f["year"], f["state"], f["fuel"]) for f in last.get("failures", [])]
        if not only:
            print("no failures in the last summary -- nothing to retry", flush=True)
            return 0
        years = sorted({y for y, _, _ in only})
    years = years or analytics_refresh.plan_years(analytics_refresh.today_ist())
    try:
        lock = await _hold_run_lock(wait)
    except ScrapeRunLockBusyError as exc:
        print(f"SCRAPE_ALREADY_RUNNING: {exc}", flush=True)
        return SCRAPE_BUSY_EXIT_CODE
    try:
        state_list = None
        if states:
            state_list = [s for s in await analytics_refresh._states() if s[0] in states]
        logger.info("analytics refresh: years=%s concurrent=%d", years, concurrent)
        try:
            summary = await analytics_refresh.run_refresh(
                years, tesseract_path=tesseract_path, concurrent=concurrent, states=state_list, only=only)
        except ScrapeAlreadyRunningError as exc:  # a hand-run runner holds a per-year key
            print(f"SCRAPE_ALREADY_RUNNING: {exc}", flush=True)
            return SCRAPE_BUSY_EXIT_CODE
    finally:
        await lock.__aexit__(None, None, None)
    summary["trigger"] = "cli" if sys.stdin and sys.stdin.isatty() else "scheduled"
    if only_failures:  # keep the full run's summary (and the scheduler's age) intact
        summary["retry_of"] = analytics_refresh.read_last_summary().get("finished_at")
        path = analytics_refresh.write_summary(
            summary, analytics_refresh.summary_path().with_name("analytics_refresh_retry_last.json"))
    else:
        path = analytics_refresh.write_summary(summary)
    logger.info("analytics refresh done in %.0fs: %d combos, %d requests, %d failed, %d rejected, "
                "%d state-years >1%% off", summary["duration_seconds"], summary["combos"], summary["requests"],
                summary["failed"], summary["rejected"], summary["flagged_state_years"])
    print(f"SUMMARY: {path}", flush=True)
    return PARTIAL_EXIT_CODE if summary["failures"] else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, action="append", help="Year to refresh (repeatable); default: the plan")
    parser.add_argument("--concurrent", type=int, default=settings.ANALYTICS_SCRAPER_CONCURRENT)
    parser.add_argument("--wait-for-lock", action="store_true", help="Wait for a running scrape instead of exiting 4")
    parser.add_argument("--states", help="Comma-separated state codes (default: all)")
    parser.add_argument("--only-failures", action="store_true",
                        help="Re-fetch only the combos the last run's summary lists as not refreshed")
    args = parser.parse_args()
    if args.concurrent > 6:
        parser.error("--concurrent above 6 only adds CAPTCHA retries against the site (see run_analytics_scrape)")
    only = frozenset(c.strip() for c in args.states.split(",") if c.strip()) if args.states else None
    sys.exit(asyncio.run(main(args.year, args.concurrent, args.wait_for_lock, only, args.only_failures)))
