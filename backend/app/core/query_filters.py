from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import Select
from app.models.models import Registration


def apply_common_filters(
    query: Select,
    *,
    state: str | None = None,
    vehicle_class: str | None = None,
    vehicle_category: str | None = None,
    commercial_tier: str | None = None,
    maker: str | None = None,
    vehicle_model: str | None = None,
) -> Select:
    """Apply the state/vehicle_class/maker/vehicle_model filters shared by
    most registration-aggregation endpoints. Month is deliberately excluded:
    callers need different month semantics (exact match vs. "up to" a cutoff
    month for year-to-date comparisons), so they apply it themselves.
    """
    if state:
        query = query.where(Registration.state_name == state)
    if vehicle_class:
        query = query.where(Registration.vehicle_class == vehicle_class)
    if vehicle_category:
        query = query.where(Registration.vehicle_category == vehicle_category)
    if commercial_tier:
        query = query.where(Registration.commercial_tier == commercial_tier)
    if maker:
        query = query.where(Registration.maker == maker)
    if vehicle_model:
        query = query.where(Registration.vehicle_model == vehicle_model)
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
    return apply_common_filters(
        query, state=state, vehicle_class=vehicle_class, vehicle_category=vehicle_category,
        commercial_tier=commercial_tier, maker=maker, vehicle_model=vehicle_model,
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
