from sqlalchemy import Column, Integer, String, Float, Date, DateTime, Text
from sqlalchemy.sql import func
from app.core.database import Base


class State(Base):
    __tablename__ = "states"

    state_code = Column(String(5), primary_key=True)
    state_name = Column(String(100), nullable=False)


class RTO(Base):
    __tablename__ = "rtos"

    rto_code = Column(String(10), primary_key=True)
    rto_name = Column(String(200), nullable=False)
    state_code = Column(String(5), nullable=False)


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


class DashboardSummary(Base):
    __tablename__ = "dashboard_summary"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    total_registrations = Column(Integer, default=0)
    total_revenue = Column(Float, default=0.0)
    total_transactions = Column(Integer, default=0)
    total_permits = Column(Integer, default=0)
    created_at = Column(DateTime, default=func.now())
