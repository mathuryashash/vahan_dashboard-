# Live VAHAN4 Scraper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the dead/disconnected scraper stubs with a real Playwright scraper that pulls live State → RTO → Maker → Month registration data from `vahan.parivahan.gov.in/vahan4dashboard/`, persists it into the existing `Registration` table, and runs automatically every 24 hours.

**Architecture:** A pure-parsing module (`backend/scraper/parsing.py`) handles all string/regex extraction and is fully unit-tested without network access. A Playwright interaction module (`backend/scraper/vahan_scraper.py`) drives the live PrimeFaces dashboard and is verified manually against the real site (it cannot be meaningfully unit-tested — there is no safe way to mock a live gov.in PrimeFaces AJAX app). A persistence layer in `backend/app/services/scraper_service.py` takes scraped records and upserts them into SQLite via the existing async SQLAlchemy `Registration` model, tested against the in-memory test DB with fabricated records (no network). A background scheduler task, started from `main.py`'s lifespan, calls the whole pipeline once at startup and then every 24 hours; the existing `/api/v1/refresh/` endpoint triggers it on demand.

**Tech Stack:** Playwright (async, Chromium), SQLAlchemy async ORM (existing `Registration`/`RTO`/`State` models), pytest/pytest-asyncio, asyncio background task in FastAPI lifespan.

**Confirmed site facts (verified live via Playwright on 2026-07-08):**
- `https://analytics.parivahan.gov.in/analytics/publicdashboard/vahan` (used by the old dead scraper) returns **HTTP 403 "Request forbidden by administrative rules"** — a WAF block, confirmed even with a full headless Chromium browser, realistic UA, and referer chain from the root site. This URL is unusable and must not be reused.
- `https://vahan.parivahan.gov.in/vahan4dashboard/vahan/view/reportview.xhtml` returns **HTTP 200** and loads directly into the same filter UI as the "Tabular Summary" view (no menu click needed) — this is the scrape entry point.
- The page is PrimeFaces/JSF. Every filter is a `ui-selectonemenu` widget: a trigger `<div id="{id}">`, a panel `<div id="{id}_panel">` that only exists/is visible while open, containing `<li>` items with human-readable text. Native `<select id="{id}_input">` elements exist but are hidden (`aria-hidden`) — clicking them does nothing; you must click the trigger, wait for the panel, then click the matching `<li>`.
- Confirmed stable widget IDs on `reportview.xhtml` (same across repeated fresh loads): `#j_idt24` (Type: In Thousand/In Lakh/In Crore/**Actual Value**), `#j_idt33` (State), `#selectedRto` (RTO/Office — repopulates via AJAX after a State is picked), `#yaxisVar` (Y-Axis: Vehicle Category / Vehicle Class / Norms / Fuel / **Maker** / State), `#xaxisVar` (X-Axis: Vehicle Category / Norms / Fuel / Vehicle Category Group / Financial Year / Calendar Year / **Month Wise**), `#selectedYearType` (Financial Year / **Calendar Year**), `#selectedYear` (2003–2026, "Till Today").
- State option text format: `"<Name>(<rto_count>)"`, e.g. `"Delhi(16)"`, `"Andhra Pradesh(84)"`. The "All ..." aggregate option is `"All Vahan4 Running States (36/36)"` — note the `/` inside the parens, which distinguishes it from real entries and lets a regex requiring digits-only parens skip it for free.
- RTO option text format: `"<OFFICE NAME> (<LOCATION>) - <CODE>( <DATE> )"`, e.g. `"OLD DELHI (MALL ROAD) - DL1( 12-OCT-2015 )"`, `"JHULJHULI FITNESS CENTER - DL207( 19-JUN-2017 )"`. The aggregate option is `"All Vahan4 Running Office(16/16)"`.
- With Y-Axis=Maker, X-Axis=Month Wise, Year Type=Calendar Year, Year=2026, the result table's `<th>` row is `S No | Maker | Month Wise | TOTAL | JAN | FEB | ... | JUL` (only months up to the current month appear) and each `<tbody>` row is `[S No, Maker Name, <one numeric cell per month column present>, <total>]` — confirmed real example for Delhi/Old Delhi RTO: `HONDA MOTORCYCLE AND SCOOTER INDIA (P) LTD → 91, 34, 24, 21, 32, 30, 12 → total 244`. Numbers use Indian comma grouping (e.g. `1,23,456`) and must be parsed accordingly. The table paginates (~25 makers/page) via a standard PrimeFaces `.ui-paginator-next` button.
- **Scope limitation to flag to the user:** the Y-Axis list has no "Model"/"Brand" option — only Maker-level granularity is available from this public dashboard, not individual vehicle models (e.g. "Activa 3G" vs "Activa 4G"). The scraper stores `vehicle_class = "All"` for these rows since Maker×Month is captured without a vehicle-category filter (confirmed: the Delhi/Old Delhi maker list mixed two-wheeler OEMs like Yamaha with four-wheeler OEMs like Hyundai in the same unscoped result). True per-vehicle-class breakdown would require re-running the scrape once per Vehicle Category Group checkbox (≈10x cost) — out of scope for this plan; noted as a future enhancement.

---

## Task 0: Add Playwright dependency

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Add the dependency**

Append to `backend/requirements.txt`:
```
playwright>=1.45.0
```

- [ ] **Step 2: Install it and the browser binary**

Run (from `backend/`):
```bash
pip install -r requirements.txt -q
python -m playwright install chromium
```
Expected: no errors; `python -c "import playwright; print('ok')"` prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add backend/requirements.txt
git commit -m "chore: add playwright dependency for live VAHAN4 scraper"
```

---

## Task 1: Pure parsing helpers (TDD, no network)

**Files:**
- Create: `backend/scraper/__init__.py`
- Create: `backend/scraper/parsing.py`
- Test: `backend/tests/test_scraper_parsing.py`

- [ ] **Step 1: Make `scraper/` an explicit package**

`backend/scraper/` currently has no `__init__.py` (unlike `backend/app/`, which has one). Create an empty file so imports like `scraper.parsing` and `scraper.vahan_scraper` resolve the same reliable way `app.*` imports already do:

```bash
touch backend/scraper/__init__.py
```

- [ ] **Step 2: Write the failing tests**

```python
# backend/tests/test_scraper_parsing.py
from scraper.parsing import (
    parse_state_option,
    parse_rto_option,
    parse_count,
    MONTH_ABBR,
)


def test_parse_state_option_normal():
    assert parse_state_option("Delhi(16)") == {"state_name": "Delhi", "rto_count": 16}


def test_parse_state_option_with_parens_in_name():
    assert parse_state_option("UT of DNH and DD(3)") == {
        "state_name": "UT of DNH and DD",
        "rto_count": 3,
    }


def test_parse_state_option_skips_aggregate_row():
    assert parse_state_option("All Vahan4 Running States (36/36)") is None


def test_parse_rto_option_normal():
    result = parse_rto_option("OLD DELHI (MALL ROAD) - DL1( 12-OCT-2015 )")
    assert result == {"rto_name": "OLD DELHI (MALL ROAD)", "rto_code": "DL1"}


def test_parse_rto_option_fitness_center():
    result = parse_rto_option("JHULJHULI FITNESS CENTER - DL207( 19-JUN-2017 )")
    assert result == {"rto_name": "JHULJHULI FITNESS CENTER", "rto_code": "DL207"}


def test_parse_rto_option_skips_aggregate_row():
    assert parse_rto_option("All Vahan4 Running Office(16/16)") is None


def test_parse_count_indian_grouping():
    assert parse_count("1,23,456") == 123456


def test_parse_count_plain_number():
    assert parse_count("244") == 244


def test_parse_count_blank_or_dash():
    assert parse_count("") == 0
    assert parse_count("-") == 0
    assert parse_count("  ") == 0


def test_month_abbr_covers_all_twelve():
    assert MONTH_ABBR["JAN"] == 1
    assert MONTH_ABBR["DEC"] == 12
    assert len(MONTH_ABBR) == 12
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_scraper_parsing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scraper.parsing'` (or similar import error) for every test.

- [ ] **Step 4: Write the implementation**

```python
# backend/scraper/parsing.py
import re

MONTH_ABBR = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4,
    "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8,
    "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

_STATE_OPTION_RE = re.compile(r"^(.*)\((\d+)\)$")
_RTO_OPTION_RE = re.compile(r"^(.*?)\s*-\s*([A-Z]{2}\d+[A-Z]*)\(\s*[\d-]+-[A-Z]{3}-\d{4}\s*\)$")


def parse_state_option(text: str) -> dict | None:
    """Parse a VAHAN4 state dropdown option like 'Delhi(16)' into name + RTO count.

    Returns None for the aggregate 'All Vahan4 Running States (36/36)' row —
    its parenthesized content has a slash, so it never matches the digits-only pattern.
    """
    match = _STATE_OPTION_RE.match(text.strip())
    if not match:
        return None
    return {"state_name": match.group(1).strip(), "rto_count": int(match.group(2))}


def parse_rto_option(text: str) -> dict | None:
    """Parse a VAHAN4 RTO dropdown option like
    'OLD DELHI (MALL ROAD) - DL1( 12-OCT-2015 )' into name + code.

    Returns None for the aggregate 'All Vahan4 Running Office(...)' row.
    """
    match = _RTO_OPTION_RE.match(text.strip())
    if not match:
        return None
    return {"rto_name": match.group(1).strip(), "rto_code": match.group(2).strip()}


def parse_count(text: str) -> int:
    """Parse an Indian comma-grouped count like '1,23,456' into an int. Blank/'-' -> 0."""
    cleaned = text.strip().replace(",", "")
    if not cleaned or cleaned == "-":
        return 0
    return int(cleaned)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_scraper_parsing.py -v`
Expected: PASS, 10 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/scraper/__init__.py backend/scraper/parsing.py backend/tests/test_scraper_parsing.py
git commit -m "feat: add pure parsing helpers for VAHAN4 scraper"
```

---

## Task 2: Playwright interaction module (single RTO scrape)

**Files:**
- Rewrite: `backend/scraper/vahan_scraper.py`

This module cannot be meaningfully unit-tested — it drives a live government AJAX app with dynamic widget state. It is verified manually in Task 5. Keep all pure logic (parsing, month math) in `parsing.py` from Task 1; this file should contain only Playwright orchestration.

- [ ] **Step 1: Write the module**

```python
# backend/scraper/vahan_scraper.py
import asyncio
import logging
from datetime import datetime
from playwright.async_api import async_playwright, Page

from scraper.parsing import parse_state_option, parse_rto_option, parse_count, MONTH_ABBR

logger = logging.getLogger("vahan_scraper")

REPORT_URL = "https://vahan.parivahan.gov.in/vahan4dashboard/vahan/view/reportview.xhtml"
REQUEST_DELAY_SECONDS = 1.5


async def _open_dropdown_panel(page: Page, trigger_id: str, timeout_ms: int = 5000):
    trigger = await page.query_selector(f"#{trigger_id}")
    if trigger is None:
        raise RuntimeError(f"Dropdown trigger #{trigger_id} not found on page")
    await trigger.scroll_into_view_if_needed()
    await trigger.click(force=True)
    await page.wait_for_selector(f"#{trigger_id}_panel", state="visible", timeout=timeout_ms)
    return await page.query_selector(f"#{trigger_id}_panel")


async def select_dropdown_option(page: Page, trigger_id: str, predicate) -> str | None:
    """Open a PrimeFaces ui-selectonemenu identified by trigger_id and click the first
    <li> option whose text satisfies predicate(text). Returns the matched text, or None
    if no option matched (the dropdown is closed via Escape in that case)."""
    panel = await _open_dropdown_panel(page, trigger_id)
    items = await panel.query_selector_all("li")
    for item in items:
        text = (await item.inner_text()).strip()
        if predicate(text):
            await item.wait_for_element_state("visible", timeout=3000)
            await item.click(force=True, timeout=5000)
            await page.wait_for_timeout(1200)
            return text
    await page.keyboard.press("Escape")
    return None


async def list_dropdown_options(page: Page, trigger_id: str) -> list[str]:
    """Open a dropdown, read all option texts, close it without selecting anything."""
    panel = await _open_dropdown_panel(page, trigger_id)
    items = await panel.query_selector_all("li")
    texts = [(await item.inner_text()).strip() for item in items]
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(300)
    return texts


async def get_states(page: Page) -> list[dict]:
    """Return [{'state_name': ..., 'rto_count': ...}, ...] for all real states (no aggregate row)."""
    texts = await list_dropdown_options(page, "j_idt33")
    parsed = [parse_state_option(t) for t in texts]
    return [p for p in parsed if p is not None]


async def select_state(page: Page, state_name: str) -> bool:
    result = await select_dropdown_option(
        page, "j_idt33", lambda t: t.strip().startswith(f"{state_name}(")
    )
    return result is not None


async def get_rtos_for_selected_state(page: Page) -> list[dict]:
    """Assumes a state was already selected (repopulates #selectedRto via AJAX)."""
    texts = await list_dropdown_options(page, "selectedRto")
    parsed = [parse_rto_option(t) for t in texts]
    return [p for p in parsed if p is not None]


async def select_rto(page: Page, rto_code: str) -> bool:
    result = await select_dropdown_option(
        page, "selectedRto", lambda t: (parse_rto_option(t) or {}).get("rto_code") == rto_code
    )
    return result is not None


async def configure_maker_month_pivot(page: Page, year: int) -> None:
    """Set Y-Axis=Maker, X-Axis=Month Wise, Year Type=Calendar Year, Year=<year>."""
    await select_dropdown_option(page, "yaxisVar", lambda t: t.strip() == "Maker")
    await select_dropdown_option(page, "xaxisVar", lambda t: t.strip() == "Month Wise")
    await select_dropdown_option(page, "selectedYearType", lambda t: t.strip() == "Calendar Year")
    await select_dropdown_option(page, "selectedYear", lambda t: t.strip() == str(year))


async def _click_refresh(page: Page) -> None:
    buttons = await page.query_selector_all("button, .ui-button")
    for button in buttons:
        text = (await button.inner_text()).strip().lower()
        button_id = (await button.get_attribute("id")) or ""
        if "refresh" in text or "refresh" in button_id.lower():
            await button.click(force=True)
            await page.wait_for_timeout(2500)
            return
    raise RuntimeError("Refresh button not found")


async def _read_current_page_rows(page: Page) -> tuple[list[str], list[list[str]]]:
    """Read headers + body rows from the Maker x Month result table (scrollable ui-datatable)."""
    tables = await page.query_selector_all("table[role='grid']")
    for table in tables:
        headers = [
            (await th.inner_text()).strip()
            for th in await table.query_selector_all("th")
        ]
        if "Maker" in headers and any(m in headers for m in MONTH_ABBR):
            rows = []
            for tr in await table.query_selector_all("tbody tr"):
                cells = [(await td.inner_text()).strip() for td in await tr.query_selector_all("td")]
                if cells:
                    rows.append(cells)
            return headers, rows
    return [], []


async def _go_to_next_page(page: Page) -> bool:
    next_button = await page.query_selector(".ui-paginator-next")
    if next_button is None:
        return False
    classes = (await next_button.get_attribute("class")) or ""
    if "ui-state-disabled" in classes:
        return False
    await next_button.click(force=True)
    await page.wait_for_timeout(1500)
    return True


async def scrape_maker_month_table(page: Page, year: int) -> list[dict]:
    """Assumes state + RTO are already selected. Configures the Maker x Month pivot,
    reads all pages of results, returns [{'maker': str, 'month': int, 'year': year, 'count': int}, ...].
    """
    await configure_maker_month_pivot(page, year)
    await _click_refresh(page)

    records: list[dict] = []
    seen_pages = 0
    max_pages = 50  # safety cap; a single RTO's maker list should never exceed this
    while seen_pages < max_pages:
        headers, rows = await _read_current_page_rows(page)
        month_columns = {
            idx: MONTH_ABBR[h]
            for idx, h in enumerate(headers)
            if h in MONTH_ABBR
        }
        try:
            maker_idx = headers.index("Maker")
        except ValueError:
            maker_idx = 1  # fallback: [S No, Maker, ...months..., Total]

        for cells in rows:
            if len(cells) <= maker_idx:
                continue
            maker = cells[maker_idx]
            for col_idx, month in month_columns.items():
                if col_idx >= len(cells):
                    continue
                count = parse_count(cells[col_idx])
                records.append({"maker": maker, "month": month, "year": year, "count": count})

        seen_pages += 1
        has_next = await _go_to_next_page(page)
        if not has_next:
            break

    return records


async def scrape_all_india(year: int, delay_seconds: float = REQUEST_DELAY_SECONDS):
    """Async generator yielding one dict per (state, rto) combination:
    {'state_name': str, 'rto_code': str, 'rto_name': str, 'records': [ {maker, month, year, count}, ... ]}
    Launches a single browser/page and reuses it for the whole run.
    """
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1600, "height": 1000},
        )
        page = await context.new_page()
        await page.goto(REPORT_URL, wait_until="networkidle", timeout=45000)
        await page.wait_for_timeout(3000)

        states = await get_states(page)
        logger.info("Discovered %d states", len(states))

        for state in states:
            state_name = state["state_name"]
            try:
                selected = await select_state(page, state_name)
                if not selected:
                    logger.warning("Could not select state %s, skipping", state_name)
                    continue
                await page.wait_for_timeout(1000)
                rtos = await get_rtos_for_selected_state(page)
            except Exception as exc:
                logger.warning("Failed listing RTOs for %s: %s", state_name, exc)
                continue

            for rto in rtos:
                try:
                    selected_rto = await select_rto(page, rto["rto_code"])
                    if not selected_rto:
                        logger.warning("Could not select RTO %s, skipping", rto["rto_code"])
                        continue
                    records = await scrape_maker_month_table(page, year)
                    yield {
                        "state_name": state_name,
                        "rto_code": rto["rto_code"],
                        "rto_name": rto["rto_name"],
                        "records": records,
                    }
                except Exception as exc:
                    logger.warning(
                        "Failed scraping %s / %s: %s", state_name, rto["rto_code"], exc
                    )
                finally:
                    await asyncio.sleep(delay_seconds)

        await browser.close()


if __name__ == "__main__":
    async def _debug_run():
        logging.basicConfig(level=logging.INFO)
        count = 0
        async for batch in scrape_all_india(year=datetime.now().year):
            count += 1
            print(batch["state_name"], batch["rto_code"], len(batch["records"]), "records")
            if count >= 3:
                break

    asyncio.run(_debug_run())
```

- [ ] **Step 2: Manual smoke test (single small state, not full India)**

Run from `backend/`:
```bash
python -m scraper.vahan_scraper
```
Expected: logs "Discovered 36 states", then prints 3 lines like `Andaman & Nicobar Island AN5 12 records` with a nonzero record count. If it errors on a selector, re-run the exploration pattern from Task 2's DOM notes above — the site's JSF component IDs are stable but confirm against a fresh page load if this breaks.

- [ ] **Step 3: Commit**

```bash
git add backend/scraper/vahan_scraper.py
git commit -m "feat: rewrite scraper to drive live vahan4dashboard reportview"
```

---

## Task 3: Persistence layer

**Files:**
- Rewrite: `backend/app/services/scraper_service.py`
- Test: `backend/tests/test_scraper_service.py`

The persistence function is tested independently of the network: it takes already-scraped record dicts (fabricated in the test) and asserts what lands in the DB via the existing `db_session` fixture.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_scraper_service.py
from sqlalchemy import select
from app.models.models import Registration
from app.services.scraper_service import persist_rto_batch


async def test_persist_rto_batch_inserts_records(db_session):
    batch = {
        "state_name": "Delhi",
        "rto_code": "DL1",
        "rto_name": "OLD DELHI (MALL ROAD)",
        "records": [
            {"maker": "HONDA MOTORCYCLE AND SCOOTER INDIA (P) LTD", "month": 1, "year": 2026, "count": 91},
            {"maker": "HONDA MOTORCYCLE AND SCOOTER INDIA (P) LTD", "month": 2, "year": 2026, "count": 34},
        ],
    }
    await persist_rto_batch(db_session, batch, state_code="DL")
    await db_session.commit()

    result = await db_session.execute(
        select(Registration).where(Registration.rto_code == "DL1")
    )
    rows = result.scalars().all()
    assert len(rows) == 2
    assert {r.count for r in rows} == {91, 34}
    assert rows[0].state_name == "Delhi"
    assert rows[0].vehicle_class == "All"


async def test_persist_rto_batch_replaces_prior_year_data(db_session):
    batch = {
        "state_name": "Delhi",
        "rto_code": "DL1",
        "rto_name": "OLD DELHI (MALL ROAD)",
        "records": [{"maker": "OLD MAKER", "month": 1, "year": 2026, "count": 5}],
    }
    await persist_rto_batch(db_session, batch, state_code="DL")
    await db_session.commit()

    batch["records"] = [{"maker": "NEW MAKER", "month": 1, "year": 2026, "count": 9}]
    await persist_rto_batch(db_session, batch, state_code="DL")
    await db_session.commit()

    result = await db_session.execute(
        select(Registration).where(Registration.rto_code == "DL1", Registration.year == 2026)
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].maker == "NEW MAKER"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_scraper_service.py -v`
Expected: FAIL — `persist_rto_batch` does not exist yet.

- [ ] **Step 3: Write the implementation**

```python
# backend/app/services/scraper_service.py
import asyncio
import logging
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.config import settings
from app.models.models import Registration, State
from scraper.vahan_scraper import scrape_all_india

logger = logging.getLogger("scraper_service")


async def persist_rto_batch(db: AsyncSession, batch: dict, state_code: str) -> None:
    """Replace any existing rows for this (rto_code, year) with the freshly scraped ones."""
    rto_code = batch["rto_code"]
    years = {r["year"] for r in batch["records"]}
    for year in years:
        await db.execute(
            delete(Registration).where(
                Registration.rto_code == rto_code, Registration.year == year
            )
        )
    for record in batch["records"]:
        db.add(
            Registration(
                state_code=state_code,
                state_name=batch["state_name"],
                rto_code=rto_code,
                rto_name=batch["rto_name"],
                month=record["month"],
                year=record["year"],
                vehicle_class="All",
                maker=record["maker"],
                count=record["count"],
            )
        )


async def _state_code_lookup(db: AsyncSession) -> dict[str, str]:
    result = await db.execute(select(State.state_name, State.state_code))
    return {name: code for name, code in result.all()}


async def run_scraper() -> None:
    """Full-India live scrape: iterate every state/RTO on vahan4dashboard and persist results.
    Designed to run as a long-lived background task (can take over an hour for all of India).
    """
    logger.info("Starting live VAHAN4 scrape at %s", datetime.utcnow())
    year = datetime.now().year

    async with AsyncSessionLocal() as db:
        state_codes = await _state_code_lookup(db)

        rto_count = 0
        async for batch in scrape_all_india(year=year):
            code = state_codes.get(batch["state_name"])
            if code is None:
                logger.warning("No state_code found for '%s', skipping batch", batch["state_name"])
                continue
            await persist_rto_batch(db, batch, state_code=code)
            await db.commit()
            rto_count += 1
            if rto_count % 25 == 0:
                logger.info("Scraped %d RTOs so far...", rto_count)

    settings.LAST_UPDATED = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    logger.info("Live VAHAN4 scrape complete. %d RTOs processed.", rto_count)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_scraper_service.py -v`
Expected: PASS, 2 passed.

- [ ] **Step 5: Run the full test suite to check nothing broke**

Run: `cd backend && python -m pytest -v`
Expected: all tests pass (the existing 20 geo-hierarchy tests plus the new ones from this plan).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/scraper_service.py backend/tests/test_scraper_service.py
git commit -m "feat: persist live scraper output via SQLAlchemy Registration model"
```

---

## Task 4: Wire up 24-hour auto-refresh

**Files:**
- Rewrite: `backend/scraper/scheduler.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/api/v1/endpoints/refresh.py`

- [ ] **Step 1: Rewrite the scheduler to call the real async scraper**

```python
# backend/scraper/scheduler.py
import asyncio
import logging
from datetime import datetime, timedelta

from app.services.scraper_service import run_scraper

logger = logging.getLogger("scheduler")

REFRESH_INTERVAL_HOURS = 24


async def run_scheduler_loop() -> None:
    """Runs run_scraper() once immediately, then every REFRESH_INTERVAL_HOURS forever.
    Intended to be launched as a background asyncio task from the FastAPI lifespan.
    """
    while True:
        try:
            await run_scraper()
        except Exception as exc:
            logger.error("Scheduled scrape failed: %s", exc)

        next_run = datetime.utcnow() + timedelta(hours=REFRESH_INTERVAL_HOURS)
        logger.info("Next scheduled scrape at %s UTC", next_run.isoformat())
        await asyncio.sleep(REFRESH_INTERVAL_HOURS * 3600)
```

- [ ] **Step 2: Launch it from the FastAPI lifespan**

`backend/app/main.py` currently reads:

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.core.config import settings
from app.core.database import init_db, AsyncSessionLocal
from app.api.v1.router import api_router
from app.scripts.seed_geo_hierarchy import seed_geo_hierarchy


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    async with AsyncSessionLocal() as session:
        await seed_geo_hierarchy(session)
    yield
```

Replace the imports and the `lifespan` function with:

```python
import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.core.config import settings
from app.core.database import init_db, AsyncSessionLocal
from app.api.v1.router import api_router
from app.scripts.seed_geo_hierarchy import seed_geo_hierarchy
from scraper.scheduler import run_scheduler_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    async with AsyncSessionLocal() as session:
        await seed_geo_hierarchy(session)
    scheduler_task = asyncio.create_task(run_scheduler_loop())
    yield
    scheduler_task.cancel()
```

Everything below this (the `app = FastAPI(...)` block, CORS middleware, router include, `/health` endpoint) is unchanged.

- [ ] **Step 3: Fix the refresh endpoint's premature "last updated" timestamp**

`backend/app/api/v1/endpoints/refresh.py` currently reads:

```python
from fastapi import APIRouter, BackgroundTasks
from app.schemas.schemas import RefreshResponse
from app.services.scraper_service import run_scraper
from app.core.config import settings
from datetime import datetime

router = APIRouter()


@router.post("/", response_model=RefreshResponse)
async def trigger_refresh(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_scraper)
    settings.LAST_UPDATED = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    return RefreshResponse(
        status="started",
        message="Scraper job started in background. Data will be available shortly.",
    )
```

`background_tasks.add_task(run_scraper)` already works unchanged with the new async `run_scraper` (FastAPI supports async callables natively). But the `settings.LAST_UPDATED = ...` line here fires immediately when the job *starts*, not when it *finishes* — harmless for the old near-instant stub, but misleading now that a full scrape takes over an hour (the UI would claim "just updated" while still scraping). Remove that line and let `run_scraper()` in `scraper_service.py` (Task 3, already sets `settings.LAST_UPDATED` at the end) be the only place that timestamp is set:

```python
from fastapi import APIRouter, BackgroundTasks
from app.schemas.schemas import RefreshResponse
from app.services.scraper_service import run_scraper

router = APIRouter()


@router.post("/", response_model=RefreshResponse)
async def trigger_refresh(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_scraper)
    return RefreshResponse(
        status="started",
        message="Scraper job started in background. This can take over an hour for a full India refresh.",
    )
```

The `/status` endpoint below it (reads `settings.LAST_UPDATED`) is unchanged.

- [ ] **Step 4: Manual verification**

Start the backend (`cd backend && uvicorn app.main:app --reload`) and confirm in the logs:
- `"Starting live VAHAN4 scrape at ..."` appears within a few seconds of startup
- No unhandled exceptions during the first few RTOs
- Stop the server with Ctrl+C before it completes a full run (a full India run takes over an hour) — this is expected for a smoke test.

- [ ] **Step 5: Commit**

```bash
git add backend/scraper/scheduler.py backend/app/main.py
git commit -m "feat: auto-run live scraper on startup and every 24 hours"
```

---

## Task 5: Full manual verification against the live site

**Files:** none (verification only)

- [ ] **Step 1: Run a bounded manual scrape**

Temporarily edit `backend/scraper/vahan_scraper.py`'s `scrape_all_india` call site (or write a one-off script importing it) to break after 5 RTOs instead of running all of India, and run it against the live site end-to-end through `run_scraper()` — confirm real rows land in `backend/data/vahan.db`:

```bash
cd backend
python -c "
import asyncio
from app.services.scraper_service import run_scraper
asyncio.run(run_scraper())
"
```
(Let this run for a few minutes then Ctrl+C — check partial progress via the query below; do not wait for full completion here.)

- [ ] **Step 2: Confirm real data landed**

```bash
python -c "
import sqlite3
conn = sqlite3.connect('./data/vahan.db')
c = conn.cursor()
print(c.execute(\"SELECT rto_code, maker, month, year, count FROM registrations WHERE rto_code != '' LIMIT 10\").fetchall())
"
```
Expected: rows with non-empty `rto_code`, real maker names, and counts consistent with what's visible on the live site.

- [ ] **Step 3: Confirm the frontend reflects it**

With the backend running, open the Overview page and confirm the State/Maker/Model filters still populate and now include the newly-scraped rows (mixed with any remaining synthetic seed rows until a full scrape replaces all of them).

---

## Architecture correction found during Task 4 verification

The plan as originally written had `run_scraper()` execute in-process, awaited directly by
`asyncio.create_task(run_scheduler_loop())` inside the FastAPI lifespan. Manual verification
showed this crashes Playwright's Chromium reliably within seconds ("Page crashed") when
sharing uvicorn's event loop — confirmed by the exact same code running flawlessly as a
standalone `python -m scraper.vahan_scraper` process with no crashes across many RTOs.

Fix: `scraper/run_full_scrape.py` (new) contains the actual scrape+persist loop and is
invoked as a genuine child OS process via `asyncio.create_subprocess_exec` from
`scraper_service.run_scraper()`, which awaits it and streams its stdout into the parent's
logger. `persist_rto_batch`/`_state_code_lookup` stayed in `scraper_service.py` (imported by
`run_full_scrape.py`) so Task 3's tests are unaffected — only `run_scraper()`'s internals
changed. `vahan_scraper.py`'s `scrape_all_india` also gained crash-recovery (relaunch
browser, re-select state, continue) since occasional crashes still happen even in-process —
confirmed this recovery path triggers and resumes correctly rather than hanging.

Also fixed: `settings.LOG_LEVEL` was defined but never wired to `logging.basicConfig`, so
none of the scraper's `.info()` progress logs were visible — added the missing
`logging.basicConfig(level=settings.LOG_LEVEL, ...)` call in `main.py`.

## Known follow-ups (not in this plan's scope)

- The frontend still has zero UI for the Zone → State → District → RTO drill-down built in the prior session — that is a separate, larger frontend task.
- Per-vehicle-class breakdown (Two Wheeler vs Four Wheeler etc.) at Maker×Month granularity would require ~10x the scrape volume (one pass per Vehicle Category Group) — flagged above, not implemented here.
- A full India run (~1,076+ RTOs at ~4-6s each plus a 1.5s politeness delay) takes roughly 1.5-2 hours; the scheduler runs this once at startup and then every 24 hours, which is acceptable for a nightly batch but should be monitored for gov.in-side rate limiting on first real run.
- Occasional Chromium "Page crashed" events occur even as a standalone subprocess (observed once in ~5 minutes of real runtime in this sandboxed dev environment) — likely memory pressure specific to this VM. The crash-recovery logic mitigates it, but this should be watched on first production deployment.
