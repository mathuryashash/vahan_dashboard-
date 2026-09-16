from datetime import datetime
from typing import Literal

from pydantic import BaseModel


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


class MonthCount(BaseModel):
    month: int
    count: int


class RegistrationOut(BaseModel):
    id: int
    state_code: str
    state_name: str
    month: int
    year: int
    day: int | None
    vehicle_class: str
    count: int
    maker: str | None
    vehicle_model: str | None
    fuel_type: str | None


class StateComparisonData(BaseModel):
    state_a: str
    state_b: str | None
    year: int
    state_a_data: list[MonthCount]
    state_b_data: list[MonthCount]


class StateComparisonRanking(BaseModel):
    state_name: str
    count: int
    share_percent: float


class StateRankingItem(BaseModel):
    state_name: str
    total_count: int
    share_percent: float


class RtoListItem(BaseModel):
    rto_code: str
    rto_name: str
    total: int


class RtoMakerShare(BaseModel):
    maker: str
    count: int
    share_percent: float


class RtoAnalysis(BaseModel):
    rto_code: str
    rto_name: str | None
    state_name: str | None
    year: int
    total: int
    avg_monthly: float
    months_with_data: int
    makers: list[RtoMakerShare]
    # Which window the maker figures actually cover. A category-scoped account
    # is served from MakerCategoryTotal, which is scraped per CALENDAR year and
    # has no month column, so its numbers can't be cut to an Apr-Mar financial
    # year the way the unscoped maker-pass ones can (no source carries maker AND
    # category AND month). Shares are unaffected -- a wider window scales every
    # maker alike -- but the absolute totals are broader than an "FY" label
    # implies, so the UI has to be able to say which it's showing rather than
    # quietly labelling both the same.
    maker_period: Literal["financial_year", "calendar_years_spanned"] = "financial_year"


class CrosstabCoverage(BaseModel):
    maker_category: list[int]
    fuel_category: list[int]
    maker_fuel: list[int]
    # No *_partial lists here: see get_crosstab_coverage for why the
    # year-level completeness check was removed. Under-scraping is reported
    # per maker instead, on the endpoints that actually rank makers.


class CrosstabDetail(BaseModel):
    total: int | None
    top_state: str | None
    yoy_growth_percent: float | None


class MonthDetail(BaseModel):
    year: int
    month: int
    month_count: int
    month_yoy_growth_percent: float | None
    ytd_count: int
    ytd_yoy_growth_percent: float | None


class OemStatus(BaseModel):
    last_ingested_at: str | None
    days_stale: int | None
    is_stale: bool


class OemMakerShare(BaseModel):
    maker: str
    count: int
    share_percent: float | None


class OemTrendPoint(BaseModel):
    year: int
    month: int | None
    count: int
    share_percent: float | None


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str | None
    role: str
    is_active: bool
    last_login_at: datetime | None
    scope_type: str
    scope_state_code: str | None
    scope_state_name: str | None
    scope_rto_code: str | None
    scope_rto_name: str | None
    scope_vehicle_category: str | None
    organization_id: int | None


class OrganizationOut(BaseModel):
    id: int
    name: str
    is_active: bool
    user_count: int
