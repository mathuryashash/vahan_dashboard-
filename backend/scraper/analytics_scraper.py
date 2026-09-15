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
        # A state/year with genuinely no registrations still renders a
        # table (just all-zero cells, dropped below) -- no table at all
        # means the response shape wasn't the results page we expected
        # (e.g. a session-timeout interstitial), which would otherwise
        # persist silently as indistinguishable from real zero-data.
        logger.warning("no <table> found in response -- unexpected page shape, treating as 0 rows")
        return []

    rows = [
        [cell.get_text(strip=True) for cell in tr.find_all(["td", "th"])]
        for tr in table.find_all("tr")
    ]
    rows = [r for r in rows if r]
    if len(rows) < 2:
        return []

    header, *body_rows = rows
    categories = header[1:-1]  # header[0] is "Month", header[-1] is "Total"
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
