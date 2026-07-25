from app.models.models import Registration


def _reg(year, month, count, state_code="AP", state_name="Andhra Pradesh", vehicle_class="Two-Wheeler"):
    return Registration(
        state_code=state_code,
        state_name=state_name,
        month=month,
        year=year,
        vehicle_class=vehicle_class,
        count=count,
    )


async def test_month_detail_returns_month_and_ytd_with_yoy(client, db_session):
    # 2026: Jan 1000, Feb 500, Mar 800 (real month totals, no daily breakdown).
    db_session.add(_reg(2026, 1, 1000))
    db_session.add(_reg(2026, 2, 500))
    db_session.add(_reg(2026, 3, 800))
    # 2025: same months, smaller counts.
    db_session.add(_reg(2025, 1, 800))
    db_session.add(_reg(2025, 2, 400))
    db_session.add(_reg(2025, 3, 700))
    await db_session.commit()

    response = await client.get("/api/v1/summary/month-detail", params={"year": 2026, "month": 3})
    assert response.status_code == 200
    data = response.json()

    assert data["year"] == 2026
    assert data["month"] == 3
    assert data["month_count"] == 800
    assert data["month_yoy_growth_percent"] == round((800 - 700) / 700 * 100, 2)
    assert data["ytd_count"] == 2300  # Jan (1000) + Feb (500) + Mar (800)
    ytd_prev = 800 + 400 + 700  # 1900
    assert data["ytd_yoy_growth_percent"] == round((2300 - ytd_prev) / ytd_prev * 100, 2)


async def test_month_detail_null_growth_when_no_prior_year_data(client, db_session):
    db_session.add(_reg(2026, 5, 300))
    await db_session.commit()

    response = await client.get("/api/v1/summary/month-detail", params={"year": 2026, "month": 5})
    assert response.status_code == 200
    data = response.json()

    assert data["month_count"] == 300
    assert data["month_yoy_growth_percent"] is None
    assert data["ytd_count"] == 300
    assert data["ytd_yoy_growth_percent"] is None


async def test_month_detail_respects_filters(client, db_session):
    db_session.add(_reg(2026, 6, 100, vehicle_class="Two-Wheeler"))
    db_session.add(_reg(2026, 6, 200, vehicle_class="Bus"))
    db_session.add(_reg(2025, 6, 80, vehicle_class="Two-Wheeler"))
    await db_session.commit()

    response = await client.get(
        "/api/v1/summary/month-detail",
        params={"year": 2026, "month": 6, "vehicle_class": "Two-Wheeler"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["month_count"] == 100
    assert data["month_yoy_growth_percent"] == 25.0
