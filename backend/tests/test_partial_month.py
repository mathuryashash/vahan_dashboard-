"""Partial current month: YoY on /summary/kpis and /yoy/* cuts at the last
COMPLETE scraped month derived from the data (when the newest month was
scraped), never from today's date.

Scenario mirrors prod: data froze on 2026-09-19, so September 2026 holds ~19
days of registrations while September 2025 is a full month.
"""
from datetime import datetime

from app.models.models import RTO, Registration, State

FROZE = datetime(2026, 9, 19, 21, 1)
FULL = datetime(2025, 12, 31, 23, 0)


async def _seed(db, rows, state="Delhi", code="DL", rto="DL1"):
    await db.merge(State(state_code=code, state_name=state))
    await db.merge(RTO(rto_code=rto, rto_name="Test RTO", state_code=code))
    for year, month, count, recorded in rows:
        db.add(Registration(
            state_code=code, state_name=state, rto_code=rto, rto_name="Test RTO", month=month, year=year,
            count=count, vehicle_class="All", maker="HONDA", is_supplementary=False, recorded_at=recorded,
        ))
    await db.commit()


async def _seed_partial_september(db):
    rows = [(2025, m, 1000, FULL) for m in range(1, 13)]
    rows += [(2026, m, 1100, FROZE) for m in range(1, 9)]
    rows += [(2026, 9, 400, FROZE)]  # 19 days of September
    await _seed(db, rows)


async def test_kpis_yoy_excludes_the_partial_month(client, db_session):
    await _seed_partial_september(db_session)
    body = (await client.get("/api/v1/summary/kpis", params={"year": 2026})).json()
    # Headline total still covers everything stored (Jan-Sep).
    assert body["total_this_month"] == 8 * 1100 + 400 == 9200
    # YoY: Jan-Aug 8800 vs Jan-Aug 8000 = +10.0%. Cutting at max(month)=9
    # (the old behaviour) gives 9200 vs 9000 = +2.22%.
    assert body["yoy_growth_percent"] == 10.0, "partial-month regression: 2.22 means Sep was compared"
    assert body["yoy_compare_through_month"] == 8
    assert body["partial_month"] == 9
    assert body["top_state"] == "Delhi" and body["top_state_count"] == 9200


async def test_kpis_complete_month_is_compared_when_scraped_after_month_end(client, db_session):
    rows = [(2025, m, 1000, FULL) for m in range(1, 13)]
    rows += [(2026, m, 1100, datetime(2026, 10, 2, 3, 0)) for m in range(1, 10)]
    await _seed(db_session, rows)
    body = (await client.get("/api/v1/summary/kpis", params={"year": 2026})).json()
    assert body["yoy_compare_through_month"] == 9
    assert body["partial_month"] is None
    assert body["yoy_growth_percent"] == 10.0  # 9900 vs 9000


async def test_kpis_explicit_partial_month_has_no_yoy(client, db_session):
    """N3: kpis?year=2026&month=9 compared 19 days of September against a full
    one (-60% here, -21.95% on prod) and reported partial_month=null."""
    await _seed_partial_september(db_session)
    body = (await client.get("/api/v1/summary/kpis", params={"year": 2026, "month": 9})).json()
    assert body["total_this_month"] == 400
    assert body["yoy_growth_percent"] is None, "partial month must not produce a YoY (-60.0 = regression)"
    assert body["partial_month"] == 9
    assert body["yoy_compare_through_month"] is None


async def test_kpis_explicit_complete_month_is_compared(client, db_session):
    await _seed_partial_september(db_session)
    body = (await client.get("/api/v1/summary/kpis", params={"year": 2026, "month": 8})).json()
    assert body["total_this_month"] == 1100
    assert body["yoy_growth_percent"] == 10.0
    assert body["partial_month"] == 9 and body["yoy_compare_through_month"] == 8


async def test_kpis_yoy_is_null_without_prior_year_data(client, db_session):
    await _seed(db_session, [(2026, m, 1100, FROZE) for m in range(1, 10)])
    body = (await client.get("/api/v1/summary/kpis", params={"year": 2026})).json()
    assert body["total_this_month"] == 9900
    assert body["yoy_growth_percent"] is None, "no prior data is unknown, not 0.0 (flat)"


async def _seed_class_pass(db):
    """Class-pass rows (the ones /categories/ reads), partial September."""
    await db.merge(State(state_code="DL", state_name="Delhi"))
    await db.merge(RTO(rto_code="DL1", rto_name="Test RTO", state_code="DL"))
    def row(year, month, count, cls, cat, rec):
        return Registration(
            state_code="DL", state_name="Delhi", rto_code="DL1", rto_name="Test RTO", month=month, year=year,
            count=count, vehicle_class=cls, vehicle_category=cat, maker=None, is_supplementary=True,
            recorded_at=rec,
        )
    for m in range(1, 13):
        db.add(row(2025, m, 1000, "M-Cycle/Scooter", "Two-Wheeler", FULL))
        db.add(row(2025, m, 500, "Motor Car", "Four-Wheeler", FULL))
    for m in range(1, 9):
        db.add(row(2026, m, 1200, "M-Cycle/Scooter", "Two-Wheeler", FROZE))
        db.add(row(2026, m, 500, "Motor Car", "Four-Wheeler", FROZE))
    db.add(row(2026, 9, 400, "M-Cycle/Scooter", "Two-Wheeler", FROZE))
    db.add(row(2026, 9, 150, "Motor Car", "Four-Wheeler", FROZE))
    # Canonical maker-pass rows: what get_freshness / latest_month read.
    for m in range(1, 10):
        db.add(Registration(
            state_code="DL", state_name="Delhi", rto_code="DL1", rto_name="Test RTO", month=m, year=2026,
            count=1, vehicle_class="All", maker="HONDA", is_supplementary=False, recorded_at=FROZE,
        ))
    await db.commit()


async def test_categories_yoy_cuts_at_last_complete_month(client, db_session):
    """N2: /categories/ still compared Jan-Sep (partial Sep) against a full
    Jan-Sep -- 2W 2026 read +16.74% on prod vs the like-for-like +20.69%."""
    await _seed_class_pass(db_session)
    body = (await client.get("/api/v1/categories/", params={"year": 2026})).json()
    by = {r["vehicle_category"]: r for r in body}
    tw, fw = by["Two-Wheeler"], by["Four-Wheeler"]
    # Headline still covers every stored month (Jan-Sep).
    assert tw["total_count"] == 8 * 1200 + 400 == 10000
    # YoY Jan-Aug: 9600 vs 8000 = +20.0%. Old cut at Sep: 10000 vs 9000 = +11.11%.
    assert tw["yoy_growth"] == 20.0, "11.11 means the partial September was compared"
    assert tw["prev_count"] == 8000
    assert fw["yoy_growth"] == 0.0  # 4000 vs 4000: genuinely flat
    assert tw["yoy_compare_through_month"] == 8 and tw["partial_month"] == 9


async def test_categories_explicit_partial_month_has_no_yoy(client, db_session):
    await _seed_class_pass(db_session)
    body = (await client.get("/api/v1/categories/", params={"year": 2026, "month": 9})).json()
    tw = next(r for r in body if r["vehicle_category"] == "Two-Wheeler")
    assert tw["total_count"] == 400 and tw["yoy_growth"] is None


async def test_kpis_past_year_compares_full_year(client, db_session):
    rows = [(2024, m, 900, FULL) for m in range(1, 13)]
    rows += [(2025, m, 1000, FULL) for m in range(1, 13)]
    rows += [(2026, 1, 5, FROZE)]
    await _seed(db_session, rows)
    body = (await client.get("/api/v1/summary/kpis", params={"year": 2025})).json()
    assert body["total_this_month"] == 12000
    assert body["yoy_compare_through_month"] == 12
    assert body["yoy_growth_percent"] == round((12000 - 10800) / 10800 * 100, 2) == 11.11


async def test_yoy_summary_cuts_at_last_complete_month(client, db_session):
    await _seed_partial_september(db_session)
    data = (await client.get("/api/v1/yoy/summary", params={"year_a": 2025, "year_b": 2026})).json()
    assert data["compare_through_month"] == 8
    assert data["total_2025"] == 8000 and data["total_2026"] == 8800
    assert data["growth_percent"] == 10.0
    assert data["partial_month"] == 9 and data["partial_month_year"] == 2026
    assert data["last_complete_month"] == "2026-08"


async def test_yoy_monthly_withholds_growth_for_partial_month(client, db_session):
    await _seed_partial_september(db_session)
    body = (await client.get("/api/v1/yoy/monthly", params={"year_a": 2025, "year_b": 2026})).json()
    rows = {r["month"]: r for r in body["data"]}
    assert rows[8]["growth_percent"] == 10.0 and rows[8]["is_partial"] is False
    assert rows[9]["year_2026"] == 400
    assert rows[9]["growth_percent"] is None and rows[9]["is_partial"] is True  # not a fake -60%
    assert body["partial_month"] == 9 and body["partial_month_year"] == 2026
    assert body["data_scraped_at"].startswith("2026-09-19T21:01")


# Round 5 P2-1: a month AFTER the newest scraped one (Nov when data ends in
# Sep) compared 0 against a full prior month and read -100%; the partial
# month itself read -88.8% on /month-detail, which had no guard at all.
async def test_kpis_future_month_has_no_yoy(client, db_session):
    await _seed_partial_september(db_session)
    body = (await client.get("/api/v1/summary/kpis", params={"year": 2026, "month": 11})).json()
    assert body["total_this_month"] == 0
    assert body["yoy_growth_percent"] is None, "-100.0 means a future month was compared"
    assert body["month_incomplete"] is True and body["latest_month"] == 9


async def test_month_detail_partial_and_future_months_withhold_yoy(client, db_session):
    await _seed_partial_september(db_session)
    for month in (9, 11):
        body = (await client.get("/api/v1/summary/month-detail", params={"year": 2026, "month": month})).json()
        assert body["month_incomplete"] is True, month
        assert body["month_yoy_growth_percent"] is None, f"month {month}: fake decline"
        assert body["ytd_yoy_growth_percent"] is None, f"month {month}: fake YTD decline"
    body = (await client.get("/api/v1/summary/month-detail", params={"year": 2026, "month": 8})).json()
    assert body["month_incomplete"] is False
    assert body["month_yoy_growth_percent"] == 10.0 and body["ytd_yoy_growth_percent"] == 10.0


async def test_categories_future_month_has_no_yoy(client, db_session):
    await _seed_class_pass(db_session)
    body = (await client.get("/api/v1/categories/", params={"year": 2026, "month": 11})).json()
    assert all(r["yoy_growth"] is None for r in body)
