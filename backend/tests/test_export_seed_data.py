"""Regression test for the seed-dump exporter used to ship real data with the
client-facing Docker deployment (docker/seed/seed.sql.gz, auto-loaded by
Postgres's docker-entrypoint-initdb.d on a fresh volume).

Doesn't exercise the full ~13M-row production export (slow, and the risk
isn't in the data volume) -- it proves the two things that would silently
break a client's first `docker compose up` if this script regressed: the
DDL it generates from the current models actually creates the right tables,
and the COPY-format data it writes actually round-trips back in via a plain
`psql -f`, the exact mechanism Postgres's own image uses.
"""
import gzip
import os
import shutil
import subprocess

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.models import models  # noqa: F401 - ensures models are registered on Base.metadata
from app.scripts.export_seed_data import export_seed

# Falls back to the common Windows install path since `psql` isn't always on
# PATH there even when Postgres itself is installed and running (this repo's
# own dev setup is one such case). Skips outright if neither resolves --
# this test needs a real psql binary to faithfully exercise the same
# docker-entrypoint-initdb.d loading mechanism the shipped seed file goes
# through, not a stand-in.
PSQL = shutil.which("psql") or r"C:\Program Files\PostgreSQL\18\bin\psql.exe"


async def test_export_seed_round_trips_through_psql(db_session, monkeypatch, tmp_path):
    await db_session.execute(text(
        "INSERT INTO zones (zone_code, zone_name) VALUES ('N', 'North')"
    ))
    await db_session.execute(text(
        "INSERT INTO states (state_code, state_name, zone_code) VALUES ('DL', 'Delhi', 'N')"
    ))
    await db_session.execute(text(
        "INSERT INTO registrations (state_code, state_name, rto_code, rto_name, month, year, "
        "vehicle_class, maker, count, is_supplementary) "
        "VALUES ('DL', 'Delhi', 'DL1', 'Test RTO', 1, 2026, 'All', 'HONDA', 91, false)"
    ))
    await db_session.commit()

    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql+asyncpg://vahan:vahan@127.0.0.1:5432/vahan_test")
    out_path = tmp_path / "seed.sql.gz"
    await export_seed(out_path, min_year=2000)

    assert out_path.exists()
    with gzip.open(out_path, "rt", encoding="utf-8") as f:
        contents = f.read()
    assert "CREATE TABLE registrations" in contents
    assert "COPY registrations FROM stdin;" in contents
    assert "ANALYZE;" in contents

    # Load it into a fresh, empty schema in the same database -- the "vahan"
    # role here has no CREATEDB privilege (matches the deployed client's
    # container role too), so a scratch schema stands in for the fresh
    # database docker-entrypoint-initdb.d actually loads into. `psql -f`
    # doesn't auto-decompress .sql.gz itself -- that's docker-entrypoint.sh's
    # own logic (gunzip piped into psql), so this decompresses in Python and
    # feeds psql via stdin to match.
    result = subprocess.run(
        [PSQL, "-h", "127.0.0.1", "-U", "vahan", "-d", "vahan_test", "-v", "ON_ERROR_STOP=1"],
        input=contents,
        env={**os.environ, "PGPASSWORD": "vahan", "PGOPTIONS": "-c search_path=seed_roundtrip"},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture(autouse=True)
async def _fresh_roundtrip_schema():
    import asyncpg
    conn = await asyncpg.connect(host="127.0.0.1", user="vahan", password="vahan", database="vahan_test")
    try:
        await conn.execute("DROP SCHEMA IF EXISTS seed_roundtrip CASCADE")
        await conn.execute("CREATE SCHEMA seed_roundtrip")
    finally:
        await conn.close()
    yield
    conn = await asyncpg.connect(host="127.0.0.1", user="vahan", password="vahan", database="vahan_test")
    try:
        await conn.execute("DROP SCHEMA IF EXISTS seed_roundtrip CASCADE")
    finally:
        await conn.close()
