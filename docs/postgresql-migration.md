# PostgreSQL migration and rollback

The application now runs on PostgreSQL through `asyncpg`. The original
`backend/data/vahan.db` is not changed by this migration and remains the
rollback source until validation is complete.

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

## Validation gate

Before cutover, compare the source and target row counts for `registrations`,
`states`, and `oem_monthly_sales`; then check the dashboard KPIs, trend,
categories, RTO analysis, and a refresh run against PostgreSQL.

## Rollback

Keep `backend/data/vahan.db` and the last successful PostgreSQL backup. To
rollback, restore the prior application configuration with its SQLite
`DATABASE_URL`, restart the previous backend image, and do not delete the
PostgreSQL volume until validation is complete.
