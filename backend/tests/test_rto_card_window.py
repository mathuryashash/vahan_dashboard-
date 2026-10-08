"""RTO card: `total` and `avg_monthly` must cover the same FY window.

For a category-scoped account the maker rows come from MakerCategoryTotal,
which has no month column, so they span the two calendar years an FY touches.
`total` used to be that sum (UP32 / Four-Wheeler FY2025: 115,220) while
avg_monthly was FY-based (66,518 / 12) -- two windows on one card.
"""
from datetime import datetime

from app.core.auth import get_current_user
from app.main import app
from app.models.models import (
    RTO, MakerCategoryTotal, Registration, State, User, UserRole, UserScope, VehicleCategoryScope,
)

GEO = dict(state_code="UP", state_name="Uttar Pradesh", rto_code="UP32", rto_name="Lucknow")
SIB = dict(state_code="UP", state_name="Uttar Pradesh", rto_code="UP14", rto_name="Ghaziabad")
SCRAPED = datetime(2026, 9, 19, 21, 0)


async def _seed(db):
    await db.merge(State(state_code="UP", state_name="Uttar Pradesh"))
    await db.merge(RTO(rto_code="UP32", rto_name="Lucknow", state_code="UP"))
    await db.merge(RTO(rto_code="UP14", rto_name="Ghaziabad", state_code="UP"))
    await db.commit()
    rows = []
    # Class pass (carries category). FY2025 = Apr 2025 .. Mar 2026.
    # 4W: 100/month in 2025 (all 12 months), 200/month Jan-Sep 2026.
    for m in range(1, 13):
        rows.append(Registration(**GEO, vehicle_class="MOTOR CAR", vehicle_category="Four-Wheeler", year=2025,
                                 month=m, count=100, is_supplementary=True, recorded_at=SCRAPED))
        rows.append(Registration(**GEO, vehicle_class="All", vehicle_category="Other", maker="MARUTI", year=2025,
                                 month=m, count=100, is_supplementary=False, recorded_at=SCRAPED))
    for m in range(1, 10):
        rows.append(Registration(**GEO, vehicle_class="MOTOR CAR", vehicle_category="Four-Wheeler", year=2026,
                                 month=m, count=200, is_supplementary=True, recorded_at=SCRAPED))
        rows.append(Registration(**GEO, vehicle_class="All", vehicle_category="Other", maker="MARUTI", year=2026,
                                 month=m, count=200, is_supplementary=False, recorded_at=SCRAPED))
        # Sibling RTO in the same state -- must never leak into UP32's card.
        rows.append(Registration(**SIB, vehicle_class="MOTOR CAR", vehicle_category="Four-Wheeler", year=2026,
                                 month=m, count=9000, is_supplementary=True, recorded_at=SCRAPED))
    # Crosstab: calendar-year totals (2025 = 1200, 2026 = 1800) for two makers.
    rows += [
        MakerCategoryTotal(**GEO, year=2025, maker="MARUTI", vehicle_class="MOTOR CAR",
                           vehicle_category="Four-Wheeler", count=900),
        MakerCategoryTotal(**GEO, year=2025, maker="TATA", vehicle_class="MOTOR CAR",
                           vehicle_category="Four-Wheeler", count=300),
        MakerCategoryTotal(**GEO, year=2026, maker="MARUTI", vehicle_class="MOTOR CAR",
                           vehicle_category="Four-Wheeler", count=1500),
        MakerCategoryTotal(**GEO, year=2026, maker="TATA", vehicle_class="MOTOR CAR",
                           vehicle_category="Four-Wheeler", count=300),
        MakerCategoryTotal(**SIB, year=2026, maker="MARUTI", vehicle_class="MOTOR CAR",
                           vehicle_category="Four-Wheeler", count=99999),
    ]
    db.add_all(rows)
    await db.commit()


def _as_four_wheeler():
    app.dependency_overrides[get_current_user] = lambda: User(
        id=7, email="fw@example.com", role=UserRole.ANALYST, is_active=True,
        scope_type=UserScope.NATIONAL, scope_vehicle_category=VehicleCategoryScope.FOUR_WHEELER,
    )


async def test_category_account_total_uses_the_fy_window_like_avg(client, db_session):
    await _seed(db_session)
    _as_four_wheeler()
    body = (await client.get("/api/v1/rto/UP32/analysis", params={"year": 2025})).json()
    # FY2025 = Apr-Dec 2025 (9 x 100) + Jan-Mar 2026 (3 x 200) = 1,500 over 12 months.
    assert body["total"] == 1500, "total must be the FY window (it was the 2-calendar-year crosstab sum, 3000)"
    assert body["months_with_data"] == 12
    assert body["avg_monthly"] == 125.0
    assert body["total"] == round(body["avg_monthly"] * body["months_with_data"])
    # Shares keep the crosstab basis: MARUTI 2400 / 3000, TATA 600 / 3000.
    assert body["maker_window_total"] == 3000
    shares = {m["maker"]: (m["count"], m["share_percent"]) for m in body["makers"]}
    assert shares == {"MARUTI": (2400, 80.0), "TATA": (600, 20.0)}
    assert body["maker_period"] == "calendar_years_spanned"


async def test_unscoped_total_unchanged_and_last_scraped_month_exposed(client, db_session):
    await _seed(db_session)
    fy25 = (await client.get("/api/v1/rto/UP32/analysis", params={"year": 2025})).json()
    assert fy25["total"] == fy25["maker_window_total"] == 9 * 100 + 3 * 200 == 1500
    assert fy25["makers"] == [{"maker": "MARUTI", "count": 1500, "share_percent": 100.0}]
    assert fy25["last_scraped_month"] == "2026-09"
    assert fy25["fy_months_scraped"] == 12

    # FY2026 = Apr 2026 .. Mar 2027: only Apr-Sep scraped -> 6 months, not 12.
    fy26 = (await client.get("/api/v1/rto/UP32/analysis", params={"year": 2026})).json()
    assert fy26["total"] == 6 * 200
    assert fy26["months_with_data"] == 6
    assert fy26["fy_months_scraped"] == 6
    assert fy26["last_scraped_month"] == "2026-09"
