# Deploy notes: branch `fix/review-2026-10-08`

Read this before merging or restarting the production backend on this branch.

## 1. The first boot starts a FULL scrape about 60 seconds after startup

**Setting:** `SCRAPE_CATCHUP_ON_BOOT` (in `backend/app/core/config.py`; default **`True`**, kept on purpose).

**What changed.** The scheduler used to wait a fixed `REFRESH_INTERVAL_HOURS` (5 h) after each process start. Every restart reset that timer, so a server restarted more often than every 5 h never scraped. This is why the data froze on **2026-09-19**. The scheduler now measures the age of the last successful scrape from the database (`scrape_quality_log.checked_at`, falling back to `registrations.recorded_at`, read in the DB session time zone) and schedules the first run at:

```
first_run_delay = max(60 s, REFRESH_INTERVAL_HOURS - data_age)
```

**Consequence on the first deploy.** The production data is about 19 days old, so `data_age` is far beyond 5 h. **About 60 s after boot** (`BOOT_CATCHUP_MIN_DELAY_SECONDS`), the server launches a full current-year scrape. That is three concurrent OS processes (maker, vehicle_class and fuel passes) against the VAHAN site. It is the intended fix, but plan for it:

- Expect the usual load: hours of scraping, a VACUUM ANALYZE at the end, and response caches cleared afterwards.
- Do not schedule a manual backfill (`run_full_scrape --force`, see `REVIEW_2026-10-08_DDL.md` §7) at the same time. The per-(dimension, year) advisory locks make the second one fail fast instead of double-writing, but it is wasted work.
- If the source site is down, check `GET /api/v1/refresh/source-health` first. Restarts bypass the scheduler's in-memory exponential backoff, so **every restart during a source outage produces one doomed full scrape about 60 s later**.
- No data at all, or an unreadable DB, means the full interval is used. A first-ever backfill is never started by a boot.

**Turning it off.** Set `SCRAPE_CATCHUP_ON_BOOT=false` in the environment or `.env`. The first scheduled run then happens a full interval (5 h) after boot, which is the old behaviour. Use this for:

- dev, test and review servers that point at the production database (for example the worktree server on port 8021, which runs with `SCRAPE_CATCHUP_ON_BOOT=false ENABLE_FADA_SCRAPER=false`);
- a restart during a known source outage.

Booting still runs `init_db` (index check, `ensure_rtos_backfilled`). That WRITES to whatever database `DATABASE_URL` points at, whether or not catch-up is on.

## 2. `/refresh/status` partial semantics

- `status: "partial"` now means at least one state has a failed or skipped RTO, or an RTO that **had data for that year before the run and returned zero records now**.
- RTOs that were empty and never had data for the year (closed offices, catch-all codes: about 376 of 1,784 have no 2026 maker data) do not make a run partial. They are reported in the new additive field `structurally_empty_rtos: {dimension: count}`.
- The synthetic-row purge is unchanged and strict: any empty RTO blocks it.

## 3. Timestamps

`last_updated` and the scheduler's data age read the naive `recorded_at` and `checked_at` columns as `::timestamptz` in the DB session time zone. On this native install that zone is `Asia/Calcutta`. The header used to show `2026-09-19 21:01 UTC`; it now correctly shows `2026-09-19 15:31 UTC`.
