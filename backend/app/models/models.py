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

    # These covering indexes support the dashboard's high-cardinality
    # aggregates on both PostgreSQL and SQLite migration sources.
    __table_args__ = (
        Index("idx_reg_year_month_supp_count", "year", "month", "is_supplementary", "count"),
        Index("idx_reg_state_year_month_count", "state_name", "year", "month", "count"),
        Index("idx_reg_year_class_month_count", "year", "vehicle_class", "month", "count"),
        Index("idx_reg_class_state_rto", "vehicle_class", "state_name", "rto_code"),
        Index("idx_reg_rto_year_supp_month_maker_count", "rto_code", "year", "is_supplementary", "month", "maker", "count"),
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
