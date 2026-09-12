from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.query_filters import apply_fuel_group_filter, apply_total_filters
from app.core.scope import enforce_state
from app.core.cache import TTLCache
from app.models.models import Registration, User, UserScope

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


@router.get("/states")
async def compare_states(
    state_a: str,
    state_b: str | None = None,
    year: int = _DEFAULT_YEAR,
    vehicle_category: str | None = None,
    fuel_group: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    state_a = enforce_state(user, state_a)
    state_b = enforce_state(user, state_b)

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
                vehicle_category=vehicle_category, fuel_group=fuel_group,
            ),
            fuel_group,
        )
        return query.group_by(Registration.month).order_by(Registration.month)

    result_a = await db.execute(_monthly_query(state_a))
    rows_a = result_a.all()

    result_b = await db.execute(_monthly_query(state_b)) if state_b else None
    rows_b = result_b.all() if result_b else []

    return {
        "state_a": state_a,
        "state_b": state_b,
        "year": year,
        "state_a_data": [{"month": r[0], "count": r[1]} for r in rows_a],
        "state_b_data": [{"month": r[0], "count": r[1]} for r in rows_b]
        if rows_b
        else [],
    }


@router.get("/all-states")
async def get_all_states_comparison(
    year: int = _DEFAULT_YEAR,
    limit: int = 36,
    vehicle_category: str | None = None,
    fuel_group: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    cache_key = (year, limit, vehicle_category, fuel_group, user.scope_type, user.scope_state_name)
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
            vehicle_category=vehicle_category, fuel_group=fuel_group,
        ),
        fuel_group,
    )
    total_query = apply_fuel_group_filter(
        apply_total_filters(
            select(func.sum(Registration.count)).where(Registration.year == year),
            vehicle_category=vehicle_category, fuel_group=fuel_group,
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
