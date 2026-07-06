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