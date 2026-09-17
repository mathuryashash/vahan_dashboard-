from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, or_, and_
from app.core.database import get_db
from app.core.query_filters import apply_total_filters, category_makers, exclude_supplementary
from app.core.scope import require_rto_code, require_state_code, scoped_category, scoped_rto
from app.core.cache import TTLCache
from app.models.models import MakerCategoryTotal, Registration
from app.schemas.schemas import RtoAnalysis, RtoListItem

router = APIRouter()

# Same cost shape and same fix as summary.py/categories.py's hot endpoints --
# both of these scan the 26M-row registrations table (state-wide or one
# RTO's full FY), and RTO Analysis re-fires them on every state/year/RTO
# pick.
_CACHE_TTL_SECONDS = 90
_rto_list_cache = TTLCache(_CACHE_TTL_SECONDS)
_rto_analysis_cache = TTLCache(_CACHE_TTL_SECONDS)


def fy_filter(fy_year: int):
    """Indian financial year: April `fy_year` through March `fy_year + 1`.
    Month values never collide across the two calendar years (Apr-Dec vs
    Jan-Mar), so downstream DISTINCT month/aggregate math stays correct.
    """
    return or_(
        and_(Registration.year == fy_year, Registration.month >= 4),
        and_(Registration.year == fy_year + 1, Registration.month <= 3),
    )


@router.get("/{state_code}/list", response_model=list[RtoListItem])
async def get_rtos_for_state(
    state_code: str = Depends(require_state_code),
    year: int = Query(..., description="Financial year start (April `year` - March `year+1`)"),
    user_category: str | None = Depends(scoped_category),
    user_rto: str | None = Depends(scoped_rto),
    db: AsyncSession = Depends(get_db),
):
    """RTOs with real registration data for this state/FY, ranked by
    volume. Reads from `registrations` directly (not the `rtos` master
    table) so the list only ever shows RTOs that actually have data.
    """
    # Kept as a comment, not in the docstring above: FastAPI publishes a
    # route docstring as the OpenAPI `description`, and the rest of this
    # explains an exploit and quotes real volumes. ENABLE_API_DOCS is False
    # by default, but that is one flag away from being public.
    #
    # require_state_code alone is NOT enough here. It only checks that the
    # requested state is the caller's own, which an RTO-tier account passes
    # trivially -- its RTO lives in that state. With no RTO clamp this
    # returned every RTO in the state, ranked by volume: live-proven, an
    # RTO-tier account received all 76 of its state's RTOs, byte-identical
    # to what the state tier is sold. That is the whole state-tier product
    # handed to an RTO-tier subscriber, and it is the third recurrence of
    # this bug shape in this codebase.
    #
    # The sibling route below (/{rto_code}/analysis) was already closed via
    # require_rto_code, which is exactly what made the gap easy to miss.
    #
    # user_rto MUST also be in the cache key: the key was
    # (state_code, year, user_category), so adding the filter without the
    # key would serve one tenant's cached list to another -- turning a read
    # leak into a cross-tenant cache leak.
    cache_key = (state_code, year, user_category, user_rto)
    cached = _rto_list_cache.get(cache_key)
    if cached is not None:
        return cached

    # apply_total_filters is exclude_supplementary when no category is in
    # play (identical query for an unscoped caller) and swaps to the
    # category-carrying vehicle_class rows when there is one -- these totals
    # would otherwise be every category's, not the one the account bought.
    query = apply_total_filters(
        select(
            Registration.rto_code,
            Registration.rto_name,
            func.sum(Registration.count).label("total"),
        )
        .where(Registration.state_code == state_code, fy_filter(year)),
        rto_code=user_rto,
        vehicle_category=user_category,
    ).group_by(Registration.rto_code, Registration.rto_name).order_by(desc("total"))

    result = await db.execute(query)
    response = [
        {"rto_code": r.rto_code, "rto_name": r.rto_name, "total": r.total}
        for r in result.all()
    ]
    _rto_list_cache.set(cache_key, response)
    return response


@router.get("/{rto_code}/analysis", response_model=RtoAnalysis)
async def get_rto_analysis(
    rto_code: str = Depends(require_rto_code),
    year: int = Query(..., description="Financial year start (April `year` - March `year+1`)"),
    user_category: str | None = Depends(scoped_category),
    db: AsyncSession = Depends(get_db),
):
    """Company (maker) % breakdown for one RTO/FY, plus an overview:
    total registrations and average per active month.
    """
    cache_key = (rto_code, year, user_category)
    cached = _rto_analysis_cache.get(cache_key)
    if cached is not None:
        return cached

    base = exclude_supplementary(
        select(Registration).where(Registration.rto_code == rto_code, fy_filter(year))
    )

    if user_category:
        # Category-scoped accounts CANNOT be served from the maker-pass rows
        # below: every one of them carries vehicle_category='Other' (verified:
        # all 855,720 maker rows for 2025), so summing them yields a maker's
        # ALL-category volume. Merely restricting which makers appear isn't
        # enough -- most volume comes from makers that sell in several
        # categories, and the inflation is material, not marginal: FY2025
        # MAHINDRA is 581,193 Four-Wheeler + 280,358 Commercial Vehicle (~48%
        # over), BAJAJ 2,257,047 Two-Wheeler + 496,875 Three-Wheeler (~22%
        # over). Showing a segment customer another segment's volume inside a
        # number labelled as theirs is exactly what this boundary exists to
        # prevent, so these accounts read MakerCategoryTotal, which carries a
        # real per-category count.
        #
        # The tradeoff is the period. MakerCategoryTotal is scraped per
        # CALENDAR year (analytics_scraper sends timePeriod=0) and has no
        # month column, so an Apr-Mar financial year cannot be sliced out of
        # it -- no source in this data carries maker AND category AND month
        # together (Registration has maker+month but no category, this table
        # has maker+category but no month, StateMonthCategory* has
        # category+month but no maker; the same pairwise-only ceiling
        # tripleEstimate.ts works around on the frontend). So a scoped
        # account's window is the two calendar years the FY spans -- the
        # convention category_makers already uses just below, keeping this
        # endpoint internally consistent -- which fully covers the FY but
        # also the ~12 months either side of it.
        #
        # Deliberate: this screen is a "Company % breakdown", and a wider
        # window scales every maker roughly alike, so share_percent stays
        # meaningful. Category-blindness does NOT distort evenly (FY2025
        # MAHINDRA would read ~48% high, HERO ~0.1%), so it corrupts exactly
        # the shares this screen exists to show. Absolute totals here are
        # therefore broader than the FY label suggests for scoped accounts;
        # the shares are the trustworthy part.
        maker_query = (
            select(MakerCategoryTotal.maker, func.sum(MakerCategoryTotal.count).label("count"))
            .where(
                MakerCategoryTotal.rto_code == rto_code,
                MakerCategoryTotal.year.in_([year, year + 1]),
                MakerCategoryTotal.vehicle_category == user_category,
            )
            .group_by(MakerCategoryTotal.maker)
            .order_by(desc("count"))
        )
    else:
        maker_query = exclude_supplementary(
            select(Registration.maker, func.sum(Registration.count).label("count"))
            .where(Registration.rto_code == rto_code, fy_filter(year))
        ).group_by(Registration.maker).order_by(desc("count"))

    overview_query = exclude_supplementary(
        select(
            func.sum(Registration.count).label("total"),
            func.count(func.distinct(Registration.month)).label("months_with_data"),
        ).where(Registration.rto_code == rto_code, fy_filter(year))
    )
    # months_with_data feeds avg_monthly's denominator and is returned as-is.
    # Unfiltered it counted every category's active months, so a scoped
    # account got a denominator covering segments it can't see (and the month
    # coverage of those segments leaked through the field itself). Restricted
    # to the months this account's own makers were actually active.
    if user_category:
        overview_query = overview_query.where(
            Registration.maker.in_(category_makers(user_category, years=[year, year + 1], rto_code=rto_code))
        )

    maker_result = await db.execute(maker_query)
    makers = maker_result.all()
    total = sum(m.count for m in makers)

    overview_result = await db.execute(overview_query)
    overview_row = overview_result.one()
    months_with_data = overview_row.months_with_data or 0
    avg_monthly = round(total / months_with_data, 1) if months_with_data else 0

    name_result = await db.execute(base.limit(1))
    sample = name_result.scalars().first()

    response = {
        "rto_code": rto_code,
        "rto_name": sample.rto_name if sample else None,
        "state_name": sample.state_name if sample else None,
        "year": year,
        "total": total,
        "avg_monthly": avg_monthly,
        "months_with_data": months_with_data,
        # Say which window these maker numbers actually cover instead of
        # letting both paths render under the same "FY" label -- see the
        # MakerCategoryTotal branch above and RtoAnalysis.maker_period.
        "maker_period": "calendar_years_spanned" if user_category else "financial_year",
        "makers": [
            {
                "maker": m.maker,
                "count": m.count,
                "share_percent": round(m.count / total * 100, 2) if total else 0,
            }
            for m in makers
        ],
    }
    _rto_analysis_cache.set(cache_key, response)
    return response
