import pathlib

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


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
