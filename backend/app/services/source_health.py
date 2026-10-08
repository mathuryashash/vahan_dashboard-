"""Is each VAHAN source still usable? Checked hourly, surfaced to admins.

The old dashboard (vahan4dashboard) -- the source of every maker, vehicle-class
and fuel scrape -- has carried a banner saying it would be discontinued after
15 August 2026, and is still up past that date. When it goes, those scrapes
stop. This is how that gets noticed from the app rather than from a client.
The new site (analytics.parivahan.gov.in) feeds the state x month x category
scrapes and is checked the same way.

State is in-process. That is correct only because the app runs exactly one
worker, which app/core/worker_guard.py enforces at boot.
"""
import asyncio
import logging
from datetime import datetime, timezone

import httpx

from scraper import analytics_scraper as new_site
from scraper import vahan_scraper as old_site

logger = logging.getLogger("source_health")

CHECK_INTERVAL_SECONDS = 3600
# One transient ConnectError used to pin the header at DOWN for a full hour.
# A source is reported down only after FAILURES_BEFORE_DOWN consecutive failed
# probes; after any failure the next probe comes RECHECK_SECONDS later instead
# of an hour later, so a blip clears (or is confirmed) within ~90s. While a
# source is confirmed down it is re-probed every DOWN_RECHECK_SECONDS so the
# recovery shows up promptly too. Healthy sources keep the hourly cadence.
FAILURES_BEFORE_DOWN = 2
RECHECK_SECONDS = 90
DOWN_RECHECK_SECONDS = 300
_status: dict[str, dict] = {}

# Each probe is the exact call a scrape starts with, so the check and the
# scrape can never disagree. For the old site that matters: a shut-down JSF
# site most likely still returns HTTP 200 with a notice page, and load() is
# what checks for the report form's controls, not just a response.
_PROBES = {
    "old_site": lambda client: old_site._VahanSession(client).load(retries=1),
    "new_site": new_site.load_session,
}


async def check(name: str, client: httpx.AsyncClient) -> tuple[bool, str]:
    try:
        await _PROBES[name](client)
    except (httpx.HTTPError, RuntimeError) as exc:
        return False, str(exc) or repr(exc)
    return True, "report page loads"


def _record(name: str, ok: bool, detail: str, now: datetime) -> None:
    prev = _status.get(name)
    prev_failures = prev.get("consecutive_failures", 0) if prev else 0
    failures = 0 if ok else prev_failures + 1
    first_failure_at = None if ok else (
        prev.get("first_failure_at") if prev and prev_failures else now.isoformat())
    confirmed_down = failures >= FAILURES_BEFORE_DOWN
    was_down = bool(prev) and not prev["ok"]
    # down_since is the first failure of the streak, not the confirming one:
    # that is when the source actually stopped answering.
    down_since = first_failure_at if confirmed_down else None
    # Only real transitions. A healthy first check after boot is not a
    # "recovery" -- logging it as one on every restart teaches people to
    # skim past these lines, which is the opposite of an alert.
    if confirmed_down and not was_down:
        # ERROR, so anything watching the logs (docker, a log shipper) sees it.
        logger.error("SOURCE DOWN: %s -- %s (%d consecutive failures). Scrapes that depend on it will fail.",
                     name, detail, failures)
    elif not ok:
        logger.warning("source probe failed: %s -- %s (failure %d/%d, re-checking in %ds)",
                       name, detail, failures, FAILURES_BEFORE_DOWN, RECHECK_SECONDS)
    elif was_down:
        logger.warning("SOURCE RECOVERED: %s -- %s", name, detail)
    _status[name] = {
        # ok stays True through a single unconfirmed failure -- that is the point.
        "ok": not confirmed_down,
        "detail": detail,
        "checked_at": now.isoformat(),
        "down_since": down_since,
        "consecutive_failures": failures,
        "first_failure_at": first_failure_at,
    }


def next_check_delay() -> int:
    """Seconds until the next probe: fast re-check while any source is failing."""
    failures = [s.get("consecutive_failures", 0) for s in _status.values()]
    if any(0 < f < FAILURES_BEFORE_DOWN for f in failures):
        return RECHECK_SECONDS
    if any(f >= FAILURES_BEFORE_DOWN for f in failures):
        return DOWN_RECHECK_SECONDS
    return CHECK_INTERVAL_SECONDS


async def check_all() -> dict[str, dict]:
    now = datetime.now(timezone.utc)
    async with httpx.AsyncClient(timeout=60, follow_redirects=True,
                                 headers={"User-Agent": old_site._USER_AGENT}) as client:
        for name in _PROBES:
            _record(name, *await check(name, client), now)
    return current_status()


def current_status() -> dict[str, dict]:
    return {name: dict(s) for name, s in _status.items()}


async def run_source_health_loop() -> None:
    while True:
        try:
            await check_all()
        except Exception:
            logger.exception("source health check itself failed")
        await asyncio.sleep(next_check_delay())
