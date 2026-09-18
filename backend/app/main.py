import asyncio
import logging
import time
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
from app.core.request_context import RequestIdFilter, get_request_id, new_request_id, set_request_id
from app.core.worker_guard import assert_single_worker
from app.api.v1.router import api_router
from app.scripts.seed_geo_hierarchy import seed_geo_hierarchy
from scraper.scheduler import run_scheduler_loop, run_fada_scheduler_loop, run_previous_year_revalidation_loop

logging.basicConfig(
    level=settings.LOG_LEVEL,
    # [%(request_id)s] is what makes a production failure traceable: every
    # line a request produced carries the same id, and the response carries
    # it back, so a report of "it broke" maps to specific lines. The filter
    # below supplies "-" for records logged outside any request -- without
    # it, logging raises KeyError on its own format string.
    format="%(asctime)s %(levelname)s %(name)s [%(request_id)s]: %(message)s",
)
for _handler in logging.getLogger().handlers:
    _handler.addFilter(RequestIdFilter())


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The dev default signs a valid admin JWT for anyone who reads this
    # (open) source -- fine for local work, not for a server anyone can
    # reach. setup-native.sh generates a real secret into .env; this catches
    # every other path (a manual deploy, a forgotten .env) before it ever
    # accepts a request instead of silently running with a public key.
    # Same shape as the JWT check below, and for the same reason: a
    # misconfiguration that silently half-works is worse than a refusal to
    # boot. Multi-worker quietly multiplies the login-guess allowance, splits
    # the caches, and oversubscribes Postgres. See app/core/worker_guard.py
    # for what it can and cannot detect.
    assert_single_worker()
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
    # VAHAN only by default -- see ENABLE_FADA_SCRAPER in config.py.
    fada_scheduler_task = (
        asyncio.create_task(run_fada_scheduler_loop()) if settings.ENABLE_FADA_SCRAPER else None
    )
    # Off by default -- see ENABLE_PREVIOUS_YEAR_REVALIDATION's own comment
    # in config.py for why this isn't just always on.
    revalidation_task = asyncio.create_task(run_previous_year_revalidation_loop()) if settings.ENABLE_PREVIOUS_YEAR_REVALIDATION else None
    yield
    scheduler_task.cancel()
    if fada_scheduler_task:
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
async def request_context_and_security_headers(request: Request, call_next):
    # Set BEFORE call_next, never after: Starlette runs the rest of the stack
    # in a task that COPIES this context, so a value set here is visible
    # downstream, while one set downstream is invisible here. That asymmetry
    # is also why user_id travels back on request.state instead.
    request_id = new_request_id(request.headers.get("X-Request-ID"))
    set_request_id(request_id)
    started = time.perf_counter()

    response = await call_next(request)

    elapsed_ms = (time.perf_counter() - started) * 1000
    # One line per request, replacing uvicorn's access log (the Dockerfile
    # passes --no-access-log): uvicorn's own logger sets propagate=False and
    # its own formatter, so it can never carry the request id.
    logging.getLogger("app.request").info(
        "%s %s -> %s in %.0fms%s",
        request.method, request.url.path, response.status_code, elapsed_ms,
        f" user={request.state.user_id}" if getattr(request.state, "user_id", None) else "",
    )
    # Echoed so a screenshot or a browser network tab maps to a log line.
    response.headers["X-Request-ID"] = request_id
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
    # 57014 is Postgres' query_canceled, which is what get_db's
    # statement_timeout produces. Expected by design, not a crash -- logging it
    # as an unhandled exception with a full traceback would bury the real ones,
    # and 500 tells the caller we broke when we actually gave up on time.
    # An admin's pg_cancel_backend() reports 57014 too and would be described
    # as a timeout here; that needs someone deliberately cancelling a backend,
    # and "we stopped running your query" is true either way.
    if getattr(getattr(exc, "orig", None), "sqlstate", None) == "57014":
        logging.getLogger("app").warning(
            "Query exceeded the %sms statement timeout on %s %s",
            settings.DB_STATEMENT_TIMEOUT_MS, request.method, request.url.path,
        )
        return JSONResponse(status_code=504, content={"detail": "Query took too long; narrow the filters and retry."})
    logging.getLogger("app").exception(
        "Unhandled exception on %s %s (user=%s)",
        request.method, request.url.path, getattr(request.state, "user_id", None),
    )
    # The id is in the log line via the format string; returning it lets a
    # user quote it instead of describing what they were doing.
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": get_request_id()},
    )


app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/health")
async def health_check():
    return {"status": "ok"}
