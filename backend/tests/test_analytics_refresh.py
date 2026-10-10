"""Scheduled analytics (new-site) refresh: the plan, the upsert, the
failure handling, the reconciliation and the scheduler loop."""
import asyncio
import contextlib
import json
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.models.models import State, StateMonthCategoryFuelTotal, StateMonthCategoryTotal
from app.services import source_health
from scraper import analytics_refresh, scheduler
from scraper.analytics_scraper import CaptchaSolveError, TableIntegrityError

TW, LMV = "TWO WHEELER(NT)", "LIGHT MOTOR VEHICLE"


@pytest.fixture
async def wired(db_session, monkeypatch, tmp_path):
    """Point the refresh at the test DB, without the real advisory lock."""
    db_session.add_all([State(state_code="BR", state_name="Bihar"), State(state_code="KA", state_name="Karnataka")])
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(analytics_refresh, "AsyncSessionLocal", factory)

    @contextlib.asynccontextmanager
    async def no_lock(engine, key):
        yield
    monkeypatch.setattr(analytics_refresh, "scrape_write_lock", no_lock)
    monkeypatch.setattr(settings, "SCRAPER_DATA_DIR", str(tmp_path))
    return factory


async def _smct(db, state="BR", year=2026):
    rows = (await db.execute(select(StateMonthCategoryTotal.month, StateMonthCategoryTotal.category,
                                    StateMonthCategoryTotal.count)
                             .where(StateMonthCategoryTotal.state_code == state,
                                    StateMonthCategoryTotal.year == year))).all()
    return {(m, c): n for m, c, n in rows}


# ---- plan ------------------------------------------------------------------

@pytest.mark.parametrize("today, years", [
    (date(2026, 10, 10), [2025, 2026]),   # first 10 days: last year's tail still revising
    (date(2026, 10, 11), [2026]),
    (date(2026, 1, 25), [2025, 2026]),    # January: always (December just closed)
    (date(2026, 6, 1), [2025, 2026]),
])
def test_plan_years(today, years):
    assert analytics_refresh.plan_years(today, window_days=10) == years


# ---- current year is never skipped by resume logic ---------------------------

async def test_scheduled_run_refreshes_a_state_whose_current_month_row_exists(wired, db_session):
    # BR already has a (stale) October row: the hand-run runners' resume would skip BR entirely.
    db_session.add(StateMonthCategoryTotal(state_code="BR", state_name="Bihar", year=2026, month=10,
                                           category=TW, count=100))
    await db_session.commit()
    calls = []

    async def fetch(_t, state, year, fuel, counter):
        calls.append((state, year, fuel))
        return [{"month": 10, "category": TW, "count": 250}, {"month": 10, "category": LMV, "count": 40}]

    summary = await analytics_refresh.run_refresh([2026], tesseract_path="t", fuels=[], fetch=fetch,
                                                  states=[("BR", "Bihar")])
    assert calls == [("BR", 2026, None)]
    db_session.expire_all()
    assert await _smct(db_session) == {(10, TW): 250, (10, LMV): 40}
    assert summary["rows"] == {"inserted": 1, "updated": 1, "deleted": 0, "units_before": 100, "units_after": 290}
    assert summary["failures"] == []


def test_hand_run_runners_do_not_resume_the_current_year():
    from datetime import datetime, timezone

    from scraper import run_analytics_fuel_scrape, run_analytics_scrape
    this_year = datetime.now(timezone.utc).year
    for mod in (run_analytics_scrape, run_analytics_fuel_scrape):
        assert mod._resumable(this_year - 1)
        assert not mod._resumable(this_year)


# ---- upsert keeps good rows when a fetch fails -------------------------------

async def test_failed_fetch_is_retried_once_then_reported_and_old_rows_kept(wired, db_session):
    db_session.add_all([
        StateMonthCategoryTotal(state_code="BR", state_name="Bihar", year=2026, month=9, category=TW, count=900),
        StateMonthCategoryFuelTotal(state_code="BR", state_name="Bihar", year=2026, month=9, category=TW,
                                    fuel="PETROL", count=800),
    ])
    await db_session.commit()
    attempts = []

    async def fetch(_t, state, year, fuel, counter):
        attempts.append(fuel)
        if fuel is None:
            raise CaptchaSolveError("rejected 5 times")
        raise TableIntegrityError("row 2026-09: cells sum to 1 but Total says 2")

    summary = await analytics_refresh.run_refresh([2026], tesseract_path="t", fuels=["PETROL"], fetch=fetch,
                                                  states=[("BR", "Bihar")])
    assert sorted(attempts, key=str) == sorted([None, None, "PETROL", "PETROL"], key=str)  # one retry each
    assert summary["retried"] == 2 and summary["recovered_on_retry"] == 0
    assert summary["failed"] == 2
    assert {(f["table"], f["fuel"]) for f in summary["failures"]} == {("smct", None), ("smcft", "PETROL")}
    db_session.expire_all()
    assert await _smct(db_session) == {(9, TW): 900}
    fuel_rows = (await db_session.execute(select(StateMonthCategoryFuelTotal.count))).scalars().all()
    assert fuel_rows == [800]


async def test_failure_recovered_on_retry_counts_as_recovered(wired):
    n = {"calls": 0}

    async def fetch(_t, state, year, fuel, counter):
        n["calls"] += 1
        if n["calls"] == 1:
            raise CaptchaSolveError("first session bad")
        return [{"month": 1, "category": TW, "count": 5}]

    summary = await analytics_refresh.run_refresh([2026], tesseract_path="t", fuels=[], fetch=fetch,
                                                  states=[("BR", "Bihar")])
    assert summary["retried"] == 1 and summary["recovered_on_retry"] == 1 and summary["failures"] == []


async def test_a_shrinking_fetch_is_rejected_and_the_stored_rows_kept(wired, db_session):
    db_session.add_all([StateMonthCategoryTotal(state_code="BR", state_name="Bihar", year=2026, month=m,
                                                category=TW, count=1000) for m in (1, 2, 3)])
    await db_session.commit()

    async def fetch(_t, state, year, fuel, counter):  # a page that lost March
        return [{"month": 1, "category": TW, "count": 1000}, {"month": 2, "category": TW, "count": 1000}]

    summary = await analytics_refresh.run_refresh([2026], tesseract_path="t", fuels=[], fetch=fetch,
                                                  states=[("BR", "Bihar")])
    assert summary["rejected"] == 1 and summary["failures"][0]["status"] == "rejected"
    db_session.expire_all()
    assert len(await _smct(db_session)) == 3


async def test_upsert_deletes_a_cell_the_site_revised_away_only_from_a_good_fetch(wired, db_session):
    async with wired() as db:
        await analytics_refresh.upsert_scope(db, "BR", "Bihar", 2026, None, [
            {"month": 1, "category": TW, "count": 1000}, {"month": 1, "category": LMV, "count": 3}])
        await db.commit()
        stats = await analytics_refresh.upsert_scope(db, "BR", "Bihar", 2026, None, [
            {"month": 1, "category": TW, "count": 1004}])
        await db.commit()
    assert stats == {"inserted": 0, "updated": 1, "deleted": 1, "units_before": 1003, "units_after": 1004}
    db_session.expire_all()
    assert await _smct(db_session) == {(1, TW): 1004}


def test_unknown_category_is_rejected():
    analytics_refresh.check_categories([{"month": 1, "category": TW, "count": 1}])
    with pytest.raises(analytics_refresh.CategoryAxisError):
        analytics_refresh.check_categories([{"month": 1, "category": "FOUR WHEELER", "count": 1}])


# ---- reconciliation --------------------------------------------------------

def test_reconciliation_flags_state_years_over_one_percent_and_ignores_the_partial_month():
    today = date(2026, 10, 10)
    rows = [
        # (year, state, month, smct, smcft, registrations)
        (2026, "BR", 9, 10_000, 9_995, 10_010),     # 0.05% / -0.1% -> fine
        (2026, "BR", 10, 500, 100, 900),            # partial month: reported, not compared
        (2026, "KA", 9, 10_000, 9_800, 10_000),     # fuel 2% short -> flagged
        (2026, "UP", 9, 10_000, 10_000, 10_000),    # not touched -> not reported
    ]
    out = analytics_refresh.reconcile_rows(rows, [(2026, "BR"), (2026, "KA")], today)
    by = {r["state"]: r for r in out}
    assert set(by) == {"BR", "KA"}
    assert not by["BR"]["flagged"] and by["BR"]["partial"] == {"month": 10, "smct": 500, "smcft": 100,
                                                               "registrations": 900}
    assert by["BR"]["smct"] == 10_000
    assert by["KA"]["flagged"] and by["KA"]["pct_fuel_vs_smct"] == -2.0


def test_reconciliation_flags_a_state_year_with_no_smct_but_registrations():
    out = analytics_refresh.reconcile_rows([(2025, "BR", 3, None, None, 500)], [(2025, "BR")], date(2026, 10, 10))
    assert out[0]["flagged"]


async def test_run_summary_lists_flagged_state_years(wired, db_session):
    async def fetch(_t, state, year, fuel, counter):
        return [{"month": 1, "category": TW, "count": 1000}] if fuel is None else \
            [{"month": 1, "category": TW, "count": 900}]

    summary = await analytics_refresh.run_refresh([2025], tesseract_path="t", fuels=["PETROL"], fetch=fetch,
                                                  states=[("BR", "Bihar")])
    assert summary["flagged_state_years"] == 1
    assert summary["reconciliation"][0]["pct_fuel_vs_smct"] == -10.0
    path = analytics_refresh.write_summary(summary)
    assert json.loads(path.read_text())["flagged_state_years"] == 1


# ---- scheduler loop ----------------------------------------------------------

def _loop_harness(monkeypatch, outcomes, n_sleeps):
    sleeps, runs = [], []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) > n_sleeps:
            raise asyncio.CancelledError

    async def fake_once():
        runs.append(1)
        out = outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out

    monkeypatch.setattr(scheduler.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(scheduler, "run_analytics_refresh_once", fake_once)
    monkeypatch.setattr(scheduler, "analytics_initial_delay_seconds", lambda: 900.0)
    monkeypatch.setattr(settings, "ANALYTICS_REFRESH_INTERVAL_HOURS", 24)
    monkeypatch.setattr(settings, "REFRESH_STATUS", "idle")
    return sleeps, runs


def test_analytics_first_delay_follows_last_run_age(monkeypatch):
    monkeypatch.setattr(settings, "SCRAPE_CATCHUP_ON_BOOT", True)
    monkeypatch.setattr(scheduler, "_analytics_last_run_age_seconds", lambda: 20 * 3600.0)
    assert scheduler.analytics_initial_delay_seconds(24) == pytest.approx(4 * 3600)   # not due yet
    monkeypatch.setattr(scheduler, "_analytics_last_run_age_seconds", lambda: 30 * 3600.0)
    assert scheduler.analytics_initial_delay_seconds(24) == scheduler.ANALYTICS_BOOT_MIN_DELAY_SECONDS  # overdue
    monkeypatch.setattr(scheduler, "_analytics_last_run_age_seconds", lambda: None)
    assert scheduler.analytics_initial_delay_seconds(24) == scheduler.ANALYTICS_BOOT_MIN_DELAY_SECONDS  # never ran
    monkeypatch.setattr(settings, "SCRAPE_CATCHUP_ON_BOOT", False)
    assert scheduler.analytics_initial_delay_seconds(24) == 24 * 3600


def test_analytics_last_run_age_reads_the_summary_file(monkeypatch, tmp_path):
    from datetime import datetime, timedelta, timezone
    monkeypatch.setattr(settings, "SCRAPER_DATA_DIR", str(tmp_path))
    assert scheduler._analytics_last_run_age_seconds() is None
    finished = datetime.now(timezone.utc) - timedelta(hours=3)
    analytics_refresh.write_summary({"finished_at": finished.isoformat()})
    assert scheduler._analytics_last_run_age_seconds() == pytest.approx(3 * 3600, abs=60)


async def test_analytics_loop_runs_then_waits_the_interval(monkeypatch):
    sleeps, runs = _loop_harness(monkeypatch, ["ok"], 1)
    with pytest.raises(asyncio.CancelledError):
        await scheduler.run_analytics_scheduler_loop()
    assert sleeps == [900.0, 24 * 3600] and runs == [1]


async def test_analytics_loop_busy_lock_is_skipped_and_retried_soon_without_backoff(monkeypatch, caplog):
    sleeps, runs = _loop_harness(monkeypatch, ["busy", "ok"], 2)
    with caplog.at_level("INFO", logger="scheduler"), pytest.raises(asyncio.CancelledError):
        await scheduler.run_analytics_scheduler_loop()
    assert sleeps == [900.0, scheduler.ANALYTICS_BUSY_RETRY_SECONDS, 24 * 3600]
    assert "Scheduled analytics refresh skipped (another scrape running)" in caplog.text


async def test_analytics_loop_skips_while_an_old_site_refresh_is_running(monkeypatch, caplog):
    sleeps, runs = _loop_harness(monkeypatch, [], 1)
    monkeypatch.setattr(settings, "REFRESH_STATUS", "running")
    with caplog.at_level("INFO", logger="scheduler"), pytest.raises(asyncio.CancelledError):
        await scheduler.run_analytics_scheduler_loop()
    assert runs == [] and "skipped (another scrape running)" in caplog.text


async def test_analytics_loop_backs_off_on_failures_and_resets_on_success(monkeypatch):
    sleeps, runs = _loop_harness(monkeypatch, [RuntimeError("exit 1"), "failed", "ok"], 3)
    with pytest.raises(asyncio.CancelledError):
        await scheduler.run_analytics_scheduler_loop()
    assert sleeps == [900.0, 48 * 3600, scheduler.ANALYTICS_MAX_BACKOFF_HOURS * 3600, 24 * 3600]


async def test_tesseract_missing_logs_loudly_once_and_backs_off(monkeypatch, caplog):
    sleeps, runs = _loop_harness(monkeypatch, ["tesseract", "tesseract"], 2)
    with caplog.at_level("INFO", logger="scheduler"), pytest.raises(asyncio.CancelledError):
        await scheduler.run_analytics_scheduler_loop()
    errors = [r for r in caplog.records if r.levelname == "ERROR" and "tesseract" in r.getMessage()]
    assert len(errors) == 1
    assert sleeps[1:] == [48 * 3600, scheduler.ANALYTICS_MAX_BACKOFF_HOURS * 3600]


async def test_refresh_once_marks_the_source_unhealthy_when_tesseract_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "SCRAPER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(source_health, "_analytics_scrape", {})
    monkeypatch.setattr(scheduler, "_run_analytics_refresh_sync",
                        lambda holder: (5, ["TESSERACT_UNAVAILABLE: tesseract binary not found"]))
    assert await scheduler.run_analytics_refresh_once() == "tesseract"
    status = source_health.current_status()["analytics_scraper"]
    assert status["ok"] is False and "tesseract" in status["detail"]
    assert status["consecutive_failures"] >= source_health.FAILURES_BEFORE_DOWN


async def test_refresh_once_success_exposes_the_run_summary(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "SCRAPER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(source_health, "_analytics_scrape", {})
    analytics_refresh.write_summary({"finished_at": "2026-10-10T00:00:00+00:00", "combos": 1260, "failed": 1,
                                     "rejected": 0, "failures": [{"state": "BR"}], "reconciliation": [
                                         {"year": 2026, "state": "WB", "flagged": True, "pct_smct_vs_reg": 1.4}]})
    monkeypatch.setattr(scheduler, "_run_analytics_refresh_sync", lambda holder: (3, []))
    assert await scheduler.run_analytics_refresh_once() == "partial"
    status = source_health.current_status()["analytics_scraper"]
    assert status["ok"] is True and "1 failed" in status["detail"]
    assert status["last_run"]["combos"] == 1260 and status["last_run"]["flagged"][0]["state"] == "WB"


async def test_refresh_once_busy_child_is_reported_as_busy(monkeypatch):
    monkeypatch.setattr(scheduler, "_run_analytics_refresh_sync", lambda holder: (4, ["SCRAPE_ALREADY_RUNNING: x"]))
    assert await scheduler.run_analytics_refresh_once() == "busy"


async def test_source_health_endpoint_shows_the_analytics_job(client, monkeypatch):
    monkeypatch.setattr(source_health, "_analytics_scrape", {"ok": False, "detail": "tesseract unavailable",
                                                             "consecutive_failures": 2})
    body = (await client.get("/api/v1/refresh/source-health")).json()
    assert body["analytics_scraper"]["ok"] is False


async def test_only_restricts_the_run_to_the_listed_combos(wired):
    calls = []

    async def fetch(_t, state, year, fuel, counter):
        calls.append((state, fuel))
        return []

    summary = await analytics_refresh.run_refresh(
        [2026], tesseract_path="t", fuels=["PETROL", "DIESEL"], fetch=fetch,
        states=[("BR", "Bihar"), ("KA", "Karnataka")], only=[(2026, "KA", "DIESEL")])
    assert calls == [("KA", "DIESEL")] and summary["combos"] == 1
