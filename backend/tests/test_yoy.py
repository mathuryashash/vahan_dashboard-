"""Regression tests for the year-over-year endpoints' month-capping logic.

Comparing a full prior year against an in-progress current year (e.g. 12
months of 2025 vs 7 months of 2026) without capping both periods at the same
latest month produces a nonsensical, deeply negative "growth" number -- the
same class of bug summary.get_dashboard_kpis already guards against.
"""
from app.models.models import Registration


async def _seed_month(db_session, year, month, count, state_name="Delhi", rto_code="DL1"):
    db_session.add(Registration(
        state_code="DL", state_name=state_name, rto_code=rto_code, rto_name="Test RTO",
        month=month, year=year, count=count, vehicle_class="All", maker="HONDA", fuel_type=None,
        is_supplementary=False,
    ))


async def test_yoy_summary_caps_partial_current_year(client, db_session):
    # 2025: full 12 months, 1000/month = 12000 total.
    for m in range(1, 13):
        await _seed_month(db_session, 2025, m, 1000)
    # 2026: only Jan-Jul so far, 1100/month (a real 10% MoM gain).
    for m in range(1, 8):
        await _seed_month(db_session, 2026, m, 1100)
    await db_session.commit()

    response = await client.get("/api/v1/yoy/summary", params={"year_a": 2025, "year_b": 2026})
    assert response.status_code == 200
    data = response.json()

    # Capped at month 7: 7*1000 = 7000 vs 7*1100 = 7700, not 12000 vs 7700.
    assert data["total_2025"] == 7000
    assert data["total_2026"] == 7700
    assert data["compare_through_month"] == 7
    assert data["growth_percent"] == 10.0


async def test_yoy_monthly_reports_null_growth_for_unreached_months(client, db_session):
    for m in range(1, 13):
        await _seed_month(db_session, 2025, m, 1000)
    for m in range(1, 8):
        await _seed_month(db_session, 2026, m, 1100)
    await db_session.commit()

    response = await client.get("/api/v1/yoy/monthly", params={"year_a": 2025, "year_b": 2026})
    assert response.status_code == 200
    rows = {r["month"]: r for r in response.json()["data"]}

    # Months both years have: a real growth figure.
    assert rows[1]["growth_percent"] == 10.0
    # Months 2026 hasn't reached yet: null, not a fake ~-100% decline.
    assert rows[8]["growth_percent"] is None
    assert rows[8]["year_2026"] == 0
