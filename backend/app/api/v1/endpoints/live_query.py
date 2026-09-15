from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_db
from app.core.query_filters import category_makers, classify_live_category
from app.core.rate_limit import limiter
from app.core.scope import require_state_code, scoped_category
from app.models.models import User, UserScope
from app.services.live_scrape_service import (
    UnknownRtoCodeError, UnknownStateCodeError, get_or_scrape_maker_query, get_site_rto_codes,
    get_top_makers_leaderboard, search_makers,
)
from scraper.analytics_scraper import CaptchaSolveError, TesseractUnavailableError

router = APIRouter()


@router.get("/maker")
@limiter.limit("10/minute")
async def get_maker_query(
    request: Request,  # required by @limiter.limit, unused otherwise
    year: int,
    maker: str = Query(..., max_length=200),
    fuel: str | None = Query(None, max_length=50),
    rto: str | None = Query(None, max_length=10),
    state_code: str = Depends(require_state_code),
    user_category: str | None = Depends(scoped_category),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """On-demand month x category breakdown for one maker, optionally also
    scoped to one fuel type and/or one RTO -- the exact combination the old
    VAHAN4 site's data can never answer jointly (see MakerLiveQueryCache's
    docstring). `rto` is our own rto_code ("DL9"), and only RTOs the source
    site actually lists can be looked up (see /live-query/rtos).
    Cache hit: instant. Cache miss: a few real seconds (live CAPTCHA solve
    against the new site), then cached for every request after (except the
    current year, always re-scraped -- see get_or_scrape_maker_query).

    10/minute (not the API's blanket 120/minute default): a cache miss here
    costs a real CAPTCHA solve and a live request against the source site,
    not a DB scan -- see live_scrape_service's own asyncio.Semaphore(4) for
    the matching total-concurrency cap across distinct callers."""
    # require_state_code only clamps the STATE -- an RTO-scoped account would
    # otherwise reach every other RTO in its own state through this one new
    # param, the same leak scoped_category closes on the category axis.
    # Narrowing, not merely rejecting: OMITTING rto has to mean "my own RTO",
    # never "the whole state", or the clamp is bypassed by simply leaving the
    # parameter off -- the same contract get_effective_state enforces on the
    # state axis, and what UserScope's own docstring promises for this one.
    if user.scope_type == UserScope.RTO:
        if rto and rto != user.scope_rto_code:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not permitted to view this state/RTO")
        rto = user.scope_rto_code
    try:
        records = await get_or_scrape_maker_query(db, state_code, year, maker, fuel, rto)
    except UnknownStateCodeError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Unknown state_code {state_code!r}.")
    except UnknownRtoCodeError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"The source site doesn't list RTO {rto!r} -- no live lookup is available for it.",
        )
    except TesseractUnavailableError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Live scraping is temporarily unavailable (OCR not ready on the server).",
        )
    except CaptchaSolveError:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail="Could not fetch this data right now -- the source site rejected every attempt. Try again shortly.",
        )
    except Exception:
        # Anything else from the scrape itself (a network error, the source
        # site's markup changing under load_session's CSRF lookup, ...) --
        # same "try again" message as CaptchaSolveError rather than the
        # generic 500 app.main's catch-all would otherwise give.
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail="Could not fetch this data right now. Try again shortly.",
        )
    if user_category:
        # Every record is one (month, live-site category) cell -- returned
        # whole, this hands a four-wheeler account the maker's two-wheeler
        # months as well. classify_live_category bridges the live site's own
        # category vocabulary onto the buckets a user is scoped to.
        records = [r for r in records if classify_live_category(r["category"]) == user_category]
    return {"state_code": state_code, "year": year, "maker": maker, "fuel": fuel, "rto": rto, "records": records}


@router.get("/rtos")
async def list_live_rtos(
    state_code: str = Depends(require_state_code),
    user: User = Depends(get_current_user),
):
    """Our rto_codes that the source site actually lists for this state --
    i.e. the ones /maker can be RTO-scoped to. Confirmed live for Delhi: we
    hold 27 RTOs and the site lists 23, of which only 16 are in common, so
    the UI has to ask rather than assume every RTO has a live option.
    Cheap and cached process-side (see get_site_rto_codes), so no dedicated
    rate limit -- unlike /maker, a miss here costs one plain GET, not a
    CAPTCHA-solve."""
    try:
        codes = sorted(await get_site_rto_codes(state_code))
    except Exception:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="Could not reach the source site right now.")
    if user.scope_type == UserScope.RTO:
        codes = [c for c in codes if c == user.scope_rto_code]
    return codes


@router.get("/leaderboard")
@limiter.limit("5/minute")
async def get_leaderboard(
    request: Request,  # required by @limiter.limit, unused otherwise
    year: int,
    fuel: str | None = None,
    limit: int = Query(10, ge=1, le=20),
    state_code: str = Depends(require_state_code),
    user_category: str | None = Depends(scoped_category),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Real (not modeled) top-maker ranking for one state/year, optionally
    scoped to one fuel type -- the actual-data alternative to
    MakersModels.tsx's log-linear estimate for a Maker x Fuel combo, which
    has no real data source. See get_top_makers_leaderboard's docstring for
    how "top makers" is picked and why this costs more than /maker.

    5/minute, not 10 like /maker: an uncached call here pays up to `limit`
    (capped at 20) real CAPTCHA-solves, not one -- rarer, heavier requests
    get a tighter budget."""
    try:
        makers = await get_top_makers_leaderboard(db, state_code, year, fuel, limit, vehicle_category=user_category)
    except UnknownStateCodeError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Unknown state_code {state_code!r}.")
    except TesseractUnavailableError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Live scraping is temporarily unavailable (OCR not ready on the server).",
        )
    except CaptchaSolveError:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail="Could not fetch this data right now -- the source site rejected an attempt. Try again shortly.",
        )
    except Exception:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail="Could not fetch this data right now. Try again shortly.",
        )
    return {"state_code": state_code, "year": year, "fuel": fuel, "makers": makers}


@router.get("/makers/search")
async def search_makers_endpoint(
    q: str = Query(..., min_length=1, max_length=200),
    user_category: str | None = Depends(scoped_category),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Real maker names matching `q`, straight from the source site --
    lets the frontend offer an actual autocomplete instead of requiring the
    caller to already know a manufacturer's exact full legal name (found
    live: typing "honda" into /maker's free-text field returns a real,
    genuinely-empty result -- the site needs the exact string "HONDA
    MOTORCYCLE AND SCOOTER INDIA (P) LTD", and a partial name is
    indistinguishable from a real zero without this search catching the
    mismatch first). Not state-scoped (makers aren't per-state) and no
    CAPTCHA involved, so no require_state_code dependency and no dedicated
    rate limit beyond the API's blanket default -- unlike /maker and
    /leaderboard, a miss here costs one cheap GET, not a live scrape."""
    try:
        results = await search_makers(q)
        if user_category:
            # The source site's maker list has no category dimension, so an
            # unfiltered autocomplete names two-wheeler manufacturers to a
            # four-wheeler account. Keep only makers our own crosstab knows
            # sell in their category -- deny-by-default: a maker we have no
            # category evidence for is dropped, not shown.
            allowed = {m.upper() for m in (await db.execute(category_makers(user_category))).scalars().all()}
            results = [m for m in results if m.upper() in allowed]
        return results
    except Exception:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="Could not search makers right now. Try again shortly.")
