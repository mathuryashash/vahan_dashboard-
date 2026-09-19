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
    down_since = None if ok else (prev["down_since"] if prev and not prev["ok"] else now.isoformat())
    # Only real transitions. A healthy first check after boot is not a
    # "recovery" -- logging it as one on every restart teaches people to
    # skim past these lines, which is the opposite of an alert.
    if not ok and (prev is None or prev["ok"]):
        # ERROR, so anything watching the logs (docker, a log shipper) sees it.
        logger.error("SOURCE DOWN: %s -- %s. Scrapes that depend on it will fail.", name, detail)
    elif ok and prev is not None and not prev["ok"]:
        logger.warning("SOURCE RECOVERED: %s -- %s", name, detail)
    _status[name] = {"ok": ok, "detail": detail, "checked_at": now.isoformat(), "down_since": down_since}


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
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
