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
        source_health._record("old_site", False, "HTTP 503", t0 + timedelta(hours=2))

    alerts = [r for r in caplog.records if "SOURCE DOWN" in r.getMessage()]
    assert len(alerts) == 1 and alerts[0].levelno == logging.ERROR, "alert on the transition, not every hour"
    assert source_health.current_status()["old_site"]["down_since"] == (t0 + timedelta(hours=1)).isoformat()


def test_a_healthy_first_check_is_silent_and_a_failing_one_alerts(caplog):
    """Found live: every boot logged "SOURCE RECOVERED" for healthy sites,
    because no previous status was treated as a transition."""
    now = datetime(2026, 9, 20, 3, 0, tzinfo=timezone.utc)
    with caplog.at_level(logging.WARNING, logger="source_health"):
        source_health._record("new_site", True, "report page loads", now)
        assert caplog.records == []
        source_health._record("old_site", False, "HTTP 503", now)
    assert [r.levelno for r in caplog.records] == [logging.ERROR]


def test_recovery_clears_down_since():
    t0 = datetime(2026, 9, 20, 3, 0, tzinfo=timezone.utc)
    source_health._record("old_site", False, "HTTP 503", t0)
    source_health._record("old_site", True, "report page loads", t0 + timedelta(hours=1))
    assert source_health.current_status()["old_site"]["down_since"] is None


async def test_status_endpoint_is_admin_only(client):
    source_health._record("old_site", False, "HTTP 503", datetime.now(timezone.utc))
    r = await client.get("/api/v1/refresh/source-health")
    assert r.status_code == 200 and r.json()["old_site"]["ok"] is False

    app.dependency_overrides[get_current_user] = lambda: User(
        id=1, email="analyst@example.com", role=UserRole.ANALYST, is_active=True, scope_type=UserScope.NATIONAL,
    )
    # No restore needed: the client fixture clears every override at teardown.
    assert (await client.get("/api/v1/refresh/source-health")).status_code == 403
