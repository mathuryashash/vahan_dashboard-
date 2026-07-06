import axios from 'axios';

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
});

export interface FilterParams {
  year?: number;
  month?: number | null;
  state?: string | null;
  vehicle_class?: string | null;
  maker?: string | null;
  vehicle_model?: string | null;
}

export const getKPIs = (params?: FilterParams) => api.get('/summary/kpis', { params }).then(r => r.data);
export const getTrend = (params?: FilterParams) =>
  api.get('/summary/trend', { params }).then(r => r.data);
export const getStateRanking = (params?: FilterParams & { limit?: number }) =>
  api.get('/summary/state-ranking', { params }).then(r => r.data);
export const getStates = () => api.get('/states/').then(r => r.data);
export const getStatesComparison = (year: number, limit?: number) =>
  api.get('/comparison/all-states', { params: { year, limit } }).then(r => r.data);
export const compareStates = (state_a: string, state_b?: string, year?: number) =>
  api.get('/comparison/states', { params: { state_a, state_b, year } }).then(r => r.data);
export const getYoYMonthly = (year_a: number, year_b: number, state?: string) =>
  api.get('/yoy/monthly', { params: { year_a, year_b, state } }).then(r => r.data);
export const getYoYSummary = (year_a: number, year_b: number) =>
  api.get('/yoy/summary', { params: { year_a, year_b } }).then(r => r.data);
export const getCategories = (params?: FilterParams) =>
  api.get('/categories/', { params }).then(r => r.data);
export const getTopMakers = (params?: FilterParams & { limit?: number }) =>
  api.get('/categories/top-makers', { params }).then(r => r.data);
export const getFuelBreakdown = (params?: FilterParams) =>
  api.get('/categories/fuel-breakdown', { params }).then(r => r.data);
export const getModelBreakdown = (params?: FilterParams & { limit?: number }) =>
  api.get('/categories/model-breakdown', { params }).then(r => r.data);
export const triggerRefresh = () => api.post('/refresh/').then(r => r.data);
export const getRefreshStatus = () => api.get('/refresh/status').then(r => r.data);