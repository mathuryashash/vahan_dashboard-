from pydantic import BaseModel
from datetime import date, datetime
from typing import Optional


class StateSchema(BaseModel):
    state_code: str
    state_name: str


class RTO(BaseModel):
    rto_code: str
    rto_name: str
    state_code: str


class RegistrationBase(BaseModel):
    state_code: str
    state_name: str
    month: int
    year: int
    vehicle_class: str
    count: int


class RegistrationSummary(BaseModel):
    total: int
    month: int
    year: int


class DashboardKPIs(BaseModel):
    total_registrations_today: int
    total_this_month: int
    yoy_growth_percent: float
    top_state: str
    top_state_count: int
    last_updated: str | None


class StateComparisonItem(BaseModel):
    state_name: str
    total_count: int
    yoy_growth: float | None
    share_percent: float


class YearOverYearItem(BaseModel):
    month: int
    year_a_count: int
    year_b_count: int
    growth_percent: float


class CategoryItem(BaseModel):
    vehicle_class: str
    total_count: int
    yoy_growth: float | None
    share_percent: float


class MonthlyTrendItem(BaseModel):
    month: int
    year: int
    count: int


class RefreshResponse(BaseModel):
    status: str
    message: str
    records_scraped: int | None = None


class ZoneSchema(BaseModel):
    zone_code: str
    zone_name: str


class DistrictSchema(BaseModel):
    district_code: str
    district_name: str
    state_code: str
