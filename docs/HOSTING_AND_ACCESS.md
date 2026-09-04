# Hosting & Access Model

Where the data lives, what it costs to run for real, and how the role/geography access system works. Written for whoever makes the hosting decision next — assumes no prior context beyond having the repo open.

## 1. Everything lives in one Postgres database

There is no separate "auth database" or "users service." `users`, `registrations`, the maker/fuel/category cross-tabs, FADA OEM sales — all one Postgres instance, one connection string (`DATABASE_URL` in `.env`). Provisioning users is not a separate hosting decision from provisioning the app's data.

## 2. Current size and growth

- `registrations`: ~26M+ rows, live-scraped back to 2003, growing by roughly **1.0–1.6M rows per year** as each new financial year gets scraped.
- Full database (with indexes): **17GB+** today.
- The seed file shipped in `docker/seed/seed.sql.gz` is a trimmed export (last 11 years by default via `export_seed_data.py --years N`) to stay under GitHub's 100MB file limit — the *real* production database is much larger than the seed.

This one fact drives the whole hosting decision below: **any hosting option has to hold 17GB+ today and keep growing indefinitely.**

## 3. Hosting options, with real costs

### Free tier — does not work, don't try to make it work
Every managed-Postgres free tier caps out far below 17GB:

| Provider | Free tier cap |
|---|---|
| Neon | 0.5 GB |
| Supabase | 500 MB |
| Render | 1 GB, expires after 90 days idle |

None of these fit the data. This isn't a "start free, upgrade later" situation — free tier is a dead end from day one at this data size.

### Recommended starting point: a small VM running Postgres yourself
Cheapest real option that actually holds the data:

| Provider | Spec | Cost |
|---|---|---|
| Hetzner CX22 | 2 vCPU, 4GB RAM, 40GB disk | ~€5/mo (~$5.50) |
| DigitalOcean Basic Droplet | 2 vCPU, 4GB RAM, 25–50GB disk | ~$12–24/mo |

Run the app's backend, Postgres, and the built frontend all on this one box (same pattern as `setup-native.sh` uses locally, just on a rented server instead of a laptop). Disk can be resized as data grows without downtime on both providers. **This is what most solo/small-team deployments at this scale actually do** — self-managed Postgres on a VM is not a compromise, it's the standard cost-effective choice until traffic or team size justifies paying for managed infrastructure.

**What you give up**: automated backups, point-in-time recovery, and failover are your own responsibility (a cron job running `pg_dump` to off-box storage — e.g. Backblaze B2 or S3 — covers backups for a few dollars a month more).

### When to move to managed Postgres
Once backups/patching/uptime become worth paying someone else for:

| Provider | Spec | Cost |
|---|---|---|
| DigitalOcean Managed Postgres | 10GB, 1 vCPU | ~$15/mo, scales up from there |
| Render Postgres (paid tier) | 10GB+ | ~$20+/mo |

Migration path is a straightforward `pg_dump` / `pg_restore` — the app code doesn't change, only `DATABASE_URL`.

### Total estimated monthly cost to run this for real
- **Starting out**: ~$6–25/mo (one VM, self-hosted Postgres + app).
- **Once you want managed backups/failover**: ~$25–50/mo (managed Postgres + a smaller app-only VM, or a PaaS like Render/Railway for the app).

## 4. The access hierarchy — who sees what

Two independent dimensions on every user account (`backend/app/models/models.py`, `User` table):

- **Role** (`UserRole`: `admin` / `analyst` / `viewer`) — *what actions* an account can take. Admin manages users and triggers scrapes; analyst and viewer are both read-only on the dashboard, admin is the only one who can do anything destructive.
- **Scope** (`UserScope`: `national` / `state` / `rto`) — *what data* an account can see. Independent of role — a `state`-scoped `viewer` and a `state`-scoped `analyst` see the same geography, just with different action permissions.

| Scope | Sees |
|---|---|
| `national` | Every state, can drill into any RTO |
| `state` | Locked to one state (`scope_state_code`/`scope_state_name` on the user row), can drill into any RTO within it |
| `rto` | Locked to one specific RTO (`scope_rto_code`/`scope_rto_name`) within their state |

### Enforcement is server-side, not just hidden UI
`backend/app/core/scope.py` has the enforcement logic, applied as FastAPI dependencies on every dashboard endpoint (`get_effective_state`, `require_state_code`, `require_rto_code`, `enforce_state`):

- A query-string filter (`?state=...`) from a scoped user is **silently overridden** to their own state — asking for someone else's state just returns their own data, not an error.
- A required path parameter (e.g. `/rto/{rto_code}/analysis`) that doesn't belong to the caller's scope is a hard **403**, including a real DB lookup to confirm an RTO actually belongs to the caller's state (not just a string comparison).
- This means the frontend hiding the state/RTO picker for scoped users (added this session) is a UX nicety, not the security boundary — the API enforces the same restriction even if someone bypasses the UI and calls the API directly with a browser dev tools request or curl.

### Where users are created
No self-registration. The very first admin is bootstrapped via a CLI script:

```bash
cd backend
python -m app.scripts.create_admin --email you@company.com --name "Your Name"
```

Every account after that is created by an existing admin, either through `POST /api/v1/users/` directly or (once built) an admin UI. Creating a state- or RTO-scoped account means passing `scope_type`, `scope_state_code`, `scope_state_name`, and (for `rto` scope) `scope_rto_code`/`scope_rto_name` in that request — see `backend/app/api/v1/endpoints/users.py` for the exact payload shape.

`backend/app/scripts/seed_demo_hierarchy_users.py` provisions three demo accounts (national/state/RTO) against whatever real, populated state/RTO has the most data — useful for testing the hierarchy without hand-picking geography.

## 5. Before going live, not yet done

- **`JWT_SECRET_KEY`** in `backend/app/core/config.py` defaults to a dev placeholder. Set a real random value via `.env` before this is reachable from the public internet — anyone who knows the default string can forge an admin token.
- **HTTPS**: nothing here terminates TLS. Put this behind a reverse proxy (Caddy or nginx with Let's Encrypt) before exposing it beyond a local network.
- **RTO-scoped dashboard filtering gap**: RTO-scoped accounts are correctly restricted on the dedicated RTO Analysis page, but the general dashboard endpoints (Overview, Categories, YoY, Comparison) only enforce down to the *state* level — an RTO-scoped user currently sees their whole state's numbers on those pages, not just their RTO's. Flagged, not yet fixed.
