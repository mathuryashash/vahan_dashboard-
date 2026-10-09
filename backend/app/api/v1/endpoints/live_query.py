import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_db
from app.core.query_filters import category_makers, classify_live_category
from app.core.rate_limit import limiter
from app.core.scope import get_effective_category, require_state_code, scoped_category, scoped_rto
from app.core.validation import MAX_YEAR, MIN_YEAR
from app.models.models import User, UserScope
from app.core.config import settings
from app.models.models import RTO
from app.services import fuel_groups
from app.services import stored_live_service as stored
from app.core.cache import TTLCache, single_flight
from app.services.live_scrape_service import (
    UnknownRtoCodeError, UnknownStateCodeError, get_or_scrape_maker_query, get_site_rto_codes,
    get_top_makers_leaderboard, search_makers,
)
from scraper.analytics_scraper import CaptchaSolveError, TesseractUnavailableError

router = APIRouter()


def _stored_only() -> bool:
    """The strict per-route limits below exist because a miss costs a live
    CAPTCHA solve. With LIVE_SCRAPE_FALLBACK off every answer is a stored
    query, so only the blanket 120/minute applies (override_defaults=False):
    switching the fuel group 6 times a minute returned 429 (round 5 P2-2)."""
    return not settings.LIVE_SCRAPE_FALLBACK


def _parse_group(value: str | None) -> str | None:
    try:
        return fuel_groups.normalize_group(value)
    except ValueError:
        raise HTTPException(
            422,
            detail=f"Unknown fuel_group {value!r}; expected one of {', '.join(fuel_groups.FUEL_GROUPS)}.",
        )


# Maker dropdown options: a per-state GROUP BY (~15-300 ms). Keyed on the
# fully resolved scope (state, rto, category) plus the filters, so one
# tenant's list can never be served to another.
_maker_options_cache = TTLCache(600)


@router.get("/fuel-groups")
async def list_fuel_groups(_user: User = Depends(get_current_user)):
    """The six fuel groups the Maker Lookup / Top Makers panels offer, with
    the raw VAHAN fuel labels each one sums (fuel_groups.py is the single
    source of this mapping)."""
    return fuel_groups.mapping_table()


@router.get("/maker-options")
@single_flight
async def get_maker_options(
    year: int = Query(..., ge=MIN_YEAR, le=MAX_YEAR),
    fuel_group: str | None = Query(None, max_length=20),
    rto: str | None = Query(None, max_length=10),
    state_code: str = Depends(require_state_code),
    user_category: str | None = Depends(get_effective_category),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Makers with stored registrations for this state (or RTO) + year (+
    fuel group), sorted by volume -- the Maker Lookup's dropdown. A maker
    absent here has no registrations for that combination, so the UI cannot
    offer it. Scope: state via require_state_code, RTO forced for RTO-tier
    accounts (same contract as /maker), category via get_effective_category;
    fuel group + category is refused with a reason (maker_fuel_totals has
    no category axis)."""
    if user.scope_type == UserScope.RTO:
        if rto and rto != user.scope_rto_code:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not permitted to view this state/RTO")
        rto = user.scope_rto_code
    group = _parse_group(fuel_group)
    key = (state_code, rto, user_category, year, group)
    cached = _maker_options_cache.get(key)
    if cached is not None:
        return cached
    answer = await stored.maker_options(db, state_code, year, group, user_category, rto)
    response = {
        "state_code": state_code, "year": year, "fuel_group": group, "rto": rto,
        "makers": answer.records, "source": "stored", "grain": answer.grain,
        "unanswerable_reason": answer.unanswerable_reason,
        # Lets the UI word the panel as "Live ..." only when the fallback is on.
        "live_fallback": settings.LIVE_SCRAPE_FALLBACK,
    }
    _maker_options_cache.set(key, response)
    return response


# Server-side caps kept BELOW the browser timeouts in frontend/src/api/
# vahan.ts (30s for /maker, 60s for /leaderboard): a server that outlives the
# client leaves the user staring at a timeout while it keeps scraping.
LIVE_MAKER_SERVER_TIMEOUT_S = 25
LEADERBOARD_SERVER_TIMEOUT_S = 55


@router.get("/maker")
@limiter.limit("10/minute", exempt_when=_stored_only, override_defaults=False)
async def get_maker_query(
    request: Request,  # required by @limiter.limit, unused otherwise
    year: int = Query(..., ge=MIN_YEAR, le=MAX_YEAR),
    maker: str = Query(..., max_length=200),
    fuel: str | None = Query(None, max_length=50),
    fuel_group: str | None = Query(None, max_length=20, description="One of " + ", ".join(fuel_groups.FUEL_GROUPS)),
    rto: str | None = Query(None, max_length=10),
    state_code: str = Depends(require_state_code),
    user_category: str | None = Depends(get_effective_category),
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
    group = _parse_group(fuel_group)
    if group:
        # Fuel GROUPS are a stored-data concept (several raw labels summed),
        # answered from our tables even when the live fallback is on.
        answer = await stored.maker_query_by_group(db, state_code, year, maker, group, rto, user_category)
        return {
            "state_code": state_code, "year": year, "maker": maker, "fuel": None, "fuel_group": group,
            "rto": rto, "records": answer.records, "source": "stored", "as_of": await stored.as_of(db),
            "grain": answer.grain, "unanswerable_reason": answer.unanswerable_reason,
        }
    if not settings.LIVE_SCRAPE_FALLBACK:
        # Phase A: answered from our own tables, no government-site request.
        answer = await stored.maker_query(db, state_code, year, maker, fuel, rto, user_category)
        return {
            "state_code": state_code, "year": year, "maker": maker, "fuel": fuel, "rto": rto,
            "records": answer.records, "source": "stored", "as_of": await stored.as_of(db),
            "grain": answer.grain, "unanswerable_reason": answer.unanswerable_reason,
        }
    try:
        # Server cap below the browser's 30s timeout (vahan.ts), so the user
        # gets a real error instead of a client timeout while we keep working.
        records = await asyncio.wait_for(
            get_or_scrape_maker_query(db, state_code, year, maker, fuel, rto),
            timeout=LIVE_MAKER_SERVER_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status.HTTP_504_GATEWAY_TIMEOUT,
            detail="The source site is too slow right now. Try again shortly.",
        )
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
    return {
        "state_code": state_code, "year": year, "maker": maker, "fuel": fuel, "rto": rto, "records": records,
        "source": "live", "as_of": datetime.now(timezone.utc).date().isoformat(), "grain": stored.GRAIN_MONTH,
        "unanswerable_reason": None,
    }


@router.get("/rtos")
async def list_live_rtos(
    state_code: str = Depends(require_state_code),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Our rto_codes that the source site actually lists for this state --
    i.e. the ones /maker can be RTO-scoped to. Confirmed live for Delhi: we
    hold 27 RTOs and the site lists 23, of which only 16 are in common, so
    the UI has to ask rather than assume every RTO has a live option.
    Cheap and cached process-side (see get_site_rto_codes), so no dedicated
    rate limit -- unlike /maker, a miss here costs one plain GET, not a
    CAPTCHA-solve."""
    if not settings.LIVE_SCRAPE_FALLBACK:
        # Stored answers work for every RTO we hold, not only the subset the
        # source site lists.
        codes = sorted((await db.execute(select(RTO.rto_code).where(RTO.state_code == state_code))).scalars().all())
    else:
        try:
            codes = sorted(await get_site_rto_codes(state_code))
        except Exception:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="Could not reach the source site right now.")
    if user.scope_type == UserScope.RTO:
        codes = [c for c in codes if c == user.scope_rto_code]
    return codes


@router.get("/leaderboard")
@limiter.limit("5/minute", exempt_when=_stored_only, override_defaults=False)
async def get_leaderboard(
    request: Request,  # required by @limiter.limit, unused otherwise
    year: int = Query(..., ge=MIN_YEAR, le=MAX_YEAR),
    fuel: str | None = None,
    fuel_group: str | None = Query(None, max_length=20),
    limit: int = Query(10, ge=1, le=20),
    state_code: str = Depends(require_state_code),
    user_category: str | None = Depends(get_effective_category),
    user_rto: str | None = Depends(scoped_rto),
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
    # scoped_rto, not require_state_code alone. The state guard only checks
    # that the requested state is the caller's own, which an RTO-tier
    # account passes trivially because its RTO lives in that state -- so
    # this route returned the whole STATE's top-maker ranking to an RTO
    # subscriber. Same shape as the /rto/{state}/list leak, and the fourth
    # recurrence in this codebase; the sibling /maker route above already
    # narrows RTO unconditionally for exactly this reason.
    group = _parse_group(fuel_group)
    if group:
        answer = await stored.leaderboard(db, state_code, year, None, limit, user_category, user_rto, fuel_group=group)
        return {
            "state_code": state_code, "year": year, "fuel": None, "fuel_group": group, "makers": answer.records,
            "source": "stored", "as_of": await stored.as_of(db), "grain": answer.grain,
            "unanswerable_reason": answer.unanswerable_reason,
        }
    if not settings.LIVE_SCRAPE_FALLBACK:
        answer = await stored.leaderboard(db, state_code, year, fuel, limit, user_category, user_rto)
        return {
            "state_code": state_code, "year": year, "fuel": fuel, "makers": answer.records,
            "source": "stored", "as_of": await stored.as_of(db), "grain": answer.grain,
            "unanswerable_reason": answer.unanswerable_reason,
        }
    try:
        makers = await asyncio.wait_for(
            get_top_makers_leaderboard(
                db, state_code, year, fuel, limit, vehicle_category=user_category, rto=user_rto,
            ),
            timeout=LEADERBOARD_SERVER_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status.HTTP_504_GATEWAY_TIMEOUT,
            detail="The source site is too slow right now. Try again shortly.",
        )
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
    return {
        "state_code": state_code, "year": year, "fuel": fuel, "makers": makers,
        "source": "live", "as_of": datetime.now(timezone.utc).date().isoformat(), "grain": stored.GRAIN_YEAR,
        "unanswerable_reason": None,
    }


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
    if not settings.LIVE_SCRAPE_FALLBACK:
        # Stored path: clamp to makers present in the caller's geography too
        # (state / RTO accounts), cheap via the cached per-scope set. The
        # live-fallback path below keeps the site's national list (metadata
        # only -- documented in docs/REVIEW_2026-10-08_DDL.md, N7).
        geo_state = _user.scope_state_code if _user.scope_type in (UserScope.STATE, UserScope.RTO) else None
        geo_rto = _user.scope_rto_code if _user.scope_type == UserScope.RTO else None
        return await stored.search_makers(db, q, category=user_category, state_code=geo_state, rto_code=geo_rto)
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
