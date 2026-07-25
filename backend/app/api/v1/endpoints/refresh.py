from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import select, func, distinct
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models.models import Registration, State
from app.schemas.schemas import RefreshResponse
from app.services.scraper_service import run_scraper
from app.core.config import settings

router = APIRouter()


@router.post("/", response_model=RefreshResponse)
async def trigger_refresh(background_tasks: BackgroundTasks):
    if settings.REFRESH_STATUS == "running":
        return RefreshResponse(
            status="running",
            message="A scrape is already in progress.",
        )

    # This endpoint has no auth (it's a public dashboard button), so without a
    # cooldown anyone could keep re-triggering a fresh ~1-1.5h scrape
    # back-to-back forever -- hammering this app's own DB and the government
    # site the scraper hits.
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
    background_tasks.add_task(run_scraper)
    return RefreshResponse(
        status="started",
        message="Scraper job started in background. This can take over an hour for a full India refresh.",
    )


@router.get("/status")
async def get_refresh_status():
    return {
        "last_updated": settings.LAST_UPDATED,
        "status": settings.REFRESH_STATUS,
        "error": settings.REFRESH_ERROR,
    }


@router.get("/scrape-progress")
async def get_scrape_progress(db: AsyncSession = Depends(get_db)):
    """How much of the live-data migration is done, by state (the only
    reliably-known denominator — total RTO count isn't knowable in advance
    since states not yet scraped haven't had their real RTO list discovered
    yet). Real rows are always vehicle_class='All' (see persist_rto_batch);
    a state only counts as done once ALL its synthetic rows are purged,
    which only happens once every RTO in it scraped successfully."""
    states_total = (await db.execute(select(func.count()).select_from(State))).scalar() or 36

    states_done = (
        await db.execute(
            select(func.count(distinct(Registration.state_name))).where(Registration.vehicle_class == "All")
        )
    ).scalar() or 0

    rto_subq = (
        select(Registration.state_name, Registration.rto_code)
        .where(Registration.vehicle_class == "All")
        .distinct()
        .subquery()
    )
    rtos_done = (await db.execute(select(func.count()).select_from(rto_subq))).scalar() or 0

    return {
        "states_done": states_done,
        "states_total": states_total,
        "rtos_done": rtos_done,
        "percent": round(states_done / states_total * 100, 1) if states_total else 0.0,
    }
