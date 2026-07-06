# Geo Hierarchy Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the backend a real Zone → State → District → RTO hierarchy, backed by real
public reference data (not fabricated), with API endpoints to navigate it — this is
Phase 1 of the larger drill-down initiative (see
`docs/superpowers/specs/2026-07-06-geo-drilldown-design.md`). Phases 2-5 (live scraper,
drill-down aggregation, frontend map, model/EV views) are separate plans written after
this one ships, per that spec's Section 9 build order.

**Architecture:** Add `Zone` and `District` SQLAlchemy models plus an `rto_districts`
join table (one RTO can legitimately serve multiple districts — confirmed from real
data, see Task 3). Extend `State` with a `zone_code` column. Since the existing SQLite
DB already has data and `init_db()` only creates missing tables (it won't alter existing
ones), add a small idempotent column-migration helper. Seed zones/districts/RTOs from a
real public RTO registry dataset (already downloaded to
`backend/data/reference/RTO.csv`, 1093 real RTOs) plus a hardcoded, verified India Zonal
Council mapping — not invented data. Expose the hierarchy via a new `geo` endpoint
module following the existing `states.py` pattern.

**Tech Stack:** FastAPI, SQLAlchemy (async, Column-style declarative — matches existing
`models.py`), aiosqlite, pytest + pytest-asyncio (new — no test framework exists yet).

---

## Known data caveats (read before Task 3)

- `backend/data/reference/RTO.csv` (source:
  `github.com/kishorek/India-Codes/blob/master/csv/RTO.csv`) has 1093 real RTOs but is
  somewhat dated: **no Telangana (TS) RTOs** (Telangana split from Andhra Pradesh in
  2014, after this data's vintage — its RTOs are still numbered under old AP-era
  conventions in some records) and **no Ladakh (LA) RTOs** (Ladakh became a UT in 2019).
  These states will seed with zero districts/RTOs for now; the Task 2 (Phase 2, live
  scraper) plan will backfill them from the live site's own RTO dropdown, which is the
  more authoritative source going forward anyway.
- The existing `backend/setup.sh` seeded `states` with **`LD`→`'Ladakh'` and
  `LA`→`'Lakshadweep'`, which is backwards** relative to real-world vehicle-registration
  codes (confirmed against `RTO.csv`: `LD` prefix is Lakshadweep). This plan corrects
  those two `state_name` values as part of seeding, since accurate state naming is
  required for the district/RTO data we're attaching to them. This is the only
  pre-existing data touched — everything else in `states` is left as-is.
- RTO.csv also uses a few legacy state prefixes that map onto our existing single state
  codes: `OR` → `OD` (Odisha), `UA` → `UK` (Uttarakhand, duplicate legacy prefix), `DD`
  (Daman and Diu) → `DN` (existing merged UT `"UT of DNH and DD"`).

---

## Task 1: Backend test infrastructure

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/pytest.ini`

No test framework exists in this codebase yet — this task adds the minimum needed for
every later task's TDD steps.

- [ ] **Step 1: Add test dependencies**

Modify `backend/requirements.txt`, append:

```
pytest>=8.2.0
pytest-asyncio>=0.23.7
httpx>=0.27.0
```

(`httpx` is already listed above for the app itself — keep only one entry; if it's
already present, just add the two `pytest*` lines.)

Run: `cd backend && pip install -r requirements.txt -q`
Expected: no errors.

- [ ] **Step 2: Add pytest config**

Create `backend/pytest.ini`:

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

- [ ] **Step 3: Create the async test DB fixture**

Create `backend/tests/__init__.py` (empty file).

Create `backend/tests/conftest.py`:

```python
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.database import Base
from app.main import app
from app.core.database import get_db


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def client(db_session):
    from httpx import AsyncClient, ASGITransport

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
```

- [ ] **Step 4: Verify the fixture works with a trivial test**

Create `backend/tests/test_health.py`:

```python
async def test_health_check(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
```

Run: `cd backend && python -m pytest tests/test_health.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/requirements.txt backend/pytest.ini backend/tests/
git commit -m "test: add pytest async test infrastructure"
```

---

## Task 2: Zone/District models + idempotent column migration

**Files:**
- Modify: `backend/app/models/models.py`
- Create: `backend/app/core/migrations.py`
- Modify: `backend/app/core/database.py:33-35` (`init_db`)
- Test: `backend/tests/test_migrations.py`

- [ ] **Step 1: Write the failing migration test**

Create `backend/tests/test_migrations.py`:

```python
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from app.core.migrations import ensure_columns


async def test_ensure_columns_adds_missing_column():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE states (state_code TEXT PRIMARY KEY, state_name TEXT)"))

    await ensure_columns(engine, {"states": {"zone_code": "VARCHAR(10)"}})

    async with engine.begin() as conn:
        result = await conn.execute(text("PRAGMA table_info(states)"))
        columns = {row[1] for row in result.fetchall()}
    assert "zone_code" in columns
    await engine.dispose()


async def test_ensure_columns_is_idempotent():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE states (state_code TEXT PRIMARY KEY, state_name TEXT, zone_code VARCHAR(10))"))

    # Should not raise even though the column already exists
    await ensure_columns(engine, {"states": {"zone_code": "VARCHAR(10)"}})
    await engine.dispose()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_migrations.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.migrations'`

- [ ] **Step 3: Implement `ensure_columns`**

Create `backend/app/core/migrations.py`:

```python
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def ensure_columns(engine: AsyncEngine, table_columns: dict[str, dict[str, str]]) -> None:
    """Add missing columns to existing tables. SQLite-only ALTER TABLE ADD COLUMN,
    since this project has no migration tool (Alembic) and init_db()'s create_all()
    only creates tables that don't exist yet -- it never alters existing ones."""
    async with engine.begin() as conn:
        for table_name, columns in table_columns.items():
            result = await conn.execute(text(f"PRAGMA table_info({table_name})"))
            existing = {row[1] for row in result.fetchall()}
            for column_name, column_type in columns.items():
                if column_name not in existing:
                    await conn.execute(
                        text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
                    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && python -m pytest tests/test_migrations.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Add the new models**

Modify `backend/app/models/models.py`, insert after the `RTO` class (after line 18):

```python
class Zone(Base):
    __tablename__ = "zones"

    zone_code = Column(String(10), primary_key=True)
    zone_name = Column(String(100), nullable=False)


class District(Base):
    __tablename__ = "districts"

    district_code = Column(String(50), primary_key=True)
    district_name = Column(String(200), nullable=False)
    state_code = Column(String(5), nullable=False, index=True)


class RTODistrict(Base):
    __tablename__ = "rto_districts"

    rto_code = Column(String(10), primary_key=True)
    district_code = Column(String(50), primary_key=True)
```

- [ ] **Step 6: Wire the column migration into startup**

Modify `backend/app/core/database.py`, change `init_db`:

```python
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    from app.core.migrations import ensure_columns
    await ensure_columns(engine, {"states": {"zone_code": "VARCHAR(10)"}})
```

- [ ] **Step 7: Run the full suite**

Run: `cd backend && python -m pytest -v`
Expected: PASS (3 tests: health, 2 migration tests)

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/models.py backend/app/core/migrations.py backend/app/core/database.py backend/tests/test_migrations.py
git commit -m "feat: add Zone/District models and idempotent column migration"
```

---

## Task 3: Zone mapping + RTO.csv parsing (pure functions, TDD)

**Files:**
- Create: `backend/app/scripts/__init__.py`
- Create: `backend/app/scripts/geo_reference_data.py`
- Test: `backend/tests/test_geo_reference_data.py`

This isolates the tricky parsing logic (verified against the real
`backend/data/reference/RTO.csv`, which has 1093 rows and uses **both** `/` and `,` as
delimiters within the `Place` column — confirmed by direct inspection) from the DB
upsert logic (Task 4), so it can be unit-tested without a database.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_geo_reference_data.py`:

```python
from app.scripts.geo_reference_data import (
    split_district_names,
    normalize_state_code,
    ZONE_BY_STATE_CODE,
)


def test_split_district_names_handles_slash_delimiter():
    assert split_district_names("Adilabad / Mancherial / Nirmal") == [
        "Adilabad", "Mancherial", "Nirmal",
    ]


def test_split_district_names_handles_comma_delimiter():
    assert split_district_names("Kolkata, Howrah") == ["Kolkata", "Howrah"]


def test_split_district_names_single_name():
    assert split_district_names("Kakinada") == ["Kakinada"]


def test_normalize_state_code_maps_legacy_prefixes():
    assert normalize_state_code("OR") == "OD"
    assert normalize_state_code("UA") == "UK"
    assert normalize_state_code("DD") == "DN"


def test_normalize_state_code_passes_through_known_codes():
    assert normalize_state_code("MH") == "MH"
    assert normalize_state_code("AP") == "AP"


def test_zone_mapping_covers_all_zonal_council_states():
    # Spot-check a few real Zonal Council memberships (verified via
    # mha.gov.in/en/page/zonal-council during design).
    assert ZONE_BY_STATE_CODE["DL"] == "NORTH"
    assert ZONE_BY_STATE_CODE["MH"] == "WEST"
    assert ZONE_BY_STATE_CODE["TN"] == "SOUTH"
    assert ZONE_BY_STATE_CODE["WB"] == "EAST"
    assert ZONE_BY_STATE_CODE["UP"] == "CENTRAL"
    assert ZONE_BY_STATE_CODE["AS"] == "NORTHEAST"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_geo_reference_data.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.scripts.geo_reference_data'`

- [ ] **Step 3: Implement it**

Create `backend/app/scripts/__init__.py` (empty file).

Create `backend/app/scripts/geo_reference_data.py`:

```python
import re

# Verified against mha.gov.in/en/page/zonal-council (Ministry of Home Affairs).
# Council membership is exact for the 5 official Zonal Councils + the North Eastern
# Council. States/UTs with no council membership (Andaman & Nicobar, Lakshadweep,
# Ladakh, Telangana post-formation) are assigned to the geographically/administratively
# closest zone for dashboard grouping purposes -- this is a practical extension, not an
# official council membership claim.
ZONE_BY_STATE_CODE = {
    # Northern Zonal Council
    "HR": "NORTH", "HP": "NORTH", "JK": "NORTH", "PB": "NORTH",
    "RJ": "NORTH", "DL": "NORTH", "CH": "NORTH",
    "LD": "NORTH",  # Ladakh -- extension, carved from J&K, no council yet
    # Central Zonal Council
    "CG": "CENTRAL", "UK": "CENTRAL", "UP": "CENTRAL", "MP": "CENTRAL",
    # Eastern Zonal Council
    "BR": "EAST", "JH": "EAST", "OD": "EAST", "WB": "EAST",
    # Western Zonal Council
    "GA": "WEST", "GJ": "WEST", "MH": "WEST", "DN": "WEST",
    # Southern Zonal Council
    "AP": "SOUTH", "KA": "SOUTH", "KL": "SOUTH", "TN": "SOUTH", "PY": "SOUTH",
    "TS": "SOUTH",  # Telangana -- extension, formed 2014 after council list above
    # North Eastern Council (separate from the 5 Zonal Councils)
    "AS": "NORTHEAST", "AR": "NORTHEAST", "MN": "NORTHEAST", "TR": "NORTHEAST",
    "MZ": "NORTHEAST", "ML": "NORTHEAST", "NL": "NORTHEAST", "SK": "NORTHEAST",
    # Island territories -- extension, not part of any council
    "AN": "SOUTH",  # Andaman & Nicobar -- grouped with South for proximity
    "LA": "WEST",   # Lakshadweep -- grouped with West for proximity
}

ZONES = [
    ("NORTH", "Northern Zone"),
    ("CENTRAL", "Central Zone"),
    ("EAST", "Eastern Zone"),
    ("WEST", "Western Zone"),
    ("SOUTH", "Southern Zone"),
    ("NORTHEAST", "North Eastern Zone"),
]

# RTO.csv (github.com/kishorek/India-Codes) uses some legacy/alternate state prefixes.
_LEGACY_STATE_CODE_MAP = {
    "OR": "OD",  # Odisha
    "UA": "UK",  # Uttarakhand (duplicate legacy prefix)
    "DD": "DN",  # Daman and Diu -> merged into existing "UT of DNH and DD"
}


def normalize_state_code(raw_prefix: str) -> str:
    return _LEGACY_STATE_CODE_MAP.get(raw_prefix, raw_prefix)


def split_district_names(place_field: str) -> list[str]:
    parts = re.split(r"[/,]", place_field)
    return [p.strip() for p in parts if p.strip()]
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && python -m pytest tests/test_geo_reference_data.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/scripts/__init__.py backend/app/scripts/geo_reference_data.py backend/tests/test_geo_reference_data.py
git commit -m "feat: add verified zone mapping and RTO.csv parsing helpers"
```

---

## Task 4: Seed script (DB upsert)

**Files:**
- Create: `backend/app/scripts/seed_geo_hierarchy.py`
- Modify: `backend/app/main.py:9-12` (`lifespan`)
- Test: `backend/tests/test_seed_geo_hierarchy.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_seed_geo_hierarchy.py`. This uses a tiny in-memory CSV
(not the real 1093-row file) so the test is fast and deterministic:

```python
import io
import pytest
from sqlalchemy import select
from app.scripts.seed_geo_hierarchy import seed_from_rows
from app.models.models import State, Zone, District, RTO, RTODistrict

SAMPLE_ROWS = [
    {"RegNo": "AP01", "Place": "Adilabad / Mancherial / Nirmal", "State": "Andhra Pradesh"},
    {"RegNo": "MH12", "Place": "Pune", "State": "Maharashtra"},
    {"RegNo": "OR05", "Place": "Cuttack, Jagatsinghpur", "State": "Orissa"},
]


async def test_seed_creates_zones_states_districts_rtos(db_session):
    db_session.add(State(state_code="AP", state_name="Andhra Pradesh"))
    db_session.add(State(state_code="MH", state_name="Maharashtra"))
    db_session.add(State(state_code="OD", state_name="Odisha"))
    db_session.add(State(state_code="LD", state_name="Ladakh"))
    db_session.add(State(state_code="LA", state_name="Lakshadweep"))
    await db_session.commit()

    await seed_from_rows(db_session, SAMPLE_ROWS)

    zones = (await db_session.execute(select(Zone))).scalars().all()
    assert len(zones) == 6

    ap_state = (await db_session.execute(select(State).where(State.state_code == "AP"))).scalar_one()
    assert ap_state.zone_code == "SOUTH"

    districts = (await db_session.execute(select(District).where(District.state_code == "AP"))).scalars().all()
    assert {d.district_name for d in districts} == {"Adilabad", "Mancherial", "Nirmal"}

    rto = (await db_session.execute(select(RTO).where(RTO.rto_code == "AP01"))).scalar_one()
    assert rto.state_code == "AP"

    links = (await db_session.execute(select(RTODistrict).where(RTODistrict.rto_code == "AP01"))).scalars().all()
    assert len(links) == 3

    # OR prefix should normalize onto the existing OD state
    or_rto = (await db_session.execute(select(RTO).where(RTO.rto_code == "OR05"))).scalar_one()
    assert or_rto.state_code == "OD"


async def test_seed_fixes_ladakh_lakshadweep_name_swap(db_session):
    db_session.add(State(state_code="LD", state_name="Ladakh"))
    db_session.add(State(state_code="LA", state_name="Lakshadweep"))
    await db_session.commit()

    await seed_from_rows(db_session, [])

    ld = (await db_session.execute(select(State).where(State.state_code == "LD"))).scalar_one()
    la = (await db_session.execute(select(State).where(State.state_code == "LA"))).scalar_one()
    assert ld.state_name == "Lakshadweep"
    assert la.state_name == "Ladakh"


async def test_seed_is_idempotent(db_session):
    db_session.add(State(state_code="MH", state_name="Maharashtra"))
    await db_session.commit()

    await seed_from_rows(db_session, SAMPLE_ROWS)
    await seed_from_rows(db_session, SAMPLE_ROWS)  # run twice

    rtos = (await db_session.execute(select(RTO))).scalars().all()
    assert len([r for r in rtos if r.rto_code == "MH12"]) == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_seed_geo_hierarchy.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.scripts.seed_geo_hierarchy'`

- [ ] **Step 3: Implement it**

Create `backend/app/scripts/seed_geo_hierarchy.py`:

```python
import csv
import os
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.models import State, Zone, District, RTO, RTODistrict
from app.scripts.geo_reference_data import (
    ZONES,
    ZONE_BY_STATE_CODE,
    normalize_state_code,
    split_district_names,
)

RTO_CSV_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "reference", "RTO.csv"
)

# The existing seed (backend/setup.sh) has these two swapped relative to real-world
# vehicle registration codes (confirmed against RTO.csv: LD prefix = Lakshadweep).
_NAME_CORRECTIONS = {
    "LD": "Lakshadweep",
    "LA": "Ladakh",
}


async def seed_from_rows(db: AsyncSession, rto_rows: list[dict]) -> None:
    # 1. Zones
    for zone_code, zone_name in ZONES:
        existing = await db.get(Zone, zone_code)
        if existing is None:
            db.add(Zone(zone_code=zone_code, zone_name=zone_name))

    # 2. State corrections + zone assignment
    states = (await db.execute(select(State))).scalars().all()
    for state in states:
        if state.state_code in _NAME_CORRECTIONS:
            state.state_name = _NAME_CORRECTIONS[state.state_code]
        state.zone_code = ZONE_BY_STATE_CODE.get(state.state_code)
    await db.flush()

    known_state_codes = {s.state_code for s in states}

    # 3. Districts + RTOs + links
    for row in rto_rows:
        rto_code = row["RegNo"].strip()
        raw_prefix = rto_code[:2]
        state_code = normalize_state_code(raw_prefix)
        if state_code not in known_state_codes:
            continue  # unknown/unmapped state prefix -- skip rather than guess

        existing_rto = await db.get(RTO, rto_code)
        if existing_rto is None:
            db.add(RTO(rto_code=rto_code, rto_name=row["Place"].strip(), state_code=state_code))
        await db.flush()

        for district_name in split_district_names(row["Place"]):
            district_code = f"{state_code}-{district_name.upper().replace(' ', '_')}"
            existing_district = await db.get(District, district_code)
            if existing_district is None:
                db.add(District(
                    district_code=district_code,
                    district_name=district_name,
                    state_code=state_code,
                ))
                await db.flush()

            link_key = (rto_code, district_code)
            existing_link = await db.get(RTODistrict, link_key)
            if existing_link is None:
                db.add(RTODistrict(rto_code=rto_code, district_code=district_code))

    await db.commit()


async def seed_geo_hierarchy(db: AsyncSession) -> None:
    with open(RTO_CSV_PATH, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    await seed_from_rows(db, rows)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && python -m pytest tests/test_seed_geo_hierarchy.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Wire seeding into app startup (idempotent, so safe on every restart)**

Modify `backend/app/main.py`:

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.core.config import settings
from app.core.database import init_db, AsyncSessionLocal
from app.api.v1.router import api_router
from app.scripts.seed_geo_hierarchy import seed_geo_hierarchy


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    async with AsyncSessionLocal() as session:
        await seed_geo_hierarchy(session)
    yield
```

- [ ] **Step 6: Run the full backend test suite**

Run: `cd backend && python -m pytest -v`
Expected: PASS (all tests so far)

- [ ] **Step 7: Manually verify against the real 1093-row file**

Run:
```bash
cd backend
python -c "
import asyncio
from app.core.database import init_db, AsyncSessionLocal
from app.scripts.seed_geo_hierarchy import seed_geo_hierarchy

async def main():
    await init_db()
    async with AsyncSessionLocal() as session:
        await seed_geo_hierarchy(session)

asyncio.run(main())
"
```
Expected: no errors. Then verify counts:
```bash
python -c "
import sqlite3
con = sqlite3.connect('data/vahan.db')
cur = con.cursor()
for t in ['zones', 'districts', 'rtos', 'rto_districts']:
    print(t, cur.execute(f'SELECT COUNT(*) FROM {t}').fetchone())
print('LD name:', cur.execute(\"SELECT state_name FROM states WHERE state_code='LD'\").fetchone())
print('LA name:', cur.execute(\"SELECT state_name FROM states WHERE state_code='LA'\").fetchone())
"
```
Expected: `zones` = 6, `districts` and `rtos` in the hundreds/low thousands, `LD name` =
`('Lakshadweep',)`, `LA name` = `('Ladakh',)`.

- [ ] **Step 8: Commit**

```bash
git add backend/app/scripts/seed_geo_hierarchy.py backend/app/main.py backend/tests/test_seed_geo_hierarchy.py
git commit -m "feat: seed zone/district/RTO hierarchy from real reference data on startup"
```

---

## Task 5: Geo hierarchy navigation API

**Files:**
- Create: `backend/app/api/v1/endpoints/geo.py`
- Modify: `backend/app/api/v1/router.py`
- Modify: `backend/app/schemas/schemas.py`
- Test: `backend/tests/test_geo_endpoints.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_geo_endpoints.py`:

```python
from app.models.models import State, Zone, District, RTO, RTODistrict


async def _seed_minimal(db_session):
    db_session.add(Zone(zone_code="SOUTH", zone_name="Southern Zone"))
    db_session.add(State(state_code="AP", state_name="Andhra Pradesh", zone_code="SOUTH"))
    db_session.add(District(district_code="AP-GUNTUR", district_name="Guntur", state_code="AP"))
    db_session.add(RTO(rto_code="AP07", rto_name="Guntur", state_code="AP"))
    db_session.add(RTODistrict(rto_code="AP07", district_code="AP-GUNTUR"))
    await db_session.commit()


async def test_list_zones(client, db_session):
    await _seed_minimal(db_session)
    response = await client.get("/api/v1/geo/zones")
    assert response.status_code == 200
    codes = [z["zone_code"] for z in response.json()]
    assert "SOUTH" in codes


async def test_states_in_zone(client, db_session):
    await _seed_minimal(db_session)
    response = await client.get("/api/v1/geo/zones/SOUTH/states")
    assert response.status_code == 200
    assert response.json() == [{"state_code": "AP", "state_name": "Andhra Pradesh"}]


async def test_districts_in_state(client, db_session):
    await _seed_minimal(db_session)
    response = await client.get("/api/v1/geo/states/AP/districts")
    assert response.status_code == 200
    assert response.json() == [{"district_code": "AP-GUNTUR", "district_name": "Guntur", "state_code": "AP"}]


async def test_rtos_in_district(client, db_session):
    await _seed_minimal(db_session)
    response = await client.get("/api/v1/geo/districts/AP-GUNTUR/rtos")
    assert response.status_code == 200
    assert response.json() == [{"rto_code": "AP07", "rto_name": "Guntur", "state_code": "AP"}]
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_geo_endpoints.py -v`
Expected: FAIL (404s -- routes don't exist yet)

- [ ] **Step 3: Add schemas**

Modify `backend/app/schemas/schemas.py`, append at the end:

```python
class ZoneSchema(BaseModel):
    zone_code: str
    zone_name: str


class DistrictSchema(BaseModel):
    district_code: str
    district_name: str
    state_code: str
```

- [ ] **Step 4: Implement the endpoint module**

Create `backend/app/api/v1/endpoints/geo.py`:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.models import Zone, State, District, RTO, RTODistrict
from app.schemas.schemas import ZoneSchema, StateSchema, DistrictSchema, RTO as RTOSchema

router = APIRouter()


@router.get("/zones", response_model=list[ZoneSchema])
async def get_zones(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Zone).order_by(Zone.zone_name))
    return [ZoneSchema(zone_code=z.zone_code, zone_name=z.zone_name) for z in result.scalars().all()]


@router.get("/zones/{zone_code}/states", response_model=list[StateSchema])
async def get_states_in_zone(zone_code: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(State).where(State.zone_code == zone_code).order_by(State.state_name)
    )
    return [StateSchema(state_code=s.state_code, state_name=s.state_name) for s in result.scalars().all()]


@router.get("/states/{state_code}/districts", response_model=list[DistrictSchema])
async def get_districts_in_state(state_code: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(District).where(District.state_code == state_code).order_by(District.district_name)
    )
    return [
        DistrictSchema(district_code=d.district_code, district_name=d.district_name, state_code=d.state_code)
        for d in result.scalars().all()
    ]


@router.get("/districts/{district_code}/rtos", response_model=list[RTOSchema])
async def get_rtos_in_district(district_code: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(RTO)
        .join(RTODistrict, RTO.rto_code == RTODistrict.rto_code)
        .where(RTODistrict.district_code == district_code)
        .order_by(RTO.rto_name)
    )
    return [
        RTOSchema(rto_code=r.rto_code, rto_name=r.rto_name, state_code=r.state_code)
        for r in result.scalars().all()
    ]
```

- [ ] **Step 5: Wire the router**

Modify `backend/app/api/v1/router.py`:

```python
from fastapi import APIRouter
from app.api.v1.endpoints import (
    summary,
    states,
    registrations,
    comparison,
    yoy,
    categories,
    refresh,
    geo,
)

api_router = APIRouter()

api_router.include_router(summary.router, prefix="/summary", tags=["Summary"])
api_router.include_router(states.router, prefix="/states", tags=["States"])
api_router.include_router(
    registrations.router, prefix="/registrations", tags=["Registrations"]
)
api_router.include_router(comparison.router, prefix="/comparison", tags=["Comparison"])
api_router.include_router(yoy.router, prefix="/yoy", tags=["Year-over-Year"])
api_router.include_router(categories.router, prefix="/categories", tags=["Categories"])
api_router.include_router(refresh.router, prefix="/refresh", tags=["Refresh"])
api_router.include_router(geo.router, prefix="/geo", tags=["Geo Hierarchy"])
```

- [ ] **Step 6: Run to verify it passes**

Run: `cd backend && python -m pytest tests/test_geo_endpoints.py -v`
Expected: PASS (4 tests)

- [ ] **Step 7: Run the full suite**

Run: `cd backend && python -m pytest -v`
Expected: all tests PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/v1/endpoints/geo.py backend/app/api/v1/router.py backend/app/schemas/schemas.py backend/tests/test_geo_endpoints.py
git commit -m "feat: add geo hierarchy navigation API (zones/states/districts/rtos)"
```

---

## Plan Self-Review Notes

- **Spec coverage:** This plan implements spec Section 3 (Geo Hierarchy & Data Model)
  in full, including the seeding approach described there. Sections 4-7 (scraper, drill-
  down aggregation API, frontend, roles/future-auth doc) are explicitly out of scope for
  this plan and become Plan 2+ once this ships, per spec Section 9.
- **Data honesty:** every reference value (RTO codes, zone/state membership) traces to
  either the real downloaded `RTO.csv` or a cited government source
  (mha.gov.in/en/page/zonal-council) — nothing was invented. Gaps (Telangana, Ladakh
  RTOs) are documented, not papered over.
- **Existing DB safety:** the migration approach (`ensure_columns`) only *adds* a column;
  it never drops or rewrites the existing 38k placeholder `registrations` rows, so
  nothing already in `backend/data/vahan.db` is lost.
