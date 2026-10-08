"""Round-4 scraper fixes, all offline except the DB-backed ones (test DB):

1. a newly-seen RTO is upserted into `rtos` before rows referencing it
   (AS35 killed two production runs with ForeignKeyViolationError);
2. one shared advisory run lock across every scrape entry point;
3. January false-success / previous-year baseline; legacy skip-file
   migration; empty-before-expiry RTOs are re-checked after re-login;
4. the class-pass truncation root cause (paginator offset carried across
   RTOs) cannot recur: export row count is checked against rowCount.
"""
import json
import os

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

import scraper.vahan_scraper as vs
from app.core import scrape_lock
from app.core.scrape_lock import ScrapeRunLockBusyError, scrape_run_lock, scrape_write_lock
from app.models.models import (
    RTO, FuelCategoryTotal, MakerCategoryTotal, MakerFuelTotal, Registration, State,
)
from app.services.scraper_service import (
    persist_fuel_category_batch, persist_maker_category_batch, persist_maker_fuel_batch, persist_rto_batch,
)
from scraper.rto_retry import RtoFailureTracker
from scraper.run_full_scrape import classify_state, empty_baseline, split_empty

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "postgresql+asyncpg://vahan:vahan@127.0.0.1:5432/vahan_test")


# ---- 1. FK crash: unknown RTO ------------------------------------------------

async def _seed_assam(db):
    await db.merge(State(state_code="AS", state_name="Assam"))
    await db.commit()


@pytest.mark.parametrize("dimension", ["maker", "vehicle_class", "fuel"])
async def test_registration_for_unknown_rto_creates_the_rtos_row(db_session, dimension):
    await _seed_assam(db_session)
    batch = {"state_name": "Assam", "rto_code": "AS35", "rto_name": "TAMULPUR",
             "records": [{"label": "HERO MOTOCORP LTD", "month": 10, "year": 2026, "count": 3}]}
    await persist_rto_batch(db_session, batch, state_code="AS", dimension=dimension)
    await db_session.commit()  # was: ForeignKeyViolationError registrations_rto_code_fkey
    rto = (await db_session.execute(select(RTO).where(RTO.rto_code == "AS35"))).scalar_one()
    assert (rto.rto_name, rto.state_code) == ("TAMULPUR", "AS")
    n = (await db_session.execute(select(func.sum(Registration.count)).where(Registration.rto_code == "AS35"))).scalar()
    assert n == 3


async def test_every_crosstab_writer_creates_the_rtos_row(db_session):
    await _seed_assam(db_session)
    await persist_maker_category_batch(db_session, {"state_name": "Assam", "rto_code": "AS36", "rto_name": "NEW A",
        "records": [{"maker": "HERO", "vehicle_class": "M-CYCLE/SCOOTER", "count": 2}]}, state_code="AS", year=2026)
    await persist_fuel_category_batch(db_session, {"state_name": "Assam", "rto_code": "AS37", "rto_name": "NEW B",
        "records": [{"fuel_type": "PETROL", "vehicle_class": "MOTOR CAR", "count": 4}]}, state_code="AS", year=2026)
    await persist_maker_fuel_batch(db_session, {"state_name": "Assam", "rto_code": "AS38", "rto_name": "NEW C",
        "records": [{"maker": "HERO", "fuel_type": "PETROL", "count": 5}]}, state_code="AS", year=2026)
    await db_session.commit()
    codes = set((await db_session.execute(select(RTO.rto_code))).scalars())
    assert {"AS36", "AS37", "AS38"} <= codes
    for model, code, n in ((MakerCategoryTotal, "AS36", 2), (FuelCategoryTotal, "AS37", 4), (MakerFuelTotal, "AS38", 5)):
        assert (await db_session.execute(select(func.sum(model.count)).where(model.rto_code == code))).scalar() == n


async def test_existing_rto_name_is_not_overwritten_by_a_scrape(db_session):
    await _seed_assam(db_session)
    db_session.add(RTO(rto_code="AS1", rto_name="GUWAHATI", state_code="AS"))
    await db_session.commit()
    await persist_rto_batch(db_session, {"state_name": "Assam", "rto_code": "AS1", "rto_name": "DTO KAMRUP",
        "records": [{"label": "X", "month": 1, "year": 2026, "count": 1}]}, state_code="AS")
    await db_session.commit()
    assert (await db_session.execute(select(RTO.rto_name).where(RTO.rto_code == "AS1"))).scalar() == "GUWAHATI"


# ---- 2. one shared run lock ---------------------------------------------------

async def test_second_process_is_refused_while_a_run_holds_the_lock(monkeypatch):
    holder = create_async_engine(TEST_DATABASE_URL)
    other = create_async_engine(TEST_DATABASE_URL)
    async with scrape_run_lock(holder, "holder"):
        # Simulate another process: fresh module state, no inherited env.
        monkeypatch.setattr(scrape_lock, "_run_lock_depth", 0)
        monkeypatch.setattr(scrape_lock, "_run_lock_conn", None)
        monkeypatch.setattr(scrape_lock, "_guard", None)
        monkeypatch.delenv(scrape_lock.SCRAPE_RUN_LOCK_ENV, raising=False)
        with pytest.raises(ScrapeRunLockBusyError):
            async with scrape_run_lock(other, "intruder"):
                pass  # pragma: no cover
        monkeypatch.undo()
    # Released on exit: a later run gets it.
    async with scrape_run_lock(other, "later"):
        pass
    await holder.dispose()
    await other.dispose()


async def test_run_lock_is_reentrant_within_one_process():
    eng = create_async_engine(TEST_DATABASE_URL)
    async with scrape_run_lock(eng, "outer"):
        async with scrape_run_lock(eng, "maker"), scrape_run_lock(eng, "fuel"):
            pass
    await eng.dispose()


async def test_a_legacy_per_target_lock_also_blocks_a_new_run():
    """The owner's running server never takes the run lock -- only
    registrations:<dim>:<year> keys. Those must still block a new run."""
    a = create_async_engine(TEST_DATABASE_URL)
    b = create_async_engine(TEST_DATABASE_URL)
    async with scrape_write_lock(a, "registrations:maker:2026"):
        with pytest.raises(ScrapeRunLockBusyError):
            async with scrape_run_lock(b, "new"):
                pass  # pragma: no cover
    async with scrape_run_lock(b, "after"):
        pass
    await a.dispose()
    await b.dispose()


def test_child_env_skips_the_lock(monkeypatch):
    env = scrape_lock.child_env_holding_run_lock()
    assert env[scrape_lock.SCRAPE_RUN_LOCK_ENV] == str(os.getpid())


@pytest.mark.parametrize("module", ["scraper.run_full_scrape", "scraper.run_crosstab_scrape",
                                    "scraper.backfill_all_years", "scraper.run_targeted_scrape"])
def test_every_entry_point_takes_the_run_lock(module):
    import importlib
    import inspect
    src = inspect.getsource(importlib.import_module(module))
    assert "scrape_run_lock(" in src and "exit_if_run_lock_busy" in src, module


def test_busy_lock_exits_cleanly_with_code_4(capsys):
    with pytest.raises(SystemExit) as e:
        scrape_lock.exit_if_run_lock_busy(ScrapeRunLockBusyError("busy"))
    assert e.value.code == scrape_lock.SCRAPE_BUSY_EXIT_CODE
    assert "SCRAPE_ALREADY_RUNNING" in capsys.readouterr().out


# ---- 3a. January false success -------------------------------------------------

def test_state_where_zero_rtos_returned_data_is_never_done():
    # Every RTO empty, none "had data before" (early January) -> was 'done_with_empty'.
    assert classify_state("maker", total=3, skipped=0, succeeded=0, empty=3, newly_empty=0) == "partial_empty"
    assert classify_state("fuel", total=3, skipped=0, succeeded=0, empty=3, newly_empty=0) == "partial_empty"
    # One real answer + structural empties is still fine.
    assert classify_state("fuel", total=3, skipped=0, succeeded=1, empty=2, newly_empty=0) == "done_with_empty"


def test_baseline_falls_back_to_previous_year_when_current_has_no_rows():
    prev = {"Goa": frozenset({"GA1", "GA2"})}
    base = empty_baseline("Goa", {}, prev)
    assert base == {"GA1", "GA2"}
    newly, structural = split_empty(["GA1", "GA99"], base)
    assert newly == ["GA1"] and structural == ["GA99"]
    # Current year wins once it has rows.
    assert empty_baseline("Goa", {"Goa": frozenset({"GA2"})}, prev) == {"GA2"}


# ---- 3b. legacy combined skip file ---------------------------------------------

def test_legacy_file_is_migrated_once_then_renamed(tmp_path):
    legacy = tmp_path / "rto_failures.json"
    legacy.write_text(json.dumps({"maker:MH4": {"failed_runs": 3}, "fuel:HP103": {"failed_runs": 5},
                                  "fuel:MH1": {"failed_runs": 9}}))
    (tmp_path / "rto_failures.fuel.json").write_text(json.dumps({"fuel:MH1": {"failed_runs": 1}}))
    t = RtoFailureTracker(legacy, threshold=2)
    assert not legacy.exists() and (tmp_path / "rto_failures.json.migrated").exists()
    assert t.consecutive_failures("maker", "MH4") == 3
    assert t.consecutive_failures("fuel", "MH1") == 1, "per-dimension (newer) value wins over legacy"
    assert json.loads((tmp_path / "rto_failures.maker.json").read_text())["maker:MH4"]["failed_runs"] == 3
    # A success now sticks: the legacy file is not read again to resurrect it.
    t.record_success("maker", "MH4")
    assert RtoFailureTracker(legacy, threshold=2).consecutive_failures("maker", "MH4") == 0


# ---- 3c. empty-before-expiry RTOs are re-checked -------------------------------

RTO_OPTIONS = (
    f'<select id="{vs.RTO_SELECT_ID}_input">'
    '<option value="1">A - MH1( 01-JAN-2015 )</option>'
    '<option value="2">B - MH2( 01-JAN-2015 )</option>'
    '<option value="3">C - MH3( 01-JAN-2015 )</option>'
    '</select>'
)
REC = [{"label": "HONDA", "month": 1, "year": 2026, "count": 5}]


class _Sess:
    def __init__(self):
        self.current = None
        self._form = {}

    async def select(self, select_id, value, execute, render):
        self._form[f"{select_id}_input"] = value
        if select_id == vs.RTO_SELECT_ID:
            self.current = value
            return ""
        return RTO_OPTIONS


async def test_empty_rto_before_session_expiry_is_not_carried_as_done(monkeypatch):
    outcomes = {"1": [REC], "2": [[]], "3": [Exception("ViewExpiredException")]}

    async def pivot(session, year, dimension):
        o = outcomes[session.current].pop(0)
        if isinstance(o, Exception):
            raise o
        return o
    monkeypatch.setattr(vs, "scrape_pivot_table", pivot)
    with pytest.raises(vs.SessionExpiredError) as e:
        await vs._scrape_state(_Sess(), {"state_code": "MH", "state_name": "Maharashtra"}, "s", 2026, "maker", 0,
                               frozenset())
    assert [i["rto_code"] for i in e.value.partial_items] == ["MH1"], "MH2 came back empty on a dying session"
    assert [r["rto_code"] for r in e.value.remaining_rtos] == ["MH2", "MH3"]


async def test_crosstab_rechecks_empty_rtos_after_relogin(monkeypatch):
    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False
    from unittest.mock import AsyncMock
    monkeypatch.setattr(vs.httpx, "AsyncClient", lambda **kw: _Client())
    monkeypatch.setattr(vs._VahanSession, "load", AsyncMock(return_value="<html/>"))
    monkeypatch.setattr(vs._VahanSession, "select", _Sess.select)
    monkeypatch.setattr(vs, "discover_state_select_id", lambda html: "s")
    monkeypatch.setattr(vs, "get_states", AsyncMock(return_value=[{"state_code": "MH", "state_name": "Maharashtra"}]))
    asked = []
    outcomes = {"1": [REC], "2": [[], REC], "3": [Exception("ViewExpiredException"), REC]}

    async def table(session, year):
        code = session._form[f"{vs.RTO_SELECT_ID}_input"]
        asked.append(code)
        o = outcomes[code].pop(0)
        if isinstance(o, Exception):
            raise o
        return o
    items = [i async for i in vs.scrape_all_india_crosstab(2026, table, "maker_category", delay_seconds=0)]
    assert asked == ["1", "2", "3", "2", "3"], "MH2 (empty before the expiry) must be asked again"
    assert items[-1]["rto_succeeded"] == 2 and items[-1]["rto_skipped"] == 1


# ---- 4. truncation root cause: export must match the rendered rowCount ---------

def test_export_shorter_than_rowcount_is_rejected():
    rows = [["S No", "Vehicle Class", "JAN", "TOTAL"]] + [[str(n), f"C{n}", "1", "1"] for n in range(1, 26)]
    vs._check_row_count(rows, 1, 25, context="ok")
    with pytest.raises(vs.ExportIntegrityError, match="rowCount=26"):
        vs._check_row_count(rows, 1, 26, context="tail-truncated")
    vs._check_row_count(rows, 1, None, context="no rowCount in response")


def test_rowcount_parse():
    assert vs._parse_row_count("PrimeFaces.cw('DataTable',{rowCount:26,rows:25})") == 26
    assert vs._parse_row_count("<html/>") is None


async def test_targeted_only_filter_limits_rtos(monkeypatch):
    seen = []

    async def pivot(session, year, dimension):
        seen.append(session.current)
        return REC
    monkeypatch.setattr(vs, "scrape_pivot_table", pivot)
    items = await vs._scrape_state(_Sess(), {"state_code": "MH", "state_name": "Maharashtra"}, "s", 2026, "maker", 0,
                                   frozenset(), only=frozenset({"MH2"}))
    assert seen == ["2"]
    assert items[-1]["rto_total"] == 1 and items[-1]["rto_succeeded"] == 1
