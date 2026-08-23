# Vehicle Taxonomy Redesign (Subsystem A)

## Problem

`vehicle_class` currently stores VAHAN's 89 raw categories verbatim
(`M-CYCLE/SCOOTER`, `THREE WHEELER (GOODS)`, `AGRICULTURAL TRACTOR`, ...).
That's too granular to sell as a category breakdown to companies who think
in terms of 2-Wheeler / 3-Wheeler / 4-Wheeler / Commercial Vehicle, and it's
the blocker for Subsystem B's category-based licensing (a buyer scoped to
"2-Wheeler only" needs a real category to scope by).

Also want an ICE/Hybrid/EV filter, independent of vehicle category.

## Approach

Two new persisted, indexed columns on `Registration`:

- `vehicle_category`: `Two-Wheeler` | `Three-Wheeler` | `Four-Wheeler` |
  `Commercial Vehicle` | `Other`
- `commercial_tier`: `LCV` | `MCV` | `HCV` | `Unspecified` | `NULL` (NULL
  unless `vehicle_category = 'Commercial Vehicle'`)

Persisted rather than computed-on-read (unlike `fuel_category()`) because
Subsystem B needs `WHERE vehicle_category = 'Two-Wheeler'` to be a real SQL
predicate for access control to mean anything — computing it in Python after
the fact gives B nothing to enforce against.

Classification is an explicit lookup dict (`RAW_CLASS_TO_CATEGORY`), not
substring rules like `fuel_category()` — VAHAN's raw values are a closed set
of exact strings, not free-text combinations, so exact lookup is more
precise and auditable than pattern matching. Unknown/future raw values
default to `("Other", None)` rather than guessing.

ICE/Hybrid/EV: no new column. Built as a 3-way query param on top of the
existing `fuel_category()` — `ICE` = Petrol+Diesel+CNG+Other,
`Hybrid` = Hybrid, `EV` = EV.

## Full classification table

| Raw `vehicle_class` | `vehicle_category` | `commercial_tier` |
|---|---|---|
| M-CYCLE/SCOOTER | Two-Wheeler | |
| MOPED | Two-Wheeler | |
| MOTORISED CYCLE (CC > 25CC) | Two-Wheeler | |
| Two-Wheeler | Two-Wheeler | |
| MOTOR CYCLE/SCOOTER-USED FOR HIRE | Two-Wheeler | |
| M-CYCLE/SCOOTER-WITH SIDE CAR | Two-Wheeler | |
| MOTOR CYCLE/SCOOTER-SIDECAR(T) | Two-Wheeler | |
| MOTOR CYCLE/SCOOTER-WITH TRAILER | Two-Wheeler | |
| THREE WHEELER (PASSENGER) | Three-Wheeler | |
| THREE WHEELER (GOODS) | Three-Wheeler | |
| THREE WHEELER (PERSONAL) | Three-Wheeler | |
| E-RICKSHAW(P) | Three-Wheeler | |
| E-RICKSHAW WITH CART (G) | Three-Wheeler | |
| Three-Wheeler | Three-Wheeler | |
| QUADRICYCLE (COMMERCIAL) | Three-Wheeler | |
| QUADRICYCLE (PRIVATE) | Three-Wheeler | |
| MOTOR CAR | Four-Wheeler | |
| Motor Car/Jeep/Taxi | Four-Wheeler | |
| MOTOR CAB | Four-Wheeler | |
| MAXI CAB | Four-Wheeler | |
| LUXURY CAB | Four-Wheeler | |
| Light Motor Vehicle | Four-Wheeler | |
| ADAPTED VEHICLE | Four-Wheeler | |
| PRIVATE SERVICE VEHICLE | Four-Wheeler | |
| PRIVATE SERVICE VEHICLE (INDIVIDUAL USE) | Four-Wheeler | |
| GOODS CARRIER | Commercial Vehicle | Unspecified |
| TRACTOR (COMMERCIAL) | Commercial Vehicle | HCV |
| TRACTOR-TROLLEY(COMMERCIAL) | Commercial Vehicle | Unspecified |
| Mini Bus | Commercial Vehicle | LCV |
| Bus | Commercial Vehicle | HCV |
| BUS | Commercial Vehicle | HCV |
| Medium Bus | Commercial Vehicle | MCV |
| OMNI BUS | Commercial Vehicle | Unspecified |
| OMNI BUS (PRIVATE USE) | Commercial Vehicle | Unspecified |
| EDUCATIONAL INSTITUTION BUS | Commercial Vehicle | Unspecified |
| SCHOOL BUS | Commercial Vehicle | Unspecified |
| Medium Truck | Commercial Vehicle | MCV |
| Heavy Truck | Commercial Vehicle | HCV |
| TRAILER (COMMERCIAL) | Commercial Vehicle | HCV |
| ARTICULATED VEHICLE | Commercial Vehicle | HCV |
| SEMI-TRAILER (COMMERCIAL) | Commercial Vehicle | HCV |
| AUXILIARY TRAILER | Commercial Vehicle | Unspecified |
| DUMPER | Commercial Vehicle | HCV |
| MODULAR HYDRAULIC TRAILER | Commercial Vehicle | Unspecified |
| AGRICULTURAL TRACTOR | Other | |
| TRAILER (AGRICULTURAL) | Other | |
| Tractor | Other | |
| HARVESTER | Other | |
| POWER TILLER | Other | |
| POWER TILLER (COMMERCIAL) | Other | |
| PULLER TRACTOR | Other | |
| CONSTRUCTION EQUIPMENT VEHICLE | Other | |
| CONSTRUCTION EQUIPMENT VEHICLE (COMMERCIAL) | Other | |
| Construction Equipment | Other | |
| EARTH MOVING EQUIPMENT | Other | |
| EXCAVATOR (NT) | Other | |
| EXCAVATOR (COMMERCIAL) | Other | |
| CRANE MOUNTED VEHICLE | Other | |
| FORK LIFT | Other | |
| ROAD ROLLER | Other | |
| BULLDOZER | Other | |
| VEHICLE FITTED WITH RIG | Other | |
| VEHICLE FITTED WITH COMPRESSOR | Other | |
| VEHICLE FITTED WITH GENERATOR | Other | |
| TOW TRUCK | Other | |
| RECOVERY VEHICLE | Other | |
| BREAKDOWN VAN | Other | |
| AMBULANCE | Other | |
| ANIMAL AMBULANCE | Other | |
| FIRE FIGHTING VEHICLE | Other | |
| FIRE TENDERS | Other | |
| HEARSES | Other | |
| ARMOURED/SPECIALISED VEHICLE | Other | |
| SNORKED LADDERS | Other | |
| TREE TRIMMING VEHICLE | Other | |
| MOBILE CANTEEN | Other | |
| CASH VAN | Other | |
| MOBILE CLINIC | Other | |
| MOBILE WORKSHOP | Other | |
| LIBRARY VAN | Other | |
| X-RAY VAN | Other | |
| TOWER WAGON | Other | |
| CAMPER VAN / TRAILER | Other | |
| CAMPER VAN / TRAILER (PRIVATE USE) | Other | |
| TRAILER FOR PERSONAL USE | Other | |
| MOTOR CARAVAN | Other | |
| VINTAGE MOTOR VEHICLE | Other | |
| Other | Other | |

Any raw value not in this table (future VAHAN additions) → `("Other", None)`.

## Data model

```python
# app/models/models.py, on Registration
vehicle_category = Column(String(20), nullable=True, index=True)
commercial_tier = Column(String(15), nullable=True)
```

Migration: `ensure_columns()` pattern already exists in
`app/core/migrations.py` for additive columns — extend it, plus a one-time
backfill `UPDATE` batch job keyed off the lookup table for all 13M+ existing
rows. Runs as part of `init_db()` self-heal, same as `ensure_indexes()` /
`ensure_analyzed()`, so it's safe on a partially-migrated client install too.

## Ingestion

`persist_rto_batch()` in `app/services/scraper_service.py` sets both columns
at insert time going forward, using the same lookup table (imported from
`app/core/query_filters.py`, next to `fuel_category()`).

## API changes

- `categories.py` `GET /` (category breakdown): add `vehicle_category` and
  `commercial_tier` as optional filter params; response groups by the new
  broad category by default instead of raw `vehicle_class` (raw value still
  available via an explicit `?raw=true` for anyone who wants the granular
  view).
- `categories.py` `GET /fuel-breakdown` and other endpoints taking
  `vehicle_class` filters: accept `vehicle_category` as an additional filter
  dimension.
- New `fuel_group` param (`ICE` | `Hybrid` | `EV`) on endpoints that filter
  by fuel, built on `fuel_category()`.

## Frontend changes

- Category dropdown (Categories & Fuel, Makers & Models, Overview filter
  bar) regrouped: 2-Wheeler / 3-Wheeler / 4-Wheeler / Commercial Vehicle
  (with LCV/MCV/HCV/Unspecified as a secondary drill-down filter) / Other.
- New ICE / Hybrid / EV toggle, alongside the existing category filter —
  independent axis, not nested under it.

## Testing

- `test_query_filters.py`: parametrized test over the full 89-row table,
  same shape as the existing `fuel_category` tests.
- `test_migrations.py`: backfill correctness on a scratch table with known
  raw values, idempotency (running twice doesn't reclassify already-set
  rows incorrectly).
- `test_multi_dimension_data.py`: extend the existing supplementary-row
  fixtures to assert `vehicle_category`/`commercial_tier` land correctly
  through `persist_rto_batch`.

## Out of scope (this spec)

Subsystem B (RBAC / category-based licensing) — separate spec, depends on
this one being done first.
