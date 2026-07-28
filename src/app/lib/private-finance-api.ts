import { API_BASE_URL, apiRequest } from './api';

export type PrivateFinancePlatform = 'bolt' | 'uber' | 'yango' | 'indrive' | 'other' | 'multiple';

export interface PrivateFinanceEntry {
  id: string;
  date: string;
  platform: PrivateFinancePlatform;
  cash_sales: number;
  digital_sales: number;
  other_sales: number;
  platform_fees: number;
  fuel_paid_personally: number;
  parking: number;
  tolls: number;
  washing: number;
  repairs_paid_personally: number;
  other_expenses: number;
  gross_sales: number;
  total_platform_deductions: number;
  total_personal_expenses: number;
  driver_net_earnings: number;
  notes?: string | null;
}

export interface PrivateFinanceSummary {
  period: 'daily' | 'weekly' | 'monthly';
  entry_count: number;
  gross_sales: number;
  total_platform_deductions: number;
  total_personal_expenses: number;
  driver_net_earnings: number;
  platform_breakdown: Array<{ platform: string; entries: number; gross_sales: number; net_earnings: number }>;
  trend: Array<{ period: string; gross_sales: number; net_earnings: number }>;
}

export type PrivateFinanceFilters = { start_date?: string; end_date?: string; platform?: string; period?: string };

function query(filters: PrivateFinanceFilters) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => value && params.set(key, value));
  return params.toString() ? `?${params}` : '';
}

export async function fetchPrivateFinance(filters: PrivateFinanceFilters) {
  const response = await apiRequest<{ data: { records: PrivateFinanceEntry[]; pagination: { total: number } } }>(`/driver/private-finance${query(filters)}`);
  return response.data;
}

export async function fetchPrivateFinanceSummary(filters: PrivateFinanceFilters) {
  const response = await apiRequest<{ data: { summary: PrivateFinanceSummary } }>(`/driver/private-finance/summary${query(filters)}`);
  return response.data.summary;
}

export async function savePrivateFinanceEntry(payload: Record<string, unknown>, id?: string) {
  const response = await apiRequest<{ data: { entry: PrivateFinanceEntry } }>(id ? `/driver/private-finance/${id}` : '/driver/private-finance', {
    method: id ? 'PATCH' : 'POST', body: JSON.stringify(payload),
  });
  return response.data.entry;
}

export async function deletePrivateFinanceEntry(id: string) {
  return apiRequest(`/driver/private-finance/${id}`, { method: 'DELETE' });
}

export async function downloadPrivateFinance(filters: PrivateFinanceFilters) {
  const token = localStorage.getItem('flux_token')?.trim();
  const response = await fetch(`${API_BASE_URL}/driver/private-finance/export.csv${query(filters)}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) throw new Error('Could not export private earnings.');
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = 'my-earnings.csv'; anchor.click();
  URL.revokeObjectURL(url);
}
