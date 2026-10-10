# Scheduled analytics-site refresh

The state x month x category crosstabs from analytics.parivahan.gov.in
(`state_month_category_totals`, and the per-fuel `state_month_category_fuel_totals`)
are now refreshed by the app's own scheduler, next to the old-site 5h loop.

## What runs

- `scraper/scheduler.py: run_analytics_scheduler_loop`, started in `app/main.py`'s lifespan
  when `ENABLE_ANALYTICS_SCRAPER` is true (the default) and cancelled on shutdown.
- Each run launches `python -m scraper.run_analytics_refresh` as a child process.
  Tesseract runs through asyncio subprocesses, which uvicorn's Windows loop can't create.
- Years per run: always the current year. During the first `ANALYTICS_PREVIOUS_YEAR_WINDOW_DAYS`
  (10) days of a month, and for all of January, the previous year runs too.
- Per year, every state is fetched once unfiltered and once per fuel (34 fuels):
  36 x 35 = 1,260 combos.
- There is no resume-by-natural-key. Every combo is fetched on every run, so the partial
  month gets refreshed.

## How data is written

- Writes upsert in place (`ON CONFLICT` on the natural key).
- A scope's stored rows are left untouched in any of these cases:
  - the fetch fails;
  - the table fails the parser's integrity checks (row totals, footer sums, month sequence);
  - it names a category outside the 17-category axis;
  - it would shrink the stored scope (year total down more than 2%, or a month holding
    50+ units comes back empty).
- A cell missing from a fresh fetch that passed every check is deleted (the site revised it
  to zero).
- Every failed or rejected combo is retried once with a fresh session. If it still fails, it
  is listed in the run summary.
- The hand-run runners (`run_analytics_scrape.py`, `run_analytics_fuel_scrape.py`) no longer
  resume the current year either.

## Reconciliation

After each run, every touched state-year is compared over its complete months:

- smct vs smcft;
- smct vs the old site's canonical `registrations` total.

Anything more than 1% off is logged at WARNING and listed in the summary. The partial month
is reported separately and never flagged. Run the same check by hand, read-only:
`python scripts/analytics_reconcile.py --year 2026`.

## Where to look

- **Summary file:** `SCRAPER_DATA_DIR/analytics_refresh_last.json`, which holds:
  - combos, requests and duration;
  - failures with reasons;
  - the reconciliation table.
- **`GET /api/v1/refresh/source-health`** (admin) includes an `analytics_scraper` entry with
  `ok`, `detail` and a `last_run` brief (failures, flagged state-years). When tesseract is
  missing, the entry is `ok: false` and the header pill shows it.

## Scheduling

- The first run after boot is `interval - age of the last summary`, with a floor of 15 min.
  It is gated by `SCRAPE_CATCHUP_ON_BOOT` like the old loop: when that is off, the first run
  waits the full interval.
- If no summary exists yet, the run is treated as overdue.
- **Busy shared lock:** the loop logs `Scheduled analytics refresh skipped (another scrape
  running)` and retries in 30 min, with no backoff.
- **Failures** back off exponentially, capped at 4 days.
- **Tesseract missing:** logged once at ERROR (`ANALYTICS SCRAPER DISABLED`), marks
  `analytics_scraper` unhealthy, backs off, and never crashes the app.

## Settings

| setting | default |
|---|---|
| `ENABLE_ANALYTICS_SCRAPER` | `true` |
| `ANALYTICS_REFRESH_INTERVAL_HOURS` | `24` |
| `ANALYTICS_PREVIOUS_YEAR_WINDOW_DAYS` | `10` |
| `ANALYTICS_SCRAPER_CONCURRENT` | `6` (max 6) |

## Manual run

`python -m scraper.run_analytics_refresh [--year Y ...] [--states A,B] [--wait-for-lock]`

Exit codes:

| code | meaning |
|---|---|
| 0 | done |
| 3 | done, but some combos were not refreshed |
| 4 | busy |
| 5 | tesseract unavailable |
