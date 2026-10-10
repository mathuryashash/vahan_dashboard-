"""Site interaction for the NEW VAHAN analytics site
(analytics.parivahan.gov.in) -- a from-scratch reverse-engineering, not a
port of vahan_scraper.py, since it's an entirely different backend (Spring
+ a form POST, not PrimeFaces/JSF select-cascades). Confirmed live this
session: one GET loads a session (JSESSIONID cookie + a reusable _csrf
token -- the same token works across many POSTs, no per-request refresh
needed), one GET per query fetches a session-bound CAPTCHA image, one POST
submits the filters + solved CAPTCHA + csrf and gets back a full
server-rendered HTML page (not JSON) with the result table embedded
directly -- no JS execution needed to read it.

Deliberately narrow: this only drives the one query shape that's actually
useful and working -- yAxis=monthWise x xAxis=vehicleCategoryDescription,
scoped to one state + one year (that state param takes multiple states at
once too, but one-state-per-request keeps a single request's response
small and keeps retry/resume granularity at the level run_analytics_scrape.py
already resumes on), optionally further scoped to one fuel (see FUEL_VALUES
-- 34 static values, fully enumerable) or one maker (NOT enumerable: the
site's maker list is a 7,733-item long tail behind a lazy-load search
endpoint, so no run_analytics_*_scrape.py loops over "every maker" the way
it does over every fuel). yAxis=vehicleMakerName (Maker) renders through a
separate client-side-paginated table that requires JS to populate and is
currently broken server-side even through the real browser UI (confirmed
live: "Unable to prepare Maker page numbers safely") -- not built against
here.
"""
import asyncio
import logging
import re
import tempfile
import time
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from scraper.parsing import parse_count

logger = logging.getLogger("analytics_scraper")

REPORT_URL = "https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en"
CAPTCHA_URL = "https://analytics.parivahan.gov.in/analytics/captcha-gen"
MAKER_SEARCH_URL = "https://analytics.parivahan.gov.in/analytics/vahanpublicreport/lazy/vehicle-makers"
RTO_LIST_URL = "https://analytics.parivahan.gov.in/analytics/json_rtos"
CAPTCHA_MAX_ATTEMPTS = 5
CAPTCHA_WHITELIST = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"

_TESSERACT_CANDIDATES = ["tesseract", r"C:\Program Files\Tesseract-OCR\tesseract.exe"]

# The new site's own state-code vocabulary differs from this codebase's
# `states` table (inherited from the old VAHAN4 site) for exactly 3 of 36
# states -- confirmed live by diffing the new site's <select> dropdown
# against our states table; every other code matches byte-for-byte. Applied
# only to the outgoing stateMultiple form value -- our own state_code is
# still what's logged and persisted, so this stays an internal detail of
# talking to the site, not a change to what this codebase calls a state.
_SITE_STATE_CODE_OVERRIDES = {
    "OD": "OR",  # Odisha
    "TS": "TG",  # Telangana
    "DN": "DD",  # UT of DNH and DD
}

# The site's full vehicleFuels list -- a small, static, fully-rendered
# <select> (unlike vehicleMakers, which is a lazy-loaded 7,733-item long
# tail behind a separate /lazy/vehicle-makers search endpoint and isn't
# feasible to backfill exhaustively). Extracted live from the report page;
# this enum rarely changes, so it's hardcoded rather than fetched per run.
FUEL_VALUES = [
    "BIO-CNG/BIO-GAS", "CNG ONLY", "DI-METHYL ETHER", "DIESEL", "DIESEL/HYBRID",
    "DUAL DIESEL/BIO CNG", "DUAL DIESEL/CNG", "DUAL DIESEL/LNG", "ELECTRIC(BOV)",
    "ETHANOL(E100)", "FLEX-FUEL(BIO-DIESEL)", "FLEX-FUEL(ETHANOL)", "FUEL CELL HYDROGEN",
    "HCNG", "HYDROGEN(ICE)", "LNG", "LPG ONLY", "METHANOL", "NOT APPLICABLE", "PETROL",
    "PETROL(E20)", "PETROL(E20)/CNG", "PETROL(E20)/HYBRID", "PETROL(E20)/HYBRID/CNG",
    "PETROL(E20)/LPG", "PETROL/CNG", "PETROL/HYBRID", "PETROL/HYBRID/CNG", "PETROL/LPG",
    "PETROL/METHANOL", "PLUG-IN HYBRID EV", "PURE EV", "SOLAR", "STRONG HYBRID EV",
]


class CaptchaSolveError(RuntimeError):
    """Every CAPTCHA attempt for one query was rejected."""


class UnexpectedPageError(RuntimeError):
    """The response was not a results page at all. Distinct from a state with
    no registrations, which still renders a table of zeros -- see
    parse_month_category_table for why the two must not be conflated."""


class TableIntegrityError(UnexpectedPageError):
    """The results table disagrees with its own arithmetic (row Total vs
    cells, footer Total row vs column sums, or a gap/duplicate in the month
    sequence). Same role as vahan_scraper.ExportIntegrityError: a consistency
    check on what we parsed, not an authenticity check on what was sent.
    Subclasses UnexpectedPageError so every caller that already skips a bad
    page (keeping what it had) skips this one too instead of persisting it."""


class TesseractUnavailableError(RuntimeError):
    """tesseract binary missing, or its language data can't actually OCR --
    confirmed this session that a fresh Windows Tesseract install can have
    an all-zero-bytes eng.traineddata (present on disk, wrong content) that
    only fails once you actually try to use it, not at install time. Surfacing
    this at startup (verify_tesseract) instead of mid-backfill avoids
    burning an hour of "0% solve rate" before anyone notices why."""


async def _find_tesseract() -> str:
    for candidate in _TESSERACT_CANDIDATES:
        try:
            proc = await asyncio.create_subprocess_exec(
                candidate, "--version", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            continue
        await proc.communicate()
        if proc.returncode == 0:
            return candidate
    raise TesseractUnavailableError(
        "tesseract binary not found on PATH or at the default Windows install "
        "location -- install it (https://github.com/UB-Mannheim/tesseract) first."
    )


async def verify_tesseract() -> str:
    """Call once at CLI startup, not per-query. Confirms the binary runs AND
    can actually produce non-empty OCR output against a real captcha fetch
    -- catches a present-but-corrupt eng.traineddata (hit live this session:
    a 4MB file that was all zero bytes) that `--version` alone won't catch."""
    tesseract_path = await _find_tesseract()
    async with httpx.AsyncClient(timeout=15) as client:
        image_bytes = (await client.get(CAPTCHA_URL, params={"_ts": str(int(time.time() * 1000)), "_seq": "1"})).content
    text = await _solve_captcha(tesseract_path, image_bytes)
    if not text:
        raise TesseractUnavailableError(
            f"tesseract at {tesseract_path!r} produced no output against a real CAPTCHA image -- "
            "its language data is likely missing or corrupt. Get a known-good eng.traineddata from "
            "https://github.com/tesseract-ocr/tessdata_fast and point TESSDATA_PREFIX at its folder."
        )
    logger.info("tesseract OK (%s), smoke-test OCR guess: %r", tesseract_path, text)
    return tesseract_path


async def load_session(client: httpx.AsyncClient) -> str:
    """GET the report page. Sets JSESSIONID/analytics_sh_cok on the
    client's cookie jar as a side effect; returns the _csrf token every
    POST on this session needs."""
    resp = await client.get(REPORT_URL)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    csrf_input = soup.find("input", {"name": "_csrf"})
    if not csrf_input or not csrf_input.get("value"):
        raise RuntimeError("'_csrf' token not found on the report page -- site markup likely changed")
    return csrf_input["value"]


async def _fetch_captcha_image(client: httpx.AsyncClient) -> bytes:
    resp = await client.get(CAPTCHA_URL, params={"_ts": str(int(time.time() * 1000)), "_seq": "1"})
    resp.raise_for_status()
    return resp.content


async def _solve_captcha(tesseract_path: str, image_bytes: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        f.write(image_bytes)
        image_path = Path(f.name)
    try:
        proc = await asyncio.create_subprocess_exec(
            tesseract_path, str(image_path), "stdout", "--oem", "1", "--psm", "7",
            "-c", f"tessedit_char_whitelist={CAPTCHA_WHITELIST}",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode().strip()
    finally:
        image_path.unlink(missing_ok=True)


def _build_form(*, csrf_token: str, state_code: str, year: int, captcha: str,
                 maker: str | None, fuel: str | None, rto_code: str | None = None) -> dict[str, str | list[str]]:
    # Dict, not a list of tuples: httpx 0.28's `data=` only form-encodes a
    # Mapping (a list of tuples is silently treated as raw `content=` instead
    # -- confirmed live this session, it breaks the POST with a
    # "sync request with an AsyncClient" error deep in httpx internals).
    # Repeated keys (archivedFlags) go in as a list value; httpx's doseq
    # encoding expands that back into repeated form fields.
    data: dict[str, str | list[str]] = {
        "archivedFlags": ["ACTIVE_COMPLIANT", "ACTIVE_NON_COMPLIANT", "PERMANENT_ARCHIVE", "TEMPORARY_ARCHIVE"],
        "_archivedFlags": "1",
        "timePeriod": "0",
        "_financialYearList": "1",
        "fromYear": str(year),
        "toYear": str(year),
        "reportMonth": "",
        "stateMultiple": _SITE_STATE_CODE_OVERRIDES.get(state_code, state_code),
        "_stateMultiple": "1",
        "_rtoCodeMultiple": "1",
        "_vehicleEmissions": "1",
        "_vehicleMakers": "1",
        "_vehicleCategoryGroup": "1",
        "_vehicleSubCategories": "1",
        "_vehicleClasses": "1",
        "_vehicleFuels": "1",
        "_evType": "1",
        "_vehicleStatus": "1",
        "_vehicleOwnerType": "1",
        "vehicleType": "",
        "fitnessCheck": "0",
        "delhiNcr": "0",
        "yAxis": "monthWise",
        "xAxis": "vehicleCategoryDescription",
        "captcha": captcha,
        "last5financialYearList": "",
        "_csrf": csrf_token,
    }
    if maker:
        data["vehicleMakers"] = maker
        data["selectedMakersCsv"] = maker
    if fuel:
        data["vehicleFuels"] = fuel
    if rto_code:
        # The site's own NUMERIC rto code (e.g. "9"), NOT the json_rtos
        # `id` (980 returns nothing) and NOT our own "DL9" -- see
        # map_site_rtos for how the two vocabularies are bridged. Confirmed
        # live this field really filters (unlike fromDate/toDate, which are
        # vestigial): DL/2024 returned 711,071 across months 1-12
        # unfiltered, 85,366 with rtoCodeMultiple=9, and monthly
        # granularity survives, as does composition with vehicleMakers
        # (rto+maker = 19,084, strictly less than either alone).
        data["rtoCodeMultiple"] = rto_code
    return data


async def submit_query(
    client: httpx.AsyncClient, tesseract_path: str, csrf_token: str, state_code: str, year: int,
    *, maker: str | None = None, fuel: str | None = None, rto_code: str | None = None,
) -> str:
    """Solves a fresh CAPTCHA and POSTs the query, retrying (fresh CAPTCHA
    each time) up to CAPTCHA_MAX_ATTEMPTS on a wrong guess -- confirmed live
    this session that a rejected CAPTCHA costs nothing but the retry itself
    (no lockout, no backoff penalty across 30+ requests). Raises
    CaptchaSolveError if every attempt is rejected. Returns the raw response
    HTML for parse_month_category_table."""
    for attempt in range(1, CAPTCHA_MAX_ATTEMPTS + 1):
        try:
            image_bytes = await _fetch_captcha_image(client)
            captcha_text = await _solve_captcha(tesseract_path, image_bytes)
            resp = await client.post(
                REPORT_URL,
                data=_build_form(csrf_token=csrf_token, state_code=state_code, year=year,
                                  captcha=captcha_text, maker=maker, fuel=fuel, rto_code=rto_code),
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            # Transient network blip (connect/read timeout, 5xx, dropped
            # connection) over a multi-hour unattended run -- retry the same
            # as a wrong CAPTCHA guess (cheap, no lockout) instead of failing
            # the whole state on one bad request.
            logger.info("state=%s year=%s: network error %r (attempt %d/%d), retrying",
                        state_code, year, e, attempt, CAPTCHA_MAX_ATTEMPTS)
            continue
        if "Invalid CAPTCHA" in resp.text:
            logger.info("state=%s year=%s: wrong captcha %r (attempt %d/%d), retrying",
                        state_code, year, captcha_text, attempt, CAPTCHA_MAX_ATTEMPTS)
            continue
        return resp.text
    raise CaptchaSolveError(
        f"state={state_code} year={year}: captcha rejected or request failed {CAPTCHA_MAX_ATTEMPTS} times in a row"
    )


def parse_month_category_table(html: str) -> list[dict]:
    """Returns [{'month': int, 'category': str, 'count': int}, ...] --
    every (month, category) cell in the results table, skipping the
    'Total' row (every other table in this codebase derives yearly totals
    via SUM(count), not a stored pseudo-row) and any all-zero placeholder
    the site can render for a state/year with genuinely no data. Strips
    <script>/<style> first: a dynamic-heading-builder inline script the
    page ships would otherwise pollute a naive text search for the results
    heading (not used here, but the table search shares the same soup)."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    table = soup.find("table")
    if not table:
        # A state/year with genuinely no registrations still renders a table
        # (all-zero cells, dropped below), so no table at all means this
        # wasn't a results page -- a session-timeout interstitial, an error
        # page, a changed layout. It used to log a warning and return [],
        # which every caller then treated as real zero data:
        # persist_state_month_category_batch deletes a state's year BEFORE
        # inserting, so one bad page wiped it and the run logged "0 rows";
        # and the live maker lookup cached the [] as "this maker sold 0" and
        # served it to every later request. Raising lets each caller skip the
        # state and keep what it had.
        raise UnexpectedPageError(
            "no results <table> in the response -- not a results page "
            "(session timeout, error page, or changed site layout)"
        )

    rows = [
        [cell.get_text(strip=True) for cell in tr.find_all(["td", "th"])]
        for tr in table.find_all("tr")
    ]
    rows = [r for r in rows if r]
    if len(rows) < 2:
        return []

    header, *body_rows = rows
    # The page's own category filter (same 17 names the results axis uses).
    # The collapsed-header repair names its columns from THIS, not from a
    # list captured once, so a renamed / added / reordered axis is caught.
    axis_select = soup.find("select", id="vehicleSubCategory")
    axis = [o.get("value", "").strip() for o in axis_select.find_all("option")] if axis_select else None
    header, body_rows = normalize_ragged_table(header, body_rows, axis)
    if len(header) == 2 and header[-1].strip().lower() == "total" and body_rows and all(
            len(r) == 2 and parse_count(r[1]) == 0 for r in body_rows):
        # Every month empty: the site collapses the whole table to Month/Total
        # zeros. A genuine "nothing registered", same as an all-zero table.
        return []
    categories = header[1:-1]  # header[0] is "Month", header[-1] is "Total"
    validate_month_category_table(header, body_rows)
    records = []
    for row in body_rows:
        if not row or row[0] == "Total":
            continue
        month = int(row[0].split("-")[1])
        for category, cell in zip(categories, row[1:-1]):
            count = parse_count(cell)
            if count:
                records.append({"month": month, "category": category, "count": count})
    return records


_MONTH_LABEL_RE = re.compile(r"^(\d{4})-(\d{2})$")

# The full category axis as the site renders it (alphabetical), captured live
# 2026-10-09 (TS 2026 PETROL / DIESEL). Used ONLY to name the columns of a
# table whose header collapsed to ['Month', 'Total'] while its rows carry
# exactly this many cells -- see normalize_ragged_table. Only the SET is
# trusted; the column order comes from the page itself.
SITE_CATEGORIES = (
    "FOUR WHEELER (Invalid Carriage)", "HEAVY GOODS VEHICLE", "HEAVY MOTOR VEHICLE",
    "HEAVY PASSENGER VEHICLE", "LIGHT GOODS VEHICLE", "LIGHT MOTOR VEHICLE",
    "LIGHT PASSENGER VEHICLE", "MEDIUM GOODS VEHICLE", "MEDIUM MOTOR VEHICLE",
    "MEDIUM PASSENGER VEHICLE", "OTHER THAN MENTIONED ABOVE", "THREE WHEELER (Invalid Carriage)",
    "THREE WHEELER(NT)", "THREE WHEELER(T)", "TWO WHEELER (Invalid Carriage)", "TWO WHEELER(NT)",
    "TWO WHEELER(T)",
)
_MAX_RAGGED_CANDIDATES = 4096


def normalize_ragged_table(
    header: list[str], body_rows: list[list[str]], axis: list[str] | None = None,
) -> tuple[list[str], list[list[str]]]:
    """Repair the three ragged shapes the analytics site renders (seen live
    2026-10-09) into a rectangular table, or leave it alone for
    validate_month_category_table to reject. Every repair is checked against
    the page's own arithmetic; nothing is guessed:

    1. An empty month renders as ``[month, '0']``. Expanded to all-zero cells
       (a 2-cell row whose Total is NOT 0 is left ragged -> rejected).
    2. When the FIRST month is empty the header itself collapses to
       ``['Month', 'Total']`` (and so does the footer) while later rows carry
       the full category axis. The header is rebuilt from `axis` -- the
       page's own category <select>, in page order -- which must name exactly
       the SITE_CATEGORIES set; otherwise the table is rejected loudly
       (TableIntegrityError) rather than guessing which column is which.
       Every non-empty row must then have len(axis) + 2 cells; the collapsed
       footer (it states the first row's 0) is dropped. Row totals are still checked per row. (TS 2026
       PETROL(E20): Jan-Mar empty, ~277k units were being thrown away.)
    3. A month can omit one zero-valued rare column (18 cells under a 19-cell
       header). Resolved only when the footer row exists, has full width and
       EVERY placement of the missing zero(s) that reproduces the footer's
       column sums yields the same cells; otherwise left ragged -> rejected.
    """
    from itertools import combinations, product

    def is_footer(r):
        return bool(r) and r[0] == "Total"

    width = len(header)
    if width == 2 and header and header[-1].strip().lower() == "total":
        wide = {len(r) for r in body_rows if not is_footer(r) and len(r) != 2}
        if wide and (not axis or len(set(axis)) != len(axis) or set(axis) != set(SITE_CATEGORIES)):
            raise TableIntegrityError(
                f"collapsed header: the page's category axis {axis!r} is not the expected "
                f"{len(SITE_CATEGORIES)} categories -- refusing to guess column names"
            )
        if wide == {len(SITE_CATEGORIES) + 2}:
            header = [header[0], *axis, header[-1]]
            width = len(header)
            body_rows = [r for r in body_rows if not (is_footer(r) and len(r) == 2)]
        else:
            return header, body_rows
    if width < 3:
        return header, body_rows
    header, body_rows = _widen_subset_header(header, body_rows, axis)
    width = len(header)

    out: list[list[str]] = []
    short: list[int] = []
    for r in body_rows:
        if not is_footer(r) and len(r) == 2 and parse_count(r[1]) == 0:
            r = [r[0], *(["0"] * (width - 1))]
        elif not is_footer(r) and 2 < len(r) < width:
            short.append(len(out))
        out.append(r)
    if not short:
        return header, out

    footer = next((r for r in out if is_footer(r)), None)
    if footer is None or len(footer) != width:
        return header, out
    options: list[list[list[str]]] = []
    for idx in short:
        r = out[idx]
        missing = width - len(r)
        opts = []
        for pos in combinations(range(1, width - 1), missing):
            cells = list(r[1:-1])
            for p in pos:
                cells.insert(p - 1, "0")
            opts.append([r[0], *cells, r[-1]])
        options.append(opts)
    total = 1
    for o in options:
        total *= len(o)
    if total > _MAX_RAGGED_CANDIDATES:
        return header, out
    want = [parse_count(c) for c in footer[1:]]
    fixed_rows = [r for i, r in enumerate(out) if i not in set(short) and not is_footer(r)]
    base = [0] * (width - 1)
    for r in fixed_rows:
        if len(r) != width:
            return header, out
        for i, c in enumerate(r[1:]):
            base[i] += parse_count(c)
    solutions = set()
    for combo in product(*options):
        sums = list(base)
        for r in combo:
            for i, c in enumerate(r[1:]):
                sums[i] += parse_count(c)
        if sums == want:
            solutions.add(tuple(tuple(r) for r in combo))
            if len(solutions) > 1:
                return header, out
    if len(solutions) != 1:
        return header, out
    for idx, row in zip(short, next(iter(solutions))):
        out[idx] = list(row)
    return header, out


def _widen_subset_header(
    header: list[str], body_rows: list[list[str]], axis: list[str] | None,
) -> tuple[list[str], list[list[str]]]:
    """Shape 4 (live 2026-10-10, LA 2026 PURE EV, MH/OD ETHANOL(E100), RJ
    PETROL/HYBRID/CNG): the header and footer NAME only 16 of the 17
    categories (they follow the first month's columns) while later months
    carry the full axis (19 cells). Header-width rows and the footer are
    mapped by the header's own names onto the page's axis, zero for the
    unnamed column; full-width rows are taken in axis order. Nothing is
    guessed -- every name comes from the page -- and validate_month_category_table
    then re-checks each row total and every footer column sum on the full
    axis (a non-zero in the unnamed column of a full row fails the footer's
    implicit 0). A collapsed ['Month','Total'] header over narrow rows names
    nothing, so that shape is still rejected."""
    names = header[1:-1]
    full = len(SITE_CATEGORIES) + 2
    if not axis or len(names) >= len(SITE_CATEGORIES) or not any(
            len(r) == full and r[0] != "Total" for r in body_rows):
        return header, body_rows
    if (len(set(axis)) != len(axis) or set(axis) != set(SITE_CATEGORIES)
            or len(set(names)) != len(names) or not set(names) <= set(axis)):
        raise TableIntegrityError(
            f"header names {names!r} are not a subset of the page's 17-category axis -- refusing to map columns")
    width = len(header)
    out = []
    for r in body_rows:
        if len(r) == width:
            vals = dict(zip(names, r[1:-1]))
            r = [r[0], *(vals.get(a, "0") for a in axis), r[-1]]
        out.append(r)
    return [header[0], *axis, header[-1]], out


def validate_month_category_table(header: list[str], body_rows: list[list[str]]) -> None:
    """Port of vahan_scraper._validate_export to the analytics results table.

    That table has no S No column; its rows are months, so the S-No
    contiguity check becomes a month-sequence check (labels YYYY-MM, one
    year, strictly consecutive, no duplicates -- a dropped or repeated row
    breaks it). Then the arithmetic the page states about itself:
    1. each month row's Total == sum of its category cells;
    2. the footer 'Total' row (when present) == column sums of the month rows,
       per category and for the grand total.
    Exact integer equality: both sides come from the same response. The
    CAPTCHA is OCR-solved, so a wrong-but-valid page is a real risk; this
    catches a mangled/partial table, not a correct table for the wrong query.
    """
    if not header or header[-1].strip().lower() != "total" or len(header) < 3:
        raise TableIntegrityError(f"unexpected header shape: {header[:3]}...{header[-2:]}")
    width = len(header)
    months: list[tuple[int, int]] = []
    col_sums = [0] * (width - 1)
    footer = None
    for row in body_rows:
        if row and row[0] == "Total":
            footer = row
            continue
        m = _MONTH_LABEL_RE.match(row[0].strip()) if row else None
        if not m:
            raise TableIntegrityError(f"unexpected row label {row[0] if row else row!r} (want YYYY-MM)")
        if len(row) != width:
            raise TableIntegrityError(f"row {row[0]}: {len(row)} cells, header has {width}")
        months.append((int(m.group(1)), int(m.group(2))))
        cells = [parse_count(c) for c in row[1:-1]]
        declared = parse_count(row[-1])
        if sum(cells) != declared:
            raise TableIntegrityError(
                f"row {row[0]}: cells sum to {sum(cells)} but the table's own Total says {declared}")
        for i, v in enumerate(cells + [declared]):
            col_sums[i] += v
    if months:
        years = {y for y, _ in months}
        nums = [mo for _, mo in months]
        if len(years) != 1 or nums != list(range(nums[0], nums[0] + len(nums))) or not 1 <= nums[0] <= 12 \
                or nums[-1] > 12:
            raise TableIntegrityError(
                f"month rows are not one contiguous run within a year: {[f'{y}-{mo:02d}' for y, mo in months]}")
    if footer is not None:
        if len(footer) != width:
            raise TableIntegrityError(f"Total row: {len(footer)} cells, header has {width}")
        declared_cols = [parse_count(c) for c in footer[1:]]
        if declared_cols != col_sums:
            bad = next(i for i, (a, b) in enumerate(zip(declared_cols, col_sums)) if a != b)
            raise TableIntegrityError(
                f"Total row column {header[bad + 1]!r} says {declared_cols[bad]} but the month rows sum to "
                f"{col_sums[bad]} -- rows are missing or altered")


async def scrape_state_year(
    client: httpx.AsyncClient, tesseract_path: str, csrf_token: str, state_code: str, year: int,
    *, maker: str | None = None, fuel: str | None = None, rto_code: str | None = None,
) -> list[dict]:
    html = await submit_query(client, tesseract_path, csrf_token, state_code, year,
                              maker=maker, fuel=fuel, rto_code=rto_code)
    return parse_month_category_table(html)


async def search_makers(client: httpx.AsyncClient, search_text: str, *, size: int = 20) -> list[str]:
    """Real-time substring search against the site's own maker lookup --
    confirmed live this is what the maker's search box itself calls
    (/lazy/vehicle-makers), a plain GET needing only the session cookie
    (no CSRF, no CAPTCHA). Exists because the vehicleMakers form field
    requires an EXACT match against one of these full legal names --
    confirmed live: submitting "HONDA" alone (not the real entity name
    "HONDA MOTORCYCLE AND SCOOTER INDIA (P) LTD") returns a real,
    genuinely-empty result, indistinguishable from a real zero without
    this search to catch the mismatch before it ever reaches that form."""
    resp = await client.get(MAKER_SEARCH_URL, params={"page": 0, "size": size, "search": search_text})
    resp.raise_for_status()
    return resp.json()


def map_site_rtos(site_rtos: list[dict]) -> dict[str, str]:
    """{our rto_code -> the site's numeric rtoCode}, matched by the SUFFIX of
    the site's own rtoName ("DWARKA - DL9" -> "DL9").

    Deliberately not parsed out of our own rto_code: the two vocabularies
    don't line up arithmetically. Confirmed live for Delhi -- we hold 27
    RTOs, the site lists 23, only 16 are common; DL14-DL18 simply aren't on
    the site, and "DL1L" isn't even numeric, so int()-ing our code would
    both crash on some and silently produce a WRONG (but plausible) site
    code for others. An rto_code missing from this map has no live option
    at all, which is the honest answer rather than a guessed one.

    Entries whose rtoName has no "-" are skipped rather than mapped under
    their whole name -- without that guard a name like "AGRA" would land in
    the map as the key "AGRA" and could never match a real rto_code anyway.
    """
    mapped: dict[str, str] = {}
    for rto in site_rtos:
        name = str(rto.get("rtoName", ""))
        if "-" not in name:
            continue
        mapped[name.rsplit("-", 1)[-1].strip().upper()] = str(rto["rtoCode"])
    return mapped


async def fetch_site_rtos(client: httpx.AsyncClient, state_code: str) -> dict[str, str]:
    """The site's RTO list for one state, already mapped onto our own
    rto_codes (see map_site_rtos). Same shape of lazy lookup as
    search_makers: a plain GET needing only the session cookie -- no CSRF,
    no CAPTCHA."""
    resp = await client.get(
        RTO_LIST_URL, params={"stateCode": _SITE_STATE_CODE_OVERRIDES.get(state_code, state_code)}
    )
    resp.raise_for_status()
    return map_site_rtos(resp.json())
