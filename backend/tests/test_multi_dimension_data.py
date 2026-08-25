"""End-to-end checks for the multi-pivot real-data model: the live scraper
can only capture one Y-axis dimension (Maker, Vehicle Class, or Fuel) per RTO
visit, so a single RTO/month's registrations end up represented by several
independently-complete rows (see Registration.is_supplementary and
app.services.scraper_service.persist_rto_batch). This file verifies the two
things that would silently corrupt the dashboard if handled wrong:

1. Aggregate "total registrations" endpoints must count each RTO/month once,
   not once per dimension pass (no triple-counting).
2. Category/fuel breakdown endpoints must still show the real breakdown from
   the supplementary rows, not just the 'All' placeholder from the maker pass.
"""
from app.models.models import Registration
from app.services.scraper_service import persist_rto_batch
from scraper.run_full_scrape import _purge_synthetic_for_state


async def _seed_real_rto(db_session, state_name="Delhi", state_code="DL", rto_code="DL1", rto_name="Test RTO"):
    """One RTO/month's registrations as the live scraper would actually
    persist them: a maker pass (100 total) plus vehicle_class and fuel
    breakdown passes that independently also sum to 100."""
    maker_batch = {
        "state_name": state_name, "rto_code": rto_code, "rto_name": rto_name,
        "records": [
            {"label": "HONDA", "month": 1, "year": 2026, "count": 60},
            {"label": "TVS", "month": 1, "year": 2026, "count": 40},
        ],
    }
    vc_batch = {
        "state_name": state_name, "rto_code": rto_code, "rto_name": rto_name,
        "records": [
            {"label": "Two-Wheeler", "month": 1, "year": 2026, "count": 70},
            {"label": "Motor Car/Jeep/Taxi", "month": 1, "year": 2026, "count": 30},
        ],
    }
    fuel_batch = {
        "state_name": state_name, "rto_code": rto_code, "rto_name": rto_name,
        "records": [
            {"label": "PETROL", "month": 1, "year": 2026, "count": 90},
            {"label": "ELECTRIC", "month": 1, "year": 2026, "count": 10},
        ],
    }
    await persist_rto_batch(db_session, maker_batch, state_code=state_code, dimension="maker")
    await persist_rto_batch(db_session, vc_batch, state_code=state_code, dimension="vehicle_class")
    await persist_rto_batch(db_session, fuel_batch, state_code=state_code, dimension="fuel")
    await db_session.commit()


async def test_kpis_do_not_triple_count_across_dimensions(client, db_session):
    await _seed_real_rto(db_session)

    response = await client.get("/api/v1/summary/kpis", params={"year": 2026, "month": 1})
    assert response.status_code == 200
    data = response.json()
    # 100 (from the maker pass), not 300 (maker + vehicle_class + fuel all summed).
    assert data["total_this_month"] == 100


async def test_kpis_filtered_by_real_vehicle_class_reads_the_vehicle_class_pass(client, db_session):
    """Regression test: the maker-pass (is_supplementary=False) always stores
    vehicle_class='All', so it can never match a specific class filter. KPIs
    used to unconditionally exclude supplementary rows, which meant filtering
    by any real vehicle_class (e.g. 'Motor Car/Jeep/Taxi') silently zeroed out
    every total for live-scraped years -- the only rows that ever carry a
    real class are the vehicle_class-dimension pass."""
    await _seed_real_rto(db_session)

    response = await client.get(
        "/api/v1/summary/kpis", params={"year": 2026, "month": 1, "vehicle_class": "Motor Car/Jeep/Taxi"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_this_month"] == 30


async def test_trend_does_not_triple_count(client, db_session):
    await _seed_real_rto(db_session)

    response = await client.get("/api/v1/summary/trend", params={"year": 2026})
    assert response.status_code == 200
    rows = response.json()
    assert rows == [{"month": 1, "count": 100}]


async def test_state_ranking_does_not_triple_count(client, db_session):
    await _seed_real_rto(db_session)

    response = await client.get("/api/v1/summary/state-ranking", params={"year": 2026, "month": 1})
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["total_count"] == 100


async def test_all_states_comparison_share_uses_national_total(client, db_session):
    db_session.add_all([
        Registration(state_code="DL", state_name="Delhi", rto_code="DL1", month=1, year=2026, vehicle_class="All", maker="A", count=100),
        Registration(state_code="MH", state_name="Maharashtra", rto_code="MH1", month=1, year=2026, vehicle_class="All", maker="B", count=300),
    ])
    await db_session.commit()

    response = await client.get("/api/v1/comparison/all-states", params={"year": 2026, "limit": 1})
    assert response.status_code == 200
    row = response.json()[0]
    assert row["state_name"] == "Maharashtra"
    assert row["share_percent"] == 75.0


async def test_categories_breakdown_groups_by_broad_vehicle_category(client, db_session):
    await _seed_real_rto(db_session)

    response = await client.get("/api/v1/categories/", params={"year": 2026, "month": 1})
    assert response.status_code == 200
    rows = {r["vehicle_category"]: r["total_count"] for r in response.json()}
    # classify_vehicle regroups the real vehicle_class breakdown into broad
    # categories -- Two-Wheeler stays Two-Wheeler, Motor Car/Jeep/Taxi becomes
    # Four-Wheeler.
    assert rows == {"Two-Wheeler": 70, "Four-Wheeler": 30}
    assert "All" not in rows


async def test_categories_breakdown_raw_flag_returns_original_vehicle_class(client, db_session):
    await _seed_real_rto(db_session)

    response = await client.get("/api/v1/categories/", params={"year": 2026, "month": 1, "raw": True})
    assert response.status_code == 200
    rows = {r["vehicle_class"]: r["total_count"] for r in response.json()}
    assert rows == {"Two-Wheeler": 70, "Motor Car/Jeep/Taxi": 30}


async def test_fuel_breakdown_uses_fuel_dimension(client, db_session):
    await _seed_real_rto(db_session)

    response = await client.get("/api/v1/categories/fuel-breakdown", params={"year": 2026, "month": 1})
    assert response.status_code == 200
    rows = {r["fuel_type"]: r["count"] for r in response.json()}
    # Raw VAHAN fuel_type values grouped into the handful of categories
    # people actually compare -- see query_filters.fuel_category.
    assert rows == {"Petrol": 90, "EV": 10}


async def test_fuel_breakdown_filters_by_fuel_group(client, db_session):
    await _seed_real_rto(db_session)  # PETROL: 90, ELECTRIC: 10

    response = await client.get(
        "/api/v1/categories/fuel-breakdown", params={"year": 2026, "month": 1, "fuel_group": "EV"}
    )
    assert response.status_code == 200
    rows = {r["fuel_type"]: r["count"] for r in response.json()}
    assert rows == {"EV": 10}


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


async def test_top_makers_unaffected_by_supplementary_rows(client, db_session):
    await _seed_real_rto(db_session)

    response = await client.get("/api/v1/categories/top-makers", params={"year": 2026, "month": 1})
    assert response.status_code == 200
    rows = {r["maker"]: r["count"] for r in response.json()}
    assert rows == {"HONDA": 60, "TVS": 40}


async def test_purge_synthetic_does_not_delete_real_vehicle_class_rows(db_session):
    """Regression test: _purge_synthetic_for_state used to key off vehicle_class
    != 'All' alone, which also matches real vehicle_class-dimension rows (they
    legitimately carry a real class label, not 'All'). That silently wiped a
    state's real vehicle_class breakdown the moment its maker pass next
    completed. The fix requires is_supplementary=False too, since only
    old-style synthetic seed rows and the maker pass satisfy that."""
    await _seed_real_rto(db_session, state_name="Delhi", rto_code="DL1")

    # Old-style synthetic seed row: broken out by class, is_supplementary defaults False.
    db_session.add(Registration(
        state_code="DL", state_name="Delhi", rto_code="DL1", rto_name="Test RTO",
        month=1, year=2026, count=999, vehicle_class="Three-Wheeler", maker=None, fuel_type=None,
        is_supplementary=False,
    ))
    await db_session.commit()

    purged = await _purge_synthetic_for_state(db_session, "Delhi", 2026)

    assert purged == 1  # only the synthetic "Three-Wheeler" row

    from sqlalchemy import select
    result = await db_session.execute(
        select(Registration.vehicle_class, Registration.is_supplementary)
        .where(Registration.state_name == "Delhi", Registration.year == 2026, Registration.vehicle_class != "All")
    )
    remaining = set(result.all())
    # The real vehicle_class-dimension rows survive; only the synthetic one is gone.
    assert remaining == {("Two-Wheeler", True), ("Motor Car/Jeep/Taxi", True)}
