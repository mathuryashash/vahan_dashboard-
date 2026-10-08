from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.query_filters import apply_fuel_group_filter, apply_total_filters
from app.core.query_filters import fuel_group as query_fuel_group
from app.core.scope import enforce_state, get_effective_category, scoped_rto, scoped_state
from app.core.cache import TTLCache, single_flight
from app.models.models import FuelCategoryTotal, MakerCategoryTotal, Registration, User, UserScope
from app.schemas.schemas import StateComparisonData, StateComparisonRanking
from app.core.validation import MAX_YEAR, MIN_YEAR

router = APIRouter()

_DEFAULT_YEAR = datetime.now().year

# One of the endpoints measured slow enough to flag earlier this session
# (a full-country GROUP BY over 26M+ rows). Keyed on (year, limit,
# scope_type, scope_state_name) rather than the user object itself -- two
# different national users must share a cache entry, but a state-scoped
# user's clamped-to-their-state result must never be served to a national
# caller (or vice versa).
_ALL_STATES_CACHE_TTL_SECONDS = 90
_all_states_cache = TTLCache(_ALL_STATES_CACHE_TTL_SECONDS)

# /states was the one hot aggregate in this file without a cache. Measured at
# ~127ms per state against the live 21.7M-row table (no index carries
# state_name + year + vehicle_category together, so Postgres bitmap-ANDs two
# large index scans), and the page fires it for state_a and state_b
# sequentially -- ~250ms on every single view, with nothing absorbing repeat
# visits. Same keying rule as _all_states_cache: every scope component that
# changes the result is in the key, or one account's slice gets served to
# another.
_COMPARE_CACHE_TTL_SECONDS = 90
_compare_cache = TTLCache(_COMPARE_CACHE_TTL_SECONDS)


@router.get("/states", response_model=StateComparisonData)
@single_flight
async def compare_states(
    state_a: str,
    state_b: str | None = None,
    year: int = Query(_DEFAULT_YEAR, ge=MIN_YEAR, le=MAX_YEAR),
    vehicle_category: str | None = Depends(get_effective_category),
    fuel_group: str | None = None,
    user_rto: str | None = Depends(scoped_rto),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    state_a = enforce_state(user, state_a)
    state_b = enforce_state(user, state_b)

    # Keyed on the post-enforce_state values, so a scoped account's clamped
    # result can never be handed to a caller who asked for a different state.
    cache_key = (state_a, state_b, year, vehicle_category, fuel_group, user_rto)
    cached = _compare_cache.get(cache_key)
    if cached is not None:
        return cached

    def _monthly_query(state_name: str):
        # apply_total_filters (not a bare exclude_supplementary) -- the
        # canonical maker-pass always stores vehicle_class='All', which only
        # ever classifies to vehicle_category='Other', never a real category
        # like Two-Wheeler. A vehicle_category/fuel_group filter has to read
        # the vehicle_class-dimension or fuel-dimension pass instead (the
        # only rows that ever carry a real category/fuel value) -- same fix
        # already applied to summary.py's kpis/trend. Plain
        # exclude_supplementary here would have silently zeroed out every
        # category-filtered state comparison.
        query = apply_fuel_group_filter(
            apply_total_filters(
                select(Registration.month, func.sum(Registration.count).label("count"))
                .where(Registration.year == year, Registration.state_name == state_name),
                rto_code=user_rto, vehicle_category=vehicle_category, fuel_group=fuel_group,
            ),
            fuel_group,
        )
        return query.group_by(Registration.month).order_by(Registration.month)

    result_a = await db.execute(_monthly_query(state_a))
    rows_a = result_a.all()

    result_b = await db.execute(_monthly_query(state_b)) if state_b else None
    rows_b = result_b.all() if result_b else []

    response = {
        "state_a": state_a,
        "state_b": state_b,
        "year": year,
        "state_a_data": [{"month": r[0], "count": r[1]} for r in rows_a],
        "state_b_data": [{"month": r[0], "count": r[1]} for r in rows_b]
        if rows_b
        else [],
    }
    _compare_cache.set(cache_key, response)
    return response


@router.get("/all-states", response_model=list[StateComparisonRanking])
@single_flight
async def get_all_states_comparison(
    year: int = Query(_DEFAULT_YEAR, ge=MIN_YEAR, le=MAX_YEAR),
    # Bounded, matching summary.get_state_ranking and categories.get_top_makers.
    # A bare `int` let limit=-1 through to Postgres ("LIMIT must not be
    # negative") as an opaque 500, and let an unbounded positive value both
    # remove the result cap and mint unlimited distinct TTLCache keys.
    limit: int = Query(default=36, ge=1, le=200),
    vehicle_category: str | None = Depends(get_effective_category),
    fuel_group: str | None = None,
    user_rto: str | None = Depends(scoped_rto),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    cache_key = (year, limit, vehicle_category, fuel_group, user.scope_type, user.scope_state_name, user_rto)
    cached = _all_states_cache.get(cache_key)
    if cached is not None:
        return cached

    # Same apply_total_filters requirement as compare_states above -- a bare
    # exclude_supplementary would silently zero out any category/fuel_group
    # filter (the canonical maker-pass never carries a real one).
    base_query = apply_fuel_group_filter(
        apply_total_filters(
            select(Registration.state_name, func.sum(Registration.count).label("total"))
            .where(Registration.year == year),
            rto_code=user_rto, vehicle_category=vehicle_category, fuel_group=fuel_group,
        ),
        fuel_group,
    )
    total_query = apply_fuel_group_filter(
        apply_total_filters(
            select(func.sum(Registration.count)).where(Registration.year == year),
            rto_code=user_rto, vehicle_category=vehicle_category, fuel_group=fuel_group,
        ),
        fuel_group,
    )
    # A state/RTO-scoped user comparing "all states" only has one state to
    # see -- clamp both the ranking and its denominator to it, rather than
    # 403ing an endpoint the frontend calls unconditionally.
    if user.scope_type != UserScope.NATIONAL:
        base_query = base_query.where(Registration.state_name == user.scope_state_name)
        total_query = total_query.where(Registration.state_name == user.scope_state_name)

    result = await db.execute(
        base_query.group_by(Registration.state_name).order_by(func.sum(Registration.count).desc()).limit(limit)
    )
    rows = result.all()
    # A state's share must be calculated against the whole country, not just
    # the top-N rows returned to the chart. The previous denominator made the
    # top five states always add up to 100%, which is misleading.
    total_result = await db.execute(total_query)
    total = total_result.scalar() or 0
    comparison = [
        {
            "state_name": r[0],
            "count": r[1],
            "share_percent": round((r[1] / total * 100) if total > 0 else 0, 2),
        }
        for r in rows
    ]
    _all_states_cache.set(cache_key, comparison)
    return comparison


# Category x powertrain per state. The raw registrations table cannot answer
# it (the class pass carries the category, the fuel pass carries the fuel,
# never both on one row), which is why the page used to refuse the pair.
# fuel_category_totals DOES hold vehicle_class x fuel_type per RTO per
# calendar year, in the dashboard's own category taxonomy, and reconciles
# with the single-axis tables: all-category/all-fuel totals equal
# maker_category_totals to the unit for 2003-2022 and 2025 (2011 -0.08%,
# 2014 +0.48%, 2023 +0.12%), while 2024 (-4.5% for 4W; Maharashtra -42.8%,
# Kerala +34.7%) and the in-progress 2026 (-8%) are visibly incomplete.
# Year grain only: there is no month split in that table.
#
# state_month_category_fuel_totals (analytics portal, monthly) was checked
# and NOT used: its category axis is the portal's own (LIGHT MOTOR VEHICLE,
# LIGHT GOODS VEHICLE, ...), which maps onto our Four-Wheeler / Commercial
# buckets 10-26% off every year (e.g. 4W 2025 5,251,961 vs 4,638,020), and
# it is 25-29% short for 2W EV 2024.
CATEGORY_FUEL_SOURCE = "fuel_category_totals"
# A state-year whose fuel x category total is this far from the category
# totals (maker_category_totals) is flagged as incomplete, not hidden.
_COVERAGE_TOLERANCE_PCT = 2.0
_category_fuel_cache = TTLCache(_ALL_STATES_CACHE_TTL_SECONDS)


@router.get("/category-fuel")
@single_flight
async def compare_category_fuel(
    year: int = Query(_DEFAULT_YEAR, ge=MIN_YEAR, le=MAX_YEAR),
    vehicle_category: str | None = Depends(get_effective_category),
    fuel_group: str = Query(..., max_length=10),
    user_rto: str | None = Depends(scoped_rto),
    user_state: str | None = Depends(scoped_state),
    db: AsyncSession = Depends(get_db),
):
    """Per-state calendar-year totals for one vehicle category x one
    powertrain (ICE / Hybrid / EV), from fuel_category_totals, plus a
    coverage check for that year (see the module note above). Scope: the
    category is clamped by get_effective_category, the state by
    scoped_state, the RTO by scoped_rto -- all three axes."""
    if fuel_group not in ("ICE", "Hybrid", "EV"):
        raise HTTPException(422, detail="fuel_group must be ICE, Hybrid or EV")
    cache_key = (year, vehicle_category, fuel_group, user_state, user_rto)
    cached = _category_fuel_cache.get(cache_key)
    if cached is not None:
        return cached

    def _scoped(q, model):
        if user_state:
            q = q.where(model.state_name == user_state)
        if user_rto:
            q = q.where(model.rto_code == user_rto)
        return q

    fct_rows = (await db.execute(_scoped(
        select(FuelCategoryTotal.state_name, FuelCategoryTotal.vehicle_category, FuelCategoryTotal.fuel_type,
               func.sum(FuelCategoryTotal.count))
        .where(FuelCategoryTotal.year == year)
        .group_by(FuelCategoryTotal.state_name, FuelCategoryTotal.vehicle_category, FuelCategoryTotal.fuel_type),
        FuelCategoryTotal,
    ))).all()
    mct_rows = (await db.execute(_scoped(
        select(MakerCategoryTotal.state_name, func.sum(MakerCategoryTotal.count))
        .where(MakerCategoryTotal.year == year).group_by(MakerCategoryTotal.state_name),
        MakerCategoryTotal,
    ))).all()

    per_state: dict[str, int] = {}
    fct_all: dict[str, int] = {}
    for state_name, cat, raw_fuel, cnt in fct_rows:
        cnt = int(cnt or 0)
        fct_all[state_name] = fct_all.get(state_name, 0) + cnt
        if (vehicle_category is None or cat == vehicle_category) and query_fuel_group(raw_fuel) == fuel_group:
            per_state[state_name] = per_state.get(state_name, 0) + cnt
    mct_all = {s: int(c or 0) for s, c in mct_rows}

    def _pct_off(state_name: str) -> float | None:
        ref = mct_all.get(state_name)
        if not ref:
            return None
        return round((fct_all.get(state_name, 0) - ref) * 100.0 / ref, 2)

    total = sum(per_state.values())
    states = [
        {"state_name": s, "count": c, "share_percent": round(c * 100.0 / total, 2) if total else 0.0,
         "coverage_pct_off": _pct_off(s),
         "incomplete": (abs(_pct_off(s) or 0.0) > _COVERAGE_TOLERANCE_PCT)}
        for s, c in sorted(per_state.items(), key=lambda kv: (-kv[1], kv[0]))
        if c > 0
    ]
    fct_sum, mct_sum = sum(fct_all.values()), sum(mct_all.values())
    year_pct_off = round((fct_sum - mct_sum) * 100.0 / mct_sum, 2) if mct_sum else None
    if not fct_all:
        available, reason = False, f"Category x powertrain is not held for CY {year} (no fuel x category rows)."
    else:
        available, reason = True, None
    response = {
        "year": year, "vehicle_category": vehicle_category, "fuel_group": fuel_group,
        "source": CATEGORY_FUEL_SOURCE, "grain": "year",
        "available": available, "unanswerable_reason": reason,
        "coverage_pct_off": year_pct_off,
        "coverage_incomplete": year_pct_off is not None and abs(year_pct_off) > _COVERAGE_TOLERANCE_PCT,
        "total": total, "states": states,
    }
    _category_fuel_cache.set(cache_key, response)
    return response
