# Production Hardening Plan

This documents the items flagged in the security review that were **not** implemented, because the app currently only runs on localhost with no deployment target — building them now would mean designing an auth strategy, adding dependencies, and migrating a database with zero present need. This is the plan for when that changes, not code that exists yet.

Each section: why it matters, what changes, and the concrete steps to implement it.

---

## 1. Authentication & Authorization

**Why it matters:** every endpoint is public, including `POST /api/v1/refresh/` which kicks off a scrape described as taking "over an hour." Anyone who can reach the API can trigger it repeatedly or read all registration data.

**Current state:** no auth of any kind. `app/api/v1/router.py` mounts all endpoint routers with no dependency guarding them.

**Proposed approach:** a single static API key checked via a FastAPI dependency, gating only the mutating endpoint (`/refresh/`) to start. Read-only aggregate endpoints (`/summary/*`, `/categories/*`, etc.) can stay open if the deployment is meant to be a public dashboard — that's a product decision, not a security requirement, since they only expose aggregate counts.

**Implementation steps:**
1. Add `API_KEY: str | None = None` to `app/core/config.py` (read from env, `None` disables the check — keeps local dev frictionless).
2. Add `app/core/auth.py`:
   ```python
   from fastapi import Header, HTTPException
   from app.core.config import settings

   async def require_api_key(x_api_key: str | None = Header(default=None)):
       if settings.API_KEY and x_api_key != settings.API_KEY:
           raise HTTPException(status_code=401, detail="Invalid or missing API key")
   ```
3. In `refresh.py`, add `dependencies=[Depends(require_api_key)]` to the `POST /` route.
4. Frontend: `Header.tsx`'s `triggerRefresh()` call in `api/vahan.ts` needs an `X-API-Key` header sourced from a Vite env var (`import.meta.env.VITE_API_KEY`) — only relevant once the frontend is also deployed somewhere the key can be safely injected at build/deploy time, not committed to source.
5. If broader auth (per-user, not a single shared key) is ever needed: FastAPI's `OAuth2PasswordBearer` + JWT is the standard next step, but that's a materially bigger change (user table, login flow, token refresh) — don't build it speculatively.

**Effort:** ~1 hour for the API-key version above.

---

## 2. Rate Limiting

**Why it matters:** combined with #1, an unauthenticated actor can hammer `/summary/kpis` or similar aggregation endpoints, which each run several SQL aggregation queries, with no throttling.

**Current state:** none. No rate-limiting middleware or dependency anywhere.

**Proposed approach:** [`slowapi`](https://github.com/laurentS/slowapi) (a FastAPI-friendly wrapper around `limits`), applied per-IP.

**Implementation steps:**
1. `pip install slowapi` (add to `requirements.txt`).
2. In `main.py`:
   ```python
   from slowapi import Limiter, _rate_limit_exceeded_handler
   from slowapi.util import get_remote_address
   from slowapi.errors import RateLimitExceeded

   limiter = Limiter(key_func=get_remote_address)
   app.state.limiter = limiter
   app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
   ```
3. Apply a stricter limit to `/refresh/` (e.g. `@limiter.limit("1/minute")`) than to read endpoints (e.g. `@limiter.limit("60/minute")`), since a full scrape trigger is far more expensive than a KPI read.
4. In-memory storage (`slowapi`'s default) is fine for a single-process deployment; if this ever runs multiple uvicorn workers behind a load balancer, the limiter needs a shared backend (Redis) instead, or limits will be per-worker rather than global.

**Effort:** ~1–2 hours including picking sensible per-endpoint limits.

---

## 3. PostgreSQL Migration

**Why it matters:** SQLite has file-level write locking (one writer at a time) and no network access — fine for a single local process, a real constraint under concurrent traffic or if the API and scraper ever need to write from different machines/containers.

**Current state:** `app/core/database.py` uses `sqlite+aiosqlite:///./data/vahan.db`. **Not currently justified** — this app has one writer (the scraper) and read traffic low enough that SQLite's limits haven't been an issue in any testing so far. Migrate only if actual concurrent-write contention or multi-instance deployment becomes real, not preemptively.

**Proposed approach:** swap the SQLAlchemy engine URL and add Alembic for schema migrations (currently there's a hand-rolled `app/core/migrations.py` — worth checking what that already does before adding Alembic on top of it, to avoid two migration systems).

**Implementation steps:**
1. Add `docker/docker-compose.yml` service:
   ```yaml
   postgres:
     image: postgres:16-alpine
     environment:
       - POSTGRES_DB=vahan
       - POSTGRES_USER=vahan
       - POSTGRES_PASSWORD=<from secret, not committed>
     volumes:
       - vahan-pgdata:/var/lib/postgresql/data
   ```
2. Add `asyncpg` to `requirements.txt`; change `DATABASE_URL` to `postgresql+asyncpg://vahan:<password>@postgres:5432/vahan`.
3. Audit `app/models/models.py` for SQLite-specific column types/defaults that don't map cleanly to Postgres (e.g. `TIMESTAMP DEFAULT CURRENT_TIMESTAMP` in the raw-SQL parts of `seed_data.py` — that script talks to SQLite directly via `sqlite3`, not SQLAlchemy, and would need rewriting or retiring, not just repointing, if it's kept at all after this migration).
4. Add connection pool tuning (`pool_size`, `max_overflow`) appropriate to expected concurrency — SQLite has no equivalent concept today.
5. Data migration: since current data is either synthetic (`seed_data.py`) or will come from a fresh live pipeline, there's likely nothing worth migrating row-for-row — just re-seed/re-scrape against the new database rather than writing a SQLite→Postgres data migration script.

**Effort:** ~1 day, mostly in verifying every query still behaves identically (SQLite and Postgres have different NULL-handling and date-function edge cases) and updating `docker-compose.yml`/CI to spin up Postgres for tests.

---

## 4. TLS / HTTPS Enforcement

**Why it matters:** not applicable until this is deployed somewhere with a real domain — there's no TLS story for `localhost` and none needed.

**Current state:** plain HTTP everywhere, which is correct for local dev.

**Proposed approach:** terminate TLS at a reverse proxy (nginx, Caddy, or the platform's load balancer — e.g. Render/Fly/an actual cloud LB), not in the FastAPI app itself. FastAPI/uvicorn serving TLS directly is uncommon outside of quick demos.

**Implementation steps (once there's a real domain):**
1. If self-hosting: Caddy is the least-effort option — automatic Let's Encrypt certs with a ~5-line Caddyfile, replacing the nginx container from the Dockerfile fix in this session (or fronting it).
2. If on a managed platform (Render, Railway, Fly.io, a cloud load balancer): TLS termination is usually a checkbox/config field, not something to build.
3. Add `Strict-Transport-Security` header (HSTS) once TLS is confirmed working — adding it before TLS exists would break plain-HTTP access.
4. Update `CORS_ORIGIN_REGEX` in `app/core/config.py` (currently `http://(localhost|127\.0\.0\.1):\d+`) to match the real `https://` origin instead once deployed.

**Effort:** ~30 minutes to a few hours depending on hosting choice — this is infrastructure configuration, not application code.

---

## 5. Request Body Size Limits

**Why it matters:** FastAPI/Starlette has no default request body size cap; a malicious or buggy client could send an oversized payload to exhaust memory.

**Current state:** no limit configured. Low real-world urgency today — every current POST endpoint (`/refresh/`) takes no body at all, so there's nothing to exhaust yet. This becomes relevant if a body-accepting endpoint (e.g. a future bulk-upload or webhook receiver) is added.

**Proposed approach:** a small ASGI middleware that rejects requests over a configured `Content-Length` before the body is read.

**Implementation steps:**
1. Add a middleware in `main.py` that checks `request.headers.get("content-length")` against a `MAX_BODY_SIZE` setting (e.g. 1 MB) and returns `413 Payload Too Large` if exceeded.
2. Note this only catches requests with a `Content-Length` header; a chunked-encoding request without one needs a streaming read-and-count instead — not worth the complexity until there's an endpoint that actually accepts arbitrary bodies.

**Effort:** ~30 minutes, and arguably worth deferring entirely until a body-accepting endpoint actually exists.

---

## Suggested order if/when this gets picked up

1. **Auth on `/refresh/`** — cheapest, highest value, no dependencies.
2. **Rate limiting** — cheap, meaningfully reduces abuse surface once auth exists (defense in depth).
3. **TLS** — required the moment this leaves localhost; mostly infra config, not app code.
4. **Postgres** — only when there's an actual concurrency need, not preemptively.
5. **Body size limits** — defer until an endpoint actually accepts a body worth limiting.
