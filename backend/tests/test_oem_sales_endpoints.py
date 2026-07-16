from app.models.models import OEMMonthlySales


async def _seed(db_session):
    db_session.add_all([
        OEMMonthlySales(source="FADA", year=2026, month=6, category="Two-Wheeler", maker="HERO MOTOCORP LTD", count=472144, share_percent=25.82, source_document="June 2026 release"),
        OEMMonthlySales(source="FADA", year=2026, month=6, category="Two-Wheeler", maker="TVS MOTOR COMPANY LTD", count=359243, share_percent=19.65, source_document="June 2026 release"),
        OEMMonthlySales(source="FADA", year=2026, month=5, category="Two-Wheeler", maker="HERO MOTOCORP LTD", count=450000, share_percent=24.0, source_document="May 2026 release"),
        OEMMonthlySales(source="FADA", year=2026, month=6, category="PV", maker="MARUTI SUZUKI INDIA LTD", count=167834, share_percent=40.85, source_document="June 2026 release"),
    ])
    await db_session.commit()


async def test_get_oem_categories(client, db_session):
    await _seed(db_session)
    response = await client.get("/api/v1/oem-sales/categories")
    assert response.status_code == 200
    assert set(response.json()) == {"Two-Wheeler", "PV"}


async def test_get_oem_monthly(client, db_session):
    await _seed(db_session)
    response = await client.get("/api/v1/oem-sales/monthly", params={"category": "Two-Wheeler", "year": 2026, "month": 6})
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 2
    hero = next(r for r in rows if r["maker"] == "HERO MOTOCORP LTD")
    assert hero["count"] == 472144
    assert hero["share_percent"] == 25.82


async def test_get_oem_trend(client, db_session):
    await _seed(db_session)
    response = await client.get("/api/v1/oem-sales/trend", params={"maker": "HERO MOTOCORP LTD", "category": "Two-Wheeler"})
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 2
    by_month = {r["month"]: r["count"] for r in rows}
    assert by_month == {5: 450000, 6: 472144}
