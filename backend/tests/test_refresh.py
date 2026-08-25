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
