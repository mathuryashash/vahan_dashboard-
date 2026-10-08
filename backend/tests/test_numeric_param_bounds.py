"""Numeric query parameters must be rejected at the edge, not by the driver.

Every year/month/day parameter is bound into a query against an INTEGER
(int32) column. asyncpg encodes bind parameters client-side, so a value
outside int32 never becomes a comparison that matches nothing -- it raises
OverflowError inside the driver, surfacing as a DBAPIError that app.main's
catch-all turns into a 500. Before these bounds existed, every endpoint
below returned 500 for `year=99999999999`: a misleading status code, and
error-log noise any authenticated caller could generate at will.

422 is the assertion that matters (FastAPI rejected it during validation);
200 would mean the bound is missing and the value reached SQL.
"""
import pytest


# (path, param) -- one per module that takes a bounded numeric parameter.
_OVERFLOW_CASES = [
    ("/api/v1/summary/trend", "year"),
    ("/api/v1/summary/kpis", "year"),
    ("/api/v1/summary/state-ranking", "year"),
    ("/api/v1/registrations/", "year"),
    ("/api/v1/yoy/monthly", "year_a"),
    ("/api/v1/yoy/monthly", "year_b"),
    ("/api/v1/yoy/summary", "year_a"),
    ("/api/v1/categories/", "year"),
    ("/api/v1/comparison/all-states", "year"),
    ("/api/v1/geo/states/MH/districts", "year"),
]

_INT32_OVERFLOW = 99999999999


@pytest.mark.parametrize("path,param", _OVERFLOW_CASES)
async def test_year_above_int32_is_rejected_not_a_500(client, path, param):
    resp = await client.get(f"{path}?{param}={_INT32_OVERFLOW}")
    assert resp.status_code == 422, (
        f"{path}?{param} returned {resp.status_code}; an out-of-int32 year must be "
        f"rejected by validation, not handed to asyncpg. Body: {resp.text[:200]}"
    )


@pytest.mark.parametrize("path,param", _OVERFLOW_CASES)
async def test_year_below_min_is_rejected(client, path, param):
    resp = await client.get(f"{path}?{param}=-1")
    assert resp.status_code == 422, f"{path}?{param}=-1 returned {resp.status_code}"


@pytest.mark.parametrize(
    "path,query",
    [
        ("/api/v1/summary/kpis", "month=9999"),
        ("/api/v1/summary/kpis", "month=0"),
        ("/api/v1/registrations/", "month=13"),
        ("/api/v1/registrations/", "day=999999"),
        ("/api/v1/registrations/", "day=0"),
        ("/api/v1/categories/", "month=99"),
    ],
)
async def test_month_and_day_are_bounded(client, path, query):
    resp = await client.get(f"{path}?{query}")
    assert resp.status_code == 422, f"{path}?{query} returned {resp.status_code}"


async def test_valid_year_still_works(client):
    """The bound must not reject real input -- 1947..2100 covers every year
    this data spans plus the in-progress one, so a legitimate request is
    unaffected."""
    for year in (1947, 2003, 2026, 2100):
        resp = await client.get(f"/api/v1/summary/trend?year={year}")
        assert resp.status_code == 200, f"year={year} returned {resp.status_code}"
