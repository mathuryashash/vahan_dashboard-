import csv
import os
import re
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

# Real, single RTO codes: 2 letters + 1-3 digits + an optional short letter suffix for
# vehicle-category sub-codes (e.g. "DL1L", "UP53AG", "CH01 G" -- confirmed against the
# real RTO.csv). ~17 of the 1093 real rows are compound/malformed values instead --
# e.g. "AP16 & AP17", "TN/N, TN/AN", "UP33T, AT, BT, CT & so on" -- that don't
# correspond to one real, joinable RTO code and must be skipped rather than seeded.
_RTO_CODE_RE = re.compile(r"^[A-Z]{2}[0-9]{1,3}\s?[A-Z]{0,3}$")


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

    # Bulk-fetch existing keys once, up front, instead of one db.get() round-trip per
    # row per table (this runs on every app startup, and the row count is in the
    # thousands -- the per-row db.get() pattern was measured at ~5.5s/run).
    existing_rto_codes = set((await db.execute(select(RTO.rto_code))).scalars().all())
    existing_district_codes = set((await db.execute(select(District.district_code))).scalars().all())
    existing_links = {
        (row.rto_code, row.district_code)
        for row in (await db.execute(select(RTODistrict.rto_code, RTODistrict.district_code))).all()
    }

    # 3. Districts + RTOs + links
    for row in rto_rows:
        rto_code = row["RegNo"].strip()
        if not _RTO_CODE_RE.match(rto_code):
            continue  # compound/malformed RegNo -- not a single real RTO code

        raw_prefix = rto_code[:2]
        state_code = normalize_state_code(raw_prefix)
        if state_code not in known_state_codes:
            continue  # unknown/unmapped state prefix -- skip rather than guess

        if rto_code not in existing_rto_codes:
            db.add(RTO(rto_code=rto_code, rto_name=row["Place"].strip(), state_code=state_code))
            existing_rto_codes.add(rto_code)

        for district_name in split_district_names(row["Place"]):
            district_code = f"{state_code}-{district_name.upper().replace(' ', '_')}"
            if district_code not in existing_district_codes:
                db.add(District(
                    district_code=district_code,
                    district_name=district_name,
                    state_code=state_code,
                ))
                existing_district_codes.add(district_code)

            link_key = (rto_code, district_code)
            if link_key not in existing_links:
                db.add(RTODistrict(rto_code=rto_code, district_code=district_code))
                existing_links.add(link_key)

    await db.commit()


async def seed_geo_hierarchy(db: AsyncSession) -> None:
    with open(RTO_CSV_PATH, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    await seed_from_rows(db, rows)
