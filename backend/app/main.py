import asyncio
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from app.core.config import settings
from app.core.database import init_db, AsyncSessionLocal
from app.core.rate_limit import limiter
from app.api.v1.router import api_router
from app.scripts.seed_geo_hierarchy import seed_geo_hierarchy
from scraper.scheduler import run_scheduler_loop, run_fada_scheduler_loop, run_previous_year_revalidation_loop

logging.basicConfig(level=settings.LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The dev default signs a valid admin JWT for anyone who reads this
    # (open) source -- fine for local work, not for a server anyone can
    # reach. setup-native.sh generates a real secret into .env; this catches
    # every other path (a manual deploy, a forgotten .env) before it ever
    # accepts a request instead of silently running with a public key.
    if settings.JWT_SECRET_KEY == "dev-only-change-me-in-production":
        raise RuntimeError(
            "JWT_SECRET_KEY is still the insecure default -- set a real one in .env "
            "before starting the server (e.g. `python -c \"import secrets; print(secrets.token_hex(32))\"`)."
        )
    # Not a hard fail like the JWT secret above: vahan:vahan is the real,
    # intended credential for local dev and the bundled docker-compose, so
    # refusing to boot would break every developer. It is still worth saying
    # out loud on a host where the DB port is reachable.
    if "://vahan:vahan@" in settings.DATABASE_URL:
        logging.getLogger("uvicorn.error").warning(
            "DATABASE_URL is using the shipped default password. Fine locally; "
            "set a real POSTGRES_PASSWORD before exposing Postgres to anything."
        )
    await init_db()
    async with AsyncSessionLocal() as session:
        await seed_geo_hierarchy(session)
    scheduler_task = asyncio.create_task(run_scheduler_loop())
    fada_scheduler_task = asyncio.create_task(run_fada_scheduler_loop())
    # Off by default -- see ENABLE_PREVIOUS_YEAR_REVALIDATION's own comment
    # in config.py for why this isn't just always on.
    revalidation_task = asyncio.create_task(run_previous_year_revalidation_loop()) if settings.ENABLE_PREVIOUS_YEAR_REVALIDATION else None
    yield
    scheduler_task.cancel()
    fada_scheduler_task.cancel()
    if revalidation_task:
        revalidation_task.cancel()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
    # See ENABLE_API_DOCS in config.py -- off in production, where these are
    # an unauthenticated map of every route and field.
    docs_url="/docs" if settings.ENABLE_API_DOCS else None,
    redoc_url="/redoc" if settings.ENABLE_API_DOCS else None,
    openapi_url="/openapi.json" if settings.ENABLE_API_DOCS else None,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
# Blanket 120/min-per-IP default (see app/core/rate_limit.py) applied to
# every route automatically -- no per-endpoint decorators to keep in sync.
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=settings.CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    # Swagger UI is the only page this API serves that needs inline scripts
    # and the jsdelivr CDN, so that exemption lives and dies with it. With
    # docs off (production), script-src is a plain 'self' and an injected
    # inline <script> would be blocked outright rather than allowed by a
    # directive nothing was using. style-src keeps 'unsafe-inline': Recharts
    # sets element style attributes at runtime.
    script_src = (
        "script-src 'self' 'unsafe-inline' cdn.jsdelivr.net; "
        if settings.ENABLE_API_DOCS
        else "script-src 'self'; "
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        + script_src +
        "style-src 'self' 'unsafe-inline' cdn.jsdelivr.net; "
        "img-src 'self' data:; "
        "frame-ancestors 'none'"
    )
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logging.getLogger("app").exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/health")
async def health_check():
    return {"status": "ok"}
