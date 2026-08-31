"""Regression tests for the manual-refresh cooldown.

POST /refresh/ has no auth (it's a public dashboard button) -- without a
cooldown, anyone could keep re-triggering a fresh ~1-1.5h scrape back-to-back
forever. This guards the cooldown branch in trigger_refresh actually rejects
and actually allows at the right times.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import app.api.v1.endpoints.refresh as refresh_module
from app.core.config import settings
from app.models.models import Registration, State


async def test_trigger_refresh_rejects_within_cooldown(client, monkeypatch):
    called = False

    async def fake_run_scraper(concurrent_states=1):
        nonlocal called
        called = True

    monkeypatch.setattr(refresh_module, "run_scraper", fake_run_scraper)
    settings.REFRESH_STATUS = "idle"
    settings.LAST_REFRESH_STARTED_AT = datetime.now(timezone.utc) - timedelta(minutes=5)
    try:
        response = await client.post("/api/v1/refresh/")
        assert response.status_code == 200
        assert response.json()["status"] == "cooldown"
        assert called is False
    finally:
        settings.LAST_REFRESH_STARTED_AT = None


async def test_trigger_refresh_allowed_once_cooldown_elapses(client, monkeypatch):
    called = False

    async def fake_run_scraper(concurrent_states=1):
        nonlocal called
        called = True

    monkeypatch.setattr(refresh_module, "run_scraper", fake_run_scraper)
    settings.REFRESH_STATUS = "idle"
    settings.LAST_REFRESH_STARTED_AT = datetime.now(timezone.utc) - timedelta(
        minutes=settings.REFRESH_COOLDOWN_MINUTES + 1
    )
    try:
        response = await client.post("/api/v1/refresh/")
        assert response.status_code == 200
        assert response.json()["status"] == "started"
        assert called is True
    finally:
        settings.LAST_REFRESH_STARTED_AT = None


async def test_scrape_progress_caches_across_requests(client, db_session):
    """Mounted in the root App component, so it fires on every page load and
    polls every 15s until fully done -- but its two DISTINCT queries scan
    every matching row (confirmed live: up to 35s on a fresh install).
    Cached briefly rather than recomputed on every mount/poll."""
    refresh_module._scrape_progress_cache["value"] = None
    refresh_module._scrape_progress_cache["at"] = 0.0

    db_session.add(State(state_code="DL", state_name="Delhi"))
    db_session.add(Registration(
        state_code="DL", state_name="Delhi", rto_code="DL1", rto_name="Test RTO",
        vehicle_class="All", vehicle_category="Other", commercial_tier=None,
        year=2026, month=1, maker="HONDA", count=5, is_supplementary=False,
    ))
    await db_session.commit()

    response = await client.get("/api/v1/refresh/scrape-progress")
    assert response.status_code == 200
    assert response.json()["states_done"] == 1

    # A second state finishes, but a call within the TTL must still return
    # the cached (now stale-looking) result, not re-query.
    db_session.add(State(state_code="MH", state_name="Maharashtra"))
    db_session.add(Registration(
        state_code="MH", state_name="Maharashtra", rto_code="MH1", rto_name="Test RTO",
        vehicle_class="All", vehicle_category="Other", commercial_tier=None,
        year=2026, month=1, maker="HONDA", count=5, is_supplementary=False,
    ))
    await db_session.commit()

    response = await client.get("/api/v1/refresh/scrape-progress")
    assert response.json()["states_done"] == 1

    # Force the cache to look expired -- the next call must pick up MH too.
    refresh_module._scrape_progress_cache["at"] = 0.0
    response = await client.get("/api/v1/refresh/scrape-progress")
    assert response.json()["states_done"] == 2


async def test_trigger_refresh_concurrent_burst_starts_scraper_only_once(client, monkeypatch):
    """Regression test: the single-flight/cooldown guard used to only get set
    inside run_scraper() itself, which runs as a BackgroundTask -- i.e. only
    after the handler already returned its response. A burst of
    near-simultaneous requests could all read the stale "idle" guard state
    and all pass, launching multiple concurrent scrapes. The guard must be
    set synchronously in the handler, before scheduling the background task.
    """
    starts = 0

    async def fake_run_scraper(concurrent_states=1):
        nonlocal starts
        starts += 1
        await asyncio.sleep(0.05)

    monkeypatch.setattr(refresh_module, "run_scraper", fake_run_scraper)
    settings.REFRESH_STATUS = "idle"
    settings.LAST_REFRESH_STARTED_AT = None
    try:
        r1, r2 = await asyncio.gather(
            client.post("/api/v1/refresh/"), client.post("/api/v1/refresh/")
        )
        statuses = sorted(r.json()["status"] for r in (r1, r2))
        assert statuses == ["running", "started"]
        assert starts == 1
    finally:
        settings.REFRESH_STATUS = "idle"
        settings.LAST_REFRESH_STARTED_AT = None
