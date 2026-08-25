# Vehicle Taxonomy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Regroup VAHAN's 89 raw `vehicle_class` values into 2-Wheeler/3-Wheeler/4-Wheeler/Commercial Vehicle (LCV/MCV/HCV/Unspecified)/Other, and add an ICE/Hybrid/EV filter — persisted as real columns so they're usable as SQL filters, not just display labels.

**Architecture:** Two new columns on `Registration` (`vehicle_category`, `commercial_tier`), populated by an explicit lookup table applied both going-forward (scraper ingestion) and retroactively (one-time backfill via the existing self-healing migration pattern in `app/core/migrations.py`). API endpoints gain `vehicle_category`/`commercial_tier`/`fuel_group` filter params. Frontend gets the category dropdown regrouped and a new ICE/Hybrid/EV toggle, reusing the existing filter-bar pattern already in `Overview.tsx`.

**Tech Stack:** FastAPI, SQLAlchemy async, PostgreSQL, React, TanStack Query, TypeScript.

**Known limitation carried forward (not fixed by this plan):** maker and vehicle_category/vehicle_class can never both be non-default on the same row for live-scraped data (VAHAN's scraper limitation, see `Overview.tsx:180-185`). This plan does not and cannot change that — see Task 8.

---

## File Structure

- `backend/app/core/query_filters.py` — add `_VEHICLE_CATEGORY_MAP` (full 89-entry lookup) and `classify_vehicle(raw_vehicle_class: str) -> tuple[str, str | None]`, alongside the existing `fuel_category()`. Also add `fuel_group(raw_fuel_type: str) -> str` (ICE/Hybrid/EV), built on `fuel_category()`.
- `backend/app/core/migrations.py` — add `ensure_vehicle_category_backfilled(engine)`: one-time backfill of the two new columns for existing rows, chunked, idempotent (skips rows already classified).
- `backend/app/core/database.py` — wire the new migration into `init_db()`.
- `backend/app/models/models.py` — add `vehicle_category` and `commercial_tier` columns to `Registration`.
- `backend/app/services/scraper_service.py` — `persist_rto_batch` sets the two new columns going forward.
- `backend/app/core/query_filters.py` — `apply_common_filters` gains `vehicle_category`/`commercial_tier` params.
- `backend/app/api/v1/endpoints/categories.py` — `GET /` groups by `vehicle_category` by default (raw `vehicle_class` via `?raw=true`); `GET /top-makers`, `GET /model-breakdown` accept `vehicle_category`/`commercial_tier`; `GET /fuel-breakdown` accepts `fuel_group`.
- `backend/tests/test_query_filters.py` — add `classify_vehicle` and `fuel_group` tests.
- `backend/tests/test_migrations.py` — add backfill tests.
- `frontend/src/types/index.ts` — extend `CategoryItem`, add `commercial_tier` to relevant types.
- `frontend/src/api/vahan.ts` — extend `FilterParams` with `vehicle_category`, `commercial_tier`, `fuel_group`.
- `frontend/src/pages/Overview.tsx` — Category dropdown now lists broad categories; add ICE/Hybrid/EV toggle next to it.
- `frontend/src/pages/Categories.tsx` — same regrouping for its category breakdown + fuel chart.

---

## Task 1: Backend classification lookup (TDD)

**Files:**
- Modify: `backend/app/core/query_filters.py`
- Test: `backend/tests/test_query_filters.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_query_filters.py`:

```python
from app.core.query_filters import classify_vehicle, fuel_group


@pytest.mark.parametrize("raw,expected_category,expected_tier", [
    ("M-CYCLE/SCOOTER", "Two-Wheeler", None),
    ("MOPED", "Two-Wheeler", None),
    ("MOTORISED CYCLE (CC > 25CC)", "Two-Wheeler", None),
    ("Two-Wheeler", "Two-Wheeler", None),
    ("MOTOR CYCLE/SCOOTER-USED FOR HIRE", "Two-Wheeler", None),
    ("M-CYCLE/SCOOTER-WITH SIDE CAR", "Two-Wheeler", None),
    ("MOTOR CYCLE/SCOOTER-SIDECAR(T)", "Two-Wheeler", None),
    ("MOTOR CYCLE/SCOOTER-WITH TRAILER", "Two-Wheeler", None),
    ("THREE WHEELER (PASSENGER)", "Three-Wheeler", None),
    ("THREE WHEELER (GOODS)", "Three-Wheeler", None),
    ("THREE WHEELER (PERSONAL)", "Three-Wheeler", None),
    ("E-RICKSHAW(P)", "Three-Wheeler", None),
    ("E-RICKSHAW WITH CART (G)", "Three-Wheeler", None),
    ("Three-Wheeler", "Three-Wheeler", None),
    ("QUADRICYCLE (COMMERCIAL)", "Three-Wheeler", None),
    ("QUADRICYCLE (PRIVATE)", "Three-Wheeler", None),
    ("MOTOR CAR", "Four-Wheeler", None),
    ("Motor Car/Jeep/Taxi", "Four-Wheeler", None),
    ("MOTOR CAB", "Four-Wheeler", None),
    ("MAXI CAB", "Four-Wheeler", None),
    ("LUXURY CAB", "Four-Wheeler", None),
    ("Light Motor Vehicle", "Four-Wheeler", None),
    ("ADAPTED VEHICLE", "Four-Wheeler", None),
    ("PRIVATE SERVICE VEHICLE", "Four-Wheeler", None),
    ("PRIVATE SERVICE VEHICLE (INDIVIDUAL USE)", "Four-Wheeler", None),
    ("GOODS CARRIER", "Commercial Vehicle", "Unspecified"),
    ("TRACTOR (COMMERCIAL)", "Commercial Vehicle", "HCV"),
    ("TRACTOR-TROLLEY(COMMERCIAL)", "Commercial Vehicle", "Unspecified"),
    ("Mini Bus", "Commercial Vehicle", "LCV"),
    ("Bus", "Commercial Vehicle", "HCV"),
    ("BUS", "Commercial Vehicle", "HCV"),
    ("Medium Bus", "Commercial Vehicle", "MCV"),
    ("OMNI BUS", "Commercial Vehicle", "Unspecified"),
    ("OMNI BUS (PRIVATE USE)", "Commercial Vehicle", "Unspecified"),
    ("EDUCATIONAL INSTITUTION BUS", "Commercial Vehicle", "Unspecified"),
    ("SCHOOL BUS", "Commercial Vehicle", "Unspecified"),
    ("Medium Truck", "Commercial Vehicle", "MCV"),
    ("Heavy Truck", "Commercial Vehicle", "HCV"),
    ("TRAILER (COMMERCIAL)", "Commercial Vehicle", "HCV"),
    ("ARTICULATED VEHICLE", "Commercial Vehicle", "HCV"),
    ("SEMI-TRAILER (COMMERCIAL)", "Commercial Vehicle", "HCV"),
    ("AUXILIARY TRAILER", "Commercial Vehicle", "Unspecified"),
    ("DUMPER", "Commercial Vehicle", "HCV"),
    ("MODULAR HYDRAULIC TRAILER", "Commercial Vehicle", "Unspecified"),
    ("AGRICULTURAL TRACTOR", "Other", None),
    ("TRAILER (AGRICULTURAL)", "Other", None),
    ("Tractor", "Other", None),
    ("HARVESTER", "Other", None),
    ("POWER TILLER", "Other", None),
    ("POWER TILLER (COMMERCIAL)", "Other", None),
    ("PULLER TRACTOR", "Other", None),
    ("CONSTRUCTION EQUIPMENT VEHICLE", "Other", None),
    ("CONSTRUCTION EQUIPMENT VEHICLE (COMMERCIAL)", "Other", None),
    ("Construction Equipment", "Other", None),
    ("EARTH MOVING EQUIPMENT", "Other", None),
    ("EXCAVATOR (NT)", "Other", None),
    ("EXCAVATOR (COMMERCIAL)", "Other", None),
    ("CRANE MOUNTED VEHICLE", "Other", None),
    ("FORK LIFT", "Other", None),
    ("ROAD ROLLER", "Other", None),
    ("BULLDOZER", "Other", None),
    ("VEHICLE FITTED WITH RIG", "Other", None),
    ("VEHICLE FITTED WITH COMPRESSOR", "Other", None),
    ("VEHICLE FITTED WITH GENERATOR", "Other", None),
    ("TOW TRUCK", "Other", None),
    ("RECOVERY VEHICLE", "Other", None),
    ("BREAKDOWN VAN", "Other", None),
    ("AMBULANCE", "Other", None),
    ("ANIMAL AMBULANCE", "Other", None),
    ("FIRE FIGHTING VEHICLE", "Other", None),
    ("FIRE TENDERS", "Other", None),
    ("HEARSES", "Other", None),
    ("ARMOURED/SPECIALISED VEHICLE", "Other", None),
    ("SNORKED LADDERS", "Other", None),
    ("TREE TRIMMING VEHICLE", "Other", None),
    ("MOBILE CANTEEN", "Other", None),
    ("CASH VAN", "Other", None),
    ("MOBILE CLINIC", "Other", None),
    ("MOBILE WORKSHOP", "Other", None),
    ("LIBRARY VAN", "Other", None),
    ("X-RAY VAN", "Other", None),
    ("TOWER WAGON", "Other", None),
    ("CAMPER VAN / TRAILER", "Other", None),
    ("CAMPER VAN / TRAILER (PRIVATE USE)", "Other", None),
    ("TRAILER FOR PERSONAL USE", "Other", None),
    ("MOTOR CARAVAN", "Other", None),
    ("VINTAGE MOTOR VEHICLE", "Other", None),
    ("Other", "Other", None),
    ("All", "Other", None),
    ("SOME FUTURE VAHAN CATEGORY NOBODY HAS SEEN YET", "Other", None),
])
def test_classify_vehicle_maps_raw_vahan_values(raw, expected_category, expected_tier):
    assert classify_vehicle(raw) == (expected_category, expected_tier)


def test_classify_vehicle_is_case_insensitive():
    assert classify_vehicle("motor car") == ("Four-Wheeler", None)


@pytest.mark.parametrize("raw,expected", [
    ("PETROL", "ICE"),
    ("DIESEL", "ICE"),
    ("CNG ONLY", "ICE"),
    ("PETROL/LPG", "ICE"),
    ("ELECTRIC(BOV)", "EV"),
    ("PURE EV", "EV"),
    ("PETROL/HYBRID", "Hybrid"),
    ("STRONG HYBRID EV", "Hybrid"),
])
def test_fuel_group_maps_fuel_category_buckets(raw, expected):
    assert fuel_group(raw) == expected
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_query_filters.py -v -k "classify_vehicle or fuel_group"`
Expected: FAIL with `ImportError: cannot import name 'classify_vehicle'`

- [ ] **Step 3: Implement the classification table and functions**

In `backend/app/core/query_filters.py`, after the existing `_FUEL_CATEGORY_RULES` / `fuel_category` block, add:

```python
# VAHAN's 89 raw vehicle_class values, mapped to the 4 broad categories a
# commercial buyer actually thinks in (2W/3W/4W/Commercial), with LCV/MCV/HCV
# sub-tiers for Commercial where VAHAN's raw label states a size class.
# "Unspecified" (not a guess) when VAHAN's label doesn't state one -- e.g.
# plain "GOODS CARRIER" or "BUS" never says LCV/MCV/HCV, so this doesn't
# invent a size VAHAN never gave us. Anything not in this table (a future
# VAHAN category, or "All"/"Other" placeholders) falls to ("Other", None)
# rather than being guessed into a bucket -- see the design spec at
# docs/superpowers/specs/2026-08-23-vehicle-taxonomy-design.md for the full
# rationale behind each judgment call (cabs -> Four-Wheeler not Commercial,
# quadricycles -> Three-Wheeler, etc).
_VEHICLE_CATEGORY_MAP: dict[str, tuple[str, str | None]] = {
    # Two-Wheeler
    "M-CYCLE/SCOOTER": ("Two-Wheeler", None),
    "MOPED": ("Two-Wheeler", None),
    "MOTORISED CYCLE (CC > 25CC)": ("Two-Wheeler", None),
    "TWO-WHEELER": ("Two-Wheeler", None),
    "MOTOR CYCLE/SCOOTER-USED FOR HIRE": ("Two-Wheeler", None),
    "M-CYCLE/SCOOTER-WITH SIDE CAR": ("Two-Wheeler", None),
    "MOTOR CYCLE/SCOOTER-SIDECAR(T)": ("Two-Wheeler", None),
    "MOTOR CYCLE/SCOOTER-WITH TRAILER": ("Two-Wheeler", None),
    # Three-Wheeler
    "THREE WHEELER (PASSENGER)": ("Three-Wheeler", None),
    "THREE WHEELER (GOODS)": ("Three-Wheeler", None),
    "THREE WHEELER (PERSONAL)": ("Three-Wheeler", None),
    "E-RICKSHAW(P)": ("Three-Wheeler", None),
    "E-RICKSHAW WITH CART (G)": ("Three-Wheeler", None),
    "THREE-WHEELER": ("Three-Wheeler", None),
    "QUADRICYCLE (COMMERCIAL)": ("Three-Wheeler", None),
    "QUADRICYCLE (PRIVATE)": ("Three-Wheeler", None),
    # Four-Wheeler
    "MOTOR CAR": ("Four-Wheeler", None),
    "MOTOR CAR/JEEP/TAXI": ("Four-Wheeler", None),
    "MOTOR CAB": ("Four-Wheeler", None),
    "MAXI CAB": ("Four-Wheeler", None),
    "LUXURY CAB": ("Four-Wheeler", None),
    "LIGHT MOTOR VEHICLE": ("Four-Wheeler", None),
    "ADAPTED VEHICLE": ("Four-Wheeler", None),
    "PRIVATE SERVICE VEHICLE": ("Four-Wheeler", None),
    "PRIVATE SERVICE VEHICLE (INDIVIDUAL USE)": ("Four-Wheeler", None),
    # Commercial Vehicle
    "GOODS CARRIER": ("Commercial Vehicle", "Unspecified"),
    "TRACTOR (COMMERCIAL)": ("Commercial Vehicle", "HCV"),
    "TRACTOR-TROLLEY(COMMERCIAL)": ("Commercial Vehicle", "Unspecified"),
    "MINI BUS": ("Commercial Vehicle", "LCV"),
    "BUS": ("Commercial Vehicle", "HCV"),
    "MEDIUM BUS": ("Commercial Vehicle", "MCV"),
    "OMNI BUS": ("Commercial Vehicle", "Unspecified"),
    "OMNI BUS (PRIVATE USE)": ("Commercial Vehicle", "Unspecified"),
    "EDUCATIONAL INSTITUTION BUS": ("Commercial Vehicle", "Unspecified"),
    "SCHOOL BUS": ("Commercial Vehicle", "Unspecified"),
    "MEDIUM TRUCK": ("Commercial Vehicle", "MCV"),
    "HEAVY TRUCK": ("Commercial Vehicle", "HCV"),
    "TRAILER (COMMERCIAL)": ("Commercial Vehicle", "HCV"),
    "ARTICULATED VEHICLE": ("Commercial Vehicle", "HCV"),
    "SEMI-TRAILER (COMMERCIAL)": ("Commercial Vehicle", "HCV"),
    "AUXILIARY TRAILER": ("Commercial Vehicle", "Unspecified"),
    "DUMPER": ("Commercial Vehicle", "HCV"),
    "MODULAR HYDRAULIC TRAILER": ("Commercial Vehicle", "Unspecified"),
    # Other / Special Purpose
    "AGRICULTURAL TRACTOR": ("Other", None),
    "TRAILER (AGRICULTURAL)": ("Other", None),
    "TRACTOR": ("Other", None),
    "HARVESTER": ("Other", None),
    "POWER TILLER": ("Other", None),
    "POWER TILLER (COMMERCIAL)": ("Other", None),
    "PULLER TRACTOR": ("Other", None),
    "CONSTRUCTION EQUIPMENT VEHICLE": ("Other", None),
    "CONSTRUCTION EQUIPMENT VEHICLE (COMMERCIAL)": ("Other", None),
    "CONSTRUCTION EQUIPMENT": ("Other", None),
    "EARTH MOVING EQUIPMENT": ("Other", None),
    "EXCAVATOR (NT)": ("Other", None),
    "EXCAVATOR (COMMERCIAL)": ("Other", None),
    "CRANE MOUNTED VEHICLE": ("Other", None),
    "FORK LIFT": ("Other", None),
    "ROAD ROLLER": ("Other", None),
    "BULLDOZER": ("Other", None),
    "VEHICLE FITTED WITH RIG": ("Other", None),
    "VEHICLE FITTED WITH COMPRESSOR": ("Other", None),
    "VEHICLE FITTED WITH GENERATOR": ("Other", None),
    "TOW TRUCK": ("Other", None),
    "RECOVERY VEHICLE": ("Other", None),
    "BREAKDOWN VAN": ("Other", None),
    "AMBULANCE": ("Other", None),
    "ANIMAL AMBULANCE": ("Other", None),
    "FIRE FIGHTING VEHICLE": ("Other", None),
    "FIRE TENDERS": ("Other", None),
    "HEARSES": ("Other", None),
    "ARMOURED/SPECIALISED VEHICLE": ("Other", None),
    "SNORKED LADDERS": ("Other", None),
    "TREE TRIMMING VEHICLE": ("Other", None),
    "MOBILE CANTEEN": ("Other", None),
    "CASH VAN": ("Other", None),
    "MOBILE CLINIC": ("Other", None),
    "MOBILE WORKSHOP": ("Other", None),
    "LIBRARY VAN": ("Other", None),
    "X-RAY VAN": ("Other", None),
    "TOWER WAGON": ("Other", None),
    "CAMPER VAN / TRAILER": ("Other", None),
    "CAMPER VAN / TRAILER (PRIVATE USE)": ("Other", None),
    "TRAILER FOR PERSONAL USE": ("Other", None),
    "MOTOR CARAVAN": ("Other", None),
    "VINTAGE MOTOR VEHICLE": ("Other", None),
    "OTHER": ("Other", None),
    "ALL": ("Other", None),
}


def classify_vehicle(raw_vehicle_class: str) -> tuple[str, str | None]:
    return _VEHICLE_CATEGORY_MAP.get(raw_vehicle_class.upper(), ("Other", None))


# ICE/Hybrid/EV is a coarser regrouping of fuel_category's own buckets, not a
# separate ruleset -- Hybrid stays its own bucket rather than folding into
# ICE, since a buyer deciding whether to compete in pure-EV needs to see
# hybrids separately from plain combustion (see design spec).
_FUEL_GROUP_MAP = {
    "Petrol": "ICE",
    "Diesel": "ICE",
    "CNG": "ICE",
    "Other": "ICE",
    "Hybrid": "Hybrid",
    "EV": "EV",
}


def fuel_group(raw_fuel_type: str) -> str:
    return _FUEL_GROUP_MAP[fuel_category(raw_fuel_type)]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_query_filters.py -v`
Expected: PASS, all tests including the pre-existing `fuel_category` ones.

- [ ] **Step 5: Commit**

```bash
cd backend
git add app/core/query_filters.py tests/test_query_filters.py
git commit -m "feat: add vehicle_category/commercial_tier/fuel_group classifiers

Explicit lookup table for VAHAN's 89 raw vehicle_class values into
2W/3W/4W/Commercial (LCV/MCV/HCV/Unspecified)/Other. fuel_group is a
coarser regrouping of the existing fuel_category buckets into ICE/Hybrid/EV.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 2: Model columns + migration backfill (TDD)

**Files:**
- Modify: `backend/app/models/models.py:44-83`
- Modify: `backend/app/core/migrations.py`
- Test: `backend/tests/test_migrations.py`

- [ ] **Step 1: Add columns to the model**

In `backend/app/models/models.py`, in the `Registration` class, after the `is_supplementary` column (line 73):

```python
    # Broad category (2W/3W/4W/Commercial/Other) and, for Commercial rows
    # only, a size tier (LCV/MCV/HCV/Unspecified) -- see
    # app.core.query_filters.classify_vehicle. Persisted (not computed on
    # read like fuel_category) so it's usable as a real SQL filter, not just
    # a display label -- category-based access control needs a real
    # predicate to enforce against.
    vehicle_category = Column(String(20), nullable=True, index=True)
    commercial_tier = Column(String(15), nullable=True)
```

- [ ] **Step 2: Write the failing migration test**

Add to `backend/tests/test_migrations.py`:

```python
from app.core.migrations import ensure_vehicle_category_backfilled


async def test_ensure_vehicle_category_backfilled_classifies_existing_rows():
    table_name = _table_name()
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    async with engine.begin() as conn:
        await conn.execute(text(
            f"CREATE TABLE {table_name} (id SERIAL PRIMARY KEY, vehicle_class TEXT NOT NULL, "
            f"vehicle_category TEXT, commercial_tier TEXT)"
        ))
        await conn.execute(text(
            f"INSERT INTO {table_name} (vehicle_class) VALUES "
            f"('M-CYCLE/SCOOTER'), ('MOTOR CAR'), ('Heavy Truck'), ('AGRICULTURAL TRACTOR')"
        ))

    await ensure_vehicle_category_backfilled(engine, table_name=table_name)

    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            f"SELECT vehicle_class, vehicle_category, commercial_tier FROM {table_name} ORDER BY id"
        ))).all()
    assert rows == [
        ("M-CYCLE/SCOOTER", "Two-Wheeler", None),
        ("MOTOR CAR", "Four-Wheeler", None),
        ("Heavy Truck", "Commercial Vehicle", "HCV"),
        ("AGRICULTURAL TRACTOR", "Other", None),
    ]

    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE {table_name}"))
    await engine.dispose()


async def test_ensure_vehicle_category_backfilled_is_idempotent():
    table_name = _table_name()
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    async with engine.begin() as conn:
        await conn.execute(text(
            f"CREATE TABLE {table_name} (id SERIAL PRIMARY KEY, vehicle_class TEXT NOT NULL, "
            f"vehicle_category TEXT, commercial_tier TEXT)"
        ))
        await conn.execute(text(f"INSERT INTO {table_name} (vehicle_class) VALUES ('MOTOR CAR')"))

    await ensure_vehicle_category_backfilled(engine, table_name=table_name)
    await ensure_vehicle_category_backfilled(engine, table_name=table_name)  # must not raise or reclassify

    async with engine.connect() as conn:
        row = (await conn.execute(text(
            f"SELECT vehicle_category FROM {table_name} WHERE vehicle_class = 'MOTOR CAR'"
        ))).scalar()
    assert row == "Four-Wheeler"

    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE {table_name}"))
    await engine.dispose()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_migrations.py -v -k vehicle_category`
Expected: FAIL with `ImportError: cannot import name 'ensure_vehicle_category_backfilled'`

- [ ] **Step 4: Implement the backfill migration**

In `backend/app/core/migrations.py`, add the import and function:

```python
from app.core.query_filters import classify_vehicle
```

(add near the top, after the existing imports)

```python
async def ensure_vehicle_category_backfilled(engine: AsyncEngine, table_name: str = "registrations") -> None:
    """Classify every row with vehicle_category still NULL. Chunked (not one
    giant UPDATE) so this is safe to run against 13M+ existing rows on
    startup without holding a long-lived lock or blowing up memory reading
    every row into Python at once. Idempotent: only ever touches rows where
    vehicle_category IS NULL, so a completed backfill costs one cheap COUNT
    on every subsequent startup.
    """
    if not _IDENTIFIER_RE.match(table_name):
        raise ValueError(f"Invalid table name: {table_name!r}")
    CHUNK_SIZE = 5000
    async with engine.connect() as conn:
        while True:
            rows = (
                await conn.execute(
                    text(f"SELECT id, vehicle_class FROM {table_name} WHERE vehicle_category IS NULL LIMIT :n"),
                    {"n": CHUNK_SIZE},
                )
            ).all()
            if not rows:
                break
            for row_id, vehicle_class in rows:
                category, tier = classify_vehicle(vehicle_class)
                await conn.execute(
                    text(
                        f"UPDATE {table_name} SET vehicle_category = :category, commercial_tier = :tier "
                        f"WHERE id = :id"
                    ),
                    {"category": category, "tier": tier, "id": row_id},
                )
            await conn.commit()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_migrations.py -v`
Expected: PASS, all tests.

- [ ] **Step 6: Wire into init_db self-heal**

Modify `backend/app/core/database.py:39-48`:

```python
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    from app.core.migrations import ensure_analyzed, ensure_columns, ensure_indexes, ensure_vehicle_category_backfilled
    await ensure_columns(engine, {
        "states": {"zone_code": "VARCHAR(10)"},
        "registrations": {
            "is_supplementary": "BOOLEAN DEFAULT FALSE",
            "vehicle_category": "VARCHAR(20)",
            "commercial_tier": "VARCHAR(15)",
        },
    })
    await ensure_indexes(engine, Base.metadata)
    await ensure_vehicle_category_backfilled(engine)
    await ensure_analyzed(engine, list(Base.metadata.tables))
```

- [ ] **Step 7: Commit**

```bash
cd backend
git add app/models/models.py app/core/migrations.py app/core/database.py tests/test_migrations.py
git commit -m "feat: persist vehicle_category/commercial_tier, self-healing backfill

New indexed columns on Registration, classified via the lookup table
from the previous commit. ensure_vehicle_category_backfilled runs on
every startup (chunked, idempotent) so a client's existing 13M+ rows
get classified without a blocking one-shot migration.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 3: Scraper ingestion sets the new columns

**Files:**
- Modify: `backend/app/services/scraper_service.py:59-78`
- Test: `backend/tests/test_multi_dimension_data.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_multi_dimension_data.py`, after `test_purge_synthetic_does_not_delete_real_vehicle_class_rows`:

```python
async def test_persist_rto_batch_sets_vehicle_category(db_session):
    vc_batch = {
        "state_name": "Delhi", "rto_code": "DL1", "rto_name": "Test RTO",
        "records": [{"label": "Heavy Truck", "month": 1, "year": 2026, "count": 5}],
    }
    await persist_rto_batch(db_session, vc_batch, state_code="DL", dimension="vehicle_class")
    await db_session.commit()

    from sqlalchemy import select
    result = await db_session.execute(
        select(Registration.vehicle_category, Registration.commercial_tier)
        .where(Registration.rto_code == "DL1", Registration.year == 2026)
    )
    assert result.one() == ("Commercial Vehicle", "HCV")


async def test_persist_rto_batch_maker_pass_classifies_from_placeholder_all(db_session):
    # Maker-pass rows always store vehicle_class='All' (see persist_rto_batch
    # docstring) -- classify_vehicle('All') resolves to ("Other", None), same
    # as any other unrecognized/placeholder value.
    maker_batch = {
        "state_name": "Delhi", "rto_code": "DL1", "rto_name": "Test RTO",
        "records": [{"label": "HONDA", "month": 1, "year": 2026, "count": 5}],
    }
    await persist_rto_batch(db_session, maker_batch, state_code="DL", dimension="maker")
    await db_session.commit()

    from sqlalchemy import select
    result = await db_session.execute(
        select(Registration.vehicle_category).where(Registration.rto_code == "DL1", Registration.year == 2026)
    )
    assert result.scalar() == "Other"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_multi_dimension_data.py -v -k vehicle_category`
Expected: FAIL — `vehicle_category` is NULL, not the expected value (since persist_rto_batch doesn't set it yet).

- [ ] **Step 3: Implement**

Modify `backend/app/services/scraper_service.py`. Add the import at the top:

```python
from app.core.query_filters import classify_vehicle
```

Then in `persist_rto_batch`, replace the record-building loop (lines 59-78):

```python
    for record in batch["records"]:
        fields = dict(
            state_code=state_code,
            state_name=batch["state_name"],
            rto_code=rto_code,
            rto_name=batch["rto_name"],
            month=record["month"],
            year=record["year"],
            count=record["count"],
            is_supplementary=is_supplementary,
        )
        if dimension == "maker":
            fields.update(vehicle_class="All", maker=record["label"], fuel_type=None)
        elif dimension == "vehicle_class":
            fields.update(vehicle_class=record["label"], maker=None, fuel_type=None)
        elif dimension == "fuel":
            fields.update(vehicle_class="All", maker=None, fuel_type=record["label"])
        else:
            raise ValueError(f"Unknown dimension: {dimension!r}")
        category, tier = classify_vehicle(fields["vehicle_class"])
        fields.update(vehicle_category=category, commercial_tier=tier)
        db.add(Registration(**fields))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_multi_dimension_data.py tests/test_scraper_service.py -v`
Expected: PASS, all tests.

- [ ] **Step 5: Commit**

```bash
cd backend
git add app/services/scraper_service.py tests/test_multi_dimension_data.py
git commit -m "feat: classify vehicle_category at scrape-ingestion time

Every newly-scraped row now gets vehicle_category/commercial_tier set
immediately, matching what the backfill migration does retroactively
for existing rows.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 4: API filter params

**Files:**
- Modify: `backend/app/core/query_filters.py:7-28`
- Modify: `backend/app/api/v1/endpoints/categories.py`
- Test: `backend/tests/test_multi_dimension_data.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_multi_dimension_data.py`:

```python
async def test_categories_breakdown_groups_by_broad_vehicle_category(client, db_session):
    await _seed_real_rto(db_session)  # Two-Wheeler: 70, Motor Car/Jeep/Taxi: 30 (both classify_vehicle to Two-Wheeler / Four-Wheeler)

    response = await client.get("/api/v1/categories/", params={"year": 2026, "month": 1})
    assert response.status_code == 200
    rows = {r["vehicle_category"]: r["total_count"] for r in response.json()}
    assert rows == {"Two-Wheeler": 70, "Four-Wheeler": 30}


async def test_categories_breakdown_raw_flag_returns_original_vehicle_class(client, db_session):
    await _seed_real_rto(db_session)

    response = await client.get("/api/v1/categories/", params={"year": 2026, "month": 1, "raw": True})
    assert response.status_code == 200
    rows = {r["vehicle_class"]: r["total_count"] for r in response.json()}
    assert rows == {"Two-Wheeler": 70, "Motor Car/Jeep/Taxi": 30}


async def test_fuel_breakdown_filters_by_fuel_group(client, db_session):
    await _seed_real_rto(db_session)  # PETROL: 90, ELECTRIC: 10

    response = await client.get(
        "/api/v1/categories/fuel-breakdown", params={"year": 2026, "month": 1, "fuel_group": "EV"}
    )
    assert response.status_code == 200
    rows = {r["fuel_type"]: r["count"] for r in response.json()}
    assert rows == {"EV": 10}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_multi_dimension_data.py -v -k "broad_vehicle_category or raw_flag or fuel_group"`
Expected: FAIL — current endpoint groups by raw `vehicle_class`, has no `raw` or `fuel_group` param.

- [ ] **Step 3: Extend `apply_common_filters`**

Modify `backend/app/core/query_filters.py:7-28`:

```python
def apply_common_filters(
    query: Select,
    *,
    state: str | None = None,
    vehicle_class: str | None = None,
    vehicle_category: str | None = None,
    commercial_tier: str | None = None,
    maker: str | None = None,
    vehicle_model: str | None = None,
) -> Select:
    """Apply the state/vehicle_class/maker/vehicle_model filters shared by
    most registration-aggregation endpoints. Month is deliberately excluded:
    callers need different month semantics (exact match vs. "up to" a cutoff
    month for year-to-date comparisons), so they apply it themselves.
    """
    if state:
        query = query.where(Registration.state_name == state)
    if vehicle_class:
        query = query.where(Registration.vehicle_class == vehicle_class)
    if vehicle_category:
        query = query.where(Registration.vehicle_category == vehicle_category)
    if commercial_tier:
        query = query.where(Registration.commercial_tier == commercial_tier)
    if maker:
        query = query.where(Registration.maker == maker)
    if vehicle_model:
        query = query.where(Registration.vehicle_model == vehicle_model)
    return query
```

Also update `apply_total_filters` (same file, a few lines below) to accept and pass through the same two new params:

```python
def apply_total_filters(
    query: Select,
    *,
    state: str | None = None,
    vehicle_class: str | None = None,
    vehicle_category: str | None = None,
    commercial_tier: str | None = None,
    maker: str | None = None,
    vehicle_model: str | None = None,
) -> Select:
    """apply_common_filters, for queries that sum toward an overall total
    (KPIs, trend, state-ranking) -- also excludes supplementary rows, unless
    vehicle_class narrows to one specific real class. The canonical maker-pass
    (is_supplementary=False) always stores vehicle_class='All', so it can
    never match a specific class filter anyway; the only rows that ever carry
    a real class are the vehicle_class-dimension pass (is_supplementary=True)
    and synthetic seed data. Excluding supplementary rows in that case would
    silently zero out every category-filtered total for live-scraped years,
    since it would strip out the only rows that could ever match.
    """
    if not vehicle_class or vehicle_class == "All":
        query = exclude_supplementary(query)
    return apply_common_filters(
        query, state=state, vehicle_class=vehicle_class, vehicle_category=vehicle_category,
        commercial_tier=commercial_tier, maker=maker, vehicle_model=vehicle_model,
    )
```

- [ ] **Step 4: Update the categories endpoints**

Modify `backend/app/api/v1/endpoints/categories.py`. Update the import line:

```python
from app.core.query_filters import apply_common_filters, classify_vehicle, fuel_category, fuel_group, latest_month_with_data
```

Replace `get_categories` (the `GET /` handler):

```python
@router.get("/")
async def get_categories(
    year: int = _DEFAULT_YEAR,
    month: int | None = None,
    state: str | None = None,
    maker: str | None = None,
    vehicle_model: str | None = None,
    raw: bool = False,
    db: AsyncSession = Depends(get_db)
):
    # vehicle_class='All' is the placeholder used by real scraped rows that
    # don't carry class info at that pivot (the maker- and fuel-dimension
    # passes -- see Registration.is_supplementary). Excluding it here means
    # this breakdown only reflects rows that actually have a real class:
    # synthetic data (always did) and the vehicle_class-dimension real pass.
    group_col = Registration.vehicle_class if raw else Registration.vehicle_category
    q_curr = (
        select(group_col, func.sum(Registration.count).label("total"))
        .where(Registration.year == year, Registration.vehicle_class != "All")
    )
    q_prev = (
        select(group_col, func.sum(Registration.count).label("total"))
        .where(Registration.year == year - 1, Registration.vehicle_class != "All")
    )

    # When no specific month is requested, compare year-to-date rather than
    # full calendar year vs full calendar year (see summary.py get_dashboard_kpis
    # for the same fix and full rationale): cap both years at the latest month
    # that actually has data for `year`, so a partially-populated current year
    # isn't compared against a fully-populated prior year.
    compare_month = month
    if compare_month is None:
        compare_month = await latest_month_with_data(db, year)

    if month:
        q_curr = q_curr.where(Registration.month == month)
        q_prev = q_prev.where(Registration.month == month)
    elif compare_month:
        q_curr = q_curr.where(Registration.month <= compare_month)
        q_prev = q_prev.where(Registration.month <= compare_month)
    q_curr = apply_common_filters(q_curr, state=state, maker=maker, vehicle_model=vehicle_model)
    q_prev = apply_common_filters(q_prev, state=state, maker=maker, vehicle_model=vehicle_model)

    q_curr = q_curr.group_by(group_col).order_by(desc("total"))
    q_prev = q_prev.group_by(group_col)

    result = await db.execute(q_curr)
    rows = result.all()
    total = sum(r[1] for r in rows)

    prev_result = await db.execute(q_prev)
    prev_rows = {r[0]: r[1] for r in prev_result.all()}

    key_name = "vehicle_class" if raw else "vehicle_category"
    return [
        {
            key_name: r[0],
            "total_count": r[1],
            "share_percent": round((r[1] / total * 100) if total > 0 else 0, 2),
            "prev_count": prev_rows.get(r[0], 0),
            "yoy_growth": round(
                ((r[1] - prev_rows.get(r[0], 0)) / prev_rows.get(r[0], 1) * 100), 2
            )
            if prev_rows.get(r[0], 0) > 0
            else 0.0,
        }
        for r in rows
    ]
```

Update `get_top_makers` and `get_model_breakdown` to accept `vehicle_category`/`commercial_tier` alongside the existing `vehicle_class` param — add the two params to each function signature and pass them through to `apply_common_filters`:

```python
@router.get("/top-makers")
async def get_top_makers(
    vehicle_class: str | None = None,
    vehicle_category: str | None = None,
    commercial_tier: str | None = None,
    year: int = _DEFAULT_YEAR,
    month: int | None = None,
    state: str | None = None,
    vehicle_model: str | None = None,
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
):
    query = select(
        Registration.maker, func.sum(Registration.count).label("total")
    ).where(Registration.year == year, Registration.maker.isnot(None))

    if month:
        query = query.where(Registration.month == month)
    query = apply_common_filters(
        query, state=state, vehicle_class=vehicle_class, vehicle_category=vehicle_category,
        commercial_tier=commercial_tier, vehicle_model=vehicle_model,
    )

    query = query.group_by(Registration.maker).order_by(desc("total")).limit(limit)

    result = await db.execute(query)
    rows = result.all()
    return [{"maker": r[0], "count": r[1]} for r in rows]
```

```python
@router.get("/model-breakdown")
async def get_model_breakdown(
    vehicle_class: str | None = None,
    vehicle_category: str | None = None,
    commercial_tier: str | None = None,
    maker: str | None = None,
    year: int = _DEFAULT_YEAR,
    month: int | None = None,
    state: str | None = None,
    limit: int = 15,
    db: AsyncSession = Depends(get_db),
):
    query = select(
        Registration.vehicle_model, func.sum(Registration.count).label("total")
    ).where(
        Registration.year == year,
        Registration.vehicle_model.isnot(None),
        Registration.vehicle_model != ""
    )

    if month:
        query = query.where(Registration.month == month)
    query = apply_common_filters(
        query, state=state, vehicle_class=vehicle_class, vehicle_category=vehicle_category,
        commercial_tier=commercial_tier, maker=maker,
    )

    query = query.group_by(Registration.vehicle_model).order_by(desc("total")).limit(limit)

    result = await db.execute(query)
    rows = result.all()

    total = sum(r[1] for r in rows)
    return [
        {
            "model": r[0],
            "count": r[1],
            "share_percent": round((r[1] / total * 100) if total > 0 else 0, 2),
        }
        for r in rows
    ]
```

Update `get_fuel_breakdown` to accept and apply `fuel_group`:

```python
@router.get("/fuel-breakdown")
async def get_fuel_breakdown(
    vehicle_class: str | None = None,
    vehicle_category: str | None = None,
    commercial_tier: str | None = None,
    fuel_group_filter: str | None = Query(None, alias="fuel_group"),
    year: int = _DEFAULT_YEAR,
    month: int | None = None,
    state: str | None = None,
    maker: str | None = None,
    vehicle_model: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(
        Registration.fuel_type, func.sum(Registration.count).label("total")
    ).where(Registration.year == year, Registration.fuel_type.isnot(None))

    if month:
        query = query.where(Registration.month == month)
    query = apply_common_filters(
        query, state=state, vehicle_class=vehicle_class, vehicle_category=vehicle_category,
        commercial_tier=commercial_tier, maker=maker, vehicle_model=vehicle_model,
    )

    query = query.group_by(Registration.fuel_type)

    # Grouped in Python, not SQL: VAHAN's raw fuel_type is a specific
    # powertrain/fuel-system string (e.g. "PETROL/HYBRID/CNG"), not the
    # handful of categories people actually want to compare -- see
    # fuel_category's docstring. Re-aggregating ~37 already-summed rows in
    # Python is negligible cost next to the query itself, and keeps the
    # bucket rules in one plain-Python place instead of a SQL CASE
    # expression that has to be kept in sync with it by hand.
    result = await db.execute(query)
    totals: dict[str, int] = {}
    for raw_fuel_type, total in result.all():
        if fuel_group_filter and fuel_group(raw_fuel_type) != fuel_group_filter:
            continue
        bucket = fuel_category(raw_fuel_type)
        totals[bucket] = totals.get(bucket, 0) + total
    return [
        {"fuel_type": bucket, "count": total}
        for bucket, total in sorted(totals.items(), key=lambda item: item[1], reverse=True)
    ]
```

This needs `Query` imported — update the fastapi import line at the top of the file:

```python
from fastapi import APIRouter, Depends, Query
```

(already present — verify, no change needed if so)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/test_multi_dimension_data.py -v`
Expected: PASS, all tests including the pre-existing ones (`test_categories_breakdown_uses_vehicle_class_dimension` — check this one still passes; it asserts on `vehicle_class` key from a `raw=false` default call, so it needs updating too, see Step 6).

- [ ] **Step 6: Fix the now-outdated pre-existing test**

The existing `test_categories_breakdown_uses_vehicle_class_dimension` in `backend/tests/test_multi_dimension_data.py` asserts on a `vehicle_class` key with raw values. Since the default response now groups by broad category, update it to match the new default behavior (this is the same assertion as the new `test_categories_breakdown_groups_by_broad_vehicle_category` test added in Step 1 — remove the duplicate, keeping one):

Find and delete the old `test_categories_breakdown_uses_vehicle_class_dimension` function (it's superseded by `test_categories_breakdown_groups_by_broad_vehicle_category` added above).

- [ ] **Step 7: Run the full test suite**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/ -v`
Expected: PASS, all tests, no regressions.

- [ ] **Step 8: Commit**

```bash
cd backend
git add app/core/query_filters.py app/api/v1/endpoints/categories.py tests/test_multi_dimension_data.py
git commit -m "feat: expose vehicle_category/commercial_tier/fuel_group as API filters

Categories endpoint groups by broad category by default (?raw=true for
the old granular vehicle_class view). top-makers, model-breakdown, and
fuel-breakdown all gain vehicle_category/commercial_tier filter params;
fuel-breakdown also gains fuel_group (ICE/Hybrid/EV).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 5: Frontend types and API client

**Files:**
- Modify: `frontend/src/types/index.ts:21-27`
- Modify: `frontend/src/api/vahan.ts:8-15`

- [ ] **Step 1: Update types**

Modify `frontend/src/types/index.ts`, replace the `CategoryItem` interface (lines 21-27):

```typescript
export interface CategoryItem {
  vehicle_category: string;
  total_count: number;
  share_percent: number;
  prev_count: number;
  yoy_growth: number;
}
```

- [ ] **Step 2: Update FilterParams**

Modify `frontend/src/api/vahan.ts`, replace the `FilterParams` interface (lines 8-15):

```typescript
export interface FilterParams {
  year?: number;
  month?: number | null;
  state?: string | null;
  vehicle_class?: string | null;
  vehicle_category?: string | null;
  commercial_tier?: string | null;
  fuel_group?: string | null;
  maker?: string | null;
  vehicle_model?: string | null;
}
```

- [ ] **Step 3: Verify the build still typechecks**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new type errors (existing code reading `c.vehicle_class` off a `CategoryItem` in `Categories.tsx`/`Overview.tsx` will now show errors — these get fixed in Task 6/7).

- [ ] **Step 4: Commit**

```bash
cd frontend
git add src/types/index.ts src/api/vahan.ts
git commit -m "feat: add vehicle_category/commercial_tier/fuel_group to frontend types

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 6: Overview page — regrouped category dropdown + ICE/Hybrid/EV toggle

**Files:**
- Modify: `frontend/src/pages/Overview.tsx`
- Modify: `frontend/src/hooks/useAppStore.ts`

- [ ] **Step 1: Add fuelGroup to the app store**

Modify `frontend/src/hooks/useAppStore.ts`. Add alongside the existing `selectedCategory` state (following the exact pattern already there):

```typescript
  fuelGroup: string | null;
```

(in the interface, next to `selectedCategory: string | null;`)

```typescript
  fuelGroup: null,
```

(in the default state, next to `selectedCategory: null,`)

```typescript
  setFuelGroup: (group) => set({ fuelGroup: group }),
```

(next to `setSelectedCategory`)

- [ ] **Step 2: Wire fuelGroup into Overview's queries and add the toggle UI**

In `frontend/src/pages/Overview.tsx`, add `fuelGroup, setFuelGroup` to the destructured store values (alongside `selectedCategory` at line ~59).

Update the `vehicle_class: selectedCategory` params on the KPI/trend/state-ranking queries (lines ~79, ~90, ~102) to `vehicle_category: selectedCategory` — since the dropdown now populates from broad categories (Task 6, Step 3), not raw classes. Add `fuel_group: fuelGroup` alongside each.

Add the toggle UI immediately after the Category `<select>` block (after line 264):

```tsx
        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] uppercase font-mono tracking-widest text-[var(--text-muted)] font-bold">Powertrain</label>
          <div className="flex rounded-xl border border-[var(--border)] overflow-hidden">
            {(['ICE', 'Hybrid', 'EV'] as const).map((group) => (
              <button
                key={group}
                onClick={() => setFuelGroup(fuelGroup === group ? null : group)}
                className={`flex-1 text-xs font-semibold py-2 transition-colors ${
                  fuelGroup === group
                    ? 'bg-[var(--accent)] text-[var(--accent-contrast)]'
                    : 'bg-[var(--bg-sunken)] text-[var(--text-secondary)] hover:bg-[var(--bg-card-hover)]'
                }`}
              >
                {group}
              </button>
            ))}
          </div>
        </div>
```

- [ ] **Step 3: Update the Category dropdown options to use broad categories**

The category `<select>` (around line 258-263) currently maps `categories` (from `getCategories()`) using `c.vehicle_class`. Since `getCategories()` now returns `vehicle_category` by default (Task 4), update:

```tsx
          <select value={selectedCategory || ''} onChange={(e) => setSelectedCategory(e.target.value || null)} className={selectClass}>
            <option value="">All Categories</option>
            {(categories || []).map((c: { vehicle_category: string }) => (
              <option key={c.vehicle_category} value={c.vehicle_category}>{c.vehicle_category}</option>
            ))}
          </select>
```

- [ ] **Step 4: Update the vehicle mix pie chart data mapping**

Find where `categories` feeds the "Vehicle Mix" pie chart (search for `pieData` in Overview.tsx) — update `c.vehicle_class` references to `c.vehicle_category`, matching the same rename applied in Task 7 for `Categories.tsx`.

- [ ] **Step 5: Verify typecheck and manual smoke test**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors referencing `Overview.tsx`.

Manually verify: start the app (`npm run dev` in frontend, backend already running), open the Overview page, confirm the Category dropdown now shows `Two-Wheeler / Three-Wheeler / Four-Wheeler / Commercial Vehicle / Other` instead of 89 raw values, and the ICE/Hybrid/EV toggle buttons render and are clickable.

- [ ] **Step 6: Commit**

```bash
cd frontend
git add src/pages/Overview.tsx src/hooks/useAppStore.ts
git commit -m "feat: regroup Overview category filter, add ICE/Hybrid/EV toggle

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 7: Categories page — same regrouping

**Files:**
- Modify: `frontend/src/pages/Categories.tsx`

- [ ] **Step 1: Update field references from vehicle_class to vehicle_category**

In `frontend/src/pages/Categories.tsx`, replace every `c.vehicle_class` reference with `c.vehicle_category` (lines 24-26, 91, 94, 97-99, 101) and the corresponding type annotations (`{ vehicle_class: string; ... }` → `{ vehicle_category: string; ... }`). The navigate call on line 94 (`navigate(\`/categories/${encodeURIComponent(c.vehicle_class)}\`)`) becomes `navigate(\`/categories/${encodeURIComponent(c.vehicle_category)}\`)`.

- [ ] **Step 2: Add the fuel_group toggle to the Fuel Type Breakdown chart**

The existing `CategoryChart` component (lines 127-160) takes a `fn` prop that fetches data. Add a fuel-group filter state and toggle above the fuel chart specifically. Replace the fuel chart's `CategoryChart` invocation (line 121):

```tsx
        <FuelBreakdownChart title="Fuel Type Breakdown — All Categories" year={selectedYear} chart={chart} index={1} />
```

Add the new component at the bottom of the file, alongside `CategoryChart`:

```tsx
function FuelBreakdownChart({ title, year, chart, index }: { title: string; year: number; chart: ReturnType<typeof useChartTheme>; index: number }) {
  const [fuelGroup, setFuelGroup] = useState<string | null>(null);
  const { data, isLoading } = useQuery({
    queryKey: ['fuel', year, fuelGroup],
    queryFn: () => getFuelBreakdown({ year, fuel_group: fuelGroup }),
  });

  const chartData = ((data as { fuel_type?: string; count: number }[]) || []).map((d) => ({
    name: d.fuel_type || '',
    count: d.count,
  }));

  return (
    <div className="bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] p-5 animate-entrance" style={{ animationDelay: `${250 + index * 80}ms` }}>
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-bold text-[var(--text-primary)] tracking-tight">{title}</h3>
        <div className="flex rounded-lg border border-[var(--border)] overflow-hidden">
          {(['ICE', 'Hybrid', 'EV'] as const).map((group) => (
            <button
              key={group}
              onClick={() => setFuelGroup(fuelGroup === group ? null : group)}
              className={`px-2.5 py-1 text-[10px] font-semibold transition-colors ${
                fuelGroup === group
                  ? 'bg-[var(--accent)] text-[var(--accent-contrast)]'
                  : 'bg-[var(--bg-sunken)] text-[var(--text-secondary)] hover:bg-[var(--bg-card-hover)]'
              }`}
            >
              {group}
            </button>
          ))}
        </div>
      </div>
      {isLoading ? (
        <div className="h-[220px] rounded-xl bg-[var(--bg-sunken)] animate-pulse-soft" />
      ) : (
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={chartData} layout="vertical">
            <CartesianGrid strokeDasharray="1 2" stroke={chart.grid} horizontal={false} />
            <XAxis type="number" tick={{ fontSize: 10, fill: chart.axisText, fontFamily: 'JetBrains Mono' }} />
            <YAxis dataKey="name" type="category" tick={(props) => <TruncatedYAxisTick {...props} fill={chart.axisText} />} width={150} />
            <Tooltip
              formatter={(val: number) => [val.toLocaleString('en-IN'), 'Count']}
              contentStyle={chart.tooltipContentStyle({ fontSize: 12 })} {...chart.tooltipTextStyle}
            />
            <Bar dataKey="count" radius={[0, 4, 4, 0]}>
              {chartData.map((d: { name: string }, i: number) => (
                <Cell key={i} fill={chart.seriesColor(d.name)} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
```

Add `useState` to the existing React import at the top of the file:

```tsx
import { useState } from 'react';
```

- [ ] **Step 3: Verify typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors referencing `Categories.tsx`.

- [ ] **Step 4: Manual smoke test**

Start the app, open Categories & Fuel page, confirm: category donut/list show broad categories, clicking a category navigates to `/categories/<Broad Category Name>`, the ICE/Hybrid/EV toggle above the fuel chart filters it correctly.

- [ ] **Step 5: Commit**

```bash
cd frontend
git add src/pages/Categories.tsx
git commit -m "feat: regroup Categories page, add ICE/Hybrid/EV toggle to fuel chart

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 8: Makers & Models page — add category filter

**Files:**
- Modify: `frontend/src/pages/MakersModels.tsx`

**Note on scope:** per the structural limitation documented in `Overview.tsx:180-185` (maker-pass rows always have `vehicle_class`/`vehicle_category` = the placeholder default, never a real value), adding a category dropdown here has the *same* "always zero when both are set" ceiling as Overview's maker+category combination — because `getTopMakers` sums the maker-dimension pass, which never carries a real `vehicle_category`. This task adds the dropdown and the **same honest warning banner pattern already used in Overview**, not a working combined filter — that combination is not achievable without VAHAN itself supporting a two-axis pivot.

- [ ] **Step 1: Add category filter state and dropdown**

In `frontend/src/pages/MakersModels.tsx`, add state for the category filter and fetch available categories:

```tsx
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const { data: categories } = useQuery({
    queryKey: ['categories', selectedYear],
    queryFn: () => getCategories({ year: selectedYear }),
  });
```

Update the import line to include `getCategories`:

```tsx
import { getTopMakers, getModelBreakdown, getCategories } from '../api/vahan';
```

Add the dropdown in the JSX, near the existing header/controls, plus the honest-limitation banner:

```tsx
      <div className="flex items-center gap-3">
        <select
          value={selectedCategory || ''}
          onChange={(e) => setSelectedCategory(e.target.value || null)}
          className="bg-[var(--bg-sunken)] border border-[var(--border)] text-xs font-semibold px-3 py-2 rounded-xl"
        >
          <option value="">All Categories</option>
          {(categories || []).map((c: { vehicle_category: string }) => (
            <option key={c.vehicle_category} value={c.vehicle_category}>{c.vehicle_category}</option>
          ))}
        </select>
      </div>
      {selectedCategory && (
        <div className="bg-[var(--bg-card)] border border-[var(--accent)] rounded-xl px-4 py-2.5 text-xs text-[var(--text-secondary)]">
          <span className="font-semibold text-[var(--accent)]">Category + Maker together always shows 0 —</span>{' '}
          VAHAN's live scraper can only pivot one dimension (maker OR category) per visit, so this leaderboard can't be scoped to a category. Showing all-category maker totals instead.
        </div>
      )}
```

- [ ] **Step 2: Verify typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors referencing `MakersModels.tsx`.

- [ ] **Step 3: Commit**

```bash
cd frontend
git add src/pages/MakersModels.tsx
git commit -m "feat: add category dropdown to Makers & Models, with honest scope banner

Adds the filter UI for consistency with Overview/Categories, but keeps
the same explicit limitation banner as Overview -- maker and category
can't combine for live-scraped data (VAHAN single-dimension pivot).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 9: Production backfill + regenerate seed

**Files:** none (operational task)

- [ ] **Step 1: Restart the backend to trigger the self-healing backfill**

The backend's `init_db()` (Task 2) runs `ensure_vehicle_category_backfilled` on every startup. Restarting against the real production database (13M+ rows, chunked at 5000/batch) classifies everything without a separate manual step.

Run: restart the backend process (kill existing `uvicorn` process, start again per the native-setup instructions already in `README.md`).

- [ ] **Step 2: Verify the backfill completed**

Run:
```bash
cd backend && .venv/Scripts/python.exe -c "
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
async def main():
    engine = create_async_engine('postgresql+asyncpg://vahan:vahan@localhost:5432/vahan')
    async with engine.connect() as conn:
        r = await conn.execute(text('SELECT COUNT(*) FROM registrations WHERE vehicle_category IS NULL'))
        print('unclassified rows remaining:', r.scalar())
        r2 = await conn.execute(text('SELECT vehicle_category, COUNT(*) FROM registrations GROUP BY vehicle_category ORDER BY 2 DESC'))
        print(r2.fetchall())
    await engine.dispose()
asyncio.run(main())
"
```
Expected: `unclassified rows remaining: 0`, and a sensible distribution across the 5 categories.

- [ ] **Step 3: Regenerate and push the seed file**

```bash
cd backend
.venv/Scripts/python.exe -m app.scripts.export_seed_data --years 20 --out ../docker/seed/seed.sql.gz
cd ..
git add docker/seed/seed.sql.gz
git commit -m "chore: regenerate seed with vehicle_category/commercial_tier + refreshed data

Includes both the new taxonomy columns and the corrected registration
counts from the 2026-08-24 force-refresh (fixed the stale-data bug
where the scheduler never actually re-scraped current-year RTOs).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
git push
```

---

## Self-Review

**Spec coverage:**
- Persisted `vehicle_category`/`commercial_tier` columns — Task 2. ✅
- Full 89-row classification table — Task 1 (test parametrization covers every spec row) + Task 2 backfill. ✅
- ICE/Hybrid/EV filter built on `fuel_category()` — Task 1 (`fuel_group`). ✅
- Ingestion sets columns going forward — Task 3. ✅
- API filter params on categories/top-makers/model-breakdown/fuel-breakdown — Task 4. ✅
- Frontend category dropdown regrouped (Overview, Categories, Makers & Models) — Tasks 6-8. ✅
- Testing (query_filters, migrations, multi_dimension_data) — Tasks 1-4. ✅
- Migration/backfill self-healing pattern — Task 2, matches `ensure_indexes`/`ensure_analyzed` precedent. ✅

**Out of scope, explicitly:** Subsystem B (RBAC) — separate spec, not started. The maker×category combined-filter limitation is structural (VAHAN's own single-dimension pivot) and is surfaced honestly (Task 8), not "fixed," because it cannot be fixed by this codebase.

**Placeholder scan:** no TBD/TODO markers; every step has complete code.

**Type consistency:** `classify_vehicle` returns `tuple[str, str | None]` consistently across Tasks 1-3. `fuel_group` return type (`str`) consistent across Tasks 1 and 4. Frontend `CategoryItem.vehicle_category` matches the API's renamed key from Task 4 Step 4.
