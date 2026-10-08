"""Scraper robustness, all offline (no live site):

- an empty RTO is not a success, so a state with empty RTOs is never purged
  and the run reports itself as partial;
- per-RTO retries with jittered backoff;
- the opt-in skip-list for RTOs failing N consecutive runs.
"""
import os
import random
from unittest.mock import AsyncMock

import pytest

import scraper.vahan_scraper as vs
from app.core.config import settings
from scraper import rto_retry
from scraper.rto_retry import RtoFailureTracker, backoff_delay, with_retries
from scraper.run_full_scrape import classify_state

RTO_OPTIONS = (
    f'<select id="{vs.RTO_SELECT_ID}_input">'
    '<option value="-1">All Vahan4 Running Office</option>'
    '<option value="1">PUNE - MH12( 01-JAN-2015 )</option>'
    '<option value="2">MUMBAI - MH1( 01-JAN-2015 )</option>'
    '<option value="3">THANE - MH4( 01-JAN-2015 )</option>'
    '</select>'
)
STATE = {"state_code": "MH", "state_name": "Maharashtra"}


class _FakeSession:
    def __init__(self):
        self.current = None

    async def select(self, select_id, value, execute, render):
        if select_id == vs.RTO_SELECT_ID:
            self.current = value
            return ""
        return RTO_OPTIONS


def _pivot(per_rto):
    """per_rto: value -> list of outcomes (records list or Exception), consumed in order."""
    async def fake(session, year, dimension):
        outcome = per_rto[session.current].pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
    return fake


REC = [{"label": "HONDA", "month": 1, "year": 2026, "count": 5}]


async def _run_state(monkeypatch, per_rto):
    monkeypatch.setattr(vs, "scrape_pivot_table", _pivot(per_rto))
    items = await vs._scrape_state(_FakeSession(), STATE, "state_sel", 2026, "maker", 0, frozenset())
    return items[-1], items[:-1]


# ---- succeeded-after-empty --------------------------------------------------

async def test_empty_rto_is_not_counted_as_succeeded(monkeypatch):
    summary, batches = await _run_state(monkeypatch, {"1": [REC], "2": [[]], "3": [REC]})
    assert summary["rto_total"] == 3
    assert summary["rto_succeeded"] == 2, "empty RTO must not count toward success (it used to: 3)"
    assert summary["rto_empty"] == 1
    assert len(batches) == 3  # the empty batch is still yielded (persist handles zero rows)


def test_state_with_some_empty_rtos_is_partial_never_purged():
    # MH: 3 RTOs, 2 with records, 1 empty. Before the fix succeeded was 3 ->
    # done == total -> purge of the whole state-year.
    assert classify_state("maker", total=3, skipped=0, succeeded=2, empty=1) == "partial_empty"
    assert classify_state("maker", total=3, skipped=0, succeeded=0, empty=3) == "partial_empty"
    assert classify_state("maker", total=3, skipped=1, succeeded=2, empty=0) == "purge"
    assert classify_state("fuel", total=3, skipped=0, succeeded=3, empty=0) == "done"
    assert classify_state("maker", total=3, skipped=0, succeeded=2, empty=0) == "partial"  # one failed
    assert classify_state("maker", total=0, skipped=0, succeeded=0, empty=0) == "partial"


def test_structurally_empty_rtos_do_not_make_a_state_partial_forever():
    """P2-1: ~376 of 1,784 RTOs have no 2026 maker data at all (closed
    offices, catch-all codes). Counting them as partial pinned the run status
    at 'partial' on every run. Only NEWLY-empty RTOs (had data before) or
    real failures make a state partial -- and NO empty RTO ever allows a purge."""
    # 3 RTOs: 2 with records, 1 empty that never had data -> not partial, not purged.
    assert classify_state("maker", total=3, skipped=0, succeeded=2, empty=1, newly_empty=0) == "done_with_empty"
    assert classify_state("fuel", total=3, skipped=0, succeeded=2, empty=1, newly_empty=0) == "done_with_empty"
    # The same empty RTO that HAD data before this run -> partial.
    assert classify_state("maker", total=3, skipped=0, succeeded=2, empty=1, newly_empty=1) == "partial_empty"
    # Structurally empty + one failed RTO -> still partial (the failure).
    assert classify_state("maker", total=4, skipped=0, succeeded=2, empty=1, newly_empty=0) == "partial"
    # Earlier-run RTOs count toward completeness.
    assert classify_state("maker", total=4, skipped=1, succeeded=2, empty=1, newly_empty=0) == "done_with_empty"


def test_split_empty_uses_prior_data_baseline():
    from scraper.run_full_scrape import split_empty
    newly, structural = split_empty(["MH4", "MH99"], frozenset({"MH4", "MH12"}))
    assert newly == ["MH4"] and structural == ["MH99"]


async def test_scrape_state_reports_which_rtos_were_empty(monkeypatch):
    summary, _ = await _run_state(monkeypatch, {"1": [REC], "2": [[]], "3": [[]]})
    assert summary["rto_empty"] == 2 and summary["rto_empty_codes"] == ["MH1", "MH4"]


async def test_run_full_scrape_main_status_with_structural_and_new_empties(monkeypatch, capsys):
    """End-to-end over main(): a state whose only empty RTO never had data is
    done (exit 0 path, no purge); a state whose empty RTO had data is partial."""
    from scraper import run_full_scrape as rfs

    class _DB:
        async def commit(self):
            pass

    class _Ctx:
        async def __aenter__(self):
            return _DB()

        async def __aexit__(self, *exc):
            return False

    class _Lock:
        def __call__(self, *a, **k):
            return self

        async def __aenter__(self):
            return None

        async def __aexit__(self, *exc):
            return False

    async def noop(*a, **k):
        return None

    async def had_data(db, year, dimension):
        return {"Sikkim": frozenset({"SK1"}), "Haryana": frozenset({"HR26", "HR51"})}

    async def codes(db):
        return {"Sikkim": "SK", "Haryana": "HR"}

    purged = []

    async def purge(db, state_name, year):
        purged.append(state_name)
        return 0

    async def scrape(**kw):
        yield {"state_complete": True, "state_name": "Sikkim", "rto_total": 2, "rto_skipped": 0,
               "rto_succeeded": 1, "rto_empty": 1, "rto_empty_codes": ["SK99"]}
        yield {"state_complete": True, "state_name": "Haryana", "rto_total": 2, "rto_skipped": 0,
               "rto_succeeded": 1, "rto_empty": 1, "rto_empty_codes": ["HR51"]}

    monkeypatch.setattr(rfs, "init_db", noop)
    monkeypatch.setattr(rfs, "scrape_write_lock", _Lock())
    monkeypatch.setattr(rfs, "AsyncSessionLocal", _Ctx)
    monkeypatch.setattr(rfs, "_already_done_rtos", had_data)
    monkeypatch.setattr(rfs, "_state_code_lookup", codes)
    monkeypatch.setattr(rfs, "_purge_synthetic_for_state", purge)
    monkeypatch.setattr(rfs, "scrape_all_india", scrape)
    partial = await rfs.main(2026, "maker", force=True)
    out = capsys.readouterr().out
    assert partial == 1, "only Haryana (HR51 had data, now empty) is partial"
    assert "PARTIAL_STATES: Haryana" in out and "Sikkim" not in out.split("PARTIAL_STATES:")[1].splitlines()[0]
    assert "STRUCTURALLY_EMPTY_RTOS: 1" in out
    assert purged == [], "purge guard stays strict: any empty RTO blocks the purge"


async def test_crosstab_path_does_not_count_empty_as_succeeded(monkeypatch):
    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(vs.httpx, "AsyncClient", lambda **kw: _Client())
    monkeypatch.setattr(vs._VahanSession, "load", AsyncMock(return_value="<html/>"))
    monkeypatch.setattr(vs._VahanSession, "select", _FakeSession.select)
    monkeypatch.setattr(vs, "discover_state_select_id", lambda html: "state_sel")
    monkeypatch.setattr(vs, "get_states", AsyncMock(return_value=[STATE]))
    outcomes = {"1": [REC], "2": [[]], "3": [REC]}

    async def table(session, year):
        return outcomes[session._form[f"{vs.RTO_SELECT_ID}_input"]].pop(0)

    async def fake_select(self, select_id, value, execute, render):
        self._form[f"{select_id}_input"] = value
        return RTO_OPTIONS
    monkeypatch.setattr(vs._VahanSession, "select", fake_select)
    items = [i async for i in vs.scrape_all_india_crosstab(2026, table, "maker_category", delay_seconds=0)]
    summary = items[-1]
    assert summary["rto_succeeded"] == 2 and summary["rto_empty"] == 1


async def test_partial_subprocess_exit_reports_run_as_partial(monkeypatch):
    from app.services import scraper_service

    def fake_dim(dimension, concurrent_states=1, force=True, year=None):
        if dimension == "maker":
            scraper_service._partial_states["maker"] = ["Chhattisgarh", "Haryana"]
            return scraper_service.PARTIAL_EXIT_CODE
        return 0

    async def noop(*a, **k):
        return None

    monkeypatch.setattr(scraper_service, "_run_dimension_sync", fake_dim)
    monkeypatch.setattr(scraper_service, "vacuum_tables", noop)
    monkeypatch.setattr("app.services.scrape_quality.check_scrape_quality", noop)
    # run_scraper clears _partial_states at start; re-populate from the fake.
    await scraper_service.run_scraper()
    assert settings.REFRESH_STATUS == "partial"
    assert settings.REFRESH_PARTIAL_STATES == ["Chhattisgarh", "Haryana"]
    assert "Chhattisgarh" in settings.REFRESH_ERROR
    settings.REFRESH_STATUS = "idle"
    settings.REFRESH_PARTIAL_STATES = []
    settings.REFRESH_ERROR = None


async def test_refresh_status_exposes_partial_states(client, monkeypatch):
    monkeypatch.setattr(settings, "REFRESH_STATUS", "partial")
    monkeypatch.setattr(settings, "REFRESH_PARTIAL_STATES", ["Haryana"])
    monkeypatch.setattr(settings, "LAST_UPDATED", "2026-10-08 10:00 UTC")
    monkeypatch.setattr(settings, "REFRESH_STRUCTURALLY_EMPTY_RTOS", {"maker": 376})
    body = (await client.get("/api/v1/refresh/status")).json()
    assert body["status"] == "partial" and body["partial_states"] == ["Haryana"]
    assert body["structurally_empty_rtos"] == {"maker": 376}
    assert set(body) >= {"last_updated", "status", "error", "partial_states"}, "backward compatible"


async def test_structurally_empty_only_run_reports_success(monkeypatch):
    from app.services import scraper_service

    def fake_dim(dimension, concurrent_states=1, force=True, year=None):
        if dimension == "maker":
            scraper_service._structurally_empty["maker"] = 376
        return 0  # run_full_scrape exits 0 when only structural empties

    async def noop(*a, **k):
        return None

    monkeypatch.setattr(scraper_service, "_run_dimension_sync", fake_dim)
    monkeypatch.setattr(scraper_service, "vacuum_tables", noop)
    monkeypatch.setattr("app.services.scrape_quality.check_scrape_quality", noop)
    try:
        await scraper_service.run_scraper()
        assert settings.REFRESH_STATUS == "success"
        assert settings.REFRESH_PARTIAL_STATES == []
        assert settings.REFRESH_STRUCTURALLY_EMPTY_RTOS == {"maker": 376}
    finally:
        settings.REFRESH_STATUS = "idle"
        settings.REFRESH_STRUCTURALLY_EMPTY_RTOS = {}
        settings.REFRESH_ERROR = None


# ---- retries ----------------------------------------------------------------

def test_backoff_is_jittered_bounded_and_grows():
    rng = random.Random(7)
    samples = [backoff_delay(a, base=2, cap=30, rng=rng) for a in range(6) for _ in range(50)]
    assert all(1.0 <= s <= 30 for s in samples)
    assert len({round(s, 3) for s in samples}) > 100, "must be jittered, not lock-step"
    assert max(backoff_delay(0, 2, 30, random.Random(i)) for i in range(50)) <= 2
    assert max(backoff_delay(5, 2, 30, random.Random(i)) for i in range(50)) > 4


async def test_with_retries_recovers_from_transient_errors():
    calls, sleeps = [], []

    async def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("blip")
        return "ok"

    async def sleep(s):
        sleeps.append(s)

    assert await with_retries(flaky, label="x", retries=2, sleep=sleep, base=1, cap=4) == "ok"
    assert len(calls) == 3 and len(sleeps) == 2


async def test_with_retries_gives_up_and_does_not_retry_dead_session():
    calls = []

    async def always():
        calls.append(1)
        raise RuntimeError("ViewExpiredException")

    async def sleep(s):
        pass

    with pytest.raises(RuntimeError):
        await with_retries(always, label="x", retries=3, sleep=sleep, no_retry=vs._is_session_expired)
    assert len(calls) == 1, "a dead JSF session must go straight to the re-auth path"

    calls.clear()

    async def boom():
        calls.append(1)
        raise ValueError("bad table")
    with pytest.raises(ValueError):
        await with_retries(boom, label="x", retries=2, sleep=sleep)
    assert len(calls) == 3


async def test_scrape_state_retries_a_transient_rto_failure(monkeypatch):
    summary, batches = await _run_state(
        monkeypatch, {"1": [ConnectionError("blip"), REC], "2": [REC], "3": [REC]})
    assert summary["rto_succeeded"] == 3
    assert [b["rto_code"] for b in batches] == ["MH12", "MH1", "MH4"]


# ---- skip-list ----------------------------------------------------------------

def test_tracker_counts_runs_not_retries_and_resets_on_success(tmp_path):
    path = tmp_path / "f.json"
    t1 = RtoFailureTracker(path, threshold=2, run_id="run1")
    t1.record_failure("maker", "MH4", "x")
    t1.record_failure("maker", "MH4", "x")  # same run: still 1
    assert t1.consecutive_failures("maker", "MH4") == 1 and not t1.should_skip("maker", "MH4")
    t2 = RtoFailureTracker(path, threshold=2, run_id="run2")  # reloads from disk
    t2.record_failure("maker", "MH4", "x")
    assert t2.should_skip("maker", "MH4")
    assert not t2.should_skip("fuel", "MH4"), "per dimension"
    t2.record_success("maker", "MH4")
    assert RtoFailureTracker(path, threshold=2).consecutive_failures("maker", "MH4") == 0


def test_skip_list_is_off_by_default(tmp_path):
    t = RtoFailureTracker(tmp_path / "f.json", threshold=0)
    for run in range(10):
        t.run_id = f"r{run}"
        t.record_failure("maker", "MH4")
    assert t.consecutive_failures("maker", "MH4") == 10
    assert not t.should_skip("maker", "MH4")
    assert rto_retry.SKIP_AFTER_FAILED_RUNS == 0 or "SCRAPER_SKIP_AFTER_FAILED_RUNS" in os.environ


async def test_skipped_rto_leaves_state_partial_and_is_reported(monkeypatch, tmp_path):
    tracker = RtoFailureTracker(tmp_path / "f.json", threshold=2, run_id="old")
    tracker._data["maker:MH4"] = {"failed_runs": 2, "last_run": "older"}
    monkeypatch.setattr(rto_retry, "_default_tracker", tracker)
    summary, batches = await _run_state(monkeypatch, {"1": [REC], "2": [REC], "3": [REC]})
    assert [b["rto_code"] for b in batches] == ["MH12", "MH1"]
    assert summary["rto_quarantined"] == 1 and summary["rto_succeeded"] == 2
    assert classify_state("maker", summary["rto_total"], summary["rto_skipped"],
                          summary["rto_succeeded"], summary["rto_empty"]) == "partial"


async def test_failed_rto_is_recorded_in_tracker(monkeypatch, tmp_path):
    tracker = RtoFailureTracker(tmp_path / "f.json", threshold=0, run_id="r")
    monkeypatch.setattr(rto_retry, "_default_tracker", tracker)
    err = ConnectionError("down")
    await _run_state(monkeypatch, {"1": [REC], "2": [err, err, err], "3": [REC]})
    assert tracker.consecutive_failures("maker", "MH1") == 1
    assert tracker.consecutive_failures("maker", "MH12") == 0

