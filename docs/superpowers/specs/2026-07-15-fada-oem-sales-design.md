# FADA OEM Monthly Sales Ingestion — Design Spec

Date: 2026-07-15
Status: Approved by user ("yes go with A, write up the spec")

## 1. Problem

VAHAN4 (the existing scraper's source) structurally cannot answer "which company
sells which vehicle in what quantity": its Y-axis pivot only offers Vehicle Category,
Vehicle Class, Norms, Fuel, Maker, State (confirmed live against
`vahan.parivahan.gov.in/vahan4dashboard` — no Model dimension exists). A user-supplied
reference screenshot showing neighborhood + maker + model-level monthly data turned out
to come from a login-gated dealer/RTO portal (`vahan.parivahan.gov.in/vahan/`) the user
has no credentials for — out of scope, not pursued.

This spec covers the first of three planned, independently-scoped data-source
additions (SIAM, FADA, OEM investor-relations press releases) to get real maker-wise
sales quantities onto the dashboard. **FADA is built first**: during reconnaissance it
turned out to be the strongest public source — better than SIAM, which was the
original pick.

## 2. Scope decisions (confirmed with user)

| Question | Decision |
|---|---|
| Which source first | FADA (not SIAM — SIAM's public data is industry-wide totals only, no maker breakdown; confirmed live against siam.in's press-release archive back to 2004) |
| Granularity | Monthly, maker-wise, across every FADA-tracked category (Two-Wheeler, Three-Wheeler, Commercial Vehicle, PV, Tractor, Construction Equipment) |
| Storage | Same `vahan.db` SQLite file, new table(s) — not a separate DB/service |
| Frontend | New dashboard page (like Overview/Categories/YoY), not just an API with no UI |
| Backfill depth | FADA's full public archive happens to span ~5 years (Aug 2021–present), matching the user's original "3-5 years" preference — take all of it |
| Model-level names (Swift, Activa, etc.) | Explicitly out of scope for FADA — FADA's public releases are maker-level only. Deferred to the OEM investor-relations sub-project (later, separate spec) |

## 3. Source facts (confirmed via direct reconnaissance, not assumed)

- Archive: `fada.in/press-release-list.php?page=1..5` (page 6+ confirmed empty — 5 pages
  is the real end). Mixes "Vehicle Retail Data" releases with unrelated press releases
  (events, conferences) — must filter by title, not treat every entry as data.
- Titles are inconsistent across years: `"FADA Releases June 2026 Vehicle Retail Data"`,
  `"FADA releases FY 2026 and March 2026 Vehicle Retail Data"`,
  `"FADA Releases October'22 & 42 Days Festive Period Vehicle Retail Data"`. A tolerant
  parser is required — see Section 5.
- Each release is a PDF with per-category "Annexure" tables titled e.g.
  `"Two-Wheeler OEM"`, headed by columns like `Jun'26 | Market Share (%) Jun'26 | Jun'25
  | Market Share (%) Jun'25`. `pdfplumber.extract_tables()` parses these cleanly with
  zero cleanup needed (verified against the June 2026 PDF: 13 pages, one clean table per
  category page). Example extracted row:
  `['HERO MOTOCORP LTD', '4,72,144', '25.82%', '4,01,803', '26.64%']`.
- The category set is not fixed — releases add/drop categories over time (e.g. EV rows
  appearing in later years). The design must not hardcode a category enum.
- Every category table ends with a `Total` row and (for some categories) an
  `"Others Including EV"` catch-all row — neither is a real maker and must be excluded
  from maker-level data.
- PDF filenames have random hex hash prefixes (e.g. `16a4b2243edbfbFADA Releases...pdf`)
  — not derivable from year/month, must be discovered from the archive listing's
  Download links each time.

## 4. Data Model

One new table, `oem_monthly_sales`, added to `backend/app/models/models.py`:

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | autoincrement |
| `source` | String | `"FADA"` for now; SIAM's category-only totals fit the same shape later with `maker=NULL` — no schema change needed to add SIAM as a second `source` value |
| `year` | Integer | parsed from the table's own column header (e.g. `Jun'26`), **not** from the release title — the title is only used to find the release, the header text is the authoritative period since combined releases (FY-total + single-month) carry both in one PDF |
| `month` | Integer, nullable | null for FY-total or multi-month-labeled columns that don't resolve to one calendar month (e.g. "42-Days Festive") — those columns are skipped, not stored, see Section 5 |
| `category` | String | literal text as FADA labels it (`"Two-Wheeler"`, `"PV"`, etc.) — no enum, tolerates FADA renaming/adding categories |
| `maker` | String | OEM name, as-is from the PDF (already consistent with existing `Registration.maker` naming style — e.g. `"HERO MOTOCORP LTD"` matches format already in the DB) |
| `count` | Integer | registrations for that maker/category/period |
| `share_percent` | Float, nullable | FADA's reported market share for that row |
| `source_document` | String | the press release title, for traceability back to the source PDF |
| `scraped_at` | DateTime | default now() |

Composite index / idempotency key: `(source, year, month, category, maker)`. Ingestion
is delete-then-insert scoped to `(source, year, month, category)` before writing new
rows for that scope — the exact pattern `persist_rto_batch` already uses in
`scraper_service.py`, reused here rather than invented fresh.

## 5. Scraper (`backend/scraper/fada_scraper.py`, new module)

Three functions, each independently testable:

1. **`discover_releases(client) -> list[{title, pdf_url}]`**: paginate
   `press-release-list.php?page=N` starting at 1, stop when a page returns zero `<h3>`
   entries (confirmed empty at page 6). Filter titles containing `"Vehicle Retail
   Data"` (case-insensitive). Return title + resolved absolute PDF URL for each match.
2. **`parse_release_pdf(pdf_bytes) -> list[dict]`**: open with `pdfplumber`, for each
   page look for a category header line (regex: a line ending in `" OEM"`, e.g.
   `"Two-Wheeler OEM"`) to name the category, then `extract_tables()` on that page.
   For each row: skip if the first cell case-insensitively matches `"Total"` or starts
   with `"Others"`. Parse the column headers (`Jun'26`, `Jun'25`, etc.) into
   `(month, year)` pairs using a small month-abbreviation map already available in
   `scraper/parsing.py` (`MONTH_ABBR`, reused, not reimplemented). A header that doesn't
   match `<Mon>'<YY>` (e.g. `"42-Days Festive Period"`) is logged and skipped — that
   column's numbers are not stored, the rest of the table still is. Parse counts via the
   existing `parse_count` helper in `scraper/parsing.py` (already strips Indian-style
   comma grouping, e.g. `"4,72,144"` — reused, not reimplemented).
3. **`persist_oem_sales(db, rows)`**: delete-then-insert scoped to
   `(source, year, month, category)` per the rows being written, mirroring
   `persist_rto_batch`.

**Backfill script** (`backend/scraper/backfill_fada.py`, new, mirrors
`backfill_all_years.py`'s shape): call `discover_releases`, iterate all matches oldest
to newest, download + parse + persist each, 2-3s delay between requests (matches the
existing scraper's politeness convention), log + skip (don't abort the whole run) on
any single release's parse failure — schema drift in a five-year-old PDF is expected,
not exceptional.

**Ongoing updates**: FADA publishes monthly, not continuously — no need for the VAHAN
scraper's hourly-scale scheduling. Add a second background loop, started from the same
FastAPI lifespan hook as `run_scheduler_loop()` (`backend/app/main.py`), running on its
own 24h interval (not folded into `run_scheduler_loop`'s 5h VAHAN cadence — different
source, different cadence, no reason to couple them). Each tick calls
`discover_releases`, diffs titles against `source_document`s already present in
`oem_monthly_sales`, and only fetches+parses genuinely new releases. Cheap because
`discover_releases` is just one HTML page fetch per archive page, not a scrape.

## 6. Error handling / edge cases

- **Combined-period releases** (FY-total + single month in one PDF): both period's
  columns get parsed and stored as separate rows differentiated by `year`/`month` —
  no special-casing needed since period comes from the column header, not the title.
- **Unparseable column header** (festive/multi-day labels): skip that column, keep
  parsing the rest of the table. Log what was skipped so gaps are visible, not silent.
- **`Total` / `"Others Including EV"` rows**: excluded at parse time — never enter the
  table, so no cleanup filter needed downstream in queries.
- **PDF template drift** (a whole release doesn't match the expected category-header
  pattern at all): catch, log which release title failed, continue to the next release
  — matches the existing scraper's per-RTO try/except convention, applied per-release
  here instead of per-RTO.
- **Re-running the backfill**: safe — delete-then-insert per `(source, year, month,
  category)` means re-running never duplicates rows.

## 7. Testing (ponytail: one runnable check per non-trivial piece, no framework)

- `backend/tests/test_fada_scraper.py`, using the already-downloaded June 2026 PDF
  (`fada_june2026.pdf`, moved into a test fixtures dir) as real fixture data —
  not a synthetic mock, since the whole risk here is template-shape surprises a mock
  would hide:
  - `parse_release_pdf` on that fixture returns the exact Two-Wheeler row already
    verified by hand (`HERO MOTOCORP LTD`, `472144`, `25.82`, prior-year `401803`).
  - `Total` and `"Others Including EV"` rows are absent from the parsed output.
  - A title-parsing unit test covering the known irregular formats collected during
    recon (`"FADA releases FY 2026 and March 2026 Vehicle Retail Data"`, etc.) each
    correctly identified as a real release (not silently dropped).
  - `persist_oem_sales` called twice with the same rows produces no duplicates
    (idempotency).

## 8. API + Frontend (lighter detail — refined further at plan time)

- New endpoints under a new `backend/app/api/v1/endpoints/oem_sales.py`:
  `GET /oem-sales/categories` (distinct categories available), `GET
  /oem-sales/monthly?category=&year=&month=` (maker-wise breakdown for a period,
  mirrors `categories.get_top_makers`'s response shape), `GET
  /oem-sales/trend?maker=&category=` (month-over-month trend for one maker).
- New frontend page, "Industry Sales" (nav entry alongside Overview/Categories/YoY/
  Makers & Models): category selector, maker leaderboard bar chart (reusing existing
  `TruncatedYAxisTick`/`useChartTheme` patterns already in the codebase), trend line
  chart per selected maker.

## 9. Build order

1. Data model + migration (Section 4)
2. Scraper module + backfill script (Section 5), with tests (Section 7) before wiring
   into the scheduler
3. Scheduler integration (Section 5, ongoing updates)
4. API endpoints (Section 8)
5. Frontend page (Section 8)
