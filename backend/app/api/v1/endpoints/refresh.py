from fastapi import APIRouter, BackgroundTasks
from app.schemas.schemas import RefreshResponse
from app.services.scraper_service import run_scraper
from app.core.config import settings
from datetime import datetime

router = APIRouter()


@router.post("/", response_model=RefreshResponse)
async def trigger_refresh(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_scraper)
    settings.LAST_UPDATED = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    return RefreshResponse(
        status="started",
        message="Scraper job started in background. Data will be available shortly.",
    )


@router.get("/status")
async def get_refresh_status():
    return {
        "last_updated": settings.LAST_UPDATED,
        "status": "ready" if settings.LAST_UPDATED else "never_run",
    }
