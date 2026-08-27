"""scrape_all_india's serial path reuses one session across every state/RTO
for the whole run. A run long enough to outlive VAHAN's server-side
ViewState then gets ViewExpiredException on every remaining request --
confirmed live, this silently killed the last ~6 hours of a real cleanup
run (every state after the expiry cascaded as individual "failed" lines,
losing all forward progress). scrape_all_india must detect this via
SessionExpiredError and re-authenticate + resume instead."""
from unittest.mock import AsyncMock

import scraper.vahan_scraper as vs
from scraper.vahan_scraper import SessionExpiredError, scrape_all_india


class _FakeClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


async def _collect(dimension="maker"):
    return [item async for item in scrape_all_india(year=2026, dimension=dimension, delay_seconds=0)]


def test_scrape_all_india_resumes_after_session_expiry(monkeypatch):
    monkeypatch.setattr(vs.httpx, "AsyncClient", lambda **kwargs: _FakeClient())
    monkeypatch.setattr(vs._VahanSession, "load", AsyncMock(return_value="<html>fake</html>"))
    monkeypatch.setattr(vs, "discover_state_select_id", lambda html: "state_select")
    monkeypatch.setattr(
        vs,
        "get_states",
        AsyncMock(return_value=[{"state_code": "S1", "state_name": "StateOne"}, {"state_code": "S2", "state_name": "StateTwo"}]),
    )

    call_count = {"n": 0}

    async def fake_scrape_state(session, state, state_select_id, year, dimension, delay_seconds, already_done):
        call_count["n"] += 1
        if state["state_name"] == "StateOne" and call_count["n"] == 1:
            err = SessionExpiredError("ViewExpiredException")
            err.partial_items = [
                {"state_name": "StateOne", "rto_code": "R1", "rto_name": "RTO One", "records": [{"count": 5}]}
            ]
            err.remaining_rtos = None
            raise err
        if state["state_name"] == "StateOne":
            assert "R1" in already_done  # resumed, not re-scraping what already succeeded
            return [
                {"state_complete": True, "state_name": "StateOne", "rto_total": 2, "rto_skipped": 1, "rto_succeeded": 1, "rto_empty": 0}
            ]
        return [
            {"state_complete": True, "state_name": "StateTwo", "rto_total": 1, "rto_skipped": 0, "rto_succeeded": 1, "rto_empty": 0}
        ]

    monkeypatch.setattr(vs, "_scrape_state", fake_scrape_state)

    import asyncio

    items = asyncio.run(_collect())

    rto_batches = [i for i in items if "rto_code" in i]
    state_completions = [i for i in items if i.get("state_complete")]

    assert rto_batches == [{"state_name": "StateOne", "rto_code": "R1", "rto_name": "RTO One", "records": [{"count": 5}]}]
    assert [s["state_name"] for s in state_completions] == ["StateOne", "StateTwo"]
    assert vs._VahanSession.load.await_count == 2  # initial load + one refresh after expiry
