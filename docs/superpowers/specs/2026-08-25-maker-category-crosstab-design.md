# Maker × Category Cross-Tab Design

## Problem

Maker and vehicle_category can never both be real on the same `Registration`
row for live-scraped years — the existing scraper's Y-axis pivot (Maker /
Vehicle Class / Fuel) always locks X-axis to "Month Wise", and VAHAN's own
report can only cross two dimensions per table. Overview and Makers & Models
both surface an honest "always shows 0" banner for this combination today.

## Discovery

VAHAN's report X-axis dropdown offers more than "Month Wise" once Y-axis is
set to Maker: it also offers Vehicle Class, Vehicle Category (VAHAN's own
coarser grouping), Norms, Financial Year, Calendar Year. Setting X-axis to
Vehicle Class produces a genuine cross-tab — rows are makers, columns are
every raw vehicle_class, cells are real per-cell registration counts for
whichever year is currently selected. Verified live against
vahan.parivahan.gov.in this session (Maharashtra, one RTO, real non-zero
cross-tab data returned).

**Trade-off**: this table has no month columns at all — the X-axis holds
either Month or Vehicle Class, never both. State/RTO granularity is
unaffected, since that comes from which RTO the scraper is visiting, not
from the pivot axes.

## Scope

Wired in two places:
1. **Makers & Models** — the category dropdown (already built, currently
   decorative) becomes a real filter on the maker leaderboard.
2. **Overview** — when both Category and Maker are selected, a new panel
   ("Maker × Category — Year Total") replaces today's banner, sourced from
   this new data. The existing KPI cards and trend chart are untouched —
   they need month data this pivot can't supply, so they keep working
   exactly as they do today for maker-only or category-only selections. If
   Month is also selected when both Category and Maker are active, the new
   panel says plainly that it's a year total and ignores the month filter,
   rather than silently guessing.

## Data model

New table, not a reuse of `Registration` (whose `month` column is
`NOT NULL` and load-bearing across nearly every existing query):

```python
class MakerCategoryTotal(Base):
    __tablename__ = "maker_category_totals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    state_code = Column(String(5), nullable=False, index=True)
    state_name = Column(String(100), nullable=False)
    rto_code = Column(String(10), nullable=True)
    rto_name = Column(String(200), nullable=True)
    year = Column(Integer, nullable=False, index=True)
    maker = Column(String(200), nullable=False, index=True)
    vehicle_class = Column(String(200), nullable=False)
    vehicle_category = Column(String(20), nullable=False, index=True)
    commercial_tier = Column(String(15), nullable=True)
    count = Column(Integer, default=0)

    __table_args__ = (
        Index("idx_mct_year_category_maker", "year", "vehicle_category", "maker"),
        Index("idx_mct_year_maker", "year", "maker"),
    )
```

Classified through the existing `classify_vehicle()` at ingestion time, same
as `Registration.vehicle_category` — one canonical taxonomy path, not two.

## Scraper

New dimension, `"maker_category"`, added to `vahan_scraper.py`'s
per-RTO-per-year loop alongside the existing three. Configuration differs
from the existing `_configure_pivot`: Y-axis=Maker (same as the `maker`
dimension), but X-axis=Vehicle Class instead of Month Wise. Table parsing
differs too — columns are vehicle classes instead of months, so this needs
its own row-parsing function (columns aren't month abbreviations, they're
whatever vehicle_class strings VAHAN currently offers, discovered from the
column headers same as `_parse_month_columns` discovers month columns).

Runs on the same resumable, `--force`, `--concurrent-states` machinery as
the existing three dimensions — a 4th entry in `DIMENSIONS`, scraped
concurrently with the others (same wall-clock time, since they already run
in parallel).

## API

New endpoint: `GET /categories/maker-category-breakdown`
- Params: `year`, `state` (optional), `vehicle_category` (optional),
  `maker` (optional) — at least one of `vehicle_category`/`maker` required.
- Returns maker totals within a category, or category totals within a
  maker, depending on which one is fixed vs. left to group by.

## Frontend

- `MakersModels.tsx`: category dropdown now passes through to the new
  endpoint; drop the banner, wire real filtering.
- `Overview.tsx`: `impossibleCrossFilter` block replaced with a new
  `<MakerCategoryPanel>` component, rendered only when both
  `selectedCategory` and `selectedMaker` are set, fetching from the new
  endpoint. Explicit "year total, ignoring month" note shown if
  `selectedMonth` is also set at that point.

## Testing

- Scraper: parsing test for the new column-header format (vehicle class
  names instead of month abbreviations), mirroring the existing
  `_parse_month_columns` test pattern.
- Backend: endpoint tests for both "makers within a category" and
  "categories within a maker" query directions, plus a state-filtered case.
- Frontend: `MakersModels.tsx` filter wiring, `Overview.tsx` panel
  conditional rendering (shows only when both filters set, shows the
  month-ignored note correctly).

## Out of scope

- No month breakdown for this data, ever — that's the actual limitation
  discovered, not a gap to close later.
- Historical backfill of this new dimension across all 19 years is a
  separate, later operational task (same shape as the original 3-dimension
  backfill) — this spec covers building the capability, not running the
  multi-hour scrape across all history.
