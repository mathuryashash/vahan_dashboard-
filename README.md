# Vahan Sewa Dashboard

Vehicle registration analytics dashboard for India, built on live VAHAN4 data.

## Run it (Docker, one command)

**Prerequisite:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running.

```bash
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

## What you get out of the box

The dashboard comes pre-loaded with real VAHAN registration data (not demo
data) covering 2016-2026. A background scheduler also keeps scraping fresh
data automatically every 5 hours, and you can trigger an on-demand refresh
from the dashboard's header (rate-limited to once per 30 minutes).

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
