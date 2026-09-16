"""A year can look complete in aggregate while individual makers are missing
from most of the country -- which is exactly what a dropped-pagination scrape
left behind in production (Bajaj Auto recorded in 173 of ~1,400 RTOs for 2025
against 1,384 for 2026, understating it roughly 20x, while TVS was fine at
1,365). Nothing year-level or table-level can see that, so this covers the
per-maker check that can.
"""
from app.core.query_filters import makers_with_coverage_gaps
from app.models.models import MakerCategoryTotal, RTO, State

MAKERS = ["WIDE MAKER", "NARROW MAKER"]
MAX_RTOS = 500


async def _seed_geo(db_session):
    """Parent rows for the rto_code/state_code foreign keys, committed before
    the children -- merge() alone leaves them pending in the same flush."""
    await db_session.merge(State(state_code="DL", state_name="Delhi"))
    for i in range(MAX_RTOS):
        await db_session.merge(RTO(rto_code=f"DL{i}", rto_name=f"RTO {i}", state_code="DL"))
    await db_session.commit()


def _rows(year: int, maker: str, rtos: int):
    """One row per RTO, so distinct-RTO coverage is `rtos`."""
    return [
        MakerCategoryTotal(
            state_code="DL", state_name="Delhi", rto_code=f"DL{i}", rto_name=f"RTO {i}",
            year=year, maker=maker, vehicle_class="M-CYCLE/SCOOTER",
            vehicle_category="Two-Wheeler", count=100,
        )
        for i in range(rtos)
    ]


async def test_flags_a_maker_that_collapses_to_a_fraction_of_its_own_rtos(db_session):
    await _seed_geo(db_session)
    db_session.add_all(
        _rows(2025, "WIDE MAKER", 100) + _rows(2026, "WIDE MAKER", 95)
        # Same maker universe, but 2026 reaches a tenth of the RTOs it did in
        # 2025: a scrape gap, not a real collapse.
        + _rows(2025, "NARROW MAKER", 100) + _rows(2026, "NARROW MAKER", 10)
    )
    await db_session.commit()

    gaps = await makers_with_coverage_gaps(db_session, MakerCategoryTotal, 2026, MAKERS)

    assert gaps == {"NARROW MAKER"}


async def test_a_consistently_small_maker_is_not_flagged(db_session):
    # Compared against ITSELF, not against bigger makers -- a genuinely
    # regional maker must not be branded incomplete just for being regional.
    await _seed_geo(db_session)
    db_session.add_all(
        _rows(2025, "WIDE MAKER", 500) + _rows(2026, "WIDE MAKER", 480)
        + _rows(2025, "NARROW MAKER", 8) + _rows(2026, "NARROW MAKER", 8)
    )
    await db_session.commit()

    gaps = await makers_with_coverage_gaps(db_session, MakerCategoryTotal, 2026, MAKERS)

    assert gaps == set()


async def test_rto_scoped_caller_gets_nothing(db_session):
    # "How many RTOs does this cover" has only one possible answer for an
    # RTO-scoped account, so the check would flag every maker in sight.
    await _seed_geo(db_session)
    db_session.add_all(_rows(2025, "NARROW MAKER", 100) + _rows(2026, "NARROW MAKER", 1))
    await db_session.commit()

    gaps = await makers_with_coverage_gaps(
        db_session, MakerCategoryTotal, 2026, MAKERS, rto_code="DL0"
    )

    assert gaps == set()
