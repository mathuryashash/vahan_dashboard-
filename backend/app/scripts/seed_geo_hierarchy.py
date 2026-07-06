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
