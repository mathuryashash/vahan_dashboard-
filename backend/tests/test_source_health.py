"""The old VAHAN dashboard is past its announced shutdown date. These pin the
two things that must hold when it goes: the scraper says "the source is gone"
instead of retrying a session forever, and admins are alerted.
"""
import logging
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.core.auth import get_current_user
from app.main import app
from app.models.models import User, UserRole, UserScope
from app.services import source_health
from scraper import vahan_scraper as vs

VIEWSTATE = '<input type="hidden" name="javax.faces.ViewState" value="-123:456" />'
HEALTHY = VIEWSTATE + "".join(
    f'<select id="{i}_input" name="{i}_input"></select>'
    for i in (vs.RTO_SELECT_ID, vs.YAXIS_SELECT_ID, vs.XAXIS_SELECT_ID, vs.YEAR_SELECT_ID)
) + f'<button id="{vs.REFRESH_BUTTON_ID}">Refresh</button>'
# The likely end state: still a JSF page -- so it HAS a ViewState -- but a
# notice instead of the report form.
NOTICE = VIEWSTATE + "<p>Vahan4Dashboard has been discontinued. Please use the new dashboard.</p>"


@pytest.fixture(autouse=True)
def _fresh_status():
    source_health._status.clear()
    yield
    source_health._status.clear()


def _client(html: str, status: int = 200) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(lambda _req: httpx.Response(status, text=html)))


def test_intact_report_form_has_nothing_missing():
    assert vs.missing_report_controls(HEALTHY) == []


def test_a_notice_page_is_missing_every_control():
    assert vs.missing_report_controls(NOTICE) == [
        vs.RTO_SELECT_ID, vs.YAXIS_SELECT_ID, vs.XAXIS_SELECT_ID, vs.YEAR_SELECT_ID, vs.REFRESH_BUTTON_ID,
    ]


async def test_scraper_reports_the_source_gone_even_though_the_notice_has_a_viewstate():
    """The ViewState check alone passes on a notice page. Without the form
    check the scrape failed later on an empty RTO dropdown, which is read as
    an expired session and retried -- never saying the site had gone."""
    async with _client(NOTICE) as client:
        with pytest.raises(vs.SourceUnavailableError, match="missing selectedRto"):
            await vs._VahanSession(client).load(retries=1)


async def test_scraper_still_loads_a_healthy_page():
    async with _client(HEALTHY) as client:
        assert await vs._VahanSession(client).load(retries=1) == HEALTHY


async def test_health_check_passes_a_healthy_site_and_fails_a_notice_page():
    async with _client(HEALTHY) as client:
        assert await source_health.check("old_site", client) == (True, "report page loads")
    async with _client(NOTICE) as client:
        ok, detail = await source_health.check("old_site", client)
    assert not ok and "missing selectedRto" in detail


async def test_health_check_fails_on_a_server_error():
    async with _client("gone", status=503) as client:
        ok, detail = await source_health.check("old_site", client)
    assert not ok and "503" in detail


def test_going_down_alerts_once_and_keeps_the_original_down_since(caplog):
    t0 = datetime(2026, 9, 20, 3, 0, tzinfo=timezone.utc)
    source_health._record("old_site", True, "report page loads", t0)
    with caplog.at_level(logging.WARNING, logger="source_health"):
        source_health._record("old_site", False, "HTTP 503", t0 + timedelta(hours=1))
        source_health._record("old_site", False, "HTTP 503", t0 + timedelta(hours=1, seconds=90))
        source_health._record("old_site", False, "HTTP 503", t0 + timedelta(hours=2))

    alerts = [r for r in caplog.records if "SOURCE DOWN" in r.getMessage()]
    assert len(alerts) == 1 and alerts[0].levelno == logging.ERROR, "alert on the transition, not every check"
    st = source_health.current_status()["old_site"]
    # down_since = first failure of the streak, not the confirming probe.
    assert st["down_since"] == (t0 + timedelta(hours=1)).isoformat()
    assert st["consecutive_failures"] == 3 and st["ok"] is False


def test_one_transient_failure_does_not_report_down(caplog):
    """Found live: one ConnectError pinned the header at DOWN for an hour."""
    t0 = datetime(2026, 9, 20, 3, 0, tzinfo=timezone.utc)
    source_health._record("old_site", True, "report page loads", t0)
    with caplog.at_level(logging.WARNING, logger="source_health"):
        source_health._record("old_site", False, "ConnectError", t0 + timedelta(hours=1))
    st = source_health.current_status()["old_site"]
    assert st["ok"] is True and st["down_since"] is None
    assert st["consecutive_failures"] == 1
    assert not [r for r in caplog.records if "SOURCE DOWN" in r.getMessage()]
    # ...and the next probe is a fast re-check, not an hour away.
    assert source_health.next_check_delay() == source_health.RECHECK_SECONDS
    source_health._record("old_site", True, "report page loads", t0 + timedelta(hours=1, seconds=90))
    st = source_health.current_status()["old_site"]
    assert st["ok"] is True and st["consecutive_failures"] == 0
    assert source_health.next_check_delay() == source_health.CHECK_INTERVAL_SECONDS


def test_cadence_hourly_when_healthy_fast_when_failing_and_down():
    t0 = datetime(2026, 9, 20, 3, 0, tzinfo=timezone.utc)
    assert source_health.next_check_delay() == 3600
    source_health._record("new_site", True, "ok", t0)
    assert source_health.next_check_delay() == 3600
    source_health._record("old_site", False, "x", t0)
    assert 60 <= source_health.next_check_delay() <= 120
    source_health._record("old_site", False, "x", t0 + timedelta(seconds=90))
    assert source_health.next_check_delay() == source_health.DOWN_RECHECK_SECONDS


def test_a_healthy_first_check_is_silent_and_two_failures_alert(caplog):
    """Found live: every boot logged "SOURCE RECOVERED" for healthy sites,
    because no previous status was treated as a transition."""
    now = datetime(2026, 9, 20, 3, 0, tzinfo=timezone.utc)
    with caplog.at_level(logging.WARNING, logger="source_health"):
        source_health._record("new_site", True, "report page loads", now)
        assert caplog.records == []
        source_health._record("old_site", False, "HTTP 503", now)
        assert [r.levelno for r in caplog.records] == [logging.WARNING]
        source_health._record("old_site", False, "HTTP 503", now + timedelta(seconds=90))
    assert [r.levelno for r in caplog.records] == [logging.WARNING, logging.ERROR]


def test_failure_log_states_the_real_next_check_delay(caplog):
    """P3: once confirmed down, later failures logged "failure 3/2,
    re-checking in 90s" while the loop actually slept DOWN_RECHECK_SECONDS."""
    t0 = datetime(2026, 9, 20, 3, 0, tzinfo=timezone.utc)
    with caplog.at_level(logging.WARNING, logger="source_health"):
        source_health._record("old_site", False, "HTTP 503", t0)
        source_health._record("old_site", False, "HTTP 503", t0 + timedelta(seconds=90))
        source_health._record("old_site", False, "HTTP 503", t0 + timedelta(seconds=390))
    msgs = [r.getMessage() for r in caplog.records]
    assert f"re-checking in {source_health.RECHECK_SECONDS}s" in msgs[0]
    assert f"Re-checking in {source_health.DOWN_RECHECK_SECONDS}s" in msgs[1]
    assert "still down" in msgs[2] and f"re-checking in {source_health.DOWN_RECHECK_SECONDS}s" in msgs[2]
    assert "3/2" not in msgs[2]
    assert source_health.next_check_delay() == source_health.DOWN_RECHECK_SECONDS


def test_recovery_clears_down_since():
    t0 = datetime(2026, 9, 20, 3, 0, tzinfo=timezone.utc)
    source_health._record("old_site", False, "HTTP 503", t0)
    source_health._record("old_site", False, "HTTP 503", t0 + timedelta(seconds=90))
    assert source_health.current_status()["old_site"]["ok"] is False
    source_health._record("old_site", True, "report page loads", t0 + timedelta(hours=1))
    st = source_health.current_status()["old_site"]
    assert st["down_since"] is None and st["ok"] is True and st["consecutive_failures"] == 0


async def test_status_endpoint_is_admin_only(client):
    source_health._record("old_site", False, "HTTP 503", datetime.now(timezone.utc))
    source_health._record("old_site", False, "HTTP 503", datetime.now(timezone.utc))
    r = await client.get("/api/v1/refresh/source-health")
    assert r.status_code == 200 and r.json()["old_site"]["ok"] is False

    app.dependency_overrides[get_current_user] = lambda: User(
        id=1, email="analyst@example.com", role=UserRole.ANALYST, is_active=True, scope_type=UserScope.NATIONAL,
    )
    # No restore needed: the client fixture clears every override at teardown.
    assert (await client.get("/api/v1/refresh/source-health")).status_code == 403
