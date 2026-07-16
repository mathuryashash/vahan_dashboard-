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
import io
import logging
import re
import pdfplumber
from urllib.parse import urljoin

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import OEMMonthlySales
from scraper.parsing import MONTH_ABBR, parse_count

logger = logging.getLogger("fada_scraper")

ARCHIVE_URL = "https://www.fada.in/press-release-list.php"
BASE_URL = "https://www.fada.in/"

# Marks the start of each press-release card. Shared by _ENTRY_RE (to find
# titles) and discover_releases (to detect an empty/end-of-archive page) so
# the two checks can't silently drift apart if FADA's markup changes.
_ENTRY_MARKER = '<h3 class="font-weight-semibold mb-3">'

# Title and PDF-download link sit a few lines apart within the same card,
# not adjacent -- DOTALL + a non-greedy middle bridges them. Confirmed
# against the real archive: matches all 15 press-release entries per page,
# title text captured verbatim for the "vehicle retail data" substring filter
# below.
_ENTRY_RE = re.compile(
    re.escape(_ENTRY_MARKER) + r'(?:<img[^>]*>\s*)?([^<]+)</h3>.*?href="([^"]+\.pdf)"',
    re.IGNORECASE | re.DOTALL,
)


def _parse_release_list_page(page_html: str) -> list[dict]:
    """[{title, pdf_url}, ...] for every "Vehicle Retail Data" entry on one
    archive listing page. Pure function, no network -- see
    test_parse_release_list_page_* for the exact archive shape this handles."""
    releases = []
    for title, href in _ENTRY_RE.findall(page_html):
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
        has_any_entries = _ENTRY_MARKER in resp.text
        if not has_any_entries:
            logger.info("FADA archive: page %d empty, stopping (found %d releases)", page, len(all_releases))
            break
        all_releases.extend(_parse_release_list_page(resp.text))
    else:
        logger.warning("FADA archive: hit max_pages=%d without finding an empty page -- archive may have grown, raise max_pages", max_pages)
    return all_releases


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

                if current_period is not None and len(data_row) > 2:
                    rows.append({
                        "category": category,
                        "maker": name,
                        "year": current_period[0],
                        "month": current_period[1],
                        "count": parse_count(data_row[1] or ""),
                        "share_percent": _parse_share_percent(data_row[2] or ""),
                    })
                if prior_period is not None and len(data_row) > 4:
                    rows.append({
                        "category": category,
                        "maker": name,
                        "year": prior_period[0],
                        "month": prior_period[1],
                        "count": parse_count(data_row[3] or ""),
                        "share_percent": _parse_share_percent(data_row[4] or ""),
                    })
    return rows


async def persist_oem_sales(db: AsyncSession, rows: list[dict], *, source: str, source_document: str) -> None:
    """Replace any existing rows for each (source, year, month, category) in
    `rows` with the freshly parsed ones, so re-ingesting the same release is
    idempotent instead of duplicating rows -- mirrors
    scraper_service.persist_rto_batch's delete-then-insert pattern."""
    periods = {(row["year"], row["month"], row["category"]) for row in rows}
    for year, month, category in periods:
        await db.execute(
            delete(OEMMonthlySales).where(
                OEMMonthlySales.source == source,
                OEMMonthlySales.year == year,
                OEMMonthlySales.month == month,
                OEMMonthlySales.category == category,
            )
        )

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
