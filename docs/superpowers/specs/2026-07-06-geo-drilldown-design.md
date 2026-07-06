# Geo Drill-Down Dashboard — Design Spec

Date: 2026-07-06
Status: Approved (foundation section reviewed with user; remaining sections approved in bulk per "go ahead and build it")

## 1. Problem

The dashboard currently shows state-level vehicle registration data only, using synthetic
placeholder data (no real RTO records, and maker/model/fuel combinations are randomly
assorted test data). The requested capability, from `addition.txt`:

- Drill down All India → Zone (region) → State → District → RTO, with role-scoped views:
  - India head: sees everything
  - Regional head: sees a cluster of states (a "zone")
  - State head: sees only their state, down to RTO level
- Per-model (brand/lineup) breakdown for every maker (e.g. Activa 3G/4G, Unicorn, Shine)
- EV-specific views (market share, adoption trends)
- Real data sourced live from the Parivahan public analytics dashboard
  (`https://analytics.parivahan.gov.in/analytics/publicdashboard/vahan`), with scheduled
  refresh — not synthetic data.

## 2. Scope decisions (confirmed with user)

| Question | Decision |
|---|---|
| Data source | Real scraping from Parivahan, full India, scheduled refresh (not synthetic, not manual import) |
| Backfill | Forward-only from current month; build history over time |
| Roles | Simple role switcher (no login) now; design must not preclude adding real auth/RBAC later; produce a separate doc on how to extend to real auth |
| "Region" meaning | Zone = cluster of states, sits *above* state. Hierarchy: **All India → Zone → State → District → RTO** |
| Map fidelity | Real GeoJSON boundaries for India/states/districts; RTOs shown as markers within their district (no free RTO polygon data exists) |
| Build order | Foundation (geo hierarchy + data model) first, then scraper, then API, then frontend (roles → map → model/EV breakdowns) |

## 3. Geo Hierarchy & Data Model

New/extended tables (SQLAlchemy models in `backend/app/models/models.py`):

- `zones` (new): `zone_code` (PK), `zone_name` — static seed, ~6 MoRTH-style zones
  (North, South, East, West, Central, Northeast) mapping to existing states.
- `states` (existing, extended): add `zone_code` FK column.
- `districts` (new): `district_code` (PK), `district_name`, `state_code` FK.
- `rtos` (existing, extended): add `district_code` FK column (currently only has
  `state_code`).
- `registrations` (existing, unchanged schema): already has `state_code`, `rto_code`,
  `maker`, `vehicle_model`, `fuel_type`, `month`, `year`, `count`. Add composite indexes:
  `(rto_code, year, month)` and `(maker, vehicle_model)`.

**Seeding**: Zone→state mapping and state→district→RTO mapping are static government
reference data (RTO code registries), not something scraped live. These are compiled
once into a seed script (`backend/scripts/seed_geo_hierarchy.py`) run at DB init, similar
to how `states`/`rtos` are currently seeded.

**Aggregation**: computed on-the-fly via grouped SQL (`GROUP BY` on the relevant hierarchy
column), not pre-materialized. Reassess if query latency becomes a problem once RTO-level
data volume grows — can add a summary table later without changing the API contract.

## 4. Live Scraper (Parivahan)

**Known constraints** (confirmed during brainstorming):
- The analytics dashboard returns HTTP 403 to plain HTTP requests — it requires a real
  browser session (the existing `vahan_scraper.py` already works around this with
  Playwright + a spoofed user agent).
- No documented public JSON API exists for this dashboard; data must be extracted from
  rendered tables via browser automation.
- Full India coverage means iterating ~36 states × their RTOs (varies per state,
  hundreds nationally) × vehicle-class/maker crosstabs each refresh — this is a slow,
  multi-hour job that must tolerate partial failure.

**Unknown that needs a discovery spike before full implementation**: the exact
UI interaction sequence to reach an RTO-level, maker × model × month crosstab (the shape
shown in `image.png`) is not yet confirmed — the current scraper only ever selects a
state and reads whatever generic 2-column table is showing; it has never driven an
RTO-level drill-down or a maker/model crosstab. The first scraper task must be a
hands-on spike (install Playwright + browser, drive the live site, record the actual
selector/filter sequence for State → RTO → Vehicle Class → maker/model-by-month) before
the general-purpose scraper is written. The scraper design below assumes this shape is
confirmed by that spike; if the site cannot produce this exact crosstab, we fall back to
whatever finer-grained view it *does* support and adjust ingestion accordingly.

**Scraper architecture** (`backend/scraper/vahan_scraper.py`, rewritten):
- Outer loop: state → RTO (from the seeded `rtos` table) → vehicle class.
- For each combination, extract the maker/model/month crosstab and upsert rows into
  `registrations` (one row per state+rto+maker+model+month+vehicle_class, matching
  existing schema).
- Checkpointing: track last-completed (state, rto, vehicle_class) in a small progress
  table so a crashed/interrupted run resumes rather than restarting from scratch.
- Retry with backoff on transient failures (timeouts, empty tables); log and skip
  (don't abort the whole run) on persistent per-RTO failures.
- Scheduling: extend the existing `scheduler.py` to run this monthly (data is
  month-bucketed) rather than the current ad-hoc trigger; also keep the existing manual
  `/refresh` endpoint for on-demand runs.

## 5. Backend API

New/extended endpoints under `backend/app/api/v1/endpoints/`:

- `geo.py` (new): `/api/v1/geo/zones`, `/geo/zones/{zone_code}/states`,
  `/geo/states/{state_code}/districts`, `/geo/districts/{district_code}/rtos` — hierarchy
  navigation, mirrors existing `states.py` pattern.
- `drilldown.py` (new): `/api/v1/drilldown/summary?level=zone|state|district|rto&code=...`
  — returns aggregated registration totals scoped to the given node, plus its immediate
  children for the next drill level (so the frontend can render one level + "drill
  further" affordance at a time).
- `models.py` (new): `/api/v1/models/by-maker?maker=Honda` and
  `/api/v1/models/lineup?scope=...` — per-model breakdown within a maker, scoped
  optionally to any geo node.
- `ev.py` (new): `/api/v1/ev/share?scope=...` and `/ev/trend?scope=...` — EV vs
  non-EV share and trend, reusing the existing `fuel_type` field (`ELECTRIC`).

All new endpoints accept an optional geo `scope` (zone/state/district/rto code) so the
same endpoints serve India-head (no scope), regional-head (zone scope), and state-head
(state scope) views — scoping logic lives in the query layer, not duplicated per role.

## 6. Frontend

- **Role switcher**: a header control ("Viewing as: India Head" / "Regional Head:
  North Zone" / "State Head: Maharashtra") backed by local/zustand state — no backend
  auth call. Selecting a role sets the `scope` used by all API calls on the drill-down
  pages.
- **Drill-down map** (new page, `pages/DrillDown.tsx`):
  - India view: real state boundary GeoJSON (public, free), choropleth by registration
    volume, click to drill into a state.
  - State view: real district boundary GeoJSON, choropleth by district, click to drill.
  - District view: RTOs shown as markers (points) within the district boundary, sized/
    colored by volume, click to select an RTO.
  - RTO view: table/chart breakdown (maker → model → month), no further map since RTO
    polygons aren't available.
  - Breadcrumb navigation (All India / Zone / State / District / RTO) to jump back up.
- **Model/brand lineup view** (new page): per-maker model breakdown table + chart,
  filterable by the current geo scope from the role switcher.
- **EV market share view** (new page): EV vs non-EV share and trend, filterable by scope.

## 7. Roles/Auth scaling doc (separate deliverable)

Per user request, a standalone doc (`docs/future-auth-scaling.md`) will describe how to
evolve the simple role switcher into real authentication + server-enforced RBAC later:
user/account model, session/JWT approach, mapping accounts to a geo scope, and where the
current scope-based query layer already does most of the enforcement work needed (so the
switch is additive, not a rewrite).

## 8. Testing

- Backend: unit tests for new aggregation queries (hierarchy rollups sum correctly,
  scope filtering is correct) using the existing test DB pattern if one exists, else
  a lightweight in-memory sqlite fixture.
- Scraper: the discovery spike itself is the primary validation; once the shape is
  confirmed, add a smoke test that runs the scraper against one known RTO and asserts
  rows land in `registrations` with the expected columns populated.
- Frontend: manual verification via the `run`/webapp-testing pattern — drive the actual
  drill-down flow (India → zone → state → district → RTO) in a browser and confirm data
  matches backend responses at each level.

## 9. Build order (for the execution plan)

1. Geo hierarchy schema + seed data (zones, districts, extended states/rtos)
2. Scraper discovery spike + rewrite (live RTO-level scraping)
3. Backend drill-down/model/EV endpoints
4. Frontend role switcher + drill-down map
5. Frontend model/brand lineup + EV views
6. Future-auth-scaling doc
