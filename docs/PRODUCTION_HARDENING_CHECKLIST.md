# Production Hardening Checklist

Four items: error tracking in logs, CI, single-worker safety, backups.
Ordered lowest-risk first. Each step is one commit, reviewable alone.

`PS>` = Windows dev machine (PowerShell), `VPS>` = Linux VPS shell. Steps
marked **VPS-only** cannot be proven on Windows.

Three places this departs from the original brief — reasons are in the step:

- **No Python `RotatingFileHandler`** (step 5/8). Docker's `json-file` driver
  already rotates; a second rotation layer inside the app is one more thing to
  misconfigure. The unrotated log is `backend.log` from `setup-native.sh`, and
  that path is dev-only.
- **A worker cannot count its siblings reliably** (step 7). Detect the
  *declared* intent instead, and say plainly what that misses.
- **Neither existing export script is a backup** (step 3). Don't extend them.

> `PRODUCTION_HARDENING.md` at the repo root is stale — its items 1 (auth),
> 2 (rate limiting) and 3 (Postgres) all shipped months ago. Delete it or
> replace its body with a pointer to this file; leaving a plan that describes
> the app as having "no auth of any kind" is worse than no plan.

---

## Step 1 — Take a verified dump today, before the demo

**Risk: none (read-only). Do this first even if nothing else ships.**

No code changes. The ~18M `registrations` rows plus crosstabs are many hours
of scraping that was repaired by hand; right now the only copy is one Postgres
data directory and the year-delta `.sql.gz` files.

```
PS> mkdir D:\backups
PS> pg_dump -h localhost -U vahan -d vahan -Fc -f D:\backups\vahan-2026-09-18.dump
```

Expect exit code 0 and a file in the low hundreds of MB (the
`export_year_delta.py` docstring records ~235 MB for a full dump — measure,
don't trust the number).

Verify it restores into a *clean* server, not the one it came from:

```
PS> docker run -d --name vahan-restore-test -e POSTGRES_PASSWORD=x postgres:18-alpine
PS> docker cp D:\backups\vahan-2026-09-18.dump vahan-restore-test:/tmp/d.dump
PS> docker exec vahan-restore-test createdb -U postgres restorecheck
PS> docker exec vahan-restore-test pg_restore -U postgres -d restorecheck --no-owner -j4 /tmp/d.dump
PS> docker exec vahan-restore-test psql -U postgres -d restorecheck -c "SELECT year, count(*) FROM registrations GROUP BY year ORDER BY year"
```

**Acceptance:** the year/count table from `restorecheck` is identical to the
same query run against the live `vahan` database. `pg_restore` exits 0;
`--no-owner` is what stops it complaining that role `vahan` does not exist in
the throwaway container.

**Rollback:** `docker rm -f vahan-restore-test`. Nothing else was touched.

---

## Step 2 — CI: backend tests + ruff, frontend lint + build

**New file:** `.github/workflows/ci.yml`
**New file:** `backend/requirements-dev.txt` (one line: the pinned `ruff`
version, so local and CI run the same rules)

Why now rather than later: it is the only step that touches nothing at
runtime, and it guards steps 6-8, which do touch `main.py`.

Shape — two jobs, `on: [push, pull_request]`, `concurrency` with
`cancel-in-progress: true`:

- **backend** (`ubuntu-latest`, `timeout-minutes: 15`, `working-directory: backend`)
  - `services.postgres`: image `postgres:18-alpine` (match local 18.3 — the
    compose file already documents why the major version is pinned), env
    `POSTGRES_USER: vahan`, `POSTGRES_PASSWORD: vahan`, `POSTGRES_DB: vahan_test`,
    `ports: 5432:5432`, health options `--health-cmd "pg_isready -U vahan"
    --health-interval 10s --health-timeout 5s --health-retries 5`.
    `vahan_test`, not `vahan`: that is what `tests/conftest.py` defaults
    `TEST_DATABASE_URL` to, so no extra env var is needed for it to work.
  - env for the job: `JWT_SECRET_KEY: ci-not-a-real-secret` and
    `DATABASE_URL: postgresql+asyncpg://vahan:vahan@127.0.0.1:5432/vahan_test`.
    The JWT check lives in `lifespan`, which `httpx`'s `ASGITransport` never
    runs — so it is insurance, not a hard requirement, and costs one line.
  - steps: `actions/setup-python@v5` with `python-version: "3.12"`,
    `cache: pip`, `cache-dependency-path: backend/requirements*.txt` ->
    `pip install -r requirements.txt -r requirements-dev.txt` ->
    `python -m ruff check .` -> `python -m pytest -q`.
  - Runtime: ~2.5 min locally, budget 5-7 on a runner (every test does a
    `drop_all`/`create_all`; that is disk-bound and runners are slower).
- **frontend** (`ubuntu-latest`, `working-directory: frontend`):
  `actions/setup-node@v4` with `node-version: "20"`, `cache: npm`,
  `cache-dependency-path: frontend/package-lock.json` -> `npm ci` ->
  `npm run lint` -> `npm run build`.

Things that will break it on the first try if ignored:

- `npm ci` fails if `package-lock.json` is out of sync with `package.json`.
  Both are currently modified-but-uncommitted — commit them together.
- The stray `debug-test*.spec.ts` / `screenshot-pages.spec.ts` at the frontend
  root are untracked. Keep them that way or `eslint .` starts linting them.
- If any test shells out to Tesseract (`live_scrape_service` resolves it
  lazily, so it should not), guard that test with
  `pytest.mark.skipif(shutil.which("tesseract") is None)` rather than
  installing Tesseract on the runner.

**Acceptance (Windows, before pushing — these are the exact CI commands):**

```
PS> cd D:\vahan_dashboard\backend; python -m ruff check .      # "All checks passed!"
PS> python -m pytest -q                                        # "362 passed"
PS> cd D:\vahan_dashboard\frontend; npm run lint; npm run build
```

Pin ruff to whatever `python -m ruff --version` prints locally — an unpinned
ruff introduces new rules on its own schedule and fails a green branch.

**Verifiable on Windows:** the commands, yes. The workflow itself only proves
itself on a push — that is the one part you cannot dry-run here.

**Rollback:** delete the workflow file. It gates nothing until you make it a
required check.

---

## Step 3 — `scripts/backup.sh`: nightly `pg_dump`, on the VPS

**VPS-only.**
**New file:** `scripts/backup.sh`

What it does, in about fifteen lines:

```
docker compose -f /opt/vahan/docker/docker-compose.yml exec -T postgres \
  pg_dump -U vahan -d vahan -Fc > /var/backups/vahan/vahan-$(date +%F).dump
```

- **`-Fc`, whole database.** Custom format is already compressed, restores
  selectively, and parallel-restores with `-j`. Everything is included:
  `registrations`, the crosstabs, `users`, the geo hierarchy.
- **`exec -T`** — without it, Docker allocates a TTY and mangles the binary
  stream. Redirect on the *host* so the dump never lands on container disk.
- **Daily, 03:30 IST**, via the VPS crontab. The scraper loop runs every 5h,
  but one lost day of current-year data is re-scrapeable; the repaired
  historical years are not.
- **Retention: keep the newest 7 dailies and newest 4 weeklies, by COUNT.**
  Not by age. An age sweep runs unconditionally every night, while promotion
  into `weekly/` only happens on a Sunday run that actually succeeded — so a
  month of failed Sundays lets the sweep empty the weekly tier entirely while
  the dailies still look healthy. Keeping the newest N cannot reach zero
  however many runs fail, and it avoids the `-mtime +7` off-by-one question.
- **Off-host copy is the point.** A dump on the same disk as the database
  dies with the VPS. Minimum viable: `rsync`/`scp` the newest file to the Mac
  that already receives year deltas. Do not put dumps in git — `docker/seed/`
  is Git LFS and dumps do not belong there.
- **Exit non-zero loudly.** `set -euo pipefail` plus `[ -s "$OUT" ]`; a
  zero-byte dump from a failed `exec` is the classic silent backup failure.

Why not reuse the existing scripts:

- `app/scripts/export_seed_data.py` is a *product artifact*: schema compiled
  from SQLAlchemy metadata (not the live DB), registrations trimmed to the
  last N years, `users` deliberately excluded. Restoring it gives you a
  plausible-looking database that has quietly lost history and every account.
  Not a backup. It stays what it is.
- `app/scripts/export_year_delta.py` is a *transfer* tool: one year, plain
  SQL, idempotent, psql-applicable across major versions. Great for shipping
  a repaired year to the Mac; useless as a recovery path for the whole DB.
- The one real overlap: after a restore, `export_seed_data.py` is how you
  regenerate `docker/seed/seed.sql.gz`. Note that in the runbook; change no
  code in either script.

Also: a filesystem copy of the `postgres-data` volume while Postgres is
running is **not** a backup — it is a torn page image. Only `pg_dump`, or a
copy taken with the container stopped, counts.

**Acceptance:**

```
VPS> bash /opt/vahan/scripts/backup.sh; echo $?          # 0
VPS> ls -lh /var/backups/vahan/                          # today's file, hundreds of MB, not 0
VPS> pg_restore -f /dev/null /var/backups/vahan/vahan-$(date +%F).dump; echo $?   # 0
```

**Not `pg_restore -l`.** In the custom format the table of contents is written
*before* the data blocks, so `-l` reads a few KB and succeeds on a dump that
was truncated halfway through — which is precisely what a disk filling
mid-dump produces, and precisely what the size check is too coarse to catch.
`-f /dev/null` reads and decompresses every block, so truncation fails it.
The script itself runs this check; these commands just reproduce it by hand.

**Rollback:** `crontab -e`, remove the line. The script writes only to
`/var/backups/vahan`.

---

## Step 4 — `scripts/restore-check.sh`: prove the dump restores

**VPS-only** (the same script runs on Windows against Docker Desktop, which is
how you should smoke-test it first).
**New file:** `scripts/restore-check.sh`

An untested backup is a rumour. This automates exactly what step 1 did by
hand: throwaway `postgres:18-alpine` container -> `pg_restore --no-owner -j4`
the newest dump -> run assertions -> destroy the container.

Assertions, in the script, exiting non-zero on any failure:

1. `SELECT count(*) FROM registrations` is within 1% of the live database's
   count (not equal — the scraper ran between the dump and the check).
2. Per-year counts exist for every year the live DB has; no year is missing
   or zero. This is the check that catches a dump taken mid-repair.
3. `maker_category_totals`, `fuel_category_totals`, `maker_fuel_totals` and
   `users` are all non-empty.
4. The restored DB has the natural-key unique indexes (`idx_reg_natural_key`
   and friends) — `SELECT count(*) FROM pg_indexes WHERE indexname LIKE
   'idx_%_natural_key'` >= 4. A dump that lost them restores "fine" and then
   silently re-admits the duplicate rows `ensure_no_duplicate_rows` exists to
   kill.

Run monthly by cron, **and by hand before the VinFast demo**.

**Acceptance:**

```
VPS> bash /opt/vahan/scripts/restore-check.sh
# RESTORE CHECK PASSED: 18,0xx,xxx registrations across 1x years
```

Then prove it can fail: `head -c 1000000 good.dump > /tmp/truncated.dump` and
point the script at that. It must exit non-zero. A verification script nobody
has seen fail is not evidence.

**Rollback:** delete the script and its cron line; it creates and removes its
own container and touches nothing else.

---

## Step 5 — Bound the log disk before touching the logging code

**File:** `docker/docker-compose.yml`

Add to all three services (`postgres`, `backend`, `frontend`):

```yaml
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"
```

Why here and not in Python: Docker's default `json-file` driver has **no**
size limit, so on a long-running VPS `/var/lib/docker/containers/**/*-json.log`
grows until the disk fills — and it takes the database down with it, since
Postgres is on the same disk. 50 MB per service is plenty to debug a demo and
is one config block, versus a `RotatingFileHandler` that has to be kept in
sync with a bind mount and log ownership.

The `setup-native.sh` path is different: `nohup uvicorn ... > ../backend.log`
grows forever with nothing rotating it. That path is dev-only — say so in the
README rather than adding rotation to it. If it ever runs on a real server,
that server gets a `logrotate` snippet, not app code.

**Acceptance (works on Windows with Docker Desktop):**

```
PS> docker compose -f docker\docker-compose.yml up -d
PS> docker inspect --format '{{json .HostConfig.LogConfig}}' vahan-dashboard-backend-1
# {"Type":"json-file","Config":{"max-file":"5","max-size":"10m"}}
```

**Rollback:** remove the blocks. Note the setting only applies to containers
*created* after the change — `docker compose up -d` recreates them.

---

## Step 6 — Make single-worker explicit, and say so where it is read

**Files:** `backend/Dockerfile` (the `CMD`), `docker/docker-compose.yml`
(comment on the `backend` service), `README.md` (a short "Deployment
constraints" section).

Today the `CMD` is `uvicorn app.main:app --host 0.0.0.0 --port 8020` — single
worker by *omission*. Make it `--workers 1` with a comment naming the three
things that depend on it:

1. `app/core/rate_limit.py`'s `LoginRateLimiter` keeps failure counts in
   process memory. N workers = N x 5 password guesses per window against the
   three publicly-documented demo accounts.
2. `app/core/cache.py`'s `TTLCache` instances are module-level. N workers = N
   independent caches; a user's "refresh" can hop to a worker holding a stale
   entry, so the dashboard shows two different numbers for the same query.
3. The pool budget. `DB_POOL_SIZE=20 + DB_MAX_OVERFLOW=40 = 60` **per
   process**, against `max_connections=100`. Two workers is 120 and the
   excess does not queue — it fails to connect. The scraper processes are
   already eating into that 100 (see `scraper/pool_sizing.py`).

Also write down the honest upgrade path, so the constraint is a decision and
not an accident: multi-worker needs the login limiter and the TTL caches moved
to a shared store, and `DB_POOL_SIZE`/`DB_MAX_OVERFLOW` divided by the worker
count. That is a real day of work. Do not do it speculatively — one worker
comfortably serves a demo and a single customer.

**Acceptance:**

```
PS> docker compose -f docker\docker-compose.yml up -d --build backend
PS> docker compose -f docker\docker-compose.yml exec backend sh -c "ps ax | grep -c '[u]vicorn'"
# 1
```

**Rollback:** revert the `CMD` line. Docs are inert.

---

## Step 7 — Fail fast when more than one worker is *declared*

**File:** `backend/app/main.py` (a check inside `lifespan`, next to the
existing `JWT_SECRET_KEY` hard-fail, which is the precedent)

**The honest finding first.** A running Uvicorn worker cannot reliably count
its siblings. Uvicorn's `Multiprocess` supervisor gives the child no worker
count, no sibling registry, and no documented env var; Gunicorn exposes
`workers` to arbiter hooks, not to application code. Anything that tries —
scanning `/proc` for processes with the same `argv`, counting listeners on the
socket — is a guess that breaks under `docker exec`, under a second container
on the same host, and under any process manager that renames the command. Not
proposing one.

What *is* reliable is reading the declared intent, because there are exactly
three ways this app becomes multi-worker:

- `WEB_CONCURRENCY` in the environment — both Uvicorn's `--workers` and
  Gunicorn's `workers` default to it.
- `--workers N` / `-w N` on the command line. `sys.argv` survives into
  Uvicorn's spawned children (`multiprocessing.spawn` replays the parent's
  argv), so the check fires in every worker, not just the supervisor.
- Gunicorn in front, detectable by `SERVER_SOFTWARE` starting with
  `gunicorn` — treat *any* Gunicorn as suspect and require the opt-out.

If any of those says more than one, raise `RuntimeError` in `lifespan` with a
message that names the three broken invariants from step 6 and points at this
file. Provide one escape hatch, `ALLOW_MULTI_WORKER=true`, so a future reader
who has actually fixed the shared state can proceed without deleting the
check. Wrap the argv parse in `try/except` and default to "1 worker" on
anything unparseable — the guard must never be the reason the API won't boot.

**What this does not catch, stated plainly:** N separate containers or N VPSes
behind a load balancer, each running one worker. Every invariant in step 6
breaks there identically, and no in-process check can see it. That case is
covered by the README section in step 6 and by nothing else.

**Acceptance (Windows):**

```
PS> cd D:\vahan_dashboard\backend
PS> $env:WEB_CONCURRENCY=2; uvicorn app.main:app --port 8021
# RuntimeError naming WEB_CONCURRENCY; process exits
PS> Remove-Item Env:WEB_CONCURRENCY; uvicorn app.main:app --port 8021 --workers 2
# same RuntimeError, from each worker
PS> uvicorn app.main:app --port 8021
# starts normally, /health returns {"status":"ok"}
```

Add one test in `backend/tests/` that calls the check function directly with a
fake env/argv and asserts it raises — the guard is a branch, and branches get
one runnable check.

**Rollback:** delete the check, or set `ALLOW_MULTI_WORKER=true`. The escape
hatch *is* the rollback, which is why it exists.

---

## Step 8 — Traceable errors: request id, one line per request, no new service

**New file:** `backend/app/core/request_context.py` (a `ContextVar` for the
request id plus a `logging.Filter` that stamps it onto every record)
**Files:** `backend/app/main.py` (format string; fold the id/timing into the
existing `security_headers` middleware and rename it),
`backend/app/core/auth.py` (`get_current_user` gains `request: Request` and
sets `request.state.user_id`). `LOG_LEVEL` already exists in `config.py`;
nothing new needed there.

What changes:

1. **Format** — `logging.basicConfig` at `main.py:17` gains `[%(request_id)s]`.
   A `logging.Filter` on the root handler defaults it to `-`, so a log record
   from a module that never saw a request (migrations, the scheduler) still
   formats instead of raising `KeyError`.
2. **Correlation id** — set the ContextVar at the top of the middleware,
   before `call_next`. That direction works with Starlette's
   `BaseHTTPMiddleware` (the downstream task copies the context). The reverse
   does not, which is why the user id goes on `request.state` and not in a
   ContextVar. Echo the id back as an `X-Request-ID` response header so a
   screenshot from the demo maps to a log line.
3. **Accept a client-supplied `X-Request-ID` only if it matches
   `^[A-Za-z0-9._-]{1,64}$`**, otherwise generate one. This is untrusted input
   going straight into log lines: unvalidated, a newline in that header forges
   whole log entries.
4. **One INFO line per request** on the way out: method, path, status,
   duration in ms, `user_id` if `get_current_user` ran. Pair it with
   `--no-access-log` on the Uvicorn command — Uvicorn's access logger sets
   `propagate = False` and its own formatter, so it will never carry the
   request id, and keeping both means two lines per request where only one is
   useful.
5. **The unhandled-exception handler** (`main.py:113`) then inherits the id
   for free; add `user_id` and elapsed ms to its message. **Leave the 57014
   branch exactly as it is** — WARNING, no traceback. That is a deliberate
   design point: burying real crashes under expected timeouts is precisely
   what this step is meant to prevent.
6. **Scrapers are out of scope.** `run_full_scrape.py` and the five siblings
   are separate processes with their own `basicConfig`; changing six
   entrypoints is churn with no payoff, and the scheduler running *inside* the
   API process already inherits the API's root config automatically. Do not
   touch them.

Log levels, unchanged in principle: INFO for the per-request line and lifecycle
events, WARNING for expected-but-notable (57014, default DB password, scrape
retries), ERROR + traceback only for genuine unhandled exceptions.

**Acceptance (Windows):**

```
PS> cd D:\vahan_dashboard\backend
PS> uvicorn app.main:app --port 8021 --no-access-log
PS> curl.exe -s -D- http://localhost:8021/health
# response carries x-request-id: <id>; the console shows exactly one INFO line
#   ... [<id>] GET /health 200 in 3ms
PS> curl.exe -s -D- -H "X-Request-ID: abc-123" http://localhost:8021/health
# same id echoed back and in the log line
PS> curl.exe -s -H "X-Request-ID: bad<newline>INJECTED" http://localhost:8021/health
# header ignored, a generated id used instead, no forged second line
```

And prove the timeout path did not regress: start with
`DB_STATEMENT_TIMEOUT_MS=1`, hit `/api/v1/summary/kpis`, expect HTTP 504, one
WARNING line carrying the request id, and **no traceback**.

Add one test asserting the `X-Request-ID` header is present and that a
well-formed client-supplied id is echoed. One test, not a suite.

**Rollback:** revert the commit. Nothing persists — no files written, no
schema change, no new dependency.

---

## If only part of this ships before the demo

Step 1 (a verified dump) and step 5 (log rotation). Step 1 is the only one
whose absence is unrecoverable.
