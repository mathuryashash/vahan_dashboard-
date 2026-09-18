from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import Select
from app.models.models import MakerCategoryTotal, Registration


# A maker is flagged when it reaches under this share of the RTOs it covers
# in its own best year. Deliberately low: a maker really can shrink its
# footprint year to year, and a false "incomplete" badge on good data costs
# more trust than it saves. Measured 2025 vs 2026 -- TVS 0.98 and Maruti 0.88
# are untouched, while Bajaj (0.13), Hero (0.44) and Honda (0.49) are caught,
# and Bajaj's stored 2025 total is ~20x below its true value.
_COVERAGE_GAP_THRESHOLD = 0.6
# How far back to look for a maker's best year. Matches the crosstab
# coverage window in categories.py; keeps the scan bounded.
_COVERAGE_YEARS = 6


async def makers_with_coverage_gaps(
    db: AsyncSession, model, year: int, makers: list[str], *,
    state: str | None = None, rto_code: str | None = None,
) -> set[str]:
    """Of `makers`, those whose stored total for `year` is built on far fewer
    RTOs than that same maker reaches in its best recent year.

    Exists because a year can look complete in aggregate while individual
    makers are missing from most of the country. Measured on the live DB:
    2025 has all 36 states, ~1,400 RTOs and all 12 months, and its national
    maker-pass total is in line with neighbouring years -- yet Bajaj Auto's
    2025 rows cover 173 RTOs against 1,384 in 2026, understating it roughly
    20x, while TVS covers 1,365 and is fine. No year-level or table-level
    check can see that; it is only visible per maker.

    Compares each maker against ITSELF rather than against other makers, so a
    genuinely regional maker is not flagged for being regional.

    An RTO-scoped caller gets an empty set: "how many RTOs does this cover"
    is meaningless when the answer can only ever be one.
    """
    if not makers or rto_code:
        return set()

    def coverage(*group_by):
        q = select(*group_by, func.count(func.distinct(model.rto_code))).where(
            model.maker.in_(makers), model.year > year - _COVERAGE_YEARS,
        )
        if state:
            q = q.where(model.state_name == state)
        return q.group_by(*group_by)

    # Best recent year per maker, and what this year actually has.
    best: dict[str, int] = {}
    for maker, _yr, rtos in (await db.execute(coverage(model.maker, model.year))).all():
        if rtos > best.get(maker, 0):
            best[maker] = rtos
    this_year = {
        maker: rtos
        for maker, rtos in (await db.execute(
            coverage(model.maker).where(model.year == year)
        )).all()
    }
    return {
        maker for maker, peak in best.items()
        if peak and this_year.get(maker, 0) < peak * _COVERAGE_GAP_THRESHOLD
    }


def reject_vehicle_model(vehicle_model: str | None) -> None:
    """Refuse a model filter rather than return a confident zero.

    VAHAN publishes no Model dimension at all -- its report Y-axis offers
    exactly Vehicle Category, Vehicle Class, Norms, Fuel, Maker and State, and
    the word "model" appears nowhere on the page -- so nothing has ever
    written this column: 0 populated rows out of 18.4M. Filtering on it
    matched nothing and returned an empty result that reads as "no
    registrations for that model" rather than "this dimension does not
    exist", which is the same silently-wrong shape this module guards against
    elsewhere.

    Module-level rather than inline in apply_common_filters because not every
    endpoint routes through that: registrations.py builds its filter list by
    hand, and without this it kept returning the confident empty result long
    after the shared path started refusing.

    Model-level data is obtainable, but only from a paid reseller of MoRTH
    data, not from the dashboard this app scrapes.
    """
    if vehicle_model:
        raise HTTPException(
            status_code=400,
            detail=(
                "vehicle_model filtering is not available: VAHAN's public reports carry no "
                "model dimension, so no model data exists in this database."
            ),
        )


def apply_common_filters(
    query: Select,
    *,
    state: str | None = None,
    rto_code: str | None = None,
    vehicle_class: str | None = None,
    vehicle_category: str | None = None,
    commercial_tier: str | None = None,
    maker: str | None = None,
    vehicle_model: str | None = None,
) -> Select:
    """Apply the state/rto/vehicle_class/maker/vehicle_model filters shared by
    most registration-aggregation endpoints. Month is deliberately excluded:
    callers need different month semantics (exact match vs. "up to" a cutoff
    month for year-to-date comparisons), so they apply it themselves.
    """
    if state:
        query = query.where(Registration.state_name == state)
    # Narrower than state, so it doesn't matter that a scoped caller passes
    # both -- the RTO already lives inside its own state. Indexed (see
    # Registration.__table_args__), so this costs nothing it doesn't save.
    if rto_code:
        query = query.where(Registration.rto_code == rto_code)
    if vehicle_class:
        query = query.where(Registration.vehicle_class == vehicle_class)
    if vehicle_category:
        query = query.where(Registration.vehicle_category == vehicle_category)
    if commercial_tier:
        query = query.where(Registration.commercial_tier == commercial_tier)
    if maker:
        query = query.where(Registration.maker == maker)
    reject_vehicle_model(vehicle_model)
    return query


def category_makers(
    category: str, *, year: int | None = None, years: list[int] | None = None,
    state: str | None = None, rto_code: str | None = None,
):
    """Subquery of the maker names that actually sell in `category` (in that
    year/state/RTO, when given).

    For the maker-level endpoints whose own source table has no category
    dimension at all: Registration's canonical maker-pass always stores
    vehicle_class='All' (see is_supplementary), and MakerFuelTotal has maker
    x fuel only -- so neither can be filtered to a category directly, and
    both would otherwise hand a four-wheeler-scoped account a list of
    two-wheeler makers. MakerCategoryTotal is the one table that knows which
    makers belong to which category, so it decides membership here.

    ponytail: this clamps WHICH makers appear, not what their counts cover
    -- a maker selling in several categories still reports its all-category
    total on those endpoints, because no Maker x Category x Month (or Maker
    x Category x Fuel) source exists anywhere in this data. Endpoints that
    DO have a category-aware source (top-makers, fuel-breakdown, every
    /summary aggregate) are clamped properly by filtering, not by this.
    """
    query = select(MakerCategoryTotal.maker).where(
        MakerCategoryTotal.vehicle_category == category
    ).distinct()
    if year is not None:
        query = query.where(MakerCategoryTotal.year == year)
    if years is not None:
        query = query.where(MakerCategoryTotal.year.in_(years))
    if state:
        query = query.where(MakerCategoryTotal.state_name == state)
    if rto_code:
        query = query.where(MakerCategoryTotal.rto_code == rto_code)
    return query


def exclude_supplementary(query: Select) -> Select:
    """For queries that sum `count` toward an overall total (KPIs, trends,
    state rankings, month-detail): the live scraper can only pivot on one
    dimension per RTO visit, so a single RTO/month's registrations may be
    represented by multiple rows -- a full maker breakdown, a full vehicle-class
    breakdown, a full fuel-type breakdown -- each independently summing to the
    true total. Summing across all of them would double- or triple-count.
    is_supplementary=True marks the non-canonical passes (vehicle_class/fuel);
    total-sum queries should exclude them. Breakdown-by-category queries
    (categories.py) do the opposite -- they WANT the supplementary rows -- so
    this is deliberately a separate opt-in helper, not baked into
    apply_common_filters which both kinds of query share.
    """
    return query.where(Registration.is_supplementary.isnot(True))


def apply_total_filters(
    query: Select,
    *,
    state: str | None = None,
    rto_code: str | None = None,
    vehicle_class: str | None = None,
    vehicle_category: str | None = None,
    commercial_tier: str | None = None,
    fuel_group: str | None = None,
    maker: str | None = None,
    vehicle_model: str | None = None,
) -> Select:
    """apply_common_filters, for queries that sum toward an overall total
    (KPIs, trend, state-ranking) -- also excludes supplementary rows, unless
    vehicle_class narrows to one specific real class, or fuel_group is set.
    The canonical maker-pass (is_supplementary=False) always stores
    vehicle_class='All' and fuel_type=NULL, so it can never match a specific
    class filter or a fuel_group filter anyway; the only rows that ever carry
    a real class are the vehicle_class-dimension pass, and the only rows that
    ever carry a real fuel_type are the fuel-dimension pass (both
    is_supplementary=True). Excluding supplementary rows in either case would
    silently zero out the filtered total for live-scraped years, since it
    would strip out the only rows that could ever match -- this exact bug
    shipped once already for vehicle_class and had to be fixed the same way.
    """
    # vehicle_category/commercial_tier are DERIVED from vehicle_class
    # (classify_vehicle) at persist time, so the maker-pass's vehicle_class=
    # 'All' always classifies to ('Other', None) -- never a real category or
    # tier -- same constraint as a real vehicle_class filter. Missing these
    # two here meant every vehicle_category-filtered total silently zeroed
    # out, for every category value including Two-Wheeler (~71% of
    # registrations); found by a live click-through QA pass.
    if (
        (not vehicle_class or vehicle_class == "All")
        and not fuel_group
        and not vehicle_category
        and not commercial_tier
    ):
        query = exclude_supplementary(query)
    # ...with one exception the comment above gets wrong: 'Other' IS a real,
    # selectable category, and it is exactly what classify_vehicle('All')
    # returns. So for vehicle_category='Other' the maker pass AND the fuel
    # pass both match, alongside the genuinely-Other vehicles (tractors,
    # ambulances, cranes), and all three get summed. Measured on 2026:
    # 45,587,609 against a true 859,783 -- 53x, on every KPI, trend, ranking,
    # YoY and comparison. An Other-scoped account would see a number
    # containing every other segment's volume, which is a scope leak and not
    # merely bad arithmetic.
    # Only the vehicle_class-dimension pass carries a real class, so that
    # single condition isolates it.
    #
    # Applied even when a fuel_group is set, deliberately. Exempting that
    # case left the fuel-dimension pass as the only rows able to satisfy
    # both filters -- and those rows carry vehicle_class='All', meaning they
    # sum that fuel across EVERY class nationwide. The answer came back as
    # the whole country's EV total wearing an "Other category" label, which
    # is the same scope-leak shape this guard exists to close. With the
    # condition applied, the class pass (fuel_type NULL) cannot match a fuel
    # filter, so the combination returns nothing -- the same honest empty
    # answer Two-Wheeler + EV already gives, since no table crosses category
    # with fuel at the registration level (that is what FuelCategoryTotal is
    # for, and what the frontend routes to instead).
    if vehicle_category == "Other":
        query = query.where(Registration.vehicle_class != "All")
    return apply_common_filters(
        query, state=state, rto_code=rto_code, vehicle_class=vehicle_class,
        vehicle_category=vehicle_category, commercial_tier=commercial_tier,
        maker=maker, vehicle_model=vehicle_model,
    )


# VAHAN's raw fuel_type values (37 distinct strings observed in scraped
# data, e.g. "PETROL/HYBRID/CNG", "STRONG HYBRID EV", "DUAL DIESEL/CNG")
# describe exact powertrain/fuel-system combinations, not the handful of
# categories people actually compare (EV/Petrol/Diesel/Hybrid/CNG) -- shown
# raw, a fuel breakdown chart is ~37 slivers instead of a few meaningful
# bars. First matching substring wins, checked in this order so a
# multi-fuel value (e.g. "PETROL/HYBRID/CNG") lands in the bucket that
# actually describes what makes it different from a plain single-fuel
# vehicle, not just the first fuel word in its name. LPG isn't one of the
# five requested buckets, so LPG-inclusive values fall to "Other" rather
# than being folded into "Petrol". Anything not matched here (ethanol,
# methanol, solar, hydrogen-ICE, "NOT APPLICABLE", ...) is "Other" too.
_FUEL_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Hybrid", ("HYBRID",)),
    ("CNG", ("CNG",)),
    ("Other", ("LPG",)),
    ("EV", ("ELECTRIC", "PURE EV", "FUEL CELL")),
    ("Diesel", ("DIESEL",)),
    ("Petrol", ("PETROL",)),
)


def fuel_category(raw_fuel_type: str) -> str:
    upper = raw_fuel_type.upper()
    for bucket, substrings in _FUEL_CATEGORY_RULES:
        if any(s in upper for s in substrings):
            return bucket
    return "Other"


# VAHAN's 89 raw vehicle_class values, mapped to the 4 broad categories a
# commercial buyer actually thinks in (2W/3W/4W/Commercial), with LCV/MCV/HCV
# sub-tiers for Commercial where VAHAN's raw label states a size class.
# "Unspecified" (not a guess) when VAHAN's label doesn't state one -- e.g.
# plain "GOODS CARRIER" or "BUS" never says LCV/MCV/HCV, so this doesn't
# invent a size VAHAN never gave us. Anything not in this table (a future
# VAHAN category, or "All"/"Other" placeholders) falls to ("Other", None)
# rather than being guessed into a bucket -- see the design spec at
# docs/superpowers/specs/2026-08-23-vehicle-taxonomy-design.md for the full
# rationale behind each judgment call (cabs -> Four-Wheeler not Commercial,
# quadricycles -> Three-Wheeler, etc).
_VEHICLE_CATEGORY_MAP: dict[str, tuple[str, str | None]] = {
    # Two-Wheeler
    "M-CYCLE/SCOOTER": ("Two-Wheeler", None),
    "MOPED": ("Two-Wheeler", None),
    "MOTORISED CYCLE (CC > 25CC)": ("Two-Wheeler", None),
    "TWO-WHEELER": ("Two-Wheeler", None),
    "MOTOR CYCLE/SCOOTER-USED FOR HIRE": ("Two-Wheeler", None),
    "M-CYCLE/SCOOTER-WITH SIDE CAR": ("Two-Wheeler", None),
    "MOTOR CYCLE/SCOOTER-SIDECAR(T)": ("Two-Wheeler", None),
    "MOTOR CYCLE/SCOOTER-WITH TRAILER": ("Two-Wheeler", None),
    # Three-Wheeler
    "THREE WHEELER (PASSENGER)": ("Three-Wheeler", None),
    "THREE WHEELER (GOODS)": ("Three-Wheeler", None),
    "THREE WHEELER (PERSONAL)": ("Three-Wheeler", None),
    "E-RICKSHAW(P)": ("Three-Wheeler", None),
    "E-RICKSHAW WITH CART (G)": ("Three-Wheeler", None),
    "THREE-WHEELER": ("Three-Wheeler", None),
    "QUADRICYCLE (COMMERCIAL)": ("Three-Wheeler", None),
    "QUADRICYCLE (PRIVATE)": ("Three-Wheeler", None),
    # Four-Wheeler
    "MOTOR CAR": ("Four-Wheeler", None),
    "MOTOR CAR/JEEP/TAXI": ("Four-Wheeler", None),
    "MOTOR CAB": ("Four-Wheeler", None),
    "MAXI CAB": ("Four-Wheeler", None),
    "LUXURY CAB": ("Four-Wheeler", None),
    "LIGHT MOTOR VEHICLE": ("Four-Wheeler", None),
    "ADAPTED VEHICLE": ("Four-Wheeler", None),
    "PRIVATE SERVICE VEHICLE": ("Four-Wheeler", None),
    "PRIVATE SERVICE VEHICLE (INDIVIDUAL USE)": ("Four-Wheeler", None),
    # Commercial Vehicle
    "GOODS CARRIER": ("Commercial Vehicle", "Unspecified"),
    "TRACTOR (COMMERCIAL)": ("Commercial Vehicle", "HCV"),
    "TRACTOR-TROLLEY(COMMERCIAL)": ("Commercial Vehicle", "Unspecified"),
    "MINI BUS": ("Commercial Vehicle", "LCV"),
    "BUS": ("Commercial Vehicle", "HCV"),
    "MEDIUM BUS": ("Commercial Vehicle", "MCV"),
    "OMNI BUS": ("Commercial Vehicle", "Unspecified"),
    "OMNI BUS (PRIVATE USE)": ("Commercial Vehicle", "Unspecified"),
    "EDUCATIONAL INSTITUTION BUS": ("Commercial Vehicle", "Unspecified"),
    "SCHOOL BUS": ("Commercial Vehicle", "Unspecified"),
    "MEDIUM TRUCK": ("Commercial Vehicle", "MCV"),
    "HEAVY TRUCK": ("Commercial Vehicle", "HCV"),
    "TRAILER (COMMERCIAL)": ("Commercial Vehicle", "HCV"),
    "ARTICULATED VEHICLE": ("Commercial Vehicle", "HCV"),
    "SEMI-TRAILER (COMMERCIAL)": ("Commercial Vehicle", "HCV"),
    "AUXILIARY TRAILER": ("Commercial Vehicle", "Unspecified"),
    "DUMPER": ("Commercial Vehicle", "HCV"),
    "MODULAR HYDRAULIC TRAILER": ("Commercial Vehicle", "Unspecified"),
    # Other / Special Purpose
    "AGRICULTURAL TRACTOR": ("Other", None),
    "TRAILER (AGRICULTURAL)": ("Other", None),
    "TRACTOR": ("Other", None),
    "HARVESTER": ("Other", None),
    "POWER TILLER": ("Other", None),
    "POWER TILLER (COMMERCIAL)": ("Other", None),
    "PULLER TRACTOR": ("Other", None),
    "CONSTRUCTION EQUIPMENT VEHICLE": ("Other", None),
    "CONSTRUCTION EQUIPMENT VEHICLE (COMMERCIAL)": ("Other", None),
    "CONSTRUCTION EQUIPMENT": ("Other", None),
    "EARTH MOVING EQUIPMENT": ("Other", None),
    "EXCAVATOR (NT)": ("Other", None),
    "EXCAVATOR (COMMERCIAL)": ("Other", None),
    "CRANE MOUNTED VEHICLE": ("Other", None),
    "FORK LIFT": ("Other", None),
    "ROAD ROLLER": ("Other", None),
    "BULLDOZER": ("Other", None),
    "VEHICLE FITTED WITH RIG": ("Other", None),
    "VEHICLE FITTED WITH COMPRESSOR": ("Other", None),
    "VEHICLE FITTED WITH GENERATOR": ("Other", None),
    "TOW TRUCK": ("Other", None),
    "RECOVERY VEHICLE": ("Other", None),
    "BREAKDOWN VAN": ("Other", None),
    "AMBULANCE": ("Other", None),
    "ANIMAL AMBULANCE": ("Other", None),
    "FIRE FIGHTING VEHICLE": ("Other", None),
    "FIRE TENDERS": ("Other", None),
    "HEARSES": ("Other", None),
    "ARMOURED/SPECIALISED VEHICLE": ("Other", None),
    "SNORKED LADDERS": ("Other", None),
    "TREE TRIMMING VEHICLE": ("Other", None),
    "MOBILE CANTEEN": ("Other", None),
    "CASH VAN": ("Other", None),
    "MOBILE CLINIC": ("Other", None),
    "MOBILE WORKSHOP": ("Other", None),
    "LIBRARY VAN": ("Other", None),
    "X-RAY VAN": ("Other", None),
    "TOWER WAGON": ("Other", None),
    "CAMPER VAN / TRAILER": ("Other", None),
    "CAMPER VAN / TRAILER (PRIVATE USE)": ("Other", None),
    "TRAILER FOR PERSONAL USE": ("Other", None),
    "MOTOR CARAVAN": ("Other", None),
    "VINTAGE MOTOR VEHICLE": ("Other", None),
    "OTHER": ("Other", None),
    "ALL": ("Other", None),
}


def classify_vehicle(raw_vehicle_class: str) -> tuple[str, str | None]:
    return _VEHICLE_CATEGORY_MAP.get(raw_vehicle_class.upper(), ("Other", None))


# The live analytics site (analytics.parivahan.gov.in, see
# scraper/analytics_scraper.py) reports a THIRD taxonomy of its own -- its
# own "vehicle category" axis: TWO WHEELER(NT), FOUR WHEELER (Invalid
# Carriage), LIGHT/MEDIUM/HEAVY GOODS|PASSENGER VEHICLE, ... -- neither the
# 89 raw VAHAN4 vehicle_class values above nor our own buckets. Substring
# rules, not an exact-value table: the labels carry suffixes ((T)/(NT)/
# (Invalid Carriage)) that vary per state/year and would each need their own
# row otherwise. Matches _VEHICLE_CATEGORY_MAP's own judgment calls (LIGHT
# MOTOR VEHICLE -> Four-Wheeler, buses/goods carriers -> Commercial);
# anything unmatched ("OTHER THAN MENTIONED ABOVE") is Other, never guessed
# into a real category.
_LIVE_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Two-Wheeler", ("TWO WHEELER",)),
    ("Three-Wheeler", ("THREE WHEELER",)),
    ("Four-Wheeler", ("FOUR WHEELER", "LIGHT MOTOR VEHICLE")),
    ("Commercial Vehicle", ("GOODS VEHICLE", "PASSENGER VEHICLE", "MEDIUM MOTOR VEHICLE", "HEAVY MOTOR VEHICLE")),
)


def classify_live_category(live_label: str) -> str:
    upper = live_label.upper()
    for bucket, substrings in _LIVE_CATEGORY_RULES:
        if any(s in upper for s in substrings):
            return bucket
    return "Other"


# ICE/Hybrid/EV is a coarser regrouping of fuel_category's own buckets, not a
# separate ruleset -- Hybrid stays its own bucket rather than folding into
# ICE, since a buyer deciding whether to compete in pure-EV needs to see
# hybrids separately from plain combustion (see design spec).
_FUEL_GROUP_MAP = {
    "Petrol": "ICE",
    "Diesel": "ICE",
    "CNG": "ICE",
    "Other": "ICE",
    "Hybrid": "Hybrid",
    "EV": "EV",
}


def fuel_group(raw_fuel_type: str) -> str:
    return _FUEL_GROUP_MAP[fuel_category(raw_fuel_type)]


def apply_fuel_group_filter(query: Select, group: str | None) -> Select:
    """SQL-level equivalent of filtering by fuel_group(), for aggregate
    endpoints (KPIs/trend/state-ranking) that SUM in SQL rather than fetch
    per-row fuel_type like fuel-breakdown does. Mirrors fuel_category's
    priority order exactly: HYBRID is checked first, so "ICE" (which
    fuel_group maps Petrol/Diesel/CNG/Other onto) is precisely "not Hybrid
    and not EV" -- there's no separate Petrol/Diesel/CNG substring list to
    keep in sync here.
    """
    if not group:
        return query
    is_hybrid = Registration.fuel_type.ilike("%HYBRID%")
    is_ev = Registration.fuel_type.ilike("%ELECTRIC%") | Registration.fuel_type.ilike("%PURE EV%") | Registration.fuel_type.ilike("%FUEL CELL%")
    if group == "Hybrid":
        return query.where(is_hybrid)
    if group == "EV":
        return query.where(~is_hybrid & is_ev)
    if group == "ICE":
        return query.where(~is_hybrid & ~is_ev)
    return query


async def latest_month_with_data(db: AsyncSession, year: int) -> int | None:
    """Highest month with any registration row for `year`, or None if the
    year has no data yet. Used to cap a year-to-date comparison at the same
    point in both years instead of comparing a full year against a partial
    one."""
    result = await db.execute(select(func.max(Registration.month)).where(Registration.year == year))
    return result.scalar()
