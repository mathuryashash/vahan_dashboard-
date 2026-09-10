import time
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.auth import require_role, get_current_user
from app.core.database import get_db
from app.models.models import OEMMonthlySales, ScrapeQualityLog, State, User, UserRole
from app.schemas.schemas import RefreshResponse
from app.services.scraper_service import run_scraper
from app.core.config import settings

router = APIRouter()

# Mounted in the root App component, so this fires on every single page
# load and then polls every 15s (see frontend useScrapeProgress) until
# fully done -- but the two DISTINCT queries below scan millions of
# matching rows each time (confirmed live: up to 35s on a fresh install).
# Cached briefly rather than left to recompute on every mount/poll; the TTL
# is short enough that live progress during an actual scrape still updates
# roughly on the same cadence the frontend polls at.
_scrape_progress_cache: dict = {"value": None, "at": 0.0}
_SCRAPE_PROGRESS_CACHE_TTL_SECONDS = 20


@router.post("/", response_model=RefreshResponse)
async def trigger_refresh(
    background_tasks: BackgroundTasks,
    _admin: User = Depends(require_role(UserRole.ADMIN)),
):
    if settings.REFRESH_STATUS == "running":
        return RefreshResponse(
            status="running",
            message="A scrape is already in progress.",
        )

    # Admin-only (see require_role above) -- was previously wide open (any
    # unauthenticated caller could trigger a ~1-1.5h scrape), with a cooldown
    # as the only defense against someone hammering it repeatedly. The
    # cooldown still matters even authenticated: an admin fat-fingering the
    # button twice shouldn't launch two concurrent scrapes either.
    if settings.LAST_REFRESH_STARTED_AT is not None:
        cooldown = timedelta(minutes=settings.REFRESH_COOLDOWN_MINUTES)
        elapsed = datetime.now(timezone.utc) - settings.LAST_REFRESH_STARTED_AT
        if elapsed < cooldown:
            retry_after_minutes = int((cooldown - elapsed).total_seconds() // 60) + 1
            return RefreshResponse(
                status="cooldown",
                message=f"A scrape ran recently. Try again in about {retry_after_minutes} minute(s).",
            )

    # Set the guard synchronously, before scheduling -- BackgroundTasks only
    # runs after this handler returns, so without this a burst of
    # near-simultaneous requests could all pass the checks above before any
    # of them actually flips REFRESH_STATUS to "running".
    settings.REFRESH_STATUS = "running"
    settings.LAST_REFRESH_STARTED_AT = datetime.now(timezone.utc)
    background_tasks.add_task(run_scraper, concurrent_states=settings.SCRAPER_CONCURRENT_STATES)
    return RefreshResponse(
        status="started",
        message="Scraper job started in background. This can take over an hour for a full India refresh.",
    )


@router.get("/status")
async def get_refresh_status(_user: User = Depends(get_current_user)):
    return {
        "last_updated": settings.LAST_UPDATED,
        "status": settings.REFRESH_STATUS,
        "error": settings.REFRESH_ERROR,
    }


@router.get("/scrape-progress")
async def get_scrape_progress(db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)):
    """How much of the live-data migration is done, by state (the only
    reliably-known denominator — total RTO count isn't knowable in advance
    since states not yet scraped haven't had their real RTO list discovered
    yet). Real rows are always vehicle_class='All' (see persist_rto_batch);
    a state only counts as done once ALL its synthetic rows are purged,
    which only happens once every RTO in it scraped successfully."""
    now = time.monotonic()
    if _scrape_progress_cache["value"] is not None and now - _scrape_progress_cache["at"] < _SCRAPE_PROGRESS_CACHE_TTL_SECONDS:
        return _scrape_progress_cache["value"]

    states_total = (await db.execute(select(func.count()).select_from(State))).scalar() or 36

    # A plain COUNT(DISTINCT ...) here forces Postgres to scan every one of
    # the ~20M rows where vehicle_class='All' just to find 36 distinct state
    # names / ~1,400 distinct RTOs (confirmed via EXPLAIN ANALYZE: ~13s + ~15s
    # -- an index doesn't help a DISTINCT scan when this many rows match).
    # A "loose index scan" (recursive CTE) walks idx_reg_class_state_rto by
    # jumping straight to the next distinct value instead of visiting every
    # row -- same index, ~36/~1,400 probes instead of 20M row reads, cuts
    # this to ~1.1s total (confirmed live).
    states_done = (await db.execute(text("""
        WITH RECURSIVE s AS (
            (SELECT state_name FROM registrations WHERE vehicle_class = 'All' ORDER BY state_name LIMIT 1)
            UNION ALL
            SELECT (
                SELECT state_name FROM registrations
                WHERE vehicle_class = 'All' AND state_name > s.state_name
                ORDER BY state_name LIMIT 1
            )
            FROM s WHERE s.state_name IS NOT NULL
        )
        SELECT count(*) FROM s WHERE state_name IS NOT NULL
    """))).scalar() or 0

    rtos_done = (await db.execute(text("""
        WITH RECURSIVE r AS (
            (SELECT state_name, rto_code FROM registrations WHERE vehicle_class = 'All'
             ORDER BY state_name, rto_code LIMIT 1)
            UNION ALL
            SELECT n.state_name, n.rto_code
            FROM r,
            LATERAL (
                SELECT state_name, rto_code FROM registrations
                WHERE vehicle_class = 'All' AND (state_name, rto_code) > (r.state_name, r.rto_code)
                ORDER BY state_name, rto_code LIMIT 1
            ) n
            WHERE r.state_name IS NOT NULL
        )
        SELECT count(*) FROM r WHERE state_name IS NOT NULL
    """))).scalar() or 0

    result = {
        "states_done": states_done,
        "states_total": states_total,
        "rtos_done": rtos_done,
        "percent": round(states_done / states_total * 100, 1) if states_total else 0.0,
    }
    _scrape_progress_cache["value"] = result
    _scrape_progress_cache["at"] = now
    return result


_CLEAN_THRESHOLD_PCT = 98.0


@router.get("/data-quality")
async def get_data_quality(db: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)):
    """Combined health signal for the frontend's data-integrity indicator
    (see Header.tsx): how fresh the last VAHAN scrape was, whether the
    cross-dimension consistency check (app.services.scrape_quality) passed,
    and whether FADA has any data at all. green/amber/red per the spec:
    green = last scrape <24h old AND per-cell check passed; amber = a scrape
    happened but is stale or the check found issues; red = FADA has never
    ingested anything (a harder failure than mere staleness -- see
    /oem-sales/status for the staleness threshold used on that page).
    """
    current_year = datetime.now(timezone.utc).year
    # One conditional-aggregation query instead of three round trips (an
    # existence check plus two separate counts) -- this endpoint is polled
    # every 5 minutes by the header's integrity badge.
    checked, clean = (await db.execute(
        select(
            func.count(),
            func.count().filter(ScrapeQualityLog.is_clean.is_(True)),
        ).select_from(ScrapeQualityLog).where(ScrapeQualityLog.year == current_year)
    )).one()
    checked, clean = checked or 0, clean or 0
    pct_clean = round(clean / checked * 100, 1) if checked else None

    scrape_fresh = False
    if settings.LAST_UPDATED:
        try:
            last_updated_dt = datetime.strptime(settings.LAST_UPDATED, "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
            scrape_fresh = (datetime.now(timezone.utc) - last_updated_dt) < timedelta(hours=24)
        except ValueError:
            scrape_fresh = False

    fada_last = (await db.execute(select(func.max(OEMMonthlySales.scraped_at)))).scalar()

    if fada_last is None:
        level = "red"
    elif scrape_fresh and pct_clean is not None and pct_clean >= _CLEAN_THRESHOLD_PCT:
        level = "green"
    else:
        level = "amber"

    return {
        "level": level,
        "scrape_fresh": scrape_fresh,
        "last_updated": settings.LAST_UPDATED,
        "quality_check": {
            "year": current_year,
            "cells_checked": checked,
            "cells_clean": clean,
            "pct_clean": pct_clean,
        },
        "fada_last_ingested_at": fada_last.isoformat() if fada_last else None,
    }
