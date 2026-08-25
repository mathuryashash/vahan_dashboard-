"""Live VAHAN4 scraper — drives the dashboard's JSF/PrimeFaces AJAX protocol
directly over HTTP, with no browser involved.

Why not Playwright: headless Chromium gets an immediate 403 "Access Forbidden"
from this site's bot detection, before any interaction even happens — plain
HTTP requests to the exact same URL get a normal 200. This was confirmed by
directly comparing the two, repeatedly, from the same network path.

The site's UI is a stateful JSF form (PrimeFaces widgets over a server-side
ViewState). Two things about it are easy to get wrong when replaying it by
hand instead of through a real browser:

1. PrimeFaces.ab() (the client-side call every widget interaction makes) is a
   thin wrapper around a full jQuery form serialization — a real browser
   submits *every* current field value on *every* AJAX request, not just the
   one that changed. This app's server-side beans throw a bare
   `javax.faces.el.EvaluationException` (no detail message) if you omit
   fields the client would normally still be sending. So this module tracks a
   full form-state dict and resubmits it whole every time, mirroring that.
2. Some components have a real DOM `id` that differs from the identifier used
   elsewhere (e.g. the actual "generate report" button's id is `irclay`, not
   any of the several buttons whose visible label is literally "Refresh";
   the results table's widget var is `reportTable` but its real id —
   the one needed for javax.faces.source/execute/render — is `groupingTable`).
   These were found by capturing real browser network traffic and diffing it
   against what this module was sending, not by guessing.

Also worth knowing: the State dropdown's JSF component id is auto-generated
from tree position (`j_idtNN`) and drifts far more often than a one-time
fluke -- observed changing THREE times in two days of scraping (`j_idt34`
-> `j_idt39` -> `j_idt38`), seemingly per-session rather than per-deploy.
Hardcoding it and re-deriving by hand each time it broke was the wrong fix at
the wrong altitude (recurring maintenance burden with detection only after a
scrape silently no-ops). Instead, `discover_state_select_id()` finds it fresh
on every page load by content, not position: the State select's first option
is always literally "All Vahan4 Running States (N/36)" -- unlike the id,
that text is stable, so we scan every `<select>` block for the one whose
first option matches it, rather than trusting a remembered id.
"""

import asyncio
import html
import logging
import re
from datetime import datetime, timezone

import httpx

from scraper.parsing import MONTH_ABBR, parse_count, parse_rto_option, parse_state_option

logger = logging.getLogger("vahan_scraper")

REPORT_URL = "https://vahan.parivahan.gov.in/vahan4dashboard/vahan/view/reportview.xhtml"
REQUEST_DELAY_SECONDS = 1.5

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

RTO_SELECT_ID = "selectedRto"
YAXIS_SELECT_ID = "yaxisVar"
XAXIS_SELECT_ID = "xaxisVar"
YEAR_SELECT_ID = "selectedYear"
REFRESH_BUTTON_ID = "irclay"
TABLE_ID = "groupingTable"
PAGE_SIZE = 25
# Safety net, not a real limit: a single RTO's pivot table has at most a few
# hundred rows in practice. This guards against a parsing bug (row_count
# misread from a malformed response) turning the pagination loop below into
# an unbounded hammer against the live site.
MAX_PAGES = 200


def _extract_viewstate(text: str) -> str | None:
    m = re.search(
        r'(?:name="javax\.faces\.ViewState"[^>]*value="([^"]*)"'
        r'|<update id="[^"]*javax\.faces\.ViewState[^"]*"><!\[CDATA\[([^\]]*)\]\]></update>)',
        text,
    )
    return (m.group(1) or m.group(2)) if m else None


def _parse_select_defaults(text: str) -> dict[str, str]:
    """Every <select id="X_input" name="X_input"> present in `text`, mapped to
    its currently-selected option value (or its first option, if none is
    marked selected). Used both for the initial full-page load and to
    re-sync after a partial response changes a field's default (e.g.
    xaxisVar=Month Wise auto-locks selectedYearType to Calendar Year)."""
    values: dict[str, str] = {}
    for m in re.finditer(r'<select id="([^"]+)_input" name="\1_input"[^>]*>(.*?)</select>', text, re.S):
        select_id, inner = m.group(1), m.group(2)
        opt = re.search(r'<option value="([^"]*)"[^>]*selected="selected"', inner)
        if opt is None:
            opt = re.search(r'<option value="([^"]*)"', inner)
        values[f"{select_id}_input"] = opt.group(1) if opt else ""
        values[f"{select_id}_focus"] = ""
    return values


def _parse_options(text: str, select_id: str) -> list[tuple[str, str]]:
    """[(value, display_text), ...] for every <option> under the given select."""
    m = re.search(rf'<select id="{re.escape(select_id)}_input"[^>]*>(.*?)</select>', text, re.S)
    if not m:
        return []
    return [
        (value, html.unescape(text_))
        for value, text_ in re.findall(r'<option value="([^"]*)"[^>]*>([^<]*)</option>', m.group(1))
    ]


def _parse_month_columns(text: str) -> list[str]:
    """Month abbreviations in column order, e.g. ['JAN', 'FEB', ...] — the
    report only has columns for months with data so far in the target year,
    so this is read from the response rather than assumed to be all 12.
    Header labels are padded with non-breaking spaces (e.g.
    'aria-label="\\xa0\\xa0 JAN \\xa0\\xa0"'), not plain whitespace."""
    return [m for m in re.findall(r'aria-label="[\s\xa0]*([A-Z]{3})[\s\xa0]*"', text) if m in MONTH_ABBR]


def _parse_table_rows(text: str, num_month_cols: int) -> list[list[str]]:
    """Row cell text values in order: [S No, Maker, <month>..., Total]."""
    cells = re.findall(rf'<label id="{TABLE_ID}:\d+:[^"]*"[^>]*>([^<]*)</label>', text)
    row_len = 2 + num_month_cols + 1
    if row_len <= 0:
        return []
    return [cells[i : i + row_len] for i in range(0, len(cells) - row_len + 1, row_len)]


def _parse_row_count(text: str) -> int:
    m = re.search(r"rowCount:(\d+)", text)
    return int(m.group(1)) if m else 0


# When Y-axis=Maker and X-axis=Vehicle Class, VAHAN's own column headers are
# ['S No', <a static "Vehicle Class" label VAHAN always shows here regardless
# of Y-axis choice -- a UI quirk, not a real column>, 'TOTAL', <class1>,
# <class2>, ...] -- TOTAL sits right after the row label, *before* the
# per-class columns, unlike the month pivot where TOTAL is last. Confirmed
# against a live response this session (2026-08-25).
_MAKER_CATEGORY_NON_CLASS_HEADERS = {"S NO", "VEHICLE CLASS", "TOTAL"}


def _parse_vehicle_class_columns(text: str) -> list[str]:
    """Vehicle class names in column order for the Maker x Vehicle Class
    pivot, read from aria-label headers same as _parse_month_columns reads
    month abbreviations -- but here the values are full class names, not
    fixed 3-letter codes, so this can't reuse the same MONTH_ABBR allowlist.
    Excludes the fixed S No/Vehicle Class-label/TOTAL headers that appear on
    every response regardless of which classes are actually present."""
    # Bounded to 1-40 chars: matches the exact pattern confirmed live against
    # a real click_refresh() response this session -- these responses are
    # JSF partial-response fragments scoped to just the table panel, not the
    # full page, so an unscoped aria-label scan doesn't pick up unrelated
    # page chrome the way it would on a full-page load.
    labels = re.findall(r'aria-label="([^"]{1,40})"', text)
    classes = []
    for label in labels:
        cleaned = label.strip("\xa0 \t")
        if not cleaned or cleaned.upper() in _MAKER_CATEGORY_NON_CLASS_HEADERS:
            continue
        classes.append(html.unescape(cleaned))
    return classes


def _parse_maker_category_table_rows(text: str, num_class_cols: int) -> list[list[str]]:
    """Row cell text values in order: [S No, Maker, Total, <class>...] -- same
    cell-extraction mechanism as _parse_table_rows (same TABLE_ID-based label
    regex), just a different column layout (Total before the per-class
    counts, not after)."""
    cells = re.findall(rf'<label id="{TABLE_ID}:\d+:[^"]*"[^>]*>([^<]*)</label>', text)
    row_len = 2 + 1 + num_class_cols
    if row_len <= 0:
        return []
    return [cells[i : i + row_len] for i in range(0, len(cells) - row_len + 1, row_len)]


class _VahanSession:
    """One authenticated (session-cookie) conversation with the VAHAN4
    dashboard's stateful JSF form. Not thread-safe / not for concurrent use —
    the server-side ViewState is a single conversation thread."""

    def __init__(self, client: httpx.AsyncClient):
        self._client = client
        self._viewstate: str | None = None
        self._form: dict[str, str] = {}

    async def load(self, retries: int = 3) -> str:
        """Fetches the report page and extracts its ViewState. A missing
        ViewState is retried like a transient failure rather than let through
        silently -- every subsequent AJAX POST needs a real value there, and
        without this check a missing one would make the whole scrape run to
        completion while quietly persisting nothing."""
        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                resp = await self._client.get(REPORT_URL)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code < 500 or attempt == retries - 1:
                    raise
                logger.warning(
                    "Transient %s loading VAHAN4 (attempt %d/%d), retrying...",
                    exc.response.status_code, attempt + 1, retries,
                )
                await asyncio.sleep(5 * (attempt + 1))
                continue
            except httpx.RequestError as exc:
                # Network/DNS/TLS failures are just as transient as a 5xx
                # response from VAHAN. Previously these escaped immediately,
                # so a short outage made every scraper subprocess fail even
                # though load() advertises retry behaviour.
                last_exc = exc
                if attempt == retries - 1:
                    raise
                logger.warning(
                    "Network error loading VAHAN4 (attempt %d/%d): %s; retrying...",
                    attempt + 1,
                    retries,
                    exc,
                )
                await asyncio.sleep(5 * (attempt + 1))
                continue

            viewstate = _extract_viewstate(resp.text)
            if viewstate is None:
                last_exc = RuntimeError(
                    "javax.faces.ViewState not found on the loaded VAHAN4 page -- "
                    "the site changed its field name/encoding, or served an "
                    "unexpected page (maintenance/error page, bot-check, etc). "
                    "Refusing to continue with no ViewState."
                )
                if attempt == retries - 1:
                    raise last_exc
                logger.warning("ViewState missing (attempt %d/%d), retrying...", attempt + 1, retries)
                await asyncio.sleep(5 * (attempt + 1))
                continue

            self._viewstate = viewstate
            self._form = _parse_select_defaults(resp.text)
            self._form["masterLayout_formlogin"] = "masterLayout_formlogin"
            return resp.text
        raise last_exc  # pragma: no cover - loop always returns or raises above

    async def _post(self, source: str, execute: str, render: str, *, is_click: bool = False) -> str:
        data = dict(self._form)
        data["javax.faces.partial.ajax"] = "true"
        data["javax.faces.source"] = source
        data["javax.faces.partial.execute"] = execute
        data["javax.faces.partial.render"] = render
        data["javax.faces.ViewState"] = self._viewstate
        if is_click:
            data[source] = source
        else:
            data["javax.faces.partial.event"] = "change"
            data["javax.faces.behavior.event"] = "change"
        resp = await self._client.post(
            REPORT_URL,
            data=data,
            headers={
                "Faces-Request": "partial/ajax",
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Referer": REPORT_URL,
                "Origin": "https://vahan.parivahan.gov.in",
                "Accept": "application/xml, text/xml, */*; q=0.01",
            },
        )
        resp.raise_for_status()
        text = resp.text
        if "<error>" in text:
            raise RuntimeError(f"VAHAN AJAX error (source={source}): {text[:300]}")
        vs = _extract_viewstate(text)
        if vs:
            self._viewstate = vs
        return text

    async def select(self, select_id: str, value: str, execute: str, render: str) -> str:
        self._form[f"{select_id}_input"] = value
        return await self._post(select_id, execute, render)

    def sync_defaults_from(self, response_text: str) -> None:
        """Re-read any <select> defaults present in a partial response — some
        selections (e.g. xaxisVar=Month Wise) server-side auto-change other
        fields (selectedYearType gets locked to Calendar Year)."""
        self._form.update(_parse_select_defaults(response_text))

    async def click_refresh(self) -> str:
        return await self._post(REFRESH_BUTTON_ID, "@all", "tablePnl", is_click=True)

    async def fetch_table_page(self, first: int) -> str:
        data = dict(self._form)
        data.update(
            {
                "javax.faces.partial.ajax": "true",
                "javax.faces.source": TABLE_ID,
                "javax.faces.partial.execute": TABLE_ID,
                "javax.faces.partial.render": TABLE_ID,
                "javax.faces.ViewState": self._viewstate,
                f"{TABLE_ID}_pagination": "true",
                f"{TABLE_ID}_first": str(first),
                f"{TABLE_ID}_rows": str(PAGE_SIZE),
                f"{TABLE_ID}_skipChildren": "true",
                f"{TABLE_ID}_encodeFeature": "true",
            }
        )
        resp = await self._client.post(
            REPORT_URL,
            data=data,
            headers={
                "Faces-Request": "partial/ajax",
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Referer": REPORT_URL,
                "Origin": "https://vahan.parivahan.gov.in",
                "Accept": "application/xml, text/xml, */*; q=0.01",
            },
        )
        resp.raise_for_status()
        text = resp.text
        vs = _extract_viewstate(text)
        if vs:
            self._viewstate = vs
        return text


_STATE_SELECT_MARKER = "All Vahan4 Running States"


def discover_state_select_id(page_html: str) -> str | None:
    """Find the State dropdown's current JSF id by content, not position --
    see module docstring for why the id itself can't be trusted to stay put.
    Returns the bare id (matching what _parse_options/select() expect), or
    None if no select's first option matches the marker text (the page's
    structure changed in some other way and this needs a fresh look)."""
    for select_id, body in re.findall(r'<select id="([^"]+)_input"[^>]*>(.*?)</select>', page_html, re.S):
        first_option = re.search(r'<option value="[^"]*"[^>]*>([^<]*)</option>', body)
        if first_option and _STATE_SELECT_MARKER in html.unescape(first_option.group(1)):
            return select_id
    return None


async def get_states(session: _VahanSession, page_html: str, state_select_id: str) -> list[dict]:
    states = []
    for value, text in _parse_options(page_html, state_select_id):
        if value == "-1":
            continue
        parsed = parse_state_option(text)
        if parsed:
            states.append({"state_code": value, "state_name": parsed["state_name"]})
    return states


# The site can only pivot on one Y-axis dimension per visit, so getting a
# full picture of a single RTO/month's registrations means visiting it
# multiple times with different yaxisVar values. Each dimension's rows
# independently sum to that RTO/month's true total (see Registration.is_supplementary
# in app/models/models.py for how callers avoid triple-counting because of this).
DIMENSIONS = {
    "maker": "Maker",
    "vehicle_class": "Vehicle Class",
    "fuel": "Fuel",
}


async def _configure_pivot(session: _VahanSession, year: int, yaxis_value: str, xaxis_value: str = "Month Wise") -> None:
    await session.select(YAXIS_SELECT_ID, yaxis_value, YAXIS_SELECT_ID, XAXIS_SELECT_ID)
    xaxis_resp = await session.select(XAXIS_SELECT_ID, xaxis_value, XAXIS_SELECT_ID, "multipleYear")
    # Month Wise locks selectedYearType to Calendar Year and re-defaults
    # selectedYear to the current year server-side; pick that up before
    # possibly overriding the year below.
    session.sync_defaults_from(xaxis_resp)
    if session._form.get(f"{YEAR_SELECT_ID}_input") != str(year):
        await session.select(YEAR_SELECT_ID, str(year), YEAR_SELECT_ID, YEAR_SELECT_ID)


async def scrape_yaxis_by_vehicle_class_table(session: _VahanSession, year: int, yaxis_value: str, label_key: str) -> list[dict]:
    """Assumes state + RTO are already selected. Configures <yaxis_value> x
    Vehicle Class (X-axis=Vehicle Class instead of Month Wise -- the only
    way to get a second real dimension alongside vehicle class, discovered
    live against VAHAN this session; see docs/superpowers/specs/
    2026-08-25-maker-category-crosstab-design.md). Works identically for
    yaxis_value='Maker' or 'Fuel' -- VAHAN's table layout is the same
    regardless of which Y-axis dimension is selected, only the row label's
    meaning differs (a maker name vs. a raw fuel_type string), which is why
    this takes `label_key` rather than hardcoding "maker" in the record
    dict. No month breakdown exists in this response at all -- returns
    [{label_key: str, 'vehicle_class': str, 'count': int}, ...] for the
    whole year in one shot."""
    await _configure_pivot(session, year, yaxis_value, xaxis_value="Vehicle Class")
    table_html = await session.click_refresh()

    class_cols = _parse_vehicle_class_columns(table_html)
    row_count = _parse_row_count(table_html)
    if not class_cols or row_count == 0:
        return []

    records: list[dict] = []

    def _rows_to_records(rows: list[list[str]]) -> None:
        for row in rows:
            if len(row) < 2 + 1 + len(class_cols):
                continue
            label = html.unescape(row[1]).strip()
            for offset, vehicle_class in enumerate(class_cols):
                count = parse_count(row[3 + offset])
                if count:
                    records.append({label_key: label, "vehicle_class": vehicle_class, "count": count})

    _rows_to_records(_parse_maker_category_table_rows(table_html, len(class_cols)))

    first = PAGE_SIZE
    pages_fetched = 0
    while first < row_count and pages_fetched < MAX_PAGES:
        page_html = await session.fetch_table_page(first)
        _rows_to_records(_parse_maker_category_table_rows(page_html, len(class_cols)))
        first += PAGE_SIZE
        pages_fetched += 1

    return records


async def scrape_maker_category_table(session: _VahanSession, year: int) -> list[dict]:
    """Maker x Vehicle Class -- see scrape_yaxis_by_vehicle_class_table."""
    return await scrape_yaxis_by_vehicle_class_table(session, year, DIMENSIONS["maker"], "maker")


async def scrape_fuel_category_table(session: _VahanSession, year: int) -> list[dict]:
    """Fuel x Vehicle Class -- see scrape_yaxis_by_vehicle_class_table.
    'label' is a raw fuel_type string (e.g. 'CNG ONLY'), not yet grouped
    into ICE/Hybrid/EV -- that happens at persist time via fuel_group()."""
    return await scrape_yaxis_by_vehicle_class_table(session, year, DIMENSIONS["fuel"], "fuel_type")


async def scrape_pivot_table(session: _VahanSession, year: int, dimension: str) -> list[dict]:
    """Assumes state + RTO are already selected. Configures the
    <dimension> x Month pivot (dimension is one of DIMENSIONS' keys), reads
    all pages of results, returns
    [{'label': str, 'month': int, 'year': year, 'count': int}, ...] — 'label'
    is the row's maker/vehicle-class/fuel-type name depending on dimension;
    the caller (persist_rto_batch) maps it to the right column."""
    yaxis_value = DIMENSIONS[dimension]
    await _configure_pivot(session, year, yaxis_value)
    table_html = await session.click_refresh()

    month_cols = _parse_month_columns(table_html)
    row_count = _parse_row_count(table_html)
    if not month_cols or row_count == 0:
        return []

    records: list[dict] = []

    def _rows_to_records(rows: list[list[str]]) -> None:
        for row in rows:
            if len(row) < 2 + len(month_cols) + 1:
                continue
            label = html.unescape(row[1]).strip()
            for offset, month_abbr in enumerate(month_cols):
                count = parse_count(row[2 + offset])
                records.append({"label": label, "month": MONTH_ABBR[month_abbr], "year": year, "count": count})

    _rows_to_records(_parse_table_rows(table_html, len(month_cols)))

    first = PAGE_SIZE
    pages_fetched = 0
    while first < row_count and pages_fetched < MAX_PAGES:
        page_html = await session.fetch_table_page(first)
        _rows_to_records(_parse_table_rows(page_html, len(month_cols)))
        first += PAGE_SIZE
        pages_fetched += 1

    return records


async def _scrape_state(
    session: _VahanSession,
    state: dict,
    state_select_id: str,
    year: int,
    dimension: str,
    delay_seconds: float,
    already_done: frozenset[str],
) -> list[dict]:
    """Scrape all RTOs for a single state. Returns list of yielded items (RTO batches + state_complete)."""
    state_name = state["state_name"]
    items: list[dict] = []
    try:
        rto_resp = await session.select(
            state_select_id, state["state_code"], state_select_id, f"{RTO_SELECT_ID} {YAXIS_SELECT_ID}"
        )
    except Exception as exc:
        logger.warning("Failed selecting state %s: %s", state_name, exc)
        items.append({
            "state_complete": True, "state_name": state_name,
            "rto_total": 0, "rto_skipped": 0, "rto_succeeded": 0, "rto_empty": 0,
        })
        return items

    all_rtos = [
        {**parsed, "rto_value": value}
        for value, text in _parse_options(rto_resp, RTO_SELECT_ID)
        if value != "-1"
        for parsed in [parse_rto_option(text)]
        if parsed
    ]
    rtos = [rto for rto in all_rtos if rto["rto_code"] not in already_done]
    skipped_count = len(all_rtos) - len(rtos)
    if skipped_count:
        logger.info("%s: skipping %d already-scraped RTOs, %d remaining", state_name, skipped_count, len(rtos))

    succeeded = 0
    empty = 0
    for rto in rtos:
        try:
            await session.select(RTO_SELECT_ID, rto["rto_value"], RTO_SELECT_ID, YAXIS_SELECT_ID)
            records = await scrape_pivot_table(session, year, dimension)
            if not records:
                empty += 1
                logger.warning(
                    "%s / %s: zero records (dimension=%s, year=%d)",
                    state_name, rto["rto_code"], dimension, year,
                )
            items.append({
                "state_name": state_name,
                "rto_code": rto["rto_code"],
                "rto_name": rto["rto_name"],
                "records": records,
            })
            succeeded += 1
        except Exception as exc:
            logger.warning("Failed scraping %s / %s: %s", state_name, rto["rto_code"], exc)
        finally:
            await asyncio.sleep(delay_seconds)

    if empty:
        logger.warning(
            "%s: %d/%d scraped RTOs returned zero records (dimension=%s, year=%d)",
            state_name, empty, succeeded, dimension, year,
        )

    items.append({
        "state_complete": True,
        "state_name": state_name,
        "rto_total": len(all_rtos),
        "rto_skipped": skipped_count,
        "rto_succeeded": succeeded,
        "rto_empty": empty,
    })
    return items


async def _scrape_state_worker(
    state: dict,
    state_select_id: str,
    year: int,
    dimension: str,
    delay_seconds: float,
    already_done: frozenset[str],
) -> list[dict]:
    """Independent worker: creates its own HTTP client + session, scrapes one state fully."""
    async with httpx.AsyncClient(
        headers={"User-Agent": _USER_AGENT}, timeout=30, follow_redirects=True
    ) as client:
        session = _VahanSession(client)
        await session.load()
        return await _scrape_state(session, state, state_select_id, year, dimension, delay_seconds, already_done)


async def scrape_all_india(
    year: int,
    dimension: str = "maker",
    delay_seconds: float = REQUEST_DELAY_SECONDS,
    skip_rtos: dict[str, frozenset[str]] = {},  # noqa: B006 - never mutated
    max_concurrent_states: int = 1,
):
    """Async generator yielding one dict per (state, rto) combination:
    {'state_name': str, 'rto_code': str, 'rto_name': str, 'records': [ {label, month, year, count}, ... ]}
    `dimension` is one of DIMENSIONS' keys ('maker', 'vehicle_class', 'fuel')
    and controls which Y-axis pivot is scraped -- see scrape_pivot_table.

    After each state's RTOs are all attempted, also yields a completion
    summary: {'state_complete': True, 'state_name': str, 'rto_total': int,
    'rto_skipped': int, 'rto_succeeded': int}. Callers that want to know
    whether a state's real data fully replaced its fallback (e.g. synthetic
    seed) data need this — a state is fully done once
    rto_skipped + rto_succeeded == rto_total, accounting for RTOs completed
    in *previous* interrupted runs, not just this one.

    `skip_rtos` maps state_name -> a set of rto_codes already scraped in a
    previous (interrupted) run, so resuming makes forward progress within a
    partially-done state instead of restarting it from its first RTO every
    time — this matters a lot for large states when the process keeps getting
    cut off before finishing even one of them.

    `max_concurrent_states` controls how many states are scraped in parallel.
    Each state runs in its own independent HTTP session with its own pacing
    (delay_seconds between RTO requests), so N concurrent states means N
    requests every ~delay_seconds instead of 1. Default=1 preserves the
    original serial behavior.
    """
    async with httpx.AsyncClient(
        headers={"User-Agent": _USER_AGENT}, timeout=30, follow_redirects=True
    ) as client:
        session = _VahanSession(client)
        page_html = await session.load()
        state_select_id = discover_state_select_id(page_html)
        if state_select_id is None:
            raise RuntimeError(
                "Could not find the State dropdown on the live page -- its marker text "
                f"({_STATE_SELECT_MARKER!r}) wasn't found in any <select>. The page's "
                "structure changed in some way beyond an id shift; inspect a fresh fetch."
            )
        states = await get_states(session, page_html, state_select_id)
        logger.info("Discovered %d states", len(states))

        if max_concurrent_states <= 1:
            # Original serial path - reuse the discovery session (client stays open)
            for state in states:
                state_name = state["state_name"]
                already_done = skip_rtos.get(state_name, frozenset())
                items = await _scrape_state(session, state, state_select_id, year, dimension, delay_seconds, already_done)
                for item in items:
                    yield item
            return

        # Concurrent path: partition states across workers, each with its own session
        semaphore = asyncio.Semaphore(max_concurrent_states)

        async def _worker(state: dict) -> list[dict]:
            async with semaphore:
                already_done = skip_rtos.get(state["state_name"], frozenset())
                return await _scrape_state_worker(state, state_select_id, year, dimension, delay_seconds, already_done)

        # Launch all state workers
        tasks = [_worker(state) for state in states]
        for coro in asyncio.as_completed(tasks):
            items = await coro
            for item in items:
                yield item


async def scrape_all_india_crosstab(
    year: int,
    table_scraper,
    dimension_label: str,
    delay_seconds: float = REQUEST_DELAY_SECONDS,
    skip_rtos: dict[str, frozenset[str]] = {},  # noqa: B006 - never mutated
):
    """Async generator for a <Y-axis> x Vehicle Class pivot -- same shape of
    yields as scrape_all_india (RTO batches + state-complete summaries), but
    serial-only (no concurrent_states) and parameterized by which table
    scraper to call (scrape_maker_category_table or scrape_fuel_category_table)
    rather than a `dimension` choice of three, since each of these is one
    pivot, not a family. Kept deliberately simpler than scrape_all_india:
    these are new, not-yet-backfilled capabilities (see the design spec's
    "out of scope" section), not a proven-at-scale path that needs the same
    throughput levers yet.
    """
    async with httpx.AsyncClient(
        headers={"User-Agent": _USER_AGENT}, timeout=30, follow_redirects=True
    ) as client:
        session = _VahanSession(client)
        page_html = await session.load()
        state_select_id = discover_state_select_id(page_html)
        if state_select_id is None:
            raise RuntimeError(
                "Could not find the State dropdown on the live page -- its marker text "
                f"({_STATE_SELECT_MARKER!r}) wasn't found in any <select>. The page's "
                "structure changed in some way beyond an id shift; inspect a fresh fetch."
            )
        states = await get_states(session, page_html, state_select_id)
        logger.info("Discovered %d states", len(states))

        for state in states:
            state_name = state["state_name"]
            already_done = skip_rtos.get(state_name, frozenset())
            try:
                rto_resp = await session.select(
                    state_select_id, state["state_code"], state_select_id, f"{RTO_SELECT_ID} {YAXIS_SELECT_ID}"
                )
            except Exception as exc:
                logger.warning("Failed selecting state %s: %s", state_name, exc)
                yield {
                    "state_complete": True, "state_name": state_name,
                    "rto_total": 0, "rto_skipped": 0, "rto_succeeded": 0, "rto_empty": 0,
                }
                continue

            all_rtos = [
                {**parsed, "rto_value": value}
                for value, text in _parse_options(rto_resp, RTO_SELECT_ID)
                if value != "-1"
                for parsed in [parse_rto_option(text)]
                if parsed
            ]
            rtos = [rto for rto in all_rtos if rto["rto_code"] not in already_done]
            skipped_count = len(all_rtos) - len(rtos)
            if skipped_count:
                logger.info("%s: skipping %d already-scraped RTOs, %d remaining", state_name, skipped_count, len(rtos))

            succeeded = 0
            empty = 0
            for rto in rtos:
                try:
                    await session.select(RTO_SELECT_ID, rto["rto_value"], RTO_SELECT_ID, YAXIS_SELECT_ID)
                    records = await table_scraper(session, year)
                    if not records:
                        empty += 1
                        logger.warning(
                            "%s / %s: zero records (dimension=%s, year=%d)",
                            state_name, rto["rto_code"], dimension_label, year,
                        )
                    yield {
                        "state_name": state_name,
                        "rto_code": rto["rto_code"],
                        "rto_name": rto["rto_name"],
                        "records": records,
                    }
                    succeeded += 1
                except Exception as exc:
                    logger.warning("Failed scraping %s / %s: %s", state_name, rto["rto_code"], exc)
                finally:
                    await asyncio.sleep(delay_seconds)

            yield {
                "state_complete": True,
                "state_name": state_name,
                "rto_total": len(all_rtos),
                "rto_skipped": skipped_count,
                "rto_succeeded": succeeded,
                "rto_empty": empty,
            }


def scrape_all_india_maker_category(year: int, delay_seconds: float = REQUEST_DELAY_SECONDS, skip_rtos: dict[str, frozenset[str]] = {}):  # noqa: B006
    """Maker x Vehicle Class -- see scrape_all_india_crosstab."""
    return scrape_all_india_crosstab(year, scrape_maker_category_table, "maker_category", delay_seconds, skip_rtos)


def scrape_all_india_fuel_category(year: int, delay_seconds: float = REQUEST_DELAY_SECONDS, skip_rtos: dict[str, frozenset[str]] = {}):  # noqa: B006
    """Fuel x Vehicle Class -- see scrape_all_india_crosstab."""
    return scrape_all_india_crosstab(year, scrape_fuel_category_table, "fuel_category", delay_seconds, skip_rtos)


if __name__ == "__main__":

    async def _debug_run():
        logging.basicConfig(level=logging.INFO)
        count = 0
        async for batch in scrape_all_india(year=datetime.now(timezone.utc).year):
            count += 1
            print(batch["state_name"], batch["rto_code"], len(batch["records"]), "records")
            if count >= 3:
                break

    asyncio.run(_debug_run())
