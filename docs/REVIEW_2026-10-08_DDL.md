# 2026-10-08 review — proposed DDL and data re-scrape plan

**Status: PROPOSED. Nothing here has been executed.** All of it comes from the
2026-10-08 backend/DB review (`backend_db_review.md` §4–§5) and the data
reconciliation (`data_reconciliation.md` #21, #22). Every `NOT VALID →
VALIDATE` step should be preceded by a SELECT proving zero violators. Run
`CONCURRENTLY` statements outside a transaction. Each index drop should first
be proven with `BEGIN; DROP INDEX …; EXPLAIN <real queries>; ROLLBACK;`,
because `idx_scan` counters reset on restart.

Code-only fixes shipped in the same review need **no** DDL: the categories
range-split, the loose-index-scan year lists, the coverage-gap hash-distinct
rewrite and removing the kpis tautology. See §6 for what each DDL item
would add on top of them.

---

## 1. Constraints

### 1a. Tighten nullability (never-null columns; no table rewrite)
```sql
ALTER TABLE registrations ALTER COLUMN is_supplementary SET DEFAULT false;
ALTER TABLE registrations ADD CONSTRAINT nn_reg_supp  CHECK (is_supplementary IS NOT NULL) NOT VALID;
ALTER TABLE registrations ADD CONSTRAINT nn_reg_rto   CHECK (rto_code IS NOT NULL) NOT VALID;
ALTER TABLE registrations ADD CONSTRAINT nn_reg_count CHECK (count IS NOT NULL) NOT VALID;
ALTER TABLE registrations VALIDATE CONSTRAINT nn_reg_supp;   -- SHARE UPDATE EXCLUSIVE only
ALTER TABLE registrations VALIDATE CONSTRAINT nn_reg_rto;
ALTER TABLE registrations VALIDATE CONSTRAINT nn_reg_count;
ALTER TABLE registrations ALTER COLUMN is_supplementary SET NOT NULL,
                          ALTER COLUMN rto_code SET NOT NULL,
                          ALTER COLUMN count SET NOT NULL;     -- uses the validated checks, no scan
ALTER TABLE registrations DROP CONSTRAINT nn_reg_supp, DROP CONSTRAINT nn_reg_rto, DROP CONSTRAINT nn_reg_count;
```
Verified: there are 0 NULLs in each of these columns. Afterwards,
`is_supplementary IS NOT TRUE` can become `NOT is_supplementary`.

### 1b. Encode the three-pass invariant (highest value)
```sql
ALTER TABLE registrations ADD CONSTRAINT ck_reg_pass_shape CHECK (
     (NOT is_supplementary AND vehicle_class = 'All' AND fuel_type IS NULL AND maker IS NOT NULL)
  OR (is_supplementary AND maker IS NULL AND vehicle_class <> 'All' AND fuel_type IS NULL)
  OR (is_supplementary AND maker IS NULL AND vehicle_class =  'All' AND fuel_type IS NOT NULL)
) NOT VALID;
ALTER TABLE registrations VALIDATE CONSTRAINT ck_reg_pass_shape;
```
All 18.4M rows satisfy it. This would have made the 2x and 53x
double-count bug classes impossible to write. It also forbids synthetic
seed rows (`NOT supp AND class <> 'All'`), so adopt it as a deliberate
decision.

### 1c. Denormalised state names, FK-checked
```sql
ALTER TABLE states ADD CONSTRAINT uq_states_code_name UNIQUE (state_code, state_name);
ALTER TABLE registrations ADD CONSTRAINT fk_reg_state_code_name
  FOREIGN KEY (state_code, state_name) REFERENCES states (state_code, state_name) NOT VALID;
ALTER TABLE registrations VALIDATE CONSTRAINT fk_reg_state_code_name;
-- same for maker_category_totals / fuel_category_totals / maker_fuel_totals
```
`rto_name` changes over time (RTO renames), so it stays denormalised.
Longer term (P3): `maker_id int REFERENCES makers`.

### 1d. Missing FK
`maker_live_query_cache.rto_code` has no FK to `rtos`. This is
SUSPECTED intentional, because live codes can precede the rtos backfill.
Decide explicitly. If wanted, add it `NOT VALID` and then `VALIDATE`.

## 2. Columns and types

- **Dead columns:** `vehicle_model`, `norms_type` and `day` (`null_frac = 1`).
  - First remove them from the ORM model, `RegistrationOut`, the query params and the cache keys.
  - Then run:
    ```sql
    ALTER TABLE registrations DROP COLUMN vehicle_model, DROP COLUMN norms_type, DROP COLUMN day;
    ```
    It is catalogue-only (no rewrite, brief ACCESS EXCLUSIVE).
- **`recorded_at timestamp` → `timestamptz`:** this is a full rewrite, so do it only as part of §5's partition migration:
  ```sql
  ALTER TABLE registrations ALTER COLUMN recorded_at TYPE timestamptz USING recorded_at AT TIME ZONE 'UTC';
  ```

## 3. Indexes

### 3a. Natural key: replace the COALESCE-expression unique index
```sql
CREATE UNIQUE INDEX CONCURRENTLY ux_reg_natural
  ON registrations (rto_code, year, is_supplementary, month, vehicle_class, maker, fuel_type)
  INCLUDE (count) NULLS NOT DISTINCT;
-- after plan comparison on rto list/analysis and updating persist_rto_batch's ON CONFLICT target:
DROP INDEX CONCURRENTLY idx_reg_natural_key;                      -- 2,514 MB
DROP INDEX CONCURRENTLY idx_reg_rto_year_supp_month_maker_count;  -- 2,195 MB
```

### 3b. Class-pass partial index (optional, on top of the shipped range-split)
```sql
CREATE INDEX CONCURRENTLY idx_reg_classpass_y_m_cat
  ON registrations (year, month, vehicle_category)
  INCLUDE (vehicle_class, count, state_name, rto_code)
  WHERE is_supplementary AND fuel_type IS NULL;     -- 5.9M rows, the class pass only
```
Requires changing the predicate to `is_supplementary IS TRUE AND fuel_type
IS NULL` (VERIFIED equivalent). Not built, so size and timing are unknown.

### 3c. Coverage counting (makers_with_coverage_gaps)
```sql
CREATE INDEX CONCURRENTLY idx_mct_maker_year_rto ON maker_category_totals (maker, year, rto_code);
```
The shipped query rewrite (hash-distinct, then count) already removed the
14 MB external-merge sort spill: 3,973 ms → 284 ms on prod, with an
identical md5 of the result set. This index would make the count
index-only.

### 3d. Redundant index drop candidates (prove each first)
| index | size | why |
|---|---|---|
| `ix_registrations_state_code` | 122 MB | prefix of `idx_reg_state_code_year_supp` |
| `ix_registrations_month` | 122 MB | 12-value column; produced the bad kpis plan |
| `ix_registrations_vehicle_category` | 122 MB | only the `IS NULL` backfill probe uses it; replace with a partial index `WHERE vehicle_category IS NULL` |
| `ix_maker_category_totals_year`, `ix_fuel_category_totals_year`, `ix_maker_fuel_totals_year` | 21 / 6.7 / 17 MB | prefixes of `idx_m?t_year_*` composites |

`registrations` carries 8.16 GB of indexes against a 3.25 GB heap.

## 4. Rollup for the Overview family
```sql
CREATE MATERIALIZED VIEW reg_state_month_rollup AS
SELECT year, month, state_code, state_name, is_supplementary, vehicle_class,
       vehicle_category, commercial_tier, fuel_type,
       sum(count)::bigint AS total, count(*)::int AS n_rows
FROM registrations
GROUP BY year, month, state_code, state_name, is_supplementary, vehicle_class,
         vehicle_category, commercial_tier, fuel_type;          -- 461,336 rows vs 18.4M
CREATE UNIQUE INDEX ux_rsmr ON reg_state_month_rollup
  (year, month, state_code, is_supplementary, vehicle_class, vehicle_category, commercial_tier, fuel_type) NULLS NOT DISTINCT;
CREATE INDEX ix_rsmr_state_year ON reg_state_month_rollup (state_name, year, month);
-- REFRESH MATERIALIZED VIEW CONCURRENTLY reg_state_month_rollup;  after each scrape+vacuum (~60 s)
```
- Route a query to the rollup only when `maker IS NULL AND user_rto IS NULL`.
- `apply_total_filters` and `apply_fuel_group_filter` must first become model-agnostic.

## 5. Partitioning (P3)
Range-partition `registrations` by `year`, or LIST-partition by pass with
optional year sub-partitions. Do it once, together with §2's `timestamptz`
rewrite. See `backend_db_review.md` §5.2(h) for the full DDL. The
verdict is P3: the shipped query fixes give larger wins for far less risk.

## 6. Boot path: `ensure_rtos_backfilled` (53 s every boot) — DOCUMENTED ONLY
The current statement is a Parallel Seq Scan of 18.4M rows, with an
external merge sort of 257 MB, and it UPSERTs all ~1,412 `rtos` rows on
every boot. **This was not changed in this review.** The worktree test boot
runs `init_db` against the production database, and this step writes to it
(boot log: `rtos backfill: inserted/refreshed 1412 row(s)`). The brief allows
changing it only if the test boot does not write to prod.

Proposed replacement (measured at 1,760 ms by the review): a loose index
scan over `rto_code`, with a lateral pick of the latest `(year, month)`
name, that only touches rows that actually changed:
```sql
WITH RECURSIVE c AS (
  (SELECT rto_code FROM registrations WHERE rto_code IS NOT NULL ORDER BY rto_code LIMIT 1)
  UNION ALL
  SELECT (SELECT rto_code FROM registrations WHERE rto_code > c.rto_code ORDER BY rto_code LIMIT 1)
  FROM c WHERE c.rto_code IS NOT NULL)
INSERT INTO rtos (rto_code, rto_name, state_code)
SELECT c.rto_code, l.rto_name, l.state_code FROM c
CROSS JOIN LATERAL (SELECT rto_name, state_code FROM registrations r WHERE r.rto_code = c.rto_code
                    ORDER BY r.year DESC, r.month DESC LIMIT 1) l
WHERE c.rto_code IS NOT NULL
ON CONFLICT (rto_code) DO UPDATE SET rto_name = EXCLUDED.rto_name, state_code = EXCLUDED.state_code
WHERE (rtos.rto_name, rtos.state_code) IS DISTINCT FROM (EXCLUDED.rto_name, EXCLUDED.state_code);
```
Better still, move the step out of boot and run it after each successful
scrape. Also:
- Run migrations as a separate deploy step, with `lock_timeout`.
- Adopt Alembic with a baseline revision (§5.3 of the review).

---

## 7. Data re-scrape plan

Detections come from `backend/scripts/check_integrity.py` (READ-ONLY).

### Diagnostic output (run 2026-10-08, 167.9 s)
```
year | classpass_short_rto_months / rto_months | classpass_missing_units | rto_years_missing_exactly_25_makers | their_units | states
2003 | 262 / 15104 | 301970 | 0 | 0 |
2004 | 327 / 15404 | 352104 | 0 | 0 |
2005 | 599 / 15608 | 617153 | 0 | 0 |
2006 | 881 / 15760 | 899798 | 0 | 0 |
2007 | 1083 / 15837 | 1271163 | 0 | 0 |
2008 | 868 / 15985 | 1188216 | 0 | 0 |
2009 | 800 / 16096 | 1147565 | 0 | 0 |
2010 | 1256 / 16259 | 2440211 | 0 | 0 |
2011 | 1666 / 16391 | 3172975 | 0 | 0 |
2012 | 1482 / 16358 | 3346021 | 0 | 0 |
2013 | 1252 / 16339 | 2966836 | 0 | 0 |
2014 | 1030 / 16375 | 2686642 | 0 | 0 |
2015 | 1121 / 16426 | 2833522 | 0 | 0 |
2016 | 1582 / 16446 | 3488838 | 0 | 0 |
2017 | 2040 / 16476 | 5397971 | 0 | 0 |
2018 | 2228 / 16544 | 6365707 | 0 | 0 |
2019 | 2025 / 16557 | 5648738 | 22 | 132785 | HP,TN
2020 | 1210 / 16182 | 2559513 | 0 | 0 |
2021 | 793 / 16524 | 1386173 | 23 | 71971 | HP,TN
2022 | 1159 / 16573 | 3038917 | 0 | 0 |
2023 | 1300 / 16630 | 3919645 | 0 | 0 |
2024 | 1233 / 16575 | 3901426 | 0 | 0 |
2025 | 124 / 16593 | 1252 | 34 | 237763 | CG,HR,JH,MZ
2026 | 0 / 12560 | 0 | 0 | 0 |
TOTAL classpass_short_rto_months=26321 classpass_missing_units=58932356 rto_years_missing_25=79 their_units=442519
```
This matches the reconciliation evidence:
- **Class pass:** 2024 has 1,233 short RTO-months / 3,901,426 missing units; 2019 has 2,025 / 5,648,738.
- **Maker pass:** 2025 has 34 RTO-years / 237,763 units (CG 27, HR 5, JH 1, MZ 1); 2019 has 22 / 132,785; 2021 has 23 / 71,971.

The tiny drift from `dq/classpass_trunc.txt` (a few RTO-months in 2003–2016)
comes from the RTO-month denominator: the script counts only RTO-months
with a positive maker total.

### 7a. Class-pass truncation (2003–2024; priority 2017–2024)
**Cause:** the vehicle_class pass was scraped with the old 25-row AJAX
paginator, which dropped the first alphabetical pages. Only the tail of the
class list survived; for example, 1,837 of 2,025 short months in 2019 have no
M-CYCLE/SCOOTER row. These years were never re-scraped with the validated
xlsx export (`_validate_export`: S.No contiguity plus per-row totals).

**Impact:**
- `/categories/` totals, shares and YoY for 2003–2024 are understated. For example, the 2W 2024 class pass is 16.77M against 19.49M in mct (−14%).
- The 2025 category YoY is inflated (+25.3% shown vs ~+7–8% true).

**Plan:**
1. Work list: the RTO-years with ≥1 short RTO-month (the detection above, grouped by `rto_code, year`).
   - The re-scrape granularity is RTO-year (one export covers all 12 months).
   - Order: 2024 → 2017 (largest user-visible error), then 2016 → 2003.
2. Run `python -m scraper.run_full_scrape --dimension vehicle_class --year <Y> --force`. This is the xlsx path, which validates every export, plus the new per-RTO retry with backoff.
   - **Gap:** `run_full_scrape` has no per-RTO work-list flag today, so `--force` re-scrapes every RTO of the year. Add a small `--rtos <file>` filter before the backfill to scrape only the detected RTO-years.
   - Run it off-peak at `--concurrent-states 2`.
   - Budget: ~5–6 requests per RTO-year; 2017–2024 is roughly 8 × ~1,400 RTOs ≈ 60–70k requests. Spread it over several nights.
3. After each year:
   - Re-run `scripts/check_integrity.py --from-year Y --to-year Y`. Expect `classpass_short_rto_months ≈ 0`; the residuals should be genuine zero-class months.
   - Re-run the scrape quality check. The response caches are cleared automatically after a successful scrape.
4. Until the backfill lands, suppress category YoY when either year's class/maker ratio is below 0.98 (reconciliation #16).
5. Add the per-RTO-month class-pass vs maker-pass check to `scrape_quality_log`, so a regression is visible the next day.

### 7b. Maker pass missing exactly 25 makers (79 RTO-years: 2019, 2021, 2025)
**Cause:** one dropped 25-row page (`PAGE_SIZE` fingerprint) in the
canonical maker pass. `maker_category_totals` (the crosstab) still holds
those makers. For example, CG6 2025 has no HERO, BAJAJ or HONDA rows in
`registrations`. Chhattisgarh 2025 is understated by 27.9%: 532,877 vs
739,033.

**Plan:**
1. Work list: RTO-years where the distinct-maker count in mct minus the count in the maker pass equals 25. That is 34 in 2025, 22 in 2019 and 23 in 2021, in states CG, HR, JH, MZ, HP and TN.
2. Re-scrape the maker dimension for exactly those RTO-years:
   ```
   run_full_scrape --dimension maker --year <Y> --force
   ```
   - It needs the same `--rtos <file>` filter as 7a; without it, `--force` re-scrapes the whole year.
   - Persistence deletes and re-inserts per RTO and commits per RTO, so this is safe to resume.
3. Verify: `check_integrity.py` should show `rto_years_missing_exactly_25_makers = 0`, and the state totals for CG 2025 should be within ±0.1% of smct (739,033).
4. Add the "distinct-maker diff = 25" query to the nightly check or CI so this signature cannot recur silently.

### 7c. Prerequisites and safety
- **Scheduler:** it is now data-age based. A production boot with `SCRAPE_CATCHUP_ON_BOOT=true` starts an overdue current-year scrape. Schedule the backfill windows so they do not overlap it; the advisory locks fail fast if they do.
- **Synthetic purge:** an empty RTO no longer counts as a success, so a state with empty RTOs is never purged and the run reports itself as `partial`.
- **Skip-list:** RTOs that keep returning 500 (31 RTOs) can be skipped with `SCRAPER_SKIP_AFTER_FAILED_RUNS=N`, which is off by default. Do not enable it during the backfill.
