"""Export a trimmed, self-contained SQL seed dump for a fresh client install.

Full production data is ~13M registration rows (~1.4GB uncompressed) -- far
too large to ship in the git repo or a zip download. This exports the full
schema (compiled from SQLAlchemy metadata, not a live pg_dump snapshot, so it
always matches the current models regardless of which pg_dump/server version
made the source -- pg_dump's own version-tagged binary format is what broke
across a Postgres 18 -> 16 restore during manual testing) plus every row of
the small reference tables, but only the most recent `--years` years of
`registrations` -- enough for the dashboard's YoY comparisons and RTO
analysis to show real, meaningful data on a client's first
`docker compose up`, without shipping the full multi-year history.

Output is a single gzipped plain-SQL file that PostgreSQL's own Docker image
auto-runs from /docker-entrypoint-initdb.d the first time it starts against
an empty data volume -- see docker/docker-compose.yml and docker/seed/.

Usage: python -m app.scripts.export_seed_data --years 3 --out ../docker/seed/seed.sql.gz
"""
import argparse
import asyncio
import gzip
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.schema import CreateIndex, CreateTable

from app.core.config import settings
from app.core.database import Base
from app.models import models  # noqa: F401 - register ORM tables on Base.metadata

TABLE_ORDER = (
    "zones",
    "states",
    "districts",
    "rtos",
    "rto_districts",
    "registrations",
    "dashboard_summary",
    "oem_monthly_sales",
    # These crosstabs were never added here, so every seed export to date
    # shipped them empty -- a freshly-seeded machine had working Registration
    # data but a blank Maker/Fuel x Category panel until it ran its own
    # scrape. Year-only (no month column), much smaller than registrations.
    "maker_category_totals",
    "fuel_category_totals",
    "maker_fuel_totals",
)


def _tables_sql() -> str:
    dialect = postgresql.dialect()
    statements = []
    for table_name in TABLE_ORDER:
        table = Base.metadata.tables[table_name]
        # DROP first: this file previously assumed a truly empty database
        # (true only on someone's very first run). Reloading a seed the
        # obvious way -- TRUNCATE the tables, then re-run setup -- leaves
        # the tables themselves in place, so a bare CREATE TABLE fails with
        # "relation already exists" (hit live: a user following exactly
        # that reload path). CASCADE handles FK dependents regardless of
        # drop order; whatever it cascades away, this same loop recreates
        # later in TABLE_ORDER anyway.
        statements.append(f"DROP TABLE IF EXISTS {table_name} CASCADE;")
        statements.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";")
    return "\n".join(statements)


def _indexes_sql() -> str:
    # Created after COPY, not alongside each CREATE TABLE: building ~13
    # indexes while inserting 13M rows (maintaining every index per row)
    # measured well over a minute; building them once against the fully
    # loaded table is a bulk operation and takes seconds. Same ordering
    # migrate_sqlite_to_postgres.py already uses for the same reason.
    dialect = postgresql.dialect()
    statements = []
    for table_name in TABLE_ORDER:
        table = Base.metadata.tables[table_name]
        for index in table.indexes:
            statements.append(str(CreateIndex(index).compile(dialect=dialect)).strip() + ";")
    return "\n".join(statements)


async def _copy_table(conn, out, table_name: str, min_year: int | None) -> int:
    query = f"SELECT * FROM {table_name}"
    if min_year is not None:
        query += f" WHERE year >= {min_year}"
    out.write(f"COPY {table_name} FROM stdin;\n".encode())
    status = await conn.copy_from_query(query, output=out, format="text")
    out.write(b"\\.\n\n")
    return int(status.split()[-1])


async def export_seed(output_path: Path, min_year: int) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            raw = await conn.get_raw_connection()
            asyncpg_conn = raw.driver_connection
            with gzip.open(output_path, "wb") as out:
                out.write(
                    f"-- Vahan Dashboard seed data, generated {datetime.now(timezone.utc).isoformat()}\n"
                    f"-- registrations trimmed to year >= {min_year}; all other tables in full.\n\n".encode()
                )
                out.write(_tables_sql().encode())
                out.write(b"\n\n")
                for table_name in TABLE_ORDER:
                    filter_year = min_year if table_name == "registrations" else None
                    copied = await _copy_table(asyncpg_conn, out, table_name, filter_year)
                    print(f"{table_name}: {copied:,} rows", flush=True)
                out.write(_indexes_sql().encode())
                out.write(b"\n\n")
                # Per-table, not a blanket ANALYZE; -- that would also hit
                # every system catalog, which a non-superuser role (the
                # normal case for a client's own Postgres install) can't
                # analyze, spamming harmless-but-alarming permission-denied
                # warnings on every fresh load.
                for table_name in TABLE_ORDER:
                    out.write(f"ANALYZE {table_name};\n".encode())
        size_mb = output_path.stat().st_size / (1024 * 1024)
        print(f"Wrote {output_path} ({size_mb:.1f} MB)")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=int, default=3, help="How many most-recent years of registrations to include")
    parser.add_argument("--out", type=Path, default=Path("../docker/seed/seed.sql.gz"))
    args = parser.parse_args()
    current_year = datetime.now(timezone.utc).year
    asyncio.run(export_seed(args.out, current_year - args.years + 1))
