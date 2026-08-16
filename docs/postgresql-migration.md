# PostgreSQL migration and rollback

The application now runs on PostgreSQL through `asyncpg`. The original
`backend/data/vahan.db` is not changed by this migration and remains the
rollback source until validation is complete.

## Fresh install (client machine, `docker compose up`)

`docker/seed/seed.sql.gz` is a real snapshot of the production data
(currently the full `registrations` history), committed to the repo.
Postgres's own Docker image auto-runs every `.sql`/`.sql.gz`/`.sh` file
under `/docker-entrypoint-initdb.d` -- mounted from `docker/seed/` -- the
very first time it starts against an empty volume, so a client's first
`docker compose up` gets a populated dashboard immediately instead of an
empty one. See `backend/app/scripts/export_seed_data.py` for how it's
generated (data first, indexes after -- building ~13 indexes while
inserting 13M rows measured well over a minute; building them once against
the loaded table takes seconds).

Regenerate it after any `models.py` schema change, or periodically to keep
the shipped snapshot current:

```bash
cd backend
python -m app.scripts.export_seed_data --years 20 --out ../docker/seed/seed.sql.gz
```

If the seed load is interrupted partway (observed once during manual
testing, caused by a host Docker Desktop crash mid-run) the data lands but
indexes/ANALYZE may not finish -- and a retry won't re-run
docker-entrypoint-initdb.d against a non-empty volume. `init_db()` (called
on every backend startup, not just once) self-heals this automatically via
`ensure_indexes`/`ensure_analyzed` in `app/core/migrations.py`, so simply
restarting the `backend` container fixes it without touching the volume.

## Local development

1. Start PostgreSQL with Docker Compose:

   ```bash
   docker compose -f docker/docker-compose.yml up --build
   ```

2. The backend receives its connection URL from `DATABASE_URL`. For a local
   non-Docker PostgreSQL instance, use:

   ```text
   postgresql+asyncpg://vahan:vahan@127.0.0.1:5432/vahan
   ```

## Import the existing SQLite data

1. Stop the backend so the SQLite file is no longer being read or written.
2. Back up `backend/data/vahan.db`.
3. Start an empty PostgreSQL target.
4. From `backend/`, run:

   ```bash
   python -m app.scripts.migrate_sqlite_to_postgres --source data/vahan.db
   ```

The importer copies every supported table in 2,000-row batches and compares
each copied count with the SQLite source. It refuses a non-empty target. Use
`--replace` only when intentionally replacing all target data.

A bulk COPY leaves the query planner's statistics at 0 rows until something
runs `ANALYZE` -- measured 5-8x slower KPI/trend/category queries with stale
statistics than after. `init_db()`'s `ensure_analyzed` catches this
automatically on the next backend startup, but running `ANALYZE;` by hand
right after a manual migration avoids that one slow window.

## Validation gate

Before cutover, compare the source and target row counts for `registrations`,
`states`, and `oem_monthly_sales`; then check the dashboard KPIs, trend,
categories, RTO analysis, and a refresh run against PostgreSQL.

## Rollback

Keep `backend/data/vahan.db` and the last successful PostgreSQL backup. To
rollback, restore the prior application configuration with its SQLite
`DATABASE_URL`, restart the previous backend image, and do not delete the
PostgreSQL volume until validation is complete.
