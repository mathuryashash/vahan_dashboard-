import asyncio
import logging
from datetime import datetime
from playwright.async_api import async_playwright, Page

from scraper.parsing import parse_state_option, parse_rto_option, parse_count, MONTH_ABBR

logger = logging.getLogger("vahan_scraper")

REPORT_URL = "https://vahan.parivahan.gov.in/vahan4dashboard/vahan/view/reportview.xhtml"
REQUEST_DELAY_SECONDS = 1.5


async def _open_dropdown_panel(page: Page, trigger_id: str, timeout_ms: int = 5000):
    """Open a PrimeFaces ui-selectonemenu panel via its JS widget API (PrimeFaces.widgets['widget_<id>'].show()).

    A plain Playwright pointer click on the trigger div is unreliable on this page: some
    widgets (confirmed for #selectedYearType) never open the panel via a simulated click,
    even with force=True and scroll-into-view, apparently due to how PrimeFaces binds its
    show/hide handlers. The JS widget API call is what PrimeFaces' own client code invokes
    internally and works reliably for every widget tested.
    """
    trigger = await page.query_selector(f"#{trigger_id}")
    if trigger is None:
        raise RuntimeError(f"Dropdown trigger #{trigger_id} not found on page")
    await trigger.scroll_into_view_if_needed()
    result = await page.evaluate(
        "(id) => { const w = PrimeFaces.widgets['widget_' + id]; if (!w) return 'no_widget'; w.show(); return 'shown'; }",
        trigger_id,
    )
    if result != "shown":
        raise RuntimeError(f"PrimeFaces widget 'widget_{trigger_id}' not found")
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
    """Read headers + body rows from the Maker x Month result table (scrollable ui-datatable).

    PrimeFaces scrollable tables render as a pair: a header-clone table (same <th> text,
    zero <tbody> rows) plus the real body table (same headers, actual rows). Both match on
    headers alone, so we must keep scanning until we find one that actually has rows.
    """
    tables = await page.query_selector_all("table[role='grid']")
    best_headers: list[str] = []
    for table in tables:
        headers = [
            (await th.inner_text()).strip()
            for th in await table.query_selector_all("th")
        ]
        if "Maker" in headers and any(m in headers for m in MONTH_ABBR):
            best_headers = headers
            rows = []
            for tr in await table.query_selector_all("tbody tr"):
                cells = [(await td.inner_text()).strip() for td in await tr.query_selector_all("td")]
                if cells:
                    rows.append(cells)
            if rows:
                return headers, rows
    return best_headers, []


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
        # The <th> row includes extra structural cells (leading blanks, a "Month Wise"
        # group header, a trailing "TOTAL") that don't line up 1:1 with <td> cells in the
        # body rows. Body rows are reliably [S No, Maker, <month value>..., TOTAL], so we
        # derive column meaning from the *order* month labels appear in the header, not
        # their header index, and apply that order starting at a fixed body-cell offset.
        month_labels_in_order = [h for h in headers if h in MONTH_ABBR]

        for cells in rows:
            if len(cells) < 2 + len(month_labels_in_order):
                continue
            maker = cells[1]
            for offset, month_label in enumerate(month_labels_in_order):
                col_idx = 2 + offset
                month = MONTH_ABBR[month_label]
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
