from fastapi import APIRouter
from app.api.v1.endpoints import (
    summary,
    states,
    registrations,
    comparison,
    yoy,
    categories,
    refresh,
    geo,
)

api_router = APIRouter()

api_router.include_router(summary.router, prefix="/summary", tags=["Summary"])
api_router.include_router(states.router, prefix="/states", tags=["States"])
api_router.include_router(
    registrations.router, prefix="/registrations", tags=["Registrations"]
)
api_router.include_router(comparison.router, prefix="/comparison", tags=["Comparison"])
api_router.include_router(yoy.router, prefix="/yoy", tags=["Year-over-Year"])
api_router.include_router(categories.router, prefix="/categories", tags=["Categories"])
api_router.include_router(refresh.router, prefix="/refresh", tags=["Refresh"])
api_router.include_router(geo.router, prefix="/geo", tags=["Geo Hierarchy"])
