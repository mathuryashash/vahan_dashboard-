# Vahan Sewa Dashboard

Vehicle registration analytics dashboard for India, built on live VAHAN4 data.

## Run it (Docker, one command)

**Prerequisites:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running,
and [Git LFS](https://git-lfs.com/) installed *before* you clone (the seed data below is stored via LFS —
without it, `git clone` silently gives you a small placeholder file instead of the real ~240MB seed, and
Postgres fails on first run with `gunzip: invalid magic`). If you already cloned without LFS installed:
install it, then run `git lfs pull` from the repo root, then `docker compose down -v` before retrying below.

You also need a real `JWT_SECRET_KEY` — the backend refuses to start with the
insecure code-level default. Create `docker/.env` (gitignored, never
committed) with one before first run:

```bash
echo "JWT_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')" > docker/.env
```

```bash
git lfs install   # one-time, after installing Git LFS
cd docker
docker compose up --build
```

First run takes about a minute (builds the images, then auto-loads the
included seed data — real registration data through 2026, ~13M rows — into
Postgres). Every run after that is fast.

Open:
- Dashboard: http://localhost:3000
- API: http://localhost:8020 (health check at `/health`)

To stop: `docker compose down` (add `-v` to also delete the database volume
and start fresh next time — you'll lose any data scraped since first run).

## Run it without Docker

No Docker Desktop available? `setup-native.sh` does the same job directly on
your machine: creates the Postgres role/database, loads the same seed data,
installs backend/frontend dependencies into a Python venv and `node_modules`,
and starts both servers.

**Prerequisites:** Python 3.12+, Node 18+, and PostgreSQL already installed
and running.

```bash
./setup-native.sh
```

Uses `postgres`/`postgres` as the Postgres superuser by default (creates the
app's own `vahan`/`vahan` role and database under it); override with
`PGSUPERUSER`/`PGSUPERPASSWORD` env vars if your install uses different
superuser credentials, e.g.:

```bash
PGSUPERUSER=postgres PGSUPERPASSWORD=mysecret ./setup-native.sh
```

Re-running is safe — it skips steps that are already done (existing
role/database, already-loaded data, existing venv). Stop both servers with
`./stop-native.sh`. Same URLs as the Docker path: dashboard on
`localhost:3000`, API on `localhost:8020`.

## What you get out of the box

The dashboard comes pre-loaded with real VAHAN registration data (not demo
data) covering 2016-2026. A background scheduler also keeps scraping fresh
data automatically every 5 hours, and you can trigger an on-demand refresh
from the dashboard's header (rate-limited to once per 30 minutes).

## Deployment constraints

**Run exactly one API worker.** The app refuses to start otherwise (see
`backend/app/core/worker_guard.py`). Three things depend on it:

1. The login rate limiter (`backend/app/core/rate_limit.py`) counts failed
   attempts in process memory. N workers means N x 5 password guesses per
   window against accounts whose emails are public.
2. The endpoint response caches (`TTLCache`, used across
   `backend/app/api/v1/endpoints/`) are per-process. N workers means N
   caches, so the same query can show two different numbers depending on
   which worker answers.
3. Each process opens `DB_POOL_SIZE + DB_MAX_OVERFLOW` = 60 connections
   against Postgres `max_connections=100`, which the scraper processes
   already draw on (`backend/scraper/pool_sizing.py`). Two workers is 120,
   and the excess fails to connect rather than queueing.

Going multi-worker is a real day of work, not a flag: the limiter and the
caches have to move to a shared store (Redis), and the pool sizes have to be
divided by the worker count. Once that is genuinely done, set
`ALLOW_MULTI_WORKER=true`. One worker comfortably serves a demo and a single
customer, so there is no need to do this speculatively.

The guard reads *declared* intent -- `WEB_CONCURRENCY`, `--workers`/`-w`,
Gunicorn. It cannot see N separate containers or VPSes each running one
worker behind a load balancer, and every constraint above breaks there
identically. Nothing but this paragraph protects that case.

**Back up the database.** `scripts/backup.sh` (nightly `pg_dump -Fc`, 7 daily
+ 4 weekly, optional off-host copy) and `scripts/restore-check.sh`, which
proves the newest dump actually restores. Run the restore check before any
demo or migration -- an untested backup is a rumour. A filesystem copy of the
`postgres-data` volume while Postgres is running is *not* a backup.

**Logs.** Each container is capped at 10 MB x 5 files
(`docker/docker-compose.yml`); Docker's default is unlimited, and a full disk
takes Postgres down with it. Every request logs one line carrying an
`X-Request-ID` that is also returned to the caller, so a reported failure maps
to specific log lines. The `setup-native.sh` path writes an unrotated
`backend.log` -- that path is for development only.

Full checklist, including TLS and the remaining items:
`docs/PRODUCTION_HARDENING_CHECKLIST.md`.

## Troubleshooting

- **Port already in use (3000 or 8020):** something else on your machine is
  using that port. Edit `docker/docker-compose.yml`, change the left side of
  the `ports:` mapping for the affected service (e.g. `"3001:3000"`), and
  re-run `docker compose up --build`.
- **Docker Desktop not running:** `docker compose up` will fail to connect —
  start Docker Desktop first and wait for it to fully start before retrying.
- **Stuck on an old build after pulling new code:** `docker compose up --build`
  always rebuilds; if something still looks stale, `docker compose down` then
  `docker compose up --build` again.

## Project layout

- `backend/` — FastAPI + PostgreSQL API and scraper (`docker/docker-compose.yml`
  is the source of truth for how the services fit together)
- `frontend/` — React + Vite dashboard
- `docker/seed/` — the committed seed data Postgres auto-loads on first run
- `docs/postgresql-migration.md` — database setup/migration notes
