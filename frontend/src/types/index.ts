export interface DashboardKPIs {
  total_registrations_today: number;
  total_this_month: number;
  yoy_growth_percent: number;
  top_state: string;
  top_state_count: number;
  last_updated: string | null;
}

export interface MonthlyTrend {
  month: number;
  count: number;
}

export interface StateRanking {
  state_name: string;
  total_count: number;
  share_percent: number;
}

export interface CategoryItem {
  vehicle_class: string;
  total_count: number;
  share_percent: number;
  prev_count: number;
  yoy_growth: number;
}

export interface YoYItem {
  month: number;
  [key: string]: number;
}

export interface StateComparison {
  state_a: string;
  state_b: string | null;
  year: number;
  state_a_data: { month: number; count: number }[];
  state_b_data: { month: number; count: number }[];
}

export interface MakerItem {
  maker: string;
  count: number;
}

export interface FuelItem {
  fuel_type: string;
  count: number;
}

export type ViewMode = 'overview' | 'comparison' | 'yoy' | 'category';

export interface RefreshStatus {
  last_updated: string | null;
  status: 'idle' | 'running' | 'success' | 'error';
  error: string | null;
}

export interface MonthDetail {
  year: number;
  month: number;
  month_count: number;
  month_yoy_growth_percent: number | null;
  ytd_count: number;
  ytd_yoy_growth_percent: number | null;
}

export interface ScrapeProgress {
  states_done: number;
  states_total: number;
  rtos_done: number;
  percent: number;
}

export interface OEMSalesRow {
  maker: string;
  count: number;
  share_percent: number | null;
}

export interface OEMTrendPoint {
  year: number;
  month: number | null;
  count: number;
  share_percent: number | null;
}

export interface RTOListItem {
  rto_code: string;
  rto_name: string | null;
  total: number;
}

export interface RTOMakerShare {
  maker: string;
  count: number;
  share_percent: number;
}

export interface RTOAnalysis {
  rto_code: string;
  rto_name: string | null;
  state_name: string | null;
  year: number;
  total: number;
  avg_monthly: number;
  months_with_data: number;
  makers: RTOMakerShare[];
}