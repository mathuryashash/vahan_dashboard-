# SIAM Wholesale Sales Ingestion — Design Spec

Date: 2026-07-18
Status: Approved by user (all sections confirmed during brainstorming)

## 1. Problem

FADA's "Vehicle Retail Data" (built and shipped, see
`2026-07-15-fada-oem-sales-design.md`) reports dealer-to-customer retail sales. SIAM
(Society of Indian Automobile Manufacturers) reports a genuinely different number:
OEM-to-dealer wholesale dispatches. The gap between the two is a real, industry-standard
signal (channel inventory build-up or drawdown) — this is the reason to add SIAM, not
redundant coverage of what FADA already provides.

This is the second of three planned data-source sub-projects (SIAM, FADA, OEM
investor-relations press releases). FADA shipped first because reconnaissance showed it
was the stronger source for maker-wise retail data; SIAM does not carry a maker
breakdown at all in its public releases (confirmed during FADA's own reconnaissance) —
it only reports industry-wide category totals, which is exactly the wholesale side of
the comparison this sub-project adds.

## 2. Scope decisions (confirmed with user)

| Question | Decision |
|---|---|
| Why add SIAM at all | Wholesale (SIAM) vs retail (FADA) comparison — the real, distinct signal SIAM offers, not just "more industry totals" |
| Granularity | Industry-wide category totals only (Passenger Vehicles, Two Wheelers, Three Wheelers, etc.) — no maker breakdown; SIAM's public releases don't carry one |
| Source(s) to scrape | Both: the static "Domestic Sales Trends" HTML table (structured, primary) and the monthly "Auto Industry Performance" press release (narrative, commentary + fallback) |
| Press-release role | Both: always store its narrative text as commentary, AND parse numeric figures from it as a fallback for any (year, month, category) missing from the table |
| Backfill depth | Full public archive back to 2004 |
| Storage | Same `vahan.db`, reuse `oem_monthly_sales` (see Section 4) — no new numeric table |
| Frontend placement | Extend the existing Industry Sales page (built for FADA) with a new "Wholesale vs Retail" comparison section, rather than a standalone page |

## 3. Source facts (confirmed via reconnaissance during the FADA sub-project)

- `siam.in` publishes a static "Automobile Domestic Sales Trends" page with month-by-month
  category totals in plain HTML tables, and separate monthly "Auto Industry Performance"
  press releases containing narrative commentary with figures embedded in prose.
- Both are public, no login required (unlike the out-of-scope Parivahan dealer portal).
- True maker-wise SIAM data is paywalled behind a "Subscription Based Report" — confirmed
  out of reach, consistent with Section 2's scope decision to never attempt maker-level
  SIAM data.
- The archive spans back to 2004. Over 20+ years, table markup and release template
  format have almost certainly changed at least once (site redesigns, column reordering,
  category renames/splits) — this must be tolerated, not assumed away. Exact historical
  format variants are not known ahead of implementation time and should be confirmed by
  direct reconnaissance during planning, the same way FADA's title-format irregularities
  were discovered by inspecting real archive pages rather than assumed.
- SIAM's category vocabulary differs from FADA's (e.g. SIAM's "Passenger Vehicles" vs
  FADA's "PV") — no attempt is made to auto-map one to the other; see Section 8.

## 4. Data Model

**Reuse `oem_monthly_sales`** (from the FADA sub-project) for SIAM's numeric rows —
its `source` column and `maker` nullability were already designed for exactly this:

| Column | SIAM row value |
|---|---|
| `source` | `"SIAM"` |
| `year` / `month` | parsed period; `month` is never null for SIAM (unlike FADA, SIAM's public archive doesn't publish FY-total-only columns) |
| `category` | literal SIAM segment text (`"Passenger Vehicles"`, `"Two Wheelers"`, etc.) — no enum, same reasoning as FADA's `category` column |
| `maker` | always `NULL` — SIAM's public data has no maker breakdown |
| `count` | the segment's wholesale dispatch total for that period |
| `share_percent` | `NULL` — SIAM's domestic sales trends table doesn't report a share figure the way FADA's OEM annexure does |
| `source_document` | which source produced the row: the domestic-sales-trends page URL/date, or the specific press release title, for traceability |

One new table, `siam_monthly_commentary`, for the narrative text (a fundamentally
different shape — one row of prose per month, not per category):

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | autoincrement |
| `year` | Integer | |
| `month` | Integer | |
| `text` | Text | the release's narrative commentary, verbatim |
| `source_document` | String | press release title/URL, for traceability |
| `scraped_at` | DateTime | default now() |

Idempotency: `oem_monthly_sales` rows keep the existing `(source, year, month,
category)` delete-then-insert scope from the FADA sub-project — no change needed.
`siam_monthly_commentary` uses `(year, month)` as its own delete-then-insert scope.

## 5. Scraper (`backend/scraper/siam_scraper.py`, new module)

Two independent parse functions, plus one persistence function that reconciles them:

1. **`parse_domestic_sales_trends_table(html) -> list[dict]`**: parses the static HTML
   table into `{category, year, month, count}` rows. Authoritative — always wins over
   the press release's fallback figures when both cover the same period.
2. **`parse_press_release(html_or_pdf) -> {"text": str, "figures": list[dict]}`**:
   extracts the narrative commentary in full (stored verbatim, no cleanup), and
   best-effort parses any category figures embeddable in prose into the same
   `{category, year, month, count}` shape as the table parser. A release with no
   parseable figures still yields its `text` — commentary storage never depends on
   fallback-parsing succeeding.
3. **`persist_siam_sales(db, table_rows, release, *, source_document)`**:
   - Delete-then-insert `table_rows` into `oem_monthly_sales` scoped to
     `(source="SIAM", year, month, category)`, mirroring `persist_oem_sales`.
   - Always delete-then-insert `release["text"]` into `siam_monthly_commentary` scoped
     to `(year, month)`.
   - For each `(year, month, category)` in `release["figures"]` **not already present**
     in `table_rows` for that same scrape, insert it into `oem_monthly_sales` too
     (`source="SIAM"`, `maker=NULL`) — this is the fallback path. The API layer then
     never needs to know whether a given row came from the table or a release; both
     look identical downstream.

**Backfill script** (`backend/scraper/backfill_siam.py`, new, mirrors
`backfill_fada.py`'s shape): fetch the domestic-sales-trends page(s) and iterate the
full press-release archive back to 2004, parsing and persisting each period. Per-period
try/except (see Section 6) — a single year's format surprise must not abort 20 years of
backfill. Logs a per-year summary (periods found / parsed / skipped) so historical gaps
are visible without combing per-line logs.

**Ongoing updates**: SIAM publishes monthly, same cadence class as FADA. Add a third
background loop (`run_siam_scheduler_loop`), same 24h-interval pattern as
`run_fada_scheduler_loop`, started from the same FastAPI lifespan hook. Per-release
try/except inside the loop (matching the fix already applied to
`run_fada_scheduler_loop` after live-testing surfaced the all-or-nothing bug there) —
one bad release must not block every other new release behind it for 24h.

## 6. Error handling / edge cases

- **Per-period parse failure** (either the table or a given release): caught, logged,
  skipped — the rest of that scrape run continues. Same convention as FADA's
  per-release isolation, applied here per-period since a single SIAM page can span many
  months/categories in one parse call.
- **Category name drift across 20 years**: stored as literal text, not mapped to a
  canonical name — old and new segment names simply coexist as distinct rows, same
  choice already made for FADA's `category` column.
- **Table/release disagreement for the same period**: table wins, unconditionally — the
  design does not attempt to reconcile conflicting figures, only to fill genuine gaps.
- **Release has no parseable figures**: `text` is still stored; only the
  fallback-figures step is skipped for that release.
- **Table page unreachable/format completely unrecognized for an entire era**: backfill
  logs the gap in its per-year summary and moves to the next; it does not retry or
  fabricate data.

## 7. Testing

Same principle as FADA: real committed fixture files, not synthetic mocks — the actual
risk is SIAM's real template drifting, which a mock would hide.

- Fixtures (to be captured during planning via direct reconnaissance, same as FADA's
  fixtures): one real current-format "Domestic Sales Trends" HTML page, one real current
  press release.
- `parse_domestic_sales_trends_table`: extracts known category/period/count rows
  correctly from the fixture.
- `parse_press_release`: extracts commentary text; separately, extracts whatever
  figures it can find in the fixture's prose (exact expected figures determined from the
  real fixture at implementation time).
- `persist_siam_sales`: idempotency (re-running produces no duplicate rows), and the
  fallback-reconciliation behavior — a release figure for a period already covered by
  the table must NOT be inserted a second time; a release figure for a period the table
  lacks MUST be inserted.
- API tests for `category-trend` (both `source=SIAM` passthrough and `source=FADA`
  aggregation paths) and `commentary`.
- No attempt to fixture 20 years of historical format variants — impractical. The
  backfill's per-period isolation and summary logging (Section 6) is the safety net for
  historical drift, not test coverage.

## 8. API + Frontend

Extends the existing `/oem-sales` router (from the FADA sub-project) rather than adding
a parallel SIAM-specific router — it's the same underlying table.

- `GET /oem-sales/categories?source=FADA|SIAM` — extend the existing endpoint with a
  `source` filter. FADA and SIAM category vocabularies differ, so each source gets its
  own dropdown; no auto-mapping between e.g. "PV" and "Passenger Vehicles" — the user
  picks the matching pair manually (only ~5-6 categories per source, trivial to eyeball).
- `GET /oem-sales/category-trend?source=&category=` — new endpoint returning a monthly
  total series `[{year, month, count}]` for one category. For `source=SIAM`, returns
  the (already category-level) rows directly. For `source=FADA`, sums `count` across
  all makers per month (same aggregation approach as the existing FADA year-to-date
  leaderboard endpoint). One endpoint, both sources.
- `GET /oem-sales/commentary?year=&month=` — new, SIAM-only: returns that month's
  `siam_monthly_commentary` text if present, else null/empty.
- Frontend: add a "Wholesale vs Retail" section to the existing `IndustrySalesPage` —
  two category pickers (one FADA, one SIAM), one combined line chart overlaying both
  trends (reusing existing `useChartTheme`/Recharts patterns already in the page), and
  the commentary text displayed for whichever month is hovered/selected on the chart.

## 9. Build order

1. Data model: `siam_monthly_commentary` table (Section 4) — `oem_monthly_sales` needs
   no schema change.
2. Scraper module (`parse_domestic_sales_trends_table`, `parse_press_release`,
   `persist_siam_sales`), with real fixtures captured via direct reconnaissance and
   tests (Section 7) before wiring into anything else.
3. Backfill script (Section 5), run against the real 2004–present archive, spot-check
   results.
4. Scheduler integration (Section 5, ongoing updates), with per-release isolation from
   the start (not retrofitted after the fact, unlike FADA's).
5. API endpoints (Section 8).
6. Frontend "Wholesale vs Retail" section (Section 8).
