from fastapi import APIRouter, BackgroundTasks
from app.schemas.schemas import RefreshResponse
from app.services.scraper_service import run_scraper
from app.core.config import settings

router = APIRouter()


@router.post("/", response_model=RefreshResponse)
async def trigger_refresh(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_scraper)
    return RefreshResponse(
        status="started",
        message="Scraper job started in background. This can take over an hour for a full India refresh.",
    )


@router.get("/status")
async def get_refresh_status():
    return {
        "last_updated": settings.LAST_UPDATED,
        "status": "ready" if settings.LAST_UPDATED else "never_run",
    }
