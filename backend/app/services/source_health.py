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
    _status[name] = {
        # ok stays True through a single unconfirmed failure -- that is the point.
        "ok": not confirmed_down,
        "detail": detail,
        "checked_at": now.isoformat(),
        "down_since": down_since,
        "consecutive_failures": failures,
        "first_failure_at": first_failure_at,
    }
    # Logged AFTER _status is updated so the delay quoted is the one the loop
    # will actually sleep (next_check_delay over every source): it used to
    # say "failure 3/2, re-checking in 90s" while the next probe was 300s away.
    delay = next_check_delay()
    if confirmed_down and not was_down:
        # ERROR, so anything watching the logs (docker, a log shipper) sees it.
        logger.error("SOURCE DOWN: %s -- %s (%d consecutive failures). Scrapes that depend on it will fail. "
                     "Re-checking in %ds.", name, detail, failures, delay)
    elif confirmed_down:
        logger.warning("source still down: %s -- %s (%d consecutive failures, re-checking in %ds)",
                       name, detail, failures, delay)
    elif not ok:
        logger.warning("source probe failed: %s -- %s (failure %d/%d, re-checking in %ds)",
                       name, detail, failures, FAILURES_BEFORE_DOWN, delay)
    elif was_down:
        logger.warning("SOURCE RECOVERED: %s -- %s", name, detail)


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
    out = {name: dict(s) for name, s in _status.items()}
    if _analytics_scrape:
        out[ANALYTICS_SCRAPE_KEY] = dict(_analytics_scrape)
    return out


# The scheduled analytics refresh (scraper/scheduler.py) reports here. Kept
# apart from _status so its failures don't drive next_check_delay's fast
# re-probe cadence -- it is a job outcome, not a reachability probe. Same
# ok/detail/consecutive_failures shape, so the header's source pill shows it
# (as "analytics_scraper down") when e.g. tesseract is missing.
ANALYTICS_SCRAPE_KEY = "analytics_scraper"
_analytics_scrape: dict = {}


def _summary_brief(summary: dict | None) -> dict | None:
    if not summary:
        return None
    keys = ("finished_at", "duration_seconds", "years", "combos", "requests", "retried",
            "recovered_on_retry", "failed", "rejected", "flagged_state_years")
    brief = {k: summary.get(k) for k in keys}
    brief["flagged"] = [
        {k: r.get(k) for k in ("year", "state", "pct_fuel_vs_smct", "pct_smct_vs_reg")}
        for r in summary.get("reconciliation", []) if r.get("flagged")
    ][:50]
    brief["failures"] = summary.get("failures", [])[:50]
    return brief


def record_analytics_scrape(ok: bool, detail: str, *, load_summary: bool = False) -> None:
    from scraper import analytics_refresh
    prev = _analytics_scrape.get("consecutive_failures", 0)
    failures = 0 if ok else prev + 1
    summary = _summary_brief(analytics_refresh.read_last_summary()) if load_summary else \
        _analytics_scrape.get("last_run")
    if ok and summary and (summary.get("failed") or summary.get("rejected")):
        detail = f"{detail}; {summary['failed']} failed + {summary['rejected']} rejected combos kept old data"
    _analytics_scrape.update({
        "ok": ok,
        "detail": detail,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "down_since": None if ok else (_analytics_scrape.get("down_since") if prev else
                                       datetime.now(timezone.utc).isoformat()),
        # >= FAILURES_BEFORE_DOWN at once: a job failure is already confirmed.
        "consecutive_failures": 0 if ok else max(failures, FAILURES_BEFORE_DOWN),
        "last_run": summary,
    })


def seed_analytics_scrape_from_disk() -> None:
    """After a restart, show the last run's summary instead of nothing."""
    from scraper import analytics_refresh
    summary = analytics_refresh.read_last_summary()
    if summary and not _analytics_scrape:
        _analytics_scrape.update({"ok": True, "detail": "last refresh (from summary file)",
                                  "checked_at": summary.get("finished_at"), "down_since": None,
                                  "consecutive_failures": 0, "last_run": _summary_brief(summary)})


async def run_source_health_loop() -> None:
    while True:
        try:
            await check_all()
        except Exception:
            logger.exception("source health check itself failed")
        await asyncio.sleep(next_check_delay())
