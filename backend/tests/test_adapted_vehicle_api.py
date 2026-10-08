"""End-to-end proof that a category-filtered API call returns the corrected
numbers after ADAPTED VEHICLE moved from Four-Wheeler to Other in 2026-09.

The unit tests in test_adapted_vehicle_classification.py pin the mapping
function and the migration. Neither touches a router, so neither would have
caught the original bug at the layer the customer actually hits: a
Four-Wheeler-scoped OEM account calling /summary/kpis and being served
adapted scooters inside its car volume.

This is that test. It asserts VALUES -- the exact totals -- because the
original defect returned a plausible number, not an error.
"""
from app.core.auth import get_current_user
from app.main import app
from app.models.models import RTO, Registration, State, User, UserScope

GEO = dict(state_code="DL", state_name="Delhi", rto_code="DL1", rto_name="Delhi RTO")

MOTOR_CAR = 5_000      # unambiguously Four-Wheeler
SCOOTER = 9_000        # unambiguously Two-Wheeler
ADAPTED = 137          # the disputed class -- Other since 2026-09


async def _seed(db):
    await db.merge(State(state_code="DL", state_name="Delhi"))
    await db.merge(RTO(rto_code="DL1", rto_name="Delhi RTO", state_code="DL"))
    await db.commit()
    db.add_all([
        Registration(**GEO, year=2026, month=1, vehicle_class="MOTOR CAR",
                     vehicle_category="Four-Wheeler", count=MOTOR_CAR, is_supplementary=True),
        Registration(**GEO, year=2026, month=1, vehicle_class="M-CYCLE/SCOOTER",
                     vehicle_category="Two-Wheeler", count=SCOOTER, is_supplementary=True),
        Registration(**GEO, year=2026, month=1, vehicle_class="ADAPTED VEHICLE",
                     vehicle_category="Other", count=ADAPTED, is_supplementary=True),
    ])
    await db.commit()


def _login_national():
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1, role="analyst", is_active=True, scope_type=UserScope.NATIONAL,
    )


def _reset():
    app.dependency_overrides[get_current_user] = lambda: User(
        id=0, role="admin", is_active=True, scope_type=UserScope.NATIONAL,
    )


async def test_four_wheeler_kpis_exclude_adapted_vehicles(client, db_session):
    """The regression this whole change exists to prevent.

    Before 2026-09 this returned MOTOR_CAR + ADAPTED. A customer billed on
    the Four-Wheeler segment was charged for, and planned against, 137 units
    that are mostly adapted scooters.
    """
    await _seed(db_session)
    _login_national()
    try:
        r = await client.get(
            "/api/v1/summary/kpis", params={"year": 2026, "vehicle_category": "Four-Wheeler"}
        )
        assert r.status_code == 200
        assert r.json()["total_this_month"] == MOTOR_CAR, (
            f"Four-Wheeler returned {r.json()['total_this_month']}, expected {MOTOR_CAR}. "
            f"If it is {MOTOR_CAR + ADAPTED}, ADAPTED VEHICLE has been mapped back "
            "to Four-Wheeler -- see _VEHICLE_CATEGORY_MAP."
        )
    finally:
        _reset()


async def test_two_wheeler_kpis_also_exclude_adapted_vehicles(client, db_session):
    """The over-correction guard.

    79.7% of adapted vehicles belong to two-wheeler makers, so the tempting
    fix is to move them to Two-Wheeler. That would be the same error pointed
    the other way -- Maruti's adapted vehicles are cars.
    """
    await _seed(db_session)
    _login_national()
    try:
        r = await client.get(
            "/api/v1/summary/kpis", params={"year": 2026, "vehicle_category": "Two-Wheeler"}
        )
        assert r.status_code == 200
        assert r.json()["total_this_month"] == SCOOTER, (
            f"Two-Wheeler returned {r.json()['total_this_month']}, expected {SCOOTER}"
        )
    finally:
        _reset()


async def test_other_kpis_include_adapted_vehicles_exactly_once(client, db_session):
    """Where the volume actually went -- and it is not double counted.

    'Other' is the one category the canonical maker pass and the fuel pass
    also carry (classify_vehicle('All') returns 'Other'), which is why
    apply_total_filters carves out vehicle_class='All'. Adapted rows carry a
    real vehicle_class, so they survive that carve-out and count once.
    """
    await _seed(db_session)
    _login_national()
    try:
        r = await client.get(
            "/api/v1/summary/kpis", params={"year": 2026, "vehicle_category": "Other"}
        )
        assert r.status_code == 200
        assert r.json()["total_this_month"] == ADAPTED, (
            f"Other returned {r.json()['total_this_month']}, expected exactly {ADAPTED}"
        )
    finally:
        _reset()


async def test_category_totals_still_sum_to_the_whole(client, db_session):
    """Conservation at the API layer: reclassifying moves volume, never
    creates or destroys it. If the three categories stop summing to the
    total, a row has been counted twice or dropped."""
    await _seed(db_session)
    _login_national()
    try:
        totals = {}
        for category in ("Four-Wheeler", "Two-Wheeler", "Other"):
            r = await client.get(
                "/api/v1/summary/kpis", params={"year": 2026, "vehicle_category": category}
            )
            totals[category] = r.json()["total_this_month"]
        assert sum(totals.values()) == MOTOR_CAR + SCOOTER + ADAPTED, (
            f"categories summed to {sum(totals.values())}, expected "
            f"{MOTOR_CAR + SCOOTER + ADAPTED}: {totals}"
        )
    finally:
        _reset()
