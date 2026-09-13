import pathlib

import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        pass


class _FakeClient:
    """Minimal stand-in for httpx.AsyncClient -- discover_releases only ever
    calls `await client.get(url, params={"page": n})` and reads `.text`."""
    def __init__(self, page_html: dict[int, str]):
        self._page_html = page_html

    async def get(self, url, params=None):
        return _FakeResponse(self._page_html.get(params["page"], ""))


async def test_discover_releases_raises_when_page_one_is_empty():
    # The archive can never genuinely be empty on page 1 -- this must mean
    # fada.in's markup changed, not "nothing published yet". Regression test
    # for the silent-failure bug: this used to return [] with only an INFO
    # log, indistinguishable from a real empty result.
    from scraper.fada_scraper import discover_releases

    client = _FakeClient({1: "<html><body>no entries here</body></html>"})
    with pytest.raises(RuntimeError, match="page 1"):
        await discover_releases(client)


async def test_persist_oem_sales_duplicate_is_recoverable_after_rollback(db_session):
    """Regression test for the run_fada_scheduler_loop/backfill_fada.py fix:
    once oem_monthly_sales has a natural-key unique constraint, a PDF that
    parses a duplicate row for the same period/maker collides at commit
    time. Without a rollback in the caller's except block, that leaves the
    shared session's transaction aborted -- every subsequent release in the
    same loop would then also fail (PendingRollbackError), never getting a
    FadaScrapeAttempt row, so it's re-fetched and re-parsed forever."""
    from sqlalchemy.exc import IntegrityError

    from scraper.fada_scraper import persist_oem_sales

    dupe_rows = [
        {"category": "PV", "maker": "TOYOTA", "year": 2026, "month": 6, "count": 100, "share_percent": 10.0},
        {"category": "PV", "maker": "TOYOTA", "year": 2026, "month": 6, "count": 100, "share_percent": 10.0},
    ]
    with pytest.raises(IntegrityError):
        await persist_oem_sales(db_session, dupe_rows, source="FADA", source_document="release-1")
        await db_session.commit()

    await db_session.rollback()

    other_row = {"category": "PV", "maker": "HONDA", "year": 2026, "month": 6, "count": 50, "share_percent": 5.0}
    await persist_oem_sales(db_session, [other_row], source="FADA", source_document="release-2")
    await db_session.commit()  # must not raise -- the rollback above must have fully cleared the aborted transaction


def _fake_archive_page(n: int) -> str:
    """n press-release cards, each a real "Vehicle Retail Data" entry with
    its own PDF link, matching _ENTRY_RE's actual shape."""
    from scraper.fada_scraper import _ENTRY_MARKER
    return "".join(
        f'{_ENTRY_MARKER}FADA Releases Month{i} Vehicle Retail Data</h3>'
        f'<a href="release{i}.pdf">link</a>'
        for i in range(n)
    )


async def test_discover_releases_stops_normally_when_a_later_page_is_empty():
    # A later page being empty is the real "end of archive" signal and must
    # NOT raise -- only page 1 being empty/near-empty is anomalous.
    from scraper.fada_scraper import MIN_EXPECTED_ENTRIES_PAGE_1, discover_releases

    client = _FakeClient({
        1: _fake_archive_page(MIN_EXPECTED_ENTRIES_PAGE_1),
        2: "<html><body>no entries here</body></html>",
    })
    releases = await discover_releases(client)
    assert len(releases) == MIN_EXPECTED_ENTRIES_PAGE_1


async def test_discover_releases_raises_when_page_one_is_near_empty_not_just_zero():
    # A narrower markup drift (most, not all, cards stop matching) must be
    # caught too -- a strict "!= 0" check would silently accept this as
    # "just a quiet month" instead of "fada.in's markup is drifting".
    from scraper.fada_scraper import MIN_EXPECTED_ENTRIES_PAGE_1, discover_releases

    client = _FakeClient({1: _fake_archive_page(MIN_EXPECTED_ENTRIES_PAGE_1 - 1)})
    with pytest.raises(RuntimeError, match="page 1"):
        await discover_releases(client)


def test_parse_release_list_page_filters_to_vehicle_retail_data_only():
    from scraper.fada_scraper import _parse_release_list_page

    html = (FIXTURES / "fada_press_release_list_page3.html").read_text(encoding="utf-8")
    releases = _parse_release_list_page(html)

    titles = [r["title"] for r in releases]
    # 12 real "Vehicle Retail Data" releases on this page, out of 15 total
    # press-release entries (3 are unrelated events/conferences and must be
    # excluded).
    assert len(releases) == 12
    assert "FADA Releases April 2023 Vehicle Retail Data" in titles
    # Irregular title formats must still be recognized, not silently dropped:
    assert "FADA releases March 2023 and FY 2023 Vehicle Retail Data" in titles
    assert "FADA Releases October'22 & 42 Days Festive Period Vehicle Retail Data" in titles
    assert "FADA Releases Navratri'22 Vehicle Retail Data" in titles
    # Every release must have a resolved, absolute PDF URL.
    for r in releases:
        assert r["pdf_url"].startswith("https://www.fada.in/")
        assert r["pdf_url"].endswith(".pdf")


def test_parse_release_list_page_returns_empty_for_a_page_with_no_entries():
    from scraper.fada_scraper import _parse_release_list_page

    assert _parse_release_list_page("<html><body>no entries here</body></html>") == []


def test_parse_release_pdf_extracts_clean_oem_rows():
    from scraper.fada_scraper import parse_release_pdf

    pdf_bytes = (FIXTURES / "fada_june2026.pdf").read_bytes()
    rows = parse_release_pdf(pdf_bytes)

    two_wheeler_current = [
        r for r in rows
        if r["category"] == "Two-Wheeler" and r["maker"] == "HERO MOTOCORP LTD" and r["year"] == 2026
    ]
    assert len(two_wheeler_current) == 1
    row = two_wheeler_current[0]
    assert row["month"] == 6
    assert row["count"] == 472144
    assert row["share_percent"] == 25.82

    # Same maker's prior-year (Jun'25) figure must also be captured as its
    # own row, from the same table's other two columns.
    two_wheeler_prior = [
        r for r in rows
        if r["category"] == "Two-Wheeler" and r["maker"] == "HERO MOTOCORP LTD" and r["year"] == 2025
    ]
    assert len(two_wheeler_prior) == 1
    assert two_wheeler_prior[0]["month"] == 6
    assert two_wheeler_prior[0]["count"] == 401803

    # A maker name that wraps across a PDF line break must be normalized to
    # a single space, not left with an embedded newline.
    honda = [r for r in rows if r["maker"].startswith("HONDA MOTORCYCLE")]
    assert any(r["maker"] == "HONDA MOTORCYCLE AND SCOOTER INDIA (P) LTD" for r in honda)

    # "Total" and "Others"/"Others Including EV" rows are not real makers.
    makers = {r["maker"] for r in rows}
    assert "Total" not in makers
    assert not any(m.lower().startswith("others") for m in makers)

    # All 6 categories present in this PDF must be found -- not a fixed
    # enum, but this specific fixture is known to have exactly these.
    categories = {r["category"] for r in rows}
    assert categories == {
        "Two-Wheeler", "Three-Wheeler", "Commercial Vehicle",
        "Wheeled - Construction Equipment", "PV", "Tractor",
    }


def test_parse_release_pdf_skips_non_oem_pages():
    from scraper.fada_scraper import parse_release_pdf

    # The real fixture mixes several non-OEM-table pages in among the 6
    # genuine OEM tables: a YTD summary table (header "CATEGORY"), a
    # month-over-month CV table, an urban/rural chart table, and a
    # president's-quote table. Their first header cell doesn't end with
    # "OEM", so parse_release_pdf must skip them -- this must not raise, and
    # none of their header/row text may leak through as a bogus category.
    # (The cover page has zero tables at all, so it can't exercise this skip
    # logic; these other non-OEM pages, which do have tables, are what
    # actually prove the "...OEM" check works rather than trivially passing.)
    pdf_bytes = (FIXTURES / "fada_june2026.pdf").read_bytes()
    rows = parse_release_pdf(pdf_bytes)

    assert len(rows) > 0  # the 6 real OEM tables still produced rows
    categories = {r["category"] for r in rows}
    assert "CATEGORY" not in categories
    assert not any("\n" in c for c in categories)


async def test_persist_oem_sales_is_idempotent(db_session):
    from scraper.fada_scraper import persist_oem_sales
    from app.models.models import OEMMonthlySales
    from sqlalchemy import select

    rows = [
        {"category": "Two-Wheeler", "maker": "HERO MOTOCORP LTD", "year": 2026, "month": 6, "count": 472144, "share_percent": 25.82},
        {"category": "Two-Wheeler", "maker": "TVS MOTOR COMPANY LTD", "year": 2026, "month": 6, "count": 359243, "share_percent": 19.65},
    ]

    await persist_oem_sales(db_session, rows, source="FADA", source_document="FADA Releases June 2026 Vehicle Retail Data")
    await db_session.commit()
    await persist_oem_sales(db_session, rows, source="FADA", source_document="FADA Releases June 2026 Vehicle Retail Data")
    await db_session.commit()

    result = await db_session.execute(select(OEMMonthlySales))
    all_rows = result.scalars().all()
    assert len(all_rows) == 2  # not 4 -- re-running must not duplicate

    hero = next(r for r in all_rows if r.maker == "HERO MOTOCORP LTD")
    assert hero.count == 472144
    assert hero.source == "FADA"
    assert hero.source_document == "FADA Releases June 2026 Vehicle Retail Data"


async def test_persist_oem_sales_does_not_delete_other_periods(db_session):
    from scraper.fada_scraper import persist_oem_sales
    from app.models.models import OEMMonthlySales
    from sqlalchemy import select

    may_rows = [{"category": "Two-Wheeler", "maker": "HERO MOTOCORP LTD", "year": 2026, "month": 5, "count": 100, "share_percent": 20.0}]
    june_rows = [{"category": "Two-Wheeler", "maker": "HERO MOTOCORP LTD", "year": 2026, "month": 6, "count": 200, "share_percent": 25.0}]

    await persist_oem_sales(db_session, may_rows, source="FADA", source_document="May release")
    await db_session.commit()
    await persist_oem_sales(db_session, june_rows, source="FADA", source_document="June release")
    await db_session.commit()

    result = await db_session.execute(select(OEMMonthlySales))
    all_rows = result.scalars().all()
    assert len(all_rows) == 2
    assert {r.month for r in all_rows} == {5, 6}


async def test_persist_oem_sales_handles_multiple_periods_in_one_call(db_session):
    """A real ingest passes rows spanning many (year, month, category) periods
    at once -- one PDF has ~6 categories, each with a current + prior period
    column, plus FY-total rows where month=None. Each period's delete scope
    must be independent within a single call, not just across separate calls."""
    from scraper.fada_scraper import persist_oem_sales
    from app.models.models import OEMMonthlySales
    from sqlalchemy import select

    rows = [
        {"category": "Two-Wheeler", "maker": "HERO MOTOCORP LTD", "year": 2026, "month": 6, "count": 100, "share_percent": 20.0},
        {"category": "Two-Wheeler", "maker": "HERO MOTOCORP LTD", "year": 2025, "month": 6, "count": 90, "share_percent": 19.0},
        {"category": "PV", "maker": "MARUTI SUZUKI", "year": 2026, "month": 6, "count": 50, "share_percent": 40.0},
        {"category": "Tractor", "maker": "MAHINDRA", "year": 2026, "month": None, "count": 1000, "share_percent": 30.0},
    ]

    await persist_oem_sales(db_session, rows, source="FADA", source_document="June release")
    await db_session.commit()
    # Re-run with the same multi-period rows: each period's own delete scope
    # must fire, not just the first/last one seen in the loop.
    await persist_oem_sales(db_session, rows, source="FADA", source_document="June release")
    await db_session.commit()

    result = await db_session.execute(select(OEMMonthlySales))
    all_rows = result.scalars().all()
    assert len(all_rows) == 4  # not 8 -- every period deduped, not just one

    fy_total = next(r for r in all_rows if r.category == "Tractor")
    assert fy_total.month is None
    assert fy_total.count == 1000
