# Vahan Sewa — Go-Live Technical & Commercial Documentation

**Version:** 2.0
**Date:** 2026-09-19
**Verified against:** commit `e45da29`, live PostgreSQL database `vahan`
**Prepared for:** Internal review & stakeholder handoff
**Status:** Application substantially complete. Production deployment artifacts and legal
instruments outstanding.

> **How to read this document.** Every quantitative figure below was verified by direct query or
> file inspection on the date above. Version 1.0 (2026-08-25) went four months without revision and
> became actively misleading in both directions — it understated the data asset, described built
> features as unbuilt, and instructed the reader to run commands against files that do not exist.
> **Re-verify before acting on anything here.** A document without a verification marker is a
> liability.

---

## Executive Summary

Vahan Sewa is a commercial vehicle-registration analytics platform built on VAHAN data published by
the Ministry of Road Transport & Highways, Government of India. It provides 24 years (2003–2026) of
RTO-level registration data across three dimensions (Maker, Vehicle Class, Fuel), with a
Zone → State → District → RTO geographic hierarchy and vehicle-category classification.

**Current state.** Backend API, scraper, 24-year backfill, frontend, authentication, multi-tenant
scoping, and rate limiting are all implemented and running. Eight scoped user accounts exist in the
database.

**What remains before first sale:** audit logging, versioned migrations, production deployment
artifacts, viewer export gating, and the legal instruments. See §3.

---

## 1. Data Foundation — Verified

### 1.1 Live Database (PostgreSQL 18, local)

| Metric | Verified value |
|---|---|
| Time range | **2003–2026 — 24 years, complete** |
| States / UTs | **36** |
| Zones | **6** |
| Districts | **1,115** |
| RTOs (master table) | **1,784** |
| RTOs present in registration data | **1,412** |
| RTO → district mappings | **1,172** |
| **Registration rows** | **18,404,824** |
| Database size | **13 GB** (`registrations` alone: 11 GB) |
| Dimensions | 3 — Maker, Vehicle Class, Fuel |

**Row counts by table:**

| Table | Rows | Size |
|---|---|---|
| `registrations` | 18,404,824 | 11 GB |
| `maker_category_totals` | 3,014,152 | 946 MB |
| `maker_fuel_totals` | 2,517,598 | 686 MB |
| `fuel_category_totals` | 946,586 | 260 MB |
| `maker_live_query_cache` | 977,262 | 246 MB |
| `state_month_category_fuel_totals` | 286,605 | 74 MB |
| `state_month_category_totals` | 120,427 | 30 MB |
| `scrape_quality_log` | 12,560 | 5.3 MB |
| `oem_monthly_sales` (FADA) | **4,034** | 1.9 MB |
| `rtos` | 1,784 | 624 kB |
| `rto_districts` | 1,172 | 160 kB |
| `districts` | 1,115 | 176 kB |
| `states` | 36 | 24 kB |
| `zones` | 6 | 24 kB |
| `users` | 8 | 64 kB |
| `organizations` | 0 | 16 kB |

*18 tables total. v1.0 claimed 8.*

**Canonical vs supplementary split** (the mechanism that prevents triple-counting):

| `is_supplementary` | Rows | Meaning |
|---|---|---|
| `false` | 10,179,697 | Canonical — maker pass, `vehicle_class = 'All'` |
| `true` | 8,225,127 | Breakdown — vehicle-class and fuel passes |

### 1.2 ⚠️ Vehicle Category Values — Corrected

**v1.0 documented these as `2W` / `3W` / `4W` / `CV`. That is wrong and would break any
integration.** The actual stored values are:

```
Two-Wheeler
Three-Wheeler
Four-Wheeler
Commercial Vehicle
Other
```

```sql
SELECT count(*) FROM registrations WHERE vehicle_category = '2W';  -- returns 0
```

All 18,404,824 rows are populated; there are no NULLs. Note the fifth value, `Other`, which v1.0
omitted entirely.

### 1.3 Data Quality & Validation

**Source-anchored validation** (`scraper/vahan_scraper.py:205-247`, wired at `:646` and `:759`).
Before any data is written, `_validate_export` asserts two facts the source states about itself:

- serial numbers form a contiguous `1..N` run — no gaps, no duplicates
- every row's own `Total` column equals the sum of that row's cells

Exact integer equality, no tolerance band. On failure it raises `ExportIntegrityError` and the data
is **rejected, not published**. This is the control that catches the defect class that previously
understated 2003–2024 by 31–77%.

**Detection coverage** (measured against synthetic corruption):

| Corruption | Result |
|---|---|
| First row dropped (the historical pagination bug) | ✅ Caught |
| Middle row dropped | ✅ Caught |
| Duplicated row | ✅ Caught |
| Single cell inflated | ✅ Caught |
| Row total inflated | ✅ Caught |
| **Every row inflated with totals adjusted to match** | ❌ **Not caught** |

The final row is the honest limit: this is a **consistency** check, not an **authenticity** check.
It proves "what we parsed matches what we were sent." It cannot prove "what we were sent is true."

**Cross-source reconciliation.** `registrations` and `maker_category_totals` are populated by
independent scrape paths with different pivots and request shapes. All 24 years agree to within
**1.83%** worst case, with 19 of 24 years matching exactly. This is the strongest authenticity
signal available, because a defect would have to corrupt both paths identically.

**Database-enforced idempotency.** Unique natural-key indexes on all five fact tables. A replayed
scrape conflicts loudly rather than silently double-counting.

**Refresh cadence.** `scraper/scheduler.py:16` — `REFRESH_INTERVAL_HOURS = 5`, with exponential
backoff capped at `MAX_BACKOFF_HOURS`. Two further scheduler loops exist (FADA daily,
previous-year revalidation), both **disabled by default** via `ENABLE_FADA_SCRAPER` and
`ENABLE_PREVIOUS_YEAR_REVALIDATION`. Exactly one scheduler runs as shipped.

### 1.4 ⚠️ Query Performance — No Benchmark Exists

**v1.0 published a table of P95 latencies (50 ms – 1.5 s). Those numbers have no backing
measurement and have been removed.** There is no load test, no benchmark script, and no timing log
anywhere in the repository.

What the code actually records:
- `app/api/v1/endpoints/refresh.py:17-21` — "confirmed live: up to 35s on a fresh install"
- `app/core/config.py:75` — `DB_STATEMENT_TIMEOUT_MS = 30_000`, because queries do time out

**Do not quote performance figures to a customer until a k6 or Locust run produces them.**

---

## 2. Implemented Technical Stack

### 2.1 Backend (FastAPI + SQLAlchemy async + PostgreSQL)

```
backend/
├── app/
│   ├── api/v1/endpoints/          # 14 modules, 48 routes (see Appendix C)
│   ├── core/
│   │   ├── auth.py                # bcrypt, JWT, get_current_user, require_role
│   │   ├── scope.py               # multi-tenant scope dependencies (111 lines)
│   │   ├── rate_limit.py          # slowapi limiter + login lockout
│   │   ├── request_context.py     # correlation IDs (ContextVar + X-Request-ID)
│   │   ├── worker_guard.py        # refuses multi-worker boot — see §4
│   │   ├── config.py              # settings
│   │   ├── database.py            # async engine, statement timeout
│   │   ├── migrations.py          # hand-rolled convergence DDL (NOT Alembic)
│   │   ├── cache.py               # TTLCache helpers
│   │   ├── query_filters.py       # shared filter builder
│   │   └── scrape_lock.py         # advisory locks
│   ├── models/models.py           # 13 model classes / 18 tables
│   ├── schemas/schemas.py
│   ├── scripts/
│   │   ├── seed_geo_hierarchy.py
│   │   └── create_admin.py
│   └── services/
│       ├── scraper_service.py
│       └── live_scrape_service.py
├── scraper/                       # 13 modules (see below)
├── tests/                         # 34 test files, 362 tests
└── requirements.txt               # 17/17 pinned
```

**Scraper modules (13):** `vahan_scraper.py`, `analytics_scraper.py`, `fada_scraper.py`,
`backfill_all_years.py`, `backfill_fada.py`, `run_full_scrape.py`, `run_analytics_scrape.py`,
`run_analytics_fuel_scrape.py`, `run_crosstab_scrape.py`, `run_top_makers_scrape.py`,
`scheduler.py`, `parsing.py`, `pool_sizing.py`.

> **v1.0 listed `explore.py` as a delivered feature. That file does not exist** and has been
> removed from this inventory.

### 2.2 Frontend (React + TypeScript + Vite + Recharts)

**9 pages** — Overview, Comparison, YoY, Categories, CategoryDetail, MakersModels, RTO, Industry,
Login.
**7 hooks** — useAppStore, useTheme, useChartTheme, useSettledLayout, useIsLiveData, useScopeLock,
useUrlSyncedFilters.
**13 components** — including ErrorBoundary, ErrorBanner, EmptyState, ExportCsvButton,
LiveMakerQueryPanel, PowertrainToggle, ThemeToggle, LabeledSelect, ChartAxisTick.

Also present: `src/api/auth.ts`, `src/contexts/AuthContext.tsx`, `src/utils/csv.ts`,
`src/utils/tripleEstimate.ts`, `src/types/index.ts`.

### 2.3 Infrastructure

`docker/` is a **top-level** directory (not under `backend/`) containing `docker-compose.yml` (dev
stack: postgres + backend + frontend) and a `seed/` directory.

Dockerfiles exist at `backend/Dockerfile`, `backend/scraper/Dockerfile`, `frontend/Dockerfile`,
plus `frontend/nginx.conf`. **No `.prod` variants exist** — see §4.

---

## 3. What Remains Before First Sale

> **v1.0's §3 "Missing Commercial Layer" is obsolete. Most of it is built.** The list below is
> what is genuinely outstanding.

### 3.1 Already Built (do not rebuild)

| Capability | Where |
|---|---|
| Password hashing (bcrypt) | `app/core/auth.py` |
| JWT in httpOnly cookie, 24h expiry | `app/core/auth.py`, `endpoints/auth.py:62-64` |
| Algorithm pinned to HS256 | `app/core/auth.py:36-39` |
| Role/scope re-read from DB per request | `app/core/auth.py:56-60` |
| Three roles — admin / analyst / viewer | `app/models/models.py` |
| Geographic scoping — national / state / RTO | `app/core/scope.py` |
| Vehicle-category scoping (independent axis) | `app/core/scope.py` |
| Admin-only refresh | `endpoints/refresh.py:28` |
| Rate limiting (120/min) + login lockout | `app/core/rate_limit.py` |
| Admin bootstrap script | `app/scripts/create_admin.py` |
| User & organization provisioning APIs | `endpoints/users.py`, `organizations.py` |
| Correlation IDs end-to-end | `app/core/request_context.py` |
| Multi-worker fail-closed guard | `app/core/worker_guard.py` |

**Live accounts:**

| Role | Scope | Count |
|---|---|---|
| admin | national | 4 |
| analyst | national | 2 |
| analyst | state | 1 |
| viewer | rto | 1 |

### 3.2 Actual Scope Model (as built)

**v1.0 proposed a separate `user_scope` table. That is not what exists.** Scope is denormalized
onto `users`:

```sql
-- columns on the users table
scope_type              -- 'national' | 'state' | 'rto'
scope_state_code
scope_state_name
scope_rto_code
scope_rto_name
scope_vehicle_category  -- full words: 'Two-Wheeler' etc., NULL = all
organization_id
```

Note the vocabulary differs from v1.0's proposal: `rto` exists; `region` and `all_india` do not
(`national` is the top tier).

**Enforcement is per-endpoint FastAPI dependencies**, not a global query-rewriter:
`get_effective_state`, `get_effective_category`, `require_state_code`, `require_rto_code`,
`scoped_category`, `scoped_rto`, `enforce_state`.

> **Why v1.0's `get_scoped_db` event-listener design was rejected.** A SQLAlchemy event listener
> injecting WHERE clauses cannot reliably know which of 18 tables or aliases to constrain in a
> given statement, and raw `text()` queries bypass it entirely. It would have silently missed the
> exact leak class that has actually occurred here — endpoints with no `rto_code` parameter to
> clamp. `scope.py`'s own docstring records the incident: *"an RTO account saw ~18.6x its paid
> scope … a param that doesn't exist can't be clamped, so the filter has to be injected here
> instead."* The explicit-dependency approach is deliberate. Do not replace it.

### 3.3 Outstanding — Engineering

| # | Item | Why it matters | Est. |
|---|---|---|---|
| 1 | **Commit untracked work** — `.github/`, `scripts/`, `request_context.py`, `worker_guard.py` | CI, DR scripts and request tracing exist on one disk only | 5 min |
| 2 | **Fix the red test** — `test_scrape_lock.py` fails on missing `aiosqlite` | CI fails on first run | 15 min |
| 3 | **Audit logging** — no table, no code, zero grep matches | Cannot answer "which customer saw what" after a scope leak. Four have occurred. | 2 hrs |
| 4 | **Alembic** — no migration environment exists | `migrations.py` runs unversioned DDL on every boot | 1 day |
| 5 | **Production deploy artifacts** — see §4 | Nothing to deploy with | 1 day |
| 6 | **Viewer export gating** — `ExportCsvButton` has no role check | A documented role restriction is unenforced | 2 hrs |
| 7 | **Redis** for caches + rate limiter | Prerequisite for >1 worker | 1 day |
| 8 | **Load test** (k6) | §1.4 cannot be filled in without it | 1 day |

### 3.4 Outstanding — Legal & Commercial

| # | Item | Status |
|---|---|---|
| 1 | **MoRTH reproduction permission** — written request to `wim.rth@nic.in` | ⚠️ **Not requested.** See §5.1. |
| 2 | **Restore source attribution** to UI and exports | ⚠️ **Currently removed.** See §5.1. |
| 3 | Terms of Service | Not drafted |
| 4 | Privacy Policy (DPDP Act 2023) | Not drafted |
| 5 | Data License Agreement | Not drafted |
| 6 | SLA with uptime target + service credits | Not defined |
| 7 | Liability cap | Not defined |
| 8 | GSTIN active before first invoice | To confirm |
| 9 | **Reconcile pricing contradiction** | ⚠️ See §6.1 |

---

## 4. Production Hosting

### 4.1 ⚠️ Single Worker Is Mandatory

**v1.0's topology specified "Uvicorn workers (4)". That configuration will not boot.**

`app/core/worker_guard.py` raises at startup on any declared worker count above 1, and it is
correct to do so:

1. `rate_limit.py`'s `LoginRateLimiter` counts failed logins **in process memory** — N workers
   means N × 5 password guesses per window against accounts whose emails are public.
2. The `TTLCache` instances in `endpoints/*` are module-level — N workers means N independent
   caches, so the same query can return different numbers depending on which worker answers.
3. `DB_POOL_SIZE + DB_MAX_OVERFLOW` = 60 connections **per process** against
   `max_connections = 100`. Two workers is 120, and the excess does not queue — it fails.

Escape hatch is `ALLOW_MULTI_WORKER=true`, for whoever has actually moved the limiter and caches to
Redis and divided the pool sizes. The guard reads *declared* intent and is blind to N separate
containers — that case is covered by documentation and nothing else.

### 4.2 ⚠️ Sizing — v1.0's Plan Does Not Fit

v1.0 specified **25 GB managed PostgreSQL with 1 GB RAM at $15/mo**, sized against a claimed 2.5 GB
database.

**The database is 13 GB today** (`docs/HOSTING_AND_ACCESS.md` records 17 GB+ with indexes) and
grows ~1.0–1.6M rows/year. A 25 GB instance is over half-consumed at provisioning and 1 GB RAM
cannot hold the working set of an 11 GB fact table.

Realistic sizing is approximately **$89/month** — 4 vCPU / 8 GB droplet plus ~250 GB block storage
and object-storage backups. Reconcile against `docs/HOSTING_AND_ACCESS.md`; do not leave two
contradictory answers in the repo.

### 4.3 ⚠️ Reverse Proxy — Header Compatibility

`rate_limit.py:16-17` keys the limiter on **`X-Real-IP`**, matching `nginx.conf:28`
(`proxy_set_header X-Real-IP`).

**Caddy sets `X-Forwarded-For`, not `X-Real-IP`.** Adopting v1.0's Caddy topology unchanged would
silently break per-IP rate limiting — the limiter would see no header and fall back to a single
bucket for all clients. If Caddy is used, either configure it to set `X-Real-IP` explicitly or
update the limiter.

> Also note: if uvicorn is ever exposed directly, any client can forge `X-Real-IP` and mint its own
> rate-limit bucket. The current design is safe only because nginx is uvicorn's sole client.

### 4.4 Deployment Artifacts — None Exist

**Every file v1.0's §10 instructs you to run is missing:**

```
MISSING: docker-compose.prod.yml
MISSING: Caddyfile
MISSING: backend/Dockerfile.prod
MISSING: frontend/Dockerfile.prod
MISSING: backend/alembic
```

Three of the four commands in v1.0's "Immediate Action Items" fail immediately. These must be
authored before any deployment attempt.

---

## 5. Data Source, Rights & Attribution

### 5.1 ⚠️ Attribution Is a Licence Condition, Not a Branding Choice

v1.0 §2.3 listed **"zero government references in UI"** as a delivered feature. This is the most
serious non-technical finding in this review.

MoRTH's published website policy makes reproduction conditional on **both**:
1. **Prior written permission** — request to `wim.rth@nic.in`
2. **Appropriate source acknowledgement**, accurately and not in a misleading context

Source: https://parivahan.gov.in/content/website-policies

Stripping every government reference is therefore not neutral white-labelling — it removes the one
condition the business's right to use this data depends on. It also creates a misrepresentation
exposure toward customers who are not told the underlying dataset is free and public.

**Required actions:**
1. **Email `wim.rth@nic.in` requesting written reproduction permission.** Costs nothing; converts
   the largest legal exposure into the strongest sales claim.
2. **Restore attribution** to the UI footer and every export:
   *"Source: VAHAN Dashboard, Ministry of Road Transport & Highways, Government of India."*
3. **Invert the positioning** — *"built on official MoRTH VAHAN public data, engineered into
   RTO-level analytics."* Provenance is a trust asset for a data product; it answers the "can I
   rely on these numbers" question every OEM planner asks. The moat is the 24-year backfill, RTO
   granularity, validation and query speed — not secrecy about the source.

### 5.2 What the Data Cannot Do

State these limits in every customer-facing document. Discovering them in a trial is worse than
reading them in a proposal.

| Not available | Reason |
|---|---|
| **Model-level data** (individual vehicle models) | VAHAN's public reporting exposes Maker as its finest manufacturer-side axis. The `vehicle_model` column exists but is **0-populated across all 18.4M rows**. ⚠️ It is still exposed as an API filter and returns empty rather than an error — **fix before any customer sees it.** |
| Retail vs wholesale split | VAHAN reports registrations, not manufacturer dispatches |
| Customer-level / PII data | Not published; restricted under DPDP Act 2023 |
| Dealer-level performance | RTO is the finest geographic unit available |
| Pricing / specification / incentive data | Not part of the registration dataset |

---

## 6. Go-to-Market

### 6.1 ⚠️ Unresolved Pricing Contradiction

| Source | Top price |
|---|---|
| This document's rate card (v1.0 §5.1) | **₹59,999/mo** — All-India, Full Catalog, **unlimited seats** |
| Live VinFast proposal | **₹2,00,000/mo** — All-India, 25 seats |

**A 3.33× gap for the same SKU, both in writing.** Under the rate card's own axes, VinFast's
requirement prices at ₹59,999/mo at most.

Two further problems with the rate card as written:
- **It does not self-consistently add up.** "All-India 2W + 5 seats" is listed at ₹29,999, but the
  stated axes give 29,999 + 4,999 + 5,000 = ₹39,998. A buyer with a spreadsheet finds this in five
  minutes and concludes prices are invented per deal.
- **"Unlimited seats" caps enterprise revenue permanently** at ₹7.2L/year and makes the DLA's
  anti-sharing clause the only thing between one paid account and an entire OEM planning
  department.

**Resolve before the next quote.** Either (a) restructure the ₹24L into a genuinely different bill
of materials — platform licence + named analyst retainer + SSO/API + onboarding + accuracy
warranty + support SLA — or (b) accept that ₹24L was anchoring and revise before contracting.
Either way: **kill "unlimited", cap the published tier at a bounded seat count**, and decide
explicitly whether prices are public. The Indian auto-analytics buyer pool is small and networked.

### 6.2 External Price Anchors

| Reference | Price |
|---|---|
| VAHAN public dashboard (the source) | **Free** |
| Auto Punditz (published VAHAN analysis, monthly) | **Free** |
| SIAM — full 5-product statistical bundle | **~₹2.21 lakh/yr** |
| SIAM — monthly **model-wise** data alone | **₹47,300/yr** |
| Mordor Intelligence — enterprise report licence | ~USD 8,750 |
| JATO Dynamics / S&P Global Mobility | Quote-only, no published rate card |
| Frost & Sullivan enterprise subscription | ~USD 100,000+/yr (third-party estimate) |

The uncomfortable comparison: SIAM sells a **superset** — including the model-wise data this
platform cannot supply — for roughly **1/11th** of the VinFast ask. The defensible counter-argument
is RTO-level granularity, 24-year depth, scoped multi-user access and refresh cadence, none of
which SIAM offers. **Write that value-basis down before the next quote.**

### 6.3 Payments — Structural Constraints

- **RBI e-mandate AFA exemption is ₹15,000 per recurring transaction.** Every tier above ₹15,000/mo
  requires customer-side authentication each cycle — a direct cause of involuntary churn. The ₹1
  lakh exemption applies only to mutual-fund SIPs, insurance premiums and credit-card bills.
  **Sell annual contracts on NEFT/RTGS against a GST invoice above ₹15,000/mo**; reserve card/UPI
  autopay for the entry tier.
- **Indian corporate buyers deduct TDS** (commonly s.194J) from SaaS payments. Auto-debit cannot
  accommodate this. Get a written CA position and state it in the ToS.
- **Stripe India is invite-only** — "Stripe later" is not a plan. If the contracting entity is
  VinFast's Vietnam parent, this is an export of services needing an LUT to be zero-rated, plus
  FIRC/e-BRC documentation. **Confirm the contracting entity before quoting.**
- **GSTIN must be active before the first invoice** — a ₹24L contract crosses the ₹20 lakh services
  threshold immediately. E-invoicing (IRN) is not triggered below ₹5 crore turnover.

### 6.4 Sales Motion

v1.0 §5.4 promised self-serve signup by month 3–4; v1.0 §7 gated it on 10+ buyers. **The §7
trigger-based version is correct** — enterprise data buyers at ₹15k–60k/mo do not swipe a card on
a new vendor's site, and self-serve conflicts directly with the DLA and scoping that constitute the
commercial moat.

Revised: **sales-assisted through the first 10 paying accounts.** Defer the reseller channel until
20+ accounts and a documented win rate exist.

---

## 7. Security Checklist

| Control | Status | Evidence |
|---|---|---|
| Authentication (bcrypt + JWT) | ✅ | `app/core/auth.py` |
| JWT algorithm pinned | ✅ | `auth.py:36-39` — HS256 only |
| httpOnly cookie | ✅ | `endpoints/auth.py:62-64` |
| Role re-read from DB per request | ✅ | `auth.py:56-60` — revocation is immediate |
| Multi-tenant scoping | ✅ | `app/core/scope.py` |
| Fail-closed on default JWT secret | ✅ | `main.py:46-50` |
| Rate limiting | ✅ | `rate_limit.py` — 120/min + login lockout |
| Correlation IDs | ✅ | `request_context.py` |
| Secrets not in repo | ✅ | `.env` git-ignored |
| API docs disabled by default | ✅ | `ENABLE_API_DOCS = False` |
| Dependencies pinned | ✅ | 17/17 in `requirements.txt` |
| **Audit logging** | ❌ | **Zero grep matches. Four scope leaks have occurred.** |
| **Row-Level Security** | ❌ | 0 tables; app owns all 18, would bypass RLS anyway |
| Least-privilege DB role | ❌ | App connects as `vahan`, the owner |
| Dependency scanning | ❌ | No dependabot / pip-audit / bandit |
| HTTPS / TLS | 🔲 | Deployment-time |
| SSH key-only + fail2ban | 🔲 | Deployment-time |
| Firewall (ufw) | 🔲 | Deployment-time |
| Backups | ⚠️ | `scripts/backup.sh` + `restore-check.sh` exist but are **untracked in git** |
| Data License Agreement | 🔲 | Not drafted |

> On RLS: `ALTER TABLE ... FORCE ROW LEVEL SECURITY` makes policies apply to the owner too, so a
> least-privilege role is the better design but not a hard prerequisite.

---

## 8. Risk Register — Revised

v1.0's register tracked "PostgreSQL cost spike" while omitting every risk capable of ending the
business. Added below and marked **[NEW]**.

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **[NEW] Commoditisation** — data is free; Auto Punditz publishes analysis monthly at zero cost | **High** | **High** | Compete on granularity, depth, validation and scoped access — never on data access itself. Say the source is public before the customer discovers it. |
| **[NEW] Source dependency** — one scraper is the sole supply line for the entire product | **High** | **Critical** | Store raw artifacts so re-parsing does not require re-scraping; monitor for portal changes; define SLA force-majeure for source unavailability |
| **[NEW] Attribution / licence breach** — reproduction permission never requested, attribution removed | **High** | **Critical** | Request permission in writing; restore attribution (§5.1) |
| **[NEW] Customer concentration** — VinFast would be ~100% of revenue | **High** | **Critical** | Close 2–3 accounts before treating revenue as durable |
| **[NEW] Key-person risk** — single founder on legal, sales, delivery and product | **High** | **High** | Document runbooks; commit all work to git; define founder hours and cut scope to fit |
| **[NEW] Model-level expectation gap** — customers assume model data exists | **High** | **High** | Disclose in every proposal; fix the empty-returning API filter |
| **[NEW] Uncapped liability** — no SLA, no cap, no accuracy warranty | Medium | **Critical** | Cap at trailing 12 months' fees; exclude consequential loss; disclaim fitness for specific decisions |
| **[NEW] Price discovery** — 3.33× gap between rate card and live quote | Medium | **High** | Resolve §6.1 before the next quote |
| VAHAN portal changes break scraper | Medium | High | `_validate_export` fails closed; add alerting |
| Scraper IP blocked | Low | High | 1.5s pacing; proxy rotation as contingency |
| Buyer resells data | Low | Critical | DLA + audit logging (**not yet built**) |
| Data freshness SLA missed | Medium | High | ⚠️ **No SLA is defined.** Define before committing to one. |
| Compliance audit failure | Low | Critical | ⚠️ Mitigation was "audit logs" — **which do not exist** |

---

## 9. Implementation Roadmap — Revised

> v1.0 proposed 3 weeks to pilot. That assumed auth was unbuilt (it is) and that legal could run in
> parallel (it cannot — lawyer turnaround is 2–4 weeks and the DLA is a stated pre-deploy blocker).
> **Realistic range: 6–8 weeks**, with legal on the critical path.

**Week 1 — Housekeeping & legal start**
- Commit untracked work; fix the red test (**25 minutes combined**)
- **Email MoRTH for reproduction permission** — do this first, it has the longest lead time
- Restore source attribution to UI and exports
- Brief to lawyer: ToS, Privacy Policy, DLA
- Resolve the pricing contradiction (§6.1)

**Week 2–3 — Engineering gaps**
- Audit logging table + middleware
- Alembic baseline (`revision --autogenerate`, then `stamp head` on the live DB)
- Production artifacts: `Dockerfile.prod` ×2, `docker-compose.prod.yml`, reverse-proxy config
  (mind §4.3 header compatibility)
- Viewer export gating
- Fix the `vehicle_model` filter to return a clear "not available" rather than empty

**Week 4 — Infrastructure**
- Provision droplet + managed PG **sized for 13 GB+, not 25 GB**
- DNS, TLS, ufw, fail2ban, SSH keys
- Restore drill from backup — prove it works
- Staging environment

**Week 5 — Observability & validation**
- Sentry (backend + frontend)
- `/health/live` and `/health/ready` split — note a readiness probe drawing from the same
  60-connection pool will block under exhaustion; use a dedicated connection or a hard 2s timeout
- k6 load test → fill in §1.4 with measured numbers

**Week 6–8 — Pilot**
- Legal documents executed
- Onboard 2 pilot accounts manually
- Collect usage, iterate pricing
- Razorpay only after pricing is locked

---

## Appendix A: Scraper Technical Details

*Verified accurate against `scraper/vahan_scraper.py`. Carried forward from v1.0.*

**Protocol:** JSF/PrimeFaces AJAX over HTTP, no browser.
- **ViewState** extracted from the `javax.faces.ViewState` hidden field and CDATA updates
- **Full form replay** — every AJAX POST resends all current field values
- **State dropdown ID drift** — discovered by content (`"All Vahan4 Running States (N/36)"`), not
  by position
- **Key element IDs:** `selectedRto`, `yaxisVar`, `xaxisVar`, `selectedYear`, `irclay` (refresh),
  `groupingTable` (results)
- **Pagination:** `PAGE_SIZE = 25`, `groupingTable_pagination`, `groupingTable_first`,
  `groupingTable_rows`
- **Pacing:** `REQUEST_DELAY_SECONDS = 1.5` between RTO requests
- **Concurrency:** `asyncio.Semaphore` over per-state workers, each with an independent HTTP
  session and ViewState. Default `SCRAPER_CONCURRENT_STATES = 4` (`config.py:39`)
- **Transport:** `httpx.AsyncClient`, default TLS verification, `follow_redirects=True`, 30s timeout
- **Validation:** `_validate_export` at `:205-247`, enforced at `:646` and `:759`

**Session expiry** is distinguished from other failures via `_is_session_expired` with a bounded
refresh-retry budget.

> **Gap:** `analytics_scraper.py` and `fada_scraper.py` have **no validation** — no S-No check, no
> total reconciliation. The analytics scraper solves CAPTCHAs via OCR, so a misread returning a
> wrong-but-valid page has nothing checking it. Port `_validate_export` to both.

---

## Appendix B: Database Schema

```sql
CREATE TABLE registrations (
    id BIGSERIAL PRIMARY KEY,
    state_code VARCHAR(5) NOT NULL,
    state_name VARCHAR(100) NOT NULL,
    rto_code VARCHAR(10),
    rto_name VARCHAR(200),
    month SMALLINT NOT NULL,
    year SMALLINT NOT NULL,
    vehicle_class VARCHAR(200) NOT NULL,
    maker VARCHAR(200),
    fuel_type VARCHAR(100),
    norms_type VARCHAR(100),
    day SMALLINT,
    vehicle_model VARCHAR(200),        -- 0-populated across all 18.4M rows
    vehicle_category VARCHAR(20),      -- 'Two-Wheeler' | 'Three-Wheeler' |
                                       -- 'Four-Wheeler' | 'Commercial Vehicle' | 'Other'
    commercial_tier VARCHAR(15),
    is_supplementary BOOLEAN DEFAULT FALSE,
    count INTEGER DEFAULT 0,
    recorded_at TIMESTAMPTZ DEFAULT now()
);
```

**⚠️ All 14 indexes on `registrations`.** v1.0 listed only 3 and **omitted the unique natural key**
— rebuilding the schema from v1.0 loses idempotent re-scraping and accumulates duplicates.

```sql
-- UNIQUE — idempotency. Do not omit.
idx_reg_natural_key

-- Query-pattern indexes
idx_reg_class_state_rto
idx_reg_rto_year_supp_month_maker_count
idx_reg_state_year_month_count
idx_reg_year_category_month_count
idx_reg_year_class_month_count
idx_reg_year_fuel_count
idx_reg_year_maker_count
idx_reg_year_month_supp_count
idx_reg_year_supp_state_count
ix_registrations_month
ix_registrations_state_code
ix_registrations_vehicle_category
registrations_pkey
```

Equivalent unique natural-key indexes exist on `maker_category_totals`, `maker_fuel_totals`,
`fuel_category_totals`, `oem_monthly_sales`, and the state-month aggregate tables.

**Geo hierarchy** (verified — matches v1.0):

```sql
CREATE TABLE zones     (zone_code VARCHAR(10) PK, zone_name VARCHAR(100));
CREATE TABLE states    (state_code VARCHAR(5) PK, state_name VARCHAR(100), zone_code FK);
CREATE TABLE districts (district_code VARCHAR(120) PK, district_name VARCHAR(200), state_code FK);
CREATE TABLE rtos      (rto_code VARCHAR(10) PK, rto_name VARCHAR(200), state_code FK);
CREATE TABLE rto_districts (rto_code FK, district_code FK, PK(rto_code, district_code));
```

**Auth (as built — note the scope columns live on `users`):**

```sql
CREATE TABLE users (
    id, email UNIQUE, hashed_password, role,        -- 'admin'|'analyst'|'viewer'
    is_active,
    scope_type,                                     -- 'national'|'state'|'rto'
    scope_state_code, scope_state_name,
    scope_rto_code, scope_rto_name,
    scope_vehicle_category,                         -- full words; NULL = all
    organization_id FK
);

CREATE TABLE organizations (...);   -- exists, 0 rows

-- NOT YET BUILT:
-- CREATE TABLE audit_log (id, user_id, endpoint, scope_resolved JSONB, created_at);
```

---

## Appendix C: API Endpoint Inventory

**14 modules, 48 routes.** All 14 are authenticated — 12 reference `get_current_user` /
`require_role` directly; `registrations.py` and `rto.py` authenticate transitively through scope
dependencies that themselves depend on `get_current_user`.

| Module | Routes | Notes |
|---|---|---|
| `auth.py` | 3 | `POST /login`, `POST /logout`, `GET /me` — **no `/refresh`**; design uses a 24h cookie |
| `categories.py` | 8 | Category and fuel breakdowns |
| `comparison.py` | 2 | State/category/maker comparison; `limit` bounded 1–200 |
| `geo.py` | 4 | ⚠️ **Actual paths:** `/geo/zones`, `/geo/zones/{zone_code}/states`, `/geo/states/{state_code}/districts`, `/geo/districts/{district_code}/rtos`. **There is no `/geo/tree`** — v1.0's four geo paths were all wrong. |
| `live_query.py` | 4 | On-demand maker lookup; RTO-scope enforced |
| `oem_sales.py` | 4 | FADA monthly sales |
| `organizations.py` | 3 | Provisioning |
| `refresh.py` | 4 | Admin only; `/refresh/data-quality` is the freshness signal |
| `registrations.py` | 2 | `limit` capped at 5,000; **no offset/cursor pagination** |
| `rto.py` | 2 | RTO drill-down; `scoped_rto` enforced |
| `states.py` | 2 | State lookups |
| `summary.py` | 5 | KPIs, trend, state ranking, month detail, available years |
| `users.py` | 3 | Provisioning |
| `yoy.py` | 2 | Year-over-year growth |

Plus `GET /health` (unauthenticated — ⚠️ returns a literal `{"status": "ok"}`, checks nothing; see
§3.3).

---

## Appendix D: Corrections from v1.0

| v1.0 claim | Verified reality | Severity |
|---|---|---|
| "No authentication, no commercial access controls" | Auth, scoping, rate limiting all built; 8 live accounts | Critical |
| Category values `2W`/`3W`/`4W`/`CV` | `Two-Wheeler`/`Three-Wheeler`/`Four-Wheeler`/`Commercial Vehicle`/`Other` — documented codes return **0 rows** | Critical |
| "Uvicorn workers (4)" | `worker_guard.py` refuses to boot — container crash-loops | Critical |
| DB size ~2.5 GB → 25 GB managed PG | **13 GB**; plan does not fit | Critical |
| P95 latency table | **No benchmark exists anywhere** | Critical |
| Appendix B lists 3 indexes | **14**, and the omitted one is the unique natural key | Critical |
| `docker-compose.prod.yml`, `Caddyfile`, `Dockerfile.prod`, `alembic` | **All missing** — 3 of 4 §10 commands fail | Critical |
| Proposed `user_scope` table + `get_scoped_db` listener | Scope denormalized onto `users`; explicit per-endpoint dependencies | Critical |
| ~13–15M registration rows | **18,404,824** | High |
| ~530 active RTOs | **1,412** in data, 1,784 in master | High |
| 700+ districts | **1,115** | High |
| 8 tables | **18** | High |
| FADA ~50K rows | **4,034** | High |
| `explore.py` delivered | **Does not exist** | High |
| `/geo/tree`, `/geo/states`, `/geo/districts`, `/geo/rtos` | **None exist** — actual paths differ | High |
| "Alembic-ready" | No Alembic environment | High |
| MH45 AKLUJ 1,008/288/144 records | 626 canonical + 432 supplementary — does not reconcile | High |
| 11 endpoints | **14 modules, 48 routes** | Medium |
| 7 frontend pages | **9 pages, 7 hooks, 13 components** | Medium |
| `POST /auth/refresh` | Not built; 24h cookie by design | High |
| "viewer: no exports" | Not enforced — `ExportCsvButton` has no role gate | High |
| "Dev + production-ready configs" | Only the dev compose file exists | Critical |
| "Zero government references" as a feature | **Conflicts with MoRTH's attribution condition** | Critical |

---

**End of Document** — verified against commit `e45da29` and the live `vahan` database on
2026-09-19. Re-verify before acting.
