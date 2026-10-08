"""Restart-proof freshness (NEVER SYNCED banner), data-age-based scheduler,
single-flight and post-scrape cache clearing.

None of these tests scrape: run_scraper / the scheduler's scrape call are
always mocked.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.core.cache import TTLCache, single_flight
from app.core.config import settings
from app.models.models import RTO, Registration, ScrapeQualityLog, State
from app.services import data_freshness
from app.services.data_freshness import Freshness, last_complete_month
from scraper import scheduler


def _reg(year, month, count, recorded_at, rto="MH1", supp=False):
    return Registration(
        state_code="MH", state_name="Maharashtra", rto_code=rto, rto_name=rto, year=year, month=month,
        vehicle_class="All", is_supplementary=supp, maker="HONDA" if not supp else None,
        fuel_type="PETROL" if supp else None, count=count, recorded_at=recorded_at,
    )


async def _geo(db):
    await db.merge(State(state_code="MH", state_name="Maharashtra"))
    for r in ("MH1", "MH2"):
        await db.merge(RTO(rto_code=r, rto_name=r, state_code="MH"))


# ---- last_complete_month ---------------------------------------------------

def test_month_scraped_mid_month_is_partial_even_months_later():
    # Data froze on 2026-09-19: September is partial in October too.
    assert last_complete_month(2026, 9, datetime(2026, 9, 19, 21, 1)) == (2026, 8)


def test_month_scraped_after_it_ended_is_complete():
    assert last_complete_month(2026, 9, datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc)) == (2026, 9)
    assert last_complete_month(2025, 12, datetime(2026, 1, 2)) == (2025, 12)


def test_january_partial_rolls_back_a_year_and_no_timestamp_is_conservative():
    assert last_complete_month(2026, 1, datetime(2026, 1, 15)) == (2025, 12)
    assert last_complete_month(2026, 5, None) == (2026, 4)
    assert last_complete_month(None, None, None) is None


def test_complete_through_cuts_only_the_newest_year():
    f = Freshness(datetime(2026, 9, 19, tzinfo=timezone.utc), 2026, 9)
    assert f.complete_through(2026, 9) == 8
    assert f.complete_through(2025, 12) == 12  # older year: whole year is complete
    assert f.partial_month(2026) == 9 and f.partial_month(2025) is None
    g = Freshness(datetime(2026, 1, 10, tzinfo=timezone.utc), 2026, 1)
    assert g.complete_through(2026, 1) == 0  # nothing complete yet this year


# ---- /refresh/status survives a restart ------------------------------------

async def test_refresh_status_last_updated_derived_from_data_after_restart(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "LAST_UPDATED", None)  # what every restart leaves behind
    await _geo(db_session)
    db_session.add_all([
        _reg(2026, 8, 10, datetime(2026, 9, 1, 2, 0)),
        _reg(2026, 9, 10, datetime(2026, 9, 19, 21, 1)),
        _reg(2026, 9, 5, datetime(2026, 9, 19, 20, 0), rto="MH2"),
        ScrapeQualityLog(rto_code="MH1", state_name="Maharashtra", year=2026, month=9, maker_total=1,
                         vehicle_class_total=1, fuel_total=1, max_pct_diff=0.0, is_clean=True,
                         checked_at=datetime(2026, 9, 19, 6, 15)),
    ])
    await db_session.commit()
    body = (await client.get("/api/v1/refresh/status")).json()
    assert body["last_updated"] == "2026-09-19 21:01 UTC", "NEVER SYNCED regression: must come from the data"

    dq = (await client.get("/api/v1/refresh/data-quality")).json()
    assert dq["last_updated"] == "2026-09-19 21:01 UTC"


async def test_refresh_status_prefers_in_memory_value_and_handles_empty_db(client, monkeypatch):
    monkeypatch.setattr(settings, "LAST_UPDATED", None)
    assert (await client.get("/api/v1/refresh/status")).json()["last_updated"] is None
    monkeypatch.setattr(settings, "LAST_UPDATED", "2026-10-08 10:00 UTC")
    assert (await client.get("/api/v1/refresh/status")).json()["last_updated"] == "2026-10-08 10:00 UTC"


# ---- scheduler: data-age based, gated --------------------------------------

async def test_initial_delay_is_interval_minus_data_age(monkeypatch):
    monkeypatch.setattr(settings, "SCRAPE_CATCHUP_ON_BOOT", True)

    async def age():
        return 2 * 3600.0  # last success 2h ago
    monkeypatch.setattr(scheduler, "_last_success_age_seconds", age)
    assert await scheduler.initial_delay_seconds(5) == pytest.approx(3 * 3600)


async def test_overdue_data_schedules_catch_up_shortly_after_boot(monkeypatch):
    monkeypatch.setattr(settings, "SCRAPE_CATCHUP_ON_BOOT", True)

    async def age():
        return 19 * 24 * 3600.0  # frozen since 2026-09-19
    monkeypatch.setattr(scheduler, "_last_success_age_seconds", age)
    assert await scheduler.initial_delay_seconds(5) == scheduler.BOOT_CATCHUP_MIN_DELAY_SECONDS


async def test_catchup_disabled_or_unknown_age_waits_full_interval(monkeypatch):
    async def age():
        return 19 * 24 * 3600.0
    monkeypatch.setattr(scheduler, "_last_success_age_seconds", age)
    monkeypatch.setattr(settings, "SCRAPE_CATCHUP_ON_BOOT", False)
    assert await scheduler.initial_delay_seconds(5) == 5 * 3600

    monkeypatch.setattr(settings, "SCRAPE_CATCHUP_ON_BOOT", True)

    async def none():
        return None
    monkeypatch.setattr(scheduler, "_last_success_age_seconds", none)
    assert await scheduler.initial_delay_seconds(5) == 5 * 3600

    async def boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(scheduler, "_last_success_age_seconds", boom)
    assert await scheduler.initial_delay_seconds(5) == 5 * 3600


async def test_scheduler_loop_uses_data_age_for_first_sleep_then_interval(monkeypatch):
    sleeps, scrapes = [], []

    async def fake_initial(interval_hours):
        return 120.0

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= 2:
            raise asyncio.CancelledError

    async def fake_run_scraper(concurrent_states=1):
        scrapes.append(1)

    monkeypatch.setattr(scheduler, "initial_delay_seconds", fake_initial)
    monkeypatch.setattr(scheduler.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(scheduler, "run_scraper", fake_run_scraper)
    monkeypatch.setattr(settings, "REFRESH_STATUS", "idle")
    with pytest.raises(asyncio.CancelledError):
        await scheduler.run_scheduler_loop()
    assert sleeps == [120.0, scheduler.REFRESH_INTERVAL_HOURS * 3600]
    assert scrapes == [1]


async def test_scheduler_skips_when_a_scrape_is_already_running(monkeypatch):
    sleeps, scrapes = [], []

    async def fake_initial(interval_hours):
        return 60.0

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= 2:
            raise asyncio.CancelledError

    async def fake_run_scraper(concurrent_states=1):
        scrapes.append(1)

    monkeypatch.setattr(scheduler, "initial_delay_seconds", fake_initial)
    monkeypatch.setattr(scheduler.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(scheduler, "run_scraper", fake_run_scraper)
    monkeypatch.setattr(settings, "REFRESH_STATUS", "running")
    with pytest.raises(asyncio.CancelledError):
        await scheduler.run_scheduler_loop()
    assert scrapes == []


async def test_last_success_age_reads_quality_log_not_partial_writes(db_session, monkeypatch):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    await _geo(db_session)
    db_session.add_all([
        _reg(2026, 9, 10, now - timedelta(minutes=5)),  # a crashed run's partial write
        ScrapeQualityLog(rto_code="MH1", state_name="Maharashtra", year=2026, month=9, maker_total=1,
                         vehicle_class_total=1, fuel_total=1, max_pct_diff=0.0, is_clean=True,
                         checked_at=now - timedelta(hours=4)),
    ])
    await db_session.commit()
    f = await data_freshness.get_freshness(db_session, use_cache=False)
    assert f.age_seconds() == pytest.approx(4 * 3600, abs=120)
    assert f.last_updated_str == (now - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M UTC")


# ---- single-flight ---------------------------------------------------------

async def test_single_flight_runs_concurrent_identical_calls_once():
    calls = []
    gate = asyncio.Event()

    @single_flight
    async def slow(year: int, state: str | None = None):
        calls.append((year, state))
        await gate.wait()
        return {"year": year, "state": state}

    tasks = [asyncio.create_task(slow(2026)) for _ in range(5)]
    other = asyncio.create_task(slow(2026, state="Kerala"))
    await asyncio.sleep(0.01)
    gate.set()
    results = await asyncio.gather(*tasks, other)
    assert calls == [(2026, None), (2026, "Kerala")], "identical calls must share one execution; distinct keys must not"
    assert results[:5] == [{"year": 2026, "state": None}] * 5
    assert results[5] == {"year": 2026, "state": "Kerala"}
    assert slow._single_flight_inflight == {}


async def test_single_flight_leader_cancellation_does_not_cancel_followers():
    calls = []
    gate = asyncio.Event()

    @single_flight
    async def slow(year: int):
        calls.append(year)
        await gate.wait()
        return year

    leader = asyncio.create_task(slow(1))
    await asyncio.sleep(0.01)
    follower = asyncio.create_task(slow(1))
    await asyncio.sleep(0.01)
    leader.cancel()
    await asyncio.sleep(0.01)
    gate.set()
    assert await follower == 1
    assert len(calls) == 2  # follower re-ran on its own


async def test_single_flight_propagates_leader_error_to_followers():
    gate = asyncio.Event()

    @single_flight
    async def bad(x: int):
        await gate.wait()
        raise ValueError("boom")

    tasks = [asyncio.create_task(bad(1)) for _ in range(3)]
    await asyncio.sleep(0.01)
    gate.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert all(isinstance(r, ValueError) for r in results)


# ---- cache cleared after a successful scrape --------------------------------

async def test_successful_scrape_clears_response_caches(monkeypatch):
    from app.services import scraper_service

    probe = TTLCache(600)
    probe.set("k", "stale")
    monkeypatch.setattr(scraper_service, "_run_dimension_sync", lambda *a, **k: 0)

    async def noop(*a, **k):
        return None
    monkeypatch.setattr(scraper_service, "vacuum_tables", noop)
    monkeypatch.setattr("app.services.scrape_quality.check_scrape_quality", noop)
    await scraper_service.run_scraper()
    assert probe.get("k") is None
