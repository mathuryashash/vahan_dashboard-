from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.scope import require_state_code
from app.models.models import User
from app.services.live_scrape_service import (
    UnknownStateCodeError, get_or_scrape_maker_query, get_top_makers_leaderboard, search_makers,
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
    state_code: str = Depends(require_state_code),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """On-demand month x category breakdown for one maker, optionally also
    scoped to one fuel type -- the exact combination the old VAHAN4 site's
    data can never answer jointly (see MakerLiveQueryCache's docstring).
    Cache hit: instant. Cache miss: a few real seconds (live CAPTCHA solve
    against the new site), then cached for every request after (except the
    current year, always re-scraped -- see get_or_scrape_maker_query).

    10/minute (not the API's blanket 120/minute default): a cache miss here
    costs a real CAPTCHA solve and a live request against the source site,
    not a DB scan -- see live_scrape_service's own asyncio.Semaphore(4) for
    the matching total-concurrency cap across distinct callers."""
    try:
        records = await get_or_scrape_maker_query(db, state_code, year, maker, fuel)
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
    return {"state_code": state_code, "year": year, "maker": maker, "fuel": fuel, "records": records}


@router.get("/leaderboard")
@limiter.limit("5/minute")
async def get_leaderboard(
    request: Request,  # required by @limiter.limit, unused otherwise
    year: int,
    fuel: str | None = None,
    limit: int = Query(10, ge=1, le=20),
    state_code: str = Depends(require_state_code),
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
        makers = await get_top_makers_leaderboard(db, state_code, year, fuel, limit)
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
        return await search_makers(q)
    except Exception:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="Could not search makers right now. Try again shortly.")
