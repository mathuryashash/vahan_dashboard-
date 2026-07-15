# FADA OEM Monthly Sales Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest FADA's public monthly "Vehicle Retail Data" press releases (maker-wise vehicle registration counts, every category, since Aug 2021) into the dashboard, giving real answers to "which company sells how many vehicles" that VAHAN4's own pivot structurally cannot provide.

**Architecture:** A new scraper module discovers FADA's press-release archive, downloads each "Vehicle Retail Data" PDF, extracts the per-category OEM tables with `pdfplumber` (verified to parse cleanly with zero manual cleanup), and persists into one new table. A one-time backfill script covers the full archive; a daily background loop (alongside the existing VAHAN scheduler) picks up new monthly releases going forward. New API endpoints and a new frontend page surface it.

**Tech Stack:** Python (httpx, pdfplumber, SQLAlchemy async, FastAPI), React/TypeScript (Recharts, TanStack Query) — all already in use in this codebase, no new frontend dependencies.

---

## Reference facts (confirmed via direct reconnaissance against the live site on 2026-07-15 — do not re-derive, use as ground truth)

- Archive: `https://www.fada.in/press-release-list.php?page=N`, `N` starting at 1. Confirmed empty (0 entries) from page 6 onward — page 5 is the real last page. Real "Vehicle Retail Data" releases found from **August 2021 through June 2026**.
- Each archive page entry looks like:
  ```html
  <a target="_blank" class="text-dark"><h3 class="font-weight-semibold mb-3"><img src="images/logo/Untitled-1.png" style="width: 30px;"> FADA Releases June 2026 Vehicle Retail Data</h3></a>
  ...
  <a href="images/press-release/16a4b2243edbfbFADA Releases June 2026 Vehicle Retail Data.pdf" target="_blank" class="btn btn-primary btn-sm mt-4">Download</a>
  ```
  Title and PDF link are a few lines apart within the same card, not adjacent — a regex spanning both with `re.DOTALL` and a non-greedy middle is required (confirmed working, see Task 3).
- Titles are inconsistent: `"FADA Releases June 2026 Vehicle Retail Data"`, `"FADA releases March 2023 and FY 2023 Vehicle Retail Data"`, `"FADA Releases October'22 & 42 Days Festive Period Vehicle Retail Data"`, `"FADA Releases Navratri'22 Vehicle Retail Data"`. Filter on the case-insensitive substring `"vehicle retail data"` — confirmed to correctly separate all 12 real releases from 3 unrelated press releases on a test page with the most irregular titles found in the archive.
- Every PDF has one `pdfplumber` table per category page, and the **table's own header row carries both the category name and the two periods being compared** — confirmed identical shape across all 6 categories in the June 2026 PDF:
  ```python
  ['Two-Wheeler OEM', "Jun'26", "Market Share\n(%) Jun'26", "Jun'25", "Market Share\n(%) Jun'25"]
  ['HERO MOTOCORP LTD', '4,72,144', '25.82%', '4,01,803', '26.64%']
  ...
  ['Others Including EV', '14,467', '0.79%', '8,206', '0.54%']
  ['Total', '18,28,458', '100%', '15,08,378', '100%']
  ```
  Category names seen: `Two-Wheeler`, `Three-Wheeler`, `Commercial Vehicle`, `Wheeled - Construction Equipment`, `PV`, `Tractor` — not a fixed set, more may appear in older/newer releases, do not hardcode an enum.
  The last-but-one row's first cell is one of `"Others"`, `"Others Including EV"`, or `"Others including EV"` (case varies) — always excluded, matched case-insensitively by prefix `"others"`. The last row's first cell is always exactly `"Total"` (case varies too in principle — match case-insensitively).
  Maker names sometimes contain an embedded newline from PDF line-wrapping (e.g.
  `"HONDA MOTORCYCLE AND SCOOTER INDIA (P)\nLTD"`) — replace `\n` with a space before storing.
- Not every page in a PDF is an OEM table (some are charts/disclaimer text) — a page whose first extracted table's header row doesn't end in `"OEM"` (case-insensitive) is not a data page and must be skipped, not treated as an error.
- The fixture PDF `backend/tests/fixtures/fada_june2026.pdf` (already committed, downloaded live from `https://www.fada.in/images/press-release/16a4b2243edbfbFADA Releases June 2026 Vehicle Retail Data.pdf`) and `backend/tests/fixtures/fada_press_release_list_page3.html` (archive page 3, already committed, has the richest set of irregular titles found) are the real regression fixtures for this plan — not synthetic mocks, since the whole risk here is FADA's real template drifting.

---

## File Structure

- Create: `backend/scraper/fada_scraper.py` — discovery, PDF parsing, persistence (3 independently testable functions + 2 small private helpers)
- Create: `backend/scraper/backfill_fada.py` — one-time full-archive backfill script
- Create: `backend/app/api/v1/endpoints/oem_sales.py` — 3 read endpoints
- Create: `frontend/src/pages/IndustrySales.tsx` — new dashboard page
- Modify: `backend/app/models/models.py` — add `OEMMonthlySales` model
- Modify: `backend/requirements.txt` — add `pdfplumber`
- Modify: `backend/scraper/scheduler.py` — add `run_fada_scheduler_loop()`
- Modify: `backend/app/main.py` — start/cancel the new loop alongside the existing one
- Modify: `backend/app/api/v1/router.py` — register the new router
- Modify: `frontend/src/types/index.ts` — add `OEMSalesRow`, `OEMTrendPoint` types
- Modify: `frontend/src/api/vahan.ts` — add `getOemCategories`, `getOemMonthly`, `getOemTrend`
- Modify: `frontend/src/App.tsx` — add the `/industry-sales` route
- Modify: `frontend/src/components/Sidebar.tsx` — add the nav entry (reusing the existing, currently-unused-in-nav `Award` icon — no new icon file needed)
- Test: `backend/tests/test_fada_scraper.py`
- Test: `backend/tests/test_oem_sales_endpoints.py`
- Fixtures (already committed as part of this plan's prep): `backend/tests/fixtures/fada_june2026.pdf`, `backend/tests/fixtures/fada_press_release_list_page3.html`

---

### Task 1: Data model

**Files:**
- Modify: `backend/app/models/models.py`

- [ ] **Step 1: Add the `OEMMonthlySales` model**

Append to the end of `backend/app/models/models.py`:

```python
class OEMMonthlySales(Base):
    __tablename__ = "oem_monthly_sales"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # "FADA" for now. SIAM's industry-wide totals (a later, separate sub-project)
    # fit this same shape with maker=NULL -- no schema change needed to add a
    # second source value here.
    source = Column(String(20), nullable=False, index=True)
    # Parsed from the PDF table's own column header (e.g. "Jun'26"), not from
    # the press release title -- titles are inconsistent (see fada_scraper.py
    # module docstring) but the table header is the authoritative period.
    year = Column(Integer, nullable=False, index=True)
    # Null for FY-total periods that don't resolve to one calendar month.
    month = Column(Integer, nullable=True)
    # Literal text as FADA labels it ("Two-Wheeler", "PV", etc.) -- not an
    # enum, since FADA has added/renamed categories across the archive.
    category = Column(String(100), nullable=False, index=True)
    maker = Column(String(200), nullable=False, index=True)
    count = Column(Integer, nullable=False)
    share_percent = Column(Float, nullable=True)
    # The press release title, for tracing a row back to its source PDF.
    source_document = Column(String(300), nullable=False)
    scraped_at = Column(DateTime, default=func.now())

    __table_args__ = (
        Index("idx_oem_sales_period", "source", "year", "month", "category"),
    )
```

- [ ] **Step 2: Verify the table is created**

Run: `cd backend && python -c "import asyncio; from app.core.database import init_db; asyncio.run(init_db())"`
Expected: no errors. Then verify the table exists:

Run: `cd backend && python -c "
import sqlite3
conn = sqlite3.connect('data/vahan.db')
c = conn.cursor()
c.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name='oem_monthly_sales'\")
print(c.fetchone())
"`
Expected: `('oem_monthly_sales',)`

- [ ] **Step 3: Commit**

```bash
git add app/models/models.py
git commit -m "feat: add OEMMonthlySales model for FADA ingestion"
```

---

### Task 2: Add pdfplumber dependency

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Add the dependency**

Add this line to `backend/requirements.txt` (after `httpx>=0.27.0`):

```
pdfplumber>=0.11.0
```

- [ ] **Step 2: Verify it's importable**

Run: `cd backend && python -c "import pdfplumber; print(pdfplumber.__version__)"`
Expected: prints a version string (already installed in this environment as `0.11.9`; this step is confirming the requirements.txt entry matches what's actually usable, not a fresh install).

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "chore: add pdfplumber for FADA PDF table extraction"
```

---

### Task 3: `discover_releases` — archive discovery

**Files:**
- Create: `backend/scraper/fada_scraper.py`
- Test: `backend/tests/test_fada_scraper.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_fada_scraper.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_fada_scraper.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scraper.fada_scraper'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/scraper/fada_scraper.py`:

```python
"""FADA monthly "Vehicle Retail Data" ingestion.

FADA (Federation of Automobile Dealers Associations) publishes free, public,
monthly maker-wise vehicle registration data as PDF press releases -- unlike
VAHAN4 (see vahan_scraper.py's module docstring) whose Y-axis pivot has no
Model or per-maker-cross-category dimension at all, and unlike SIAM whose
public releases are industry-wide totals only (no maker breakdown; confirmed
against siam.in's press-release archive).

Archive: fada.in/press-release-list.php?page=N. Titles are inconsistent
across the ~5 year archive ("FADA Releases June 2026 Vehicle Retail Data",
"FADA releases March 2023 and FY 2023 Vehicle Retail Data", "FADA Releases
October'22 & 42 Days Festive Period Vehicle Retail Data") -- filtered by the
substring "vehicle retail data", not parsed for dates. The actual period a
row belongs to comes from the PDF table's own column headers (see
parse_release_pdf), not the release title, since some releases combine an
FY-total and a single month in one document.
"""
import httpx
import logging
import re
from urllib.parse import urljoin

logger = logging.getLogger("fada_scraper")

ARCHIVE_URL = "https://www.fada.in/press-release-list.php"
BASE_URL = "https://www.fada.in/"

# Title and PDF-download link sit a few lines apart within the same card,
# not adjacent -- DOTALL + a non-greedy middle bridges them. Confirmed
# against the real archive: matches all 15 press-release entries per page,
# title text captured verbatim for the "vehicle retail data" substring filter
# below.
_ENTRY_RE = re.compile(
    r'<h3 class="font-weight-semibold mb-3">(?:<img[^>]*>\s*)?([^<]+)</h3>.*?href="([^"]+\.pdf)"',
    re.IGNORECASE | re.DOTALL,
)


def _parse_release_list_page(html: str) -> list[dict]:
    """[{title, pdf_url}, ...] for every "Vehicle Retail Data" entry on one
    archive listing page. Pure function, no network -- see
    test_parse_release_list_page_* for the exact archive shape this handles."""
    releases = []
    for title, href in _ENTRY_RE.findall(html):
        title = title.strip()
        if "vehicle retail data" not in title.lower():
            continue
        releases.append({"title": title, "pdf_url": urljoin(BASE_URL, href)})
    return releases


async def discover_releases(client: httpx.AsyncClient, max_pages: int = 10) -> list[dict]:
    """All "Vehicle Retail Data" releases found across the archive, oldest
    pagination behavior first. Confirmed live: the real archive is 5 pages,
    page 6+ returns zero entries -- max_pages=10 is headroom, not a guess;
    stops as soon as a page returns zero *total* card entries (not just zero
    VRD-filtered ones), matching the real "end of archive" signal rather than
    a coincidental page with no VRD releases on it.
    """
    all_releases: list[dict] = []
    for page in range(1, max_pages + 1):
        resp = await client.get(ARCHIVE_URL, params={"page": page})
        resp.raise_for_status()
        has_any_entries = '<h3 class="font-weight-semibold mb-3">' in resp.text
        if not has_any_entries:
            logger.info("FADA archive: page %d empty, stopping (found %d releases)", page, len(all_releases))
            break
        all_releases.extend(_parse_release_list_page(resp.text))
    else:
        logger.warning("FADA archive: hit max_pages=%d without finding an empty page -- archive may have grown, raise max_pages", max_pages)
    return all_releases
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_fada_scraper.py -v`
Expected: both tests PASS

- [ ] **Step 5: Commit**

```bash
git add scraper/fada_scraper.py tests/test_fada_scraper.py
git commit -m "feat: add FADA press-release archive discovery"
```

---

### Task 4: `parse_release_pdf` — PDF table extraction

**Files:**
- Modify: `backend/scraper/fada_scraper.py`
- Modify: `backend/tests/test_fada_scraper.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_fada_scraper.py`:

```python
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


def test_parse_release_pdf_returns_empty_list_for_non_oem_pdf():
    from scraper.fada_scraper import parse_release_pdf

    # A minimal valid PDF with no OEM tables at all must not raise -- it
    # should just produce no rows (matches the real PDFs' own disclaimer/
    # chart pages, which are non-OEM pages within an otherwise-valid release).
    import pdfplumber
    import io

    # Build a tiny in-memory PDF with plain text via pdfplumber's own test
    # helper is not available; instead assert directly against a page of the
    # real fixture that is known to have no OEM table (page 1, the cover
    # page).
    pdf_bytes = (FIXTURES / "fada_june2026.pdf").read_bytes()
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        cover_page_text = pdf.pages[0].extract_text()
    assert "OEM" not in (cover_page_text or "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_fada_scraper.py::test_parse_release_pdf_extracts_clean_oem_rows -v`
Expected: FAIL with `ImportError: cannot import name 'parse_release_pdf'`

- [ ] **Step 3: Write minimal implementation**

Append to `backend/scraper/fada_scraper.py` (add these imports at the top of the
file alongside the existing ones, then the two functions at the end of the file):

```python
import io
import pdfplumber

from scraper.parsing import MONTH_ABBR, parse_count
```

```python
_PERIOD_RE = re.compile(r"^([A-Za-z]{3})'(\d{2})$")


def _parse_period(text: str) -> tuple[int, int] | None:
    """"Jun'26" -> (2026, 6). Returns None for anything that doesn't match
    that exact shape (e.g. a future release with a non-monthly column label)
    -- callers skip just that column, not the whole page, when this returns
    None."""
    match = _PERIOD_RE.match(text.strip())
    if not match:
        return None
    month_abbr, year_suffix = match.groups()
    month = MONTH_ABBR.get(month_abbr.upper())
    if month is None:
        return None
    return (2000 + int(year_suffix), month)


def _parse_share_percent(text: str) -> float | None:
    cleaned = text.strip().rstrip("%").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_release_pdf(pdf_bytes: bytes) -> list[dict]:
    """[{category, maker, year, month, count, share_percent}, ...] for every
    real OEM row across every category table in one FADA PDF. Not every page
    is an OEM table (some are charts/disclaimer text) -- those are silently
    skipped, not treated as an error. See module docstring + this file's
    tests for the exact table shape this depends on."""
    rows: list[dict] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            if not tables or not tables[0] or not tables[0][0]:
                continue
            table = tables[0]
            header = table[0]
            first_cell = (header[0] or "").strip()
            if not first_cell.upper().endswith("OEM"):
                continue
            category = first_cell[: -len("OEM")].strip()
            current_period = _parse_period(header[1]) if len(header) > 1 else None
            prior_period = _parse_period(header[3]) if len(header) > 3 else None
            if current_period is None and prior_period is None:
                logger.warning("FADA PDF page for category %r has no parseable period columns, skipping", category)
                continue

            for data_row in table[1:]:
                name = (data_row[0] or "").replace("\n", " ").strip()
                if not name or name.lower() == "total" or name.lower().startswith("others"):
                    continue

                if current_period is not None:
                    rows.append({
                        "category": category,
                        "maker": name,
                        "year": current_period[0],
                        "month": current_period[1],
                        "count": parse_count(data_row[1]),
                        "share_percent": _parse_share_percent(data_row[2]),
                    })
                if prior_period is not None and len(data_row) > 4:
                    rows.append({
                        "category": category,
                        "maker": name,
                        "year": prior_period[0],
                        "month": prior_period[1],
                        "count": parse_count(data_row[3]),
                        "share_percent": _parse_share_percent(data_row[4]),
                    })
    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_fada_scraper.py -v`
Expected: all 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add scraper/fada_scraper.py tests/test_fada_scraper.py
git commit -m "feat: add FADA PDF OEM-table parsing"
```

---

### Task 5: `persist_oem_sales` — idempotent storage

**Files:**
- Modify: `backend/scraper/fada_scraper.py`
- Modify: `backend/tests/test_fada_scraper.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_fada_scraper.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_fada_scraper.py::test_persist_oem_sales_is_idempotent -v`
Expected: FAIL with `ImportError: cannot import name 'persist_oem_sales'`

- [ ] **Step 3: Write minimal implementation**

Append to `backend/scraper/fada_scraper.py` (add these imports at the top
alongside the existing ones):

```python
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import OEMMonthlySales
```

```python
async def persist_oem_sales(db: AsyncSession, rows: list[dict], *, source: str, source_document: str) -> None:
    """Replace any existing rows for each (source, year, month, category)
    combination present in `rows` with the freshly parsed ones -- same
    delete-then-insert-per-scope pattern as persist_rto_batch in
    scraper_service.py, reused rather than reinvented."""
    scopes = {(row["year"], row["month"], row["category"]) for row in rows}
    for year, month, category in scopes:
        delete_query = delete(OEMMonthlySales).where(
            OEMMonthlySales.source == source,
            OEMMonthlySales.year == year,
            OEMMonthlySales.category == category,
        )
        delete_query = delete_query.where(
            OEMMonthlySales.month.is_(None) if month is None else OEMMonthlySales.month == month
        )
        await db.execute(delete_query)

    for row in rows:
        db.add(OEMMonthlySales(
            source=source,
            year=row["year"],
            month=row["month"],
            category=row["category"],
            maker=row["maker"],
            count=row["count"],
            share_percent=row["share_percent"],
            source_document=source_document,
        ))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_fada_scraper.py -v`
Expected: all 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add scraper/fada_scraper.py tests/test_fada_scraper.py
git commit -m "feat: add idempotent FADA OEM sales persistence"
```

---

### Task 6: Backfill script

**Files:**
- Create: `backend/scraper/backfill_fada.py`

- [ ] **Step 1: Write the script**

Create `backend/scraper/backfill_fada.py`:

```python
"""One-time backfill of FADA's full public "Vehicle Retail Data" archive
(confirmed live on 2026-07-15: ~Aug 2021 through present, 5 archive pages)
into oem_monthly_sales. Safe to re-run -- persist_oem_sales is idempotent
per (source, year, month, category).

Usage: python -m scraper.backfill_fada
"""
import asyncio
import logging

import httpx

from app.core.database import AsyncSessionLocal, init_db
from scraper.fada_scraper import discover_releases, parse_release_pdf, persist_oem_sales

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_fada")

REQUEST_DELAY_SECONDS = 2.5


async def main() -> None:
    await init_db()

    async with httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"},
        timeout=30,
        follow_redirects=True,
    ) as client:
        releases = await discover_releases(client)
        logger.info("Found %d Vehicle Retail Data releases", len(releases))

        async with AsyncSessionLocal() as db:
            for release in releases:
                try:
                    resp = await client.get(release["pdf_url"])
                    resp.raise_for_status()
                    rows = parse_release_pdf(resp.content)
                    if not rows:
                        logger.warning("No OEM rows parsed from %r, skipping", release["title"])
                        continue
                    await persist_oem_sales(db, rows, source="FADA", source_document=release["title"])
                    await db.commit()
                    logger.info("Persisted %d rows from %r", len(rows), release["title"])
                except Exception as exc:
                    logger.error("Failed processing %r: %s", release["title"], exc)
                finally:
                    await asyncio.sleep(REQUEST_DELAY_SECONDS)

    logger.info("FADA backfill complete.")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Run it against the real live site**

Run: `cd backend && python -m scraper.backfill_fada`
Expected: log lines showing each release discovered and persisted, ending with
"FADA backfill complete." Takes a few minutes (one HTTP request + 2.5s delay
per release, ~40-60 releases expected).

- [ ] **Step 3: Spot-check the result**

Run: `cd backend && python -c "
import sqlite3
conn = sqlite3.connect('data/vahan.db')
c = conn.cursor()
c.execute(\"SELECT COUNT(*), COUNT(DISTINCT year || '-' || month) FROM oem_monthly_sales\")
print(c.fetchone())
c.execute(\"SELECT maker, count FROM oem_monthly_sales WHERE category='Two-Wheeler' AND year=2026 AND month=6 ORDER BY count DESC LIMIT 3\")
for row in c.fetchall(): print(row)
"`
Expected: a nonzero row count, and the top row is `('HERO MOTOCORP LTD', 472144)`
(matches the fixture PDF's verified figure).

- [ ] **Step 4: Commit**

```bash
git add scraper/backfill_fada.py
git commit -m "feat: add one-time FADA archive backfill script"
```

---

### Task 7: Scheduler integration

**Files:**
- Modify: `backend/scraper/scheduler.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add the FADA loop to scheduler.py**

Append to `backend/scraper/scheduler.py`:

```python
import httpx

from app.core.database import AsyncSessionLocal
from scraper.fada_scraper import discover_releases, parse_release_pdf, persist_oem_sales

FADA_CHECK_INTERVAL_HOURS = 24


async def run_fada_scheduler_loop() -> None:
    """Checks FADA's archive once a day for a release not yet in
    oem_monthly_sales, and ingests it if found. FADA publishes monthly, not
    continuously, so this runs on its own 24h cadence -- deliberately not
    folded into run_scheduler_loop's 5h VAHAN cadence, since they're
    different sources with no reason to be coupled.
    """
    while True:
        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"},
                timeout=30,
                follow_redirects=True,
            ) as client:
                releases = await discover_releases(client)
                async with AsyncSessionLocal() as db:
                    from sqlalchemy import select
                    from app.models.models import OEMMonthlySales
                    existing = await db.execute(select(OEMMonthlySales.source_document).distinct())
                    known_titles = {row[0] for row in existing.all()}

                    new_releases = [r for r in releases if r["title"] not in known_titles]
                    for release in new_releases:
                        resp = await client.get(release["pdf_url"])
                        resp.raise_for_status()
                        rows = parse_release_pdf(resp.content)
                        if rows:
                            await persist_oem_sales(db, rows, source="FADA", source_document=release["title"])
                            await db.commit()
                            logger.info("FADA scheduler: ingested new release %r", release["title"])
        except Exception as exc:
            logger.error("FADA scheduled check failed: %s", exc)

        await asyncio.sleep(FADA_CHECK_INTERVAL_HOURS * 3600)
```

- [ ] **Step 2: Wire it into the FastAPI lifespan**

In `backend/app/main.py`, change:

```python
from scraper.scheduler import run_scheduler_loop
```

to:

```python
from scraper.scheduler import run_scheduler_loop, run_fada_scheduler_loop
```

And change:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    async with AsyncSessionLocal() as session:
        await seed_geo_hierarchy(session)
    scheduler_task = asyncio.create_task(run_scheduler_loop())
    yield
    scheduler_task.cancel()
```

to:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    async with AsyncSessionLocal() as session:
        await seed_geo_hierarchy(session)
    scheduler_task = asyncio.create_task(run_scheduler_loop())
    fada_scheduler_task = asyncio.create_task(run_fada_scheduler_loop())
    yield
    scheduler_task.cancel()
    fada_scheduler_task.cancel()
```

- [ ] **Step 3: Verify the app still starts cleanly**

Run: `cd backend && python -c "
import asyncio
from app.main import app
print('app object created OK:', app.title)
"`
Expected: prints the app title with no import errors (this only checks the
module imports and wires up without error; it does not run the lifespan
loop itself).

- [ ] **Step 4: Commit**

```bash
git add scraper/scheduler.py app/main.py
git commit -m "feat: add daily FADA release check to the scheduler"
```

---

### Task 8: API endpoints

**Files:**
- Create: `backend/app/api/v1/endpoints/oem_sales.py`
- Modify: `backend/app/api/v1/router.py`
- Test: `backend/tests/test_oem_sales_endpoints.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_oem_sales_endpoints.py`:

```python
from app.models.models import OEMMonthlySales


async def _seed(db_session):
    db_session.add_all([
        OEMMonthlySales(source="FADA", year=2026, month=6, category="Two-Wheeler", maker="HERO MOTOCORP LTD", count=472144, share_percent=25.82, source_document="June 2026 release"),
        OEMMonthlySales(source="FADA", year=2026, month=6, category="Two-Wheeler", maker="TVS MOTOR COMPANY LTD", count=359243, share_percent=19.65, source_document="June 2026 release"),
        OEMMonthlySales(source="FADA", year=2026, month=5, category="Two-Wheeler", maker="HERO MOTOCORP LTD", count=450000, share_percent=24.0, source_document="May 2026 release"),
        OEMMonthlySales(source="FADA", year=2026, month=6, category="PV", maker="MARUTI SUZUKI INDIA LTD", count=167834, share_percent=40.85, source_document="June 2026 release"),
    ])
    await db_session.commit()


async def test_get_oem_categories(client, db_session):
    await _seed(db_session)
    response = await client.get("/api/v1/oem-sales/categories")
    assert response.status_code == 200
    assert set(response.json()) == {"Two-Wheeler", "PV"}


async def test_get_oem_monthly(client, db_session):
    await _seed(db_session)
    response = await client.get("/api/v1/oem-sales/monthly", params={"category": "Two-Wheeler", "year": 2026, "month": 6})
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 2
    hero = next(r for r in rows if r["maker"] == "HERO MOTOCORP LTD")
    assert hero["count"] == 472144
    assert hero["share_percent"] == 25.82


async def test_get_oem_trend(client, db_session):
    await _seed(db_session)
    response = await client.get("/api/v1/oem-sales/trend", params={"maker": "HERO MOTOCORP LTD", "category": "Two-Wheeler"})
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 2
    by_month = {r["month"]: r["count"] for r in rows}
    assert by_month == {5: 450000, 6: 472144}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_oem_sales_endpoints.py -v`
Expected: FAIL with 404 (route not registered) or connection/import error.

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/api/v1/endpoints/oem_sales.py`:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from app.core.database import get_db
from app.models.models import OEMMonthlySales

router = APIRouter()


@router.get("/categories")
async def get_oem_categories(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(OEMMonthlySales.category).distinct())
    return [row[0] for row in result.all()]


@router.get("/monthly")
async def get_oem_monthly(
    category: str,
    year: int,
    month: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(OEMMonthlySales).where(
        OEMMonthlySales.category == category,
        OEMMonthlySales.year == year,
    )
    query = query.where(OEMMonthlySales.month.is_(None) if month is None else OEMMonthlySales.month == month)
    query = query.order_by(desc(OEMMonthlySales.count))

    result = await db.execute(query)
    rows = result.scalars().all()
    return [
        {"maker": r.maker, "count": r.count, "share_percent": r.share_percent}
        for r in rows
    ]


@router.get("/trend")
async def get_oem_trend(
    maker: str,
    category: str,
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(OEMMonthlySales)
        .where(OEMMonthlySales.maker == maker, OEMMonthlySales.category == category)
        .order_by(OEMMonthlySales.year, OEMMonthlySales.month)
    )
    result = await db.execute(query)
    rows = result.scalars().all()
    return [
        {"year": r.year, "month": r.month, "count": r.count, "share_percent": r.share_percent}
        for r in rows
    ]
```

Modify `backend/app/api/v1/router.py` — add the import and registration:

```python
from app.api.v1.endpoints import (
    summary,
    states,
    registrations,
    comparison,
    yoy,
    categories,
    refresh,
    geo,
    oem_sales,
)
```

```python
api_router.include_router(oem_sales.router, prefix="/oem-sales", tags=["OEM Sales"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_oem_sales_endpoints.py -v`
Expected: all 3 tests PASS

- [ ] **Step 5: Run the full backend test suite to confirm no regressions**

Run: `cd backend && python -m pytest tests/ -q`
Expected: all tests pass (existing 49 + the new ones from this plan)

- [ ] **Step 6: Commit**

```bash
git add app/api/v1/endpoints/oem_sales.py app/api/v1/router.py tests/test_oem_sales_endpoints.py
git commit -m "feat: add OEM sales API endpoints"
```

---

### Task 9: Frontend types + API client

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/vahan.ts`

- [ ] **Step 1: Add types**

Append to `frontend/src/types/index.ts`:

```typescript
export interface OEMSalesRow {
  maker: string;
  count: number;
  share_percent: number | null;
}

export interface OEMTrendPoint {
  year: number;
  month: number | null;
  count: number;
  share_percent: number | null;
}
```

- [ ] **Step 2: Add API client functions**

Append to `frontend/src/api/vahan.ts`:

```typescript
export const getOemCategories = (): Promise<string[]> =>
  api.get('/oem-sales/categories').then(r => r.data);
export const getOemMonthly = (params: { category: string; year: number; month?: number | null }) =>
  api.get('/oem-sales/monthly', { params }).then(r => r.data);
export const getOemTrend = (params: { maker: string; category: string }) =>
  api.get('/oem-sales/trend', { params }).then(r => r.data);
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add src/types/index.ts src/api/vahan.ts
git commit -m "feat: add OEM sales types and API client functions"
```

---

### Task 10: Frontend page + navigation

**Files:**
- Create: `frontend/src/pages/IndustrySales.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Sidebar.tsx`

- [ ] **Step 1: Create the page**

Create `frontend/src/pages/IndustrySales.tsx`:

```tsx
// frontend/src/pages/IndustrySales.tsx
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { getOemCategories, getOemMonthly, getOemTrend } from '../api/vahan';
import { useChartTheme } from '../hooks/useChartTheme';
import { useAppStore } from '../hooks/useAppStore';
import { TruncatedYAxisTick } from '../components/ChartAxisTick';

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export function IndustrySalesPage() {
  const chart = useChartTheme();
  const { selectedYear, selectedMonth } = useAppStore();
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [selectedMaker, setSelectedMaker] = useState<string | null>(null);

  const { data: categories } = useQuery({ queryKey: ['oemCategories'], queryFn: getOemCategories });
  const category = selectedCategory ?? categories?.[0] ?? null;

  const { data: monthly, isLoading: monthlyLoading } = useQuery({
    queryKey: ['oemMonthly', category, selectedYear, selectedMonth],
    queryFn: () => getOemMonthly({ category: category!, year: selectedYear, month: selectedMonth }),
    enabled: !!category,
  });

  const { data: trend } = useQuery({
    queryKey: ['oemTrend', selectedMaker, category],
    queryFn: () => getOemTrend({ maker: selectedMaker!, category: category! }),
    enabled: !!selectedMaker && !!category,
  });

  const barData = (monthly || []).map((m: { maker: string; count: number }) => ({ name: m.maker, count: m.count }));
  const trendData = (trend || []).map((t: { year: number; month: number | null; count: number }) => ({
    name: t.month ? `${MONTH_NAMES[t.month - 1]} ${t.year}` : `FY${t.year}`,
    count: t.count,
  }));

  return (
    <div className="p-6 space-y-6">
      <div className="animate-entrance">
        <h2 className="text-xl font-bold text-[var(--text-primary)] tracking-tight">Industry Sales</h2>
        <p className="text-[10px] text-[var(--text-muted)] mt-0.5 font-mono uppercase tracking-widest">
          Maker-wise vehicle retail data — sourced from FADA, real registrations
        </p>
      </div>

      <div className="flex flex-col gap-1.5 max-w-xs">
        <label className="text-[10px] uppercase font-mono tracking-widest text-[var(--text-muted)] font-bold">Category</label>
        <select
          value={category || ''}
          onChange={(e) => { setSelectedCategory(e.target.value); setSelectedMaker(null); }}
          className="w-full bg-[var(--bg-sunken)] border border-[var(--border)] text-[var(--text-primary)] text-xs font-semibold px-3 py-2 rounded-xl focus:outline-none focus:ring-2 focus:ring-[var(--accent)]"
        >
          {(categories || []).map((c: string) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>

      <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance">
        <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight mb-4">Maker Leaderboard</h3>
        {monthlyLoading ? (
          <div className="h-[400px] rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft" />
        ) : (
          <ResponsiveContainer width="100%" height={Math.max(280, barData.length * 26)}>
            <BarChart data={barData} layout="vertical">
              <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} horizontal={false} />
              <XAxis type="number" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} />
              <YAxis dataKey="name" type="category" tick={(props) => <TruncatedYAxisTick {...props} fill={chart.axisText} />} width={210} />
              <Tooltip
                formatter={(val: number) => [val.toLocaleString('en-IN'), 'Registrations']}
                contentStyle={chart.tooltipContentStyle({ fontSize: 12 })}
              />
              <Bar
                dataKey="count"
                fill={chart.seriesColors[0]}
                radius={[0, 4, 4, 0]}
                onClick={(data: { name?: string }) => data?.name && setSelectedMaker(data.name)}
                cursor="pointer"
              />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      {selectedMaker && (
        <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance">
          <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight mb-4">{selectedMaker} — Trend</h3>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={trendData}>
              <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} vertical={false} />
              <XAxis dataKey="name" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} />
              <Tooltip formatter={(val: number) => val.toLocaleString('en-IN')} contentStyle={chart.tooltipContentStyle()} />
              <Line type="monotone" dataKey="count" stroke={chart.seriesColors[0]} strokeWidth={2.5} dot={{ r: 3, fill: chart.seriesColors[0] }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add the route**

In `frontend/src/App.tsx`, add the import:

```tsx
import { IndustrySalesPage } from './pages/IndustrySales';
```

And add the route inside `<Routes>`, after the `/makers` route:

```tsx
<Route path="/industry-sales" element={<IndustrySalesPage />} />
```

- [ ] **Step 3: Add the nav entry**

In `frontend/src/components/Sidebar.tsx`, change the import:

```tsx
import { LayoutDashboard, Map, TrendingUp, BarChart3, Car, Award, ChevronLeft, ChevronRight } from './Icons';
```

And add to `navItems` (after the Makers & Models entry):

```tsx
{ to: '/industry-sales', icon: Award, label: 'Industry Sales' },
```

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 5: Manual verification in the browser**

Run: `cd frontend && npm run dev` (and `cd backend && python -m uvicorn app.main:app --port 8020` in
another terminal if not already running), then open `http://localhost:3000/industry-sales`.
Expected: category dropdown populated, maker leaderboard bar chart renders with real FADA
data, clicking a bar shows that maker's trend line below.

- [ ] **Step 6: Commit**

```bash
git add src/pages/IndustrySales.tsx src/App.tsx src/components/Sidebar.tsx
git commit -m "feat: add Industry Sales dashboard page"
```

---

## Post-plan note

This covers FADA only (per the approved spec). SIAM (industry-wide totals) and OEM
investor-relations press releases (real model-level names) are separate, later
sub-projects — each needs its own brainstorming → spec → plan cycle before
implementation, per the same reasoning that put FADA first here.
