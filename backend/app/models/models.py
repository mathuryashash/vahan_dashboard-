from sqlalchemy import Column, Integer, String, Float, Date, DateTime, Text, Boolean, Index
from sqlalchemy.sql import func
from app.core.database import Base


class State(Base):
    __tablename__ = "states"

    state_code = Column(String(5), primary_key=True)
    state_name = Column(String(100), nullable=False)
    zone_code = Column(String(10), nullable=True)


class RTO(Base):
    __tablename__ = "rtos"

    rto_code = Column(String(10), primary_key=True)
    rto_name = Column(String(200), nullable=False)
    state_code = Column(String(5), nullable=False)


class Zone(Base):
    __tablename__ = "zones"

    zone_code = Column(String(10), primary_key=True)
    zone_name = Column(String(100), nullable=False)


class District(Base):
    __tablename__ = "districts"

    district_code = Column(String(120), primary_key=True)
    district_name = Column(String(200), nullable=False)
    state_code = Column(String(5), nullable=False, index=True)


class RTODistrict(Base):
    __tablename__ = "rto_districts"

    rto_code = Column(String(10), primary_key=True)
    district_code = Column(String(120), primary_key=True)


class Registration(Base):
    __tablename__ = "registrations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    state_code = Column(String(5), nullable=False, index=True)
    state_name = Column(String(100), nullable=False)
    rto_code = Column(String(10), nullable=True)
    rto_name = Column(String(200), nullable=True)
    month = Column(Integer, nullable=False, index=True)
    year = Column(Integer, nullable=False, index=True)
    vehicle_class = Column(String(200), nullable=False, index=True)
    maker = Column(String(200), nullable=True)
    fuel_type = Column(String(100), nullable=True)
    norms_type = Column(String(50), nullable=True)
    day = Column(Integer, nullable=True, index=True)
    vehicle_model = Column(String(200), nullable=True, index=True)
    count = Column(Integer, default=0)
    recorded_at = Column(DateTime, default=func.now(), index=True)
    # The live scraper can only pivot on one dimension (Maker, Vehicle Class,
    # or Fuel) per site visit, so a single RTO/month's real registrations end
    # up split across multiple rows -- one full breakdown by maker, another
    # full breakdown by vehicle class, another by fuel type. Each of those
    # rows independently sums to that RTO/month's true total, so summing
    # `count` across ALL of them for a "total registrations" figure would
    # triple-count. is_supplementary=True marks the non-canonical passes
    # (vehicle_class/fuel breakdowns) so aggregate-total queries can exclude
    # them while breakdown-by-category queries still include them. False/NULL
    # (the default) covers the canonical maker-dimension real rows and all
    # synthetic rows, which were never split this way and are safe to sum.
    is_supplementary = Column(Boolean, nullable=True, default=False, index=True)
    # Broad category (2W/3W/4W/Commercial/Other) and, for Commercial rows
    # only, a size tier (LCV/MCV/HCV/Unspecified) -- see
    # app.core.query_filters.classify_vehicle. Persisted (not computed on
    # read like fuel_category) so it's usable as a real SQL filter, not just
    # a display label -- category-based access control needs a real
    # predicate to enforce against.
    vehicle_category = Column(String(20), nullable=True, index=True)
    commercial_tier = Column(String(15), nullable=True)

    # These covering indexes support the dashboard's high-cardinality
    # aggregates on both PostgreSQL and SQLite migration sources.
    __table_args__ = (
        Index("idx_reg_year_month_supp_count", "year", "month", "is_supplementary", "count"),
        Index("idx_reg_state_year_month_count", "state_name", "year", "month", "count"),
        Index("idx_reg_year_class_month_count", "year", "vehicle_class", "month", "count"),
        Index("idx_reg_class_state_rto", "vehicle_class", "state_name", "rto_code"),
        Index("idx_reg_rto_year_supp_month_maker_count", "rto_code", "year", "is_supplementary", "month", "maker", "count"),
    )


class MakerCategoryTotal(Base):
    """Real Maker x Vehicle Category totals -- a genuinely different pivot
    from Registration, not a supplementary dimension of it. VAHAN's report
    X-axis can hold Vehicle Class OR Month Wise, never both, so this table
    has no month column at all: it's a full-year total per (state/RTO,
    maker, vehicle_class) cell. See docs/superpowers/specs/
    2026-08-25-maker-category-crosstab-design.md for how this was
    discovered and why it can't just be added as another Registration
    dimension."""
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


class FuelCategoryTotal(Base):
    """Real Fuel x Vehicle Category totals -- same shape and same reason as
    MakerCategoryTotal: the fuel-dimension pass always stores
    vehicle_class='All' (see Registration.is_supplementary), so fuel_group
    filtering can never combine with a real vehicle_category on Registration
    rows. VAHAN's report offers Vehicle Class as an X-axis option when
    Y-axis=Fuel too, giving a genuine cross-tab -- verified live this
    session, same discovery as the maker one. Year-only, no month column,
    for the same reason (X-axis holds either Month Wise or Vehicle Class,
    never both)."""
    __tablename__ = "fuel_category_totals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    state_code = Column(String(5), nullable=False, index=True)
    state_name = Column(String(100), nullable=False)
    rto_code = Column(String(10), nullable=True)
    rto_name = Column(String(200), nullable=True)
    year = Column(Integer, nullable=False, index=True)
    fuel_type = Column(String(100), nullable=False, index=True)
    vehicle_class = Column(String(200), nullable=False)
    vehicle_category = Column(String(20), nullable=False, index=True)
    commercial_tier = Column(String(15), nullable=True)
    count = Column(Integer, default=0)

    __table_args__ = (
        Index("idx_fct_year_category_fuel", "year", "vehicle_category", "fuel_type"),
        Index("idx_fct_year_fuel", "year", "fuel_type"),
    )


class MakerFuelTotal(Base):
    """Real Maker x Fuel totals -- the third pairing of {Maker, Vehicle
    Class, Fuel}, same reason as MakerCategoryTotal/FuelCategoryTotal: a
    maker name and a real fuel_type never coexist on the same Registration
    row (see Registration.is_supplementary), so selecting a Maker/OEM
    together with the ICE/Hybrid/EV filter always zeroed out. VAHAN only
    offers this one direction (Y-axis=Maker, X-axis=Fuel -- Y=Fuel's X-axis
    dropdown has no Maker option), which is fine since that's exactly the
    combination users need. Year-only, no month column, same reason as the
    other two crosstabs (X-axis holds either Month Wise or the second
    dimension, never both). fuel_type is raw (e.g. 'CNG ONLY'); grouped into
    ICE/Hybrid/EV at query time via fuel_group(), same as FuelCategoryTotal."""
    __tablename__ = "maker_fuel_totals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    state_code = Column(String(5), nullable=False, index=True)
    state_name = Column(String(100), nullable=False)
    rto_code = Column(String(10), nullable=True)
    rto_name = Column(String(200), nullable=True)
    year = Column(Integer, nullable=False, index=True)
    maker = Column(String(200), nullable=False, index=True)
    fuel_type = Column(String(100), nullable=False, index=True)
    count = Column(Integer, default=0)

    __table_args__ = (
        Index("idx_mft_year_maker", "year", "maker"),
        Index("idx_mft_year_fuel", "year", "fuel_type"),
    )


class DashboardSummary(Base):
    __tablename__ = "dashboard_summary"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    total_registrations = Column(Integer, default=0)
    total_revenue = Column(Float, default=0.0)
    total_transactions = Column(Integer, default=0)
    total_permits = Column(Integer, default=0)
    created_at = Column(DateTime, default=func.now())


class OEMMonthlySales(Base):
    __tablename__ = "oem_monthly_sales"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # "FADA" for now. SIAM's industry-wide totals (a later, separate sub-project)
    # fit this same shape with maker=NULL -- no schema change needed to add a
    # second source value here.
    source = Column(String(20), nullable=False, index=True)
    # Parsed from the PDF table's own column header (e.g. "Jun'26"), not from
    # the press release title -- titles are inconsistent (see fada_scraper.py
    # module docstring) but the table header is the authoritative period.
    year = Column(Integer, nullable=False, index=True)
    # Null for FY-total periods that don't resolve to one calendar month.
    month = Column(Integer, nullable=True)
    # Literal text as FADA labels it ("Two-Wheeler", "PV", etc.) -- not an
    # enum, since FADA has added/renamed categories across the archive.
    category = Column(String(100), nullable=False, index=True)
    maker = Column(String(200), nullable=True, index=True)
    count = Column(Integer, nullable=False)
    share_percent = Column(Float, nullable=True)
    # The press release title, for tracing a row back to its source PDF.
    source_document = Column(String(300), nullable=False)
    scraped_at = Column(DateTime, default=func.now())

    __table_args__ = (
        Index("idx_oem_sales_period", "source", "year", "month", "category"),
    )


class UserRole:
    """String constants, not a DB enum -- adding/renaming a tier later is a
    code change, not a migration. Three tiers: admin (full access, manages
    users, can trigger scrapes), analyst (full dashboard access, no admin
    actions), viewer (read-only dashboard access -- same data visibility as
    analyst for now; per-state/per-page data scoping isn't built, add if a
    buyer actually needs it)."""
    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"
    ALL = (ADMIN, ANALYST, VIEWER)


class User(Base):
    """Login + role for the access-hierarchy system. Lives in the same
    Postgres database as everything else -- there's no separate "auth
    database" to host or provision."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(200), nullable=True)
    role = Column(String(20), nullable=False, default=UserRole.VIEWER)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=func.now())
    last_login_at = Column(DateTime, nullable=True)
