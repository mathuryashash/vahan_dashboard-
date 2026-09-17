"""'Other' is the one category value the canonical maker pass and the fuel
pass both carry, because classify_vehicle('All') returns ('Other', None).
Filtering on it therefore summed all three scrape passes together: measured
45,587,609 on the live 2026 data against a true 859,783, a 53x overstatement
reaching every KPI, trend, ranking, YoY and comparison -- and an
Other-scoped account would have been shown a total containing every other
segment's volume.

The largest measured discrepancy in this codebase had no test. This is it.
"""
from sqlalchemy import func, select

from app.core.query_filters import apply_fuel_group_filter, apply_total_filters
from app.models.models import RTO, Registration, State

GEO = dict(state_code="DL", state_name="Delhi", rto_code="DL1", rto_name="Delhi RTO")
REAL_OTHER = 700          # a genuine Other vehicle (tractor)
MAKER_PASS = 50_000       # canonical maker pass, vehicle_class='All'
FUEL_PASS = 50_000        # fuel-dimension pass, vehicle_class='All'


async def _seed(db):
    await db.merge(State(state_code="DL", state_name="Delhi"))
    await db.merge(RTO(rto_code="DL1", rto_name="Delhi RTO", state_code="DL"))
    await db.commit()
    db.add_all([
        # The canonical maker pass: a maker, no real class, so it classifies
        # to 'Other' despite covering every category's volume.
        Registration(**GEO, year=2026, month=1, maker="SOME MAKER", vehicle_class="All",
                     vehicle_category="Other", count=MAKER_PASS, is_supplementary=False),
        # The fuel pass: same 'All' class, a real fuel, also 'Other'.
        Registration(**GEO, year=2026, month=1, vehicle_class="All", fuel_type="PETROL",
                     vehicle_category="Other", count=FUEL_PASS, is_supplementary=True),
        # The only genuinely-Other vehicle here.
        Registration(**GEO, year=2026, month=1, vehicle_class="AGRICULTURAL TRACTOR",
                     vehicle_category="Other", count=REAL_OTHER, is_supplementary=True),
    ])
    await db.commit()


async def test_other_category_counts_only_real_other_vehicles(db_session):
    await _seed(db_session)

    total = (await db_session.execute(
        apply_total_filters(
            select(func.sum(Registration.count)).where(Registration.year == 2026),
            vehicle_category="Other",
        )
    )).scalar()

    # Not MAKER_PASS + FUEL_PASS + REAL_OTHER (100,700), which is what the
    # unguarded filter returned.
    assert total == REAL_OTHER


async def test_a_real_category_is_unaffected_by_the_other_carve_out(db_session):
    # The carve-out must not touch the categories that were always correct:
    # they only ever appear on vehicle_class-dimension rows anyway.
    await _seed(db_session)
    db_session.add(
        Registration(**GEO, year=2026, month=1, vehicle_class="M-CYCLE/SCOOTER",
                     vehicle_category="Two-Wheeler", count=1234, is_supplementary=True)
    )
    await db_session.commit()

    total = (await db_session.execute(
        apply_total_filters(
            select(func.sum(Registration.count)).where(Registration.year == 2026),
            vehicle_category="Two-Wheeler",
        )
    )).scalar()

    assert total == 1234


async def test_other_with_a_fuel_filter_returns_nothing_rather_than_a_national_total(db_session):
    # Both filters together can only be satisfied by the fuel pass, whose
    # vehicle_class='All' rows sum that fuel across every class nationwide --
    # returning the country's petrol total wearing an 'Other' label. Failing
    # to empty is the honest answer, and matches what Two-Wheeler + a fuel
    # already does.
    await _seed(db_session)

    # Composed exactly as the endpoints compose it: apply_total_filters
    # decides which passes are in scope, apply_fuel_group_filter adds the
    # fuel_type condition. Testing only the former would not exercise the
    # combination at all.
    total = (await db_session.execute(
        apply_fuel_group_filter(
            apply_total_filters(
                select(func.sum(Registration.count)).where(Registration.year == 2026),
                vehicle_category="Other", fuel_group="ICE",
            ),
            "ICE",
        )
    )).scalar()

    assert total is None or total == 0
