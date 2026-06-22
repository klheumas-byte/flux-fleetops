import { apiRequest } from './api';

export type CurrencyCode = 'GHS' | 'USD' | 'NGN' | 'KES' | 'ZAR' | 'GBP' | 'EUR';
export type DistanceUnit = 'KM' | 'MI';

export interface SystemSettingsRecord {
  id: string;
  default_currency: CurrencyCode;
  currency_symbol: string;
  distance_unit: DistanceUnit;
  include_fuel_in_profitability: boolean;
  role_permissions: {
    admin: {
      view_vehicle_investment: boolean;
      view_vehicle_recovery: boolean;
      view_profitability: boolean;
      view_investor_information: boolean;
      view_reports: boolean;
      export_financial_reports: boolean;
      manage_vehicle_cost_items: boolean;
    };
  };
  role_permission_audit_log?: Array<{
    changed_by?: string | null;
    changed_at?: string | null;
    changed_keys?: string[];
    scope?: string;
  }>;
  supported_currencies: CurrencyCode[];
  supported_distance_units: DistanceUnit[];
  created_by?: string | null;
  updated_by?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

const SETTINGS_CACHE_KEY = 'flux_system_settings';

export async function fetchSystemSettings() {
  const response = await apiRequest<{ data: { settings: SystemSettingsRecord } }>('/system-settings');
  cacheSystemSettings(response.data.settings);
  return response.data.settings;
}

export async function updateSystemSettings(payload: Partial<SystemSettingsRecord>) {
  const response = await apiRequest<{ data: { settings: SystemSettingsRecord } }>('/system-settings', {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  cacheSystemSettings(response.data.settings);
  return response.data.settings;
}

export function cacheSystemSettings(settings: SystemSettingsRecord) {
  localStorage.setItem(SETTINGS_CACHE_KEY, JSON.stringify(settings));
}

export function getCachedSystemSettings() {
  const raw = localStorage.getItem(SETTINGS_CACHE_KEY);
  if (!raw) {
    return null;
  }

  try {
    return JSON.parse(raw) as SystemSettingsRecord;
  } catch {
    return null;
  }
}

export function formatCurrencyAmount(
  value?: number | null,
  settings?: Pick<SystemSettingsRecord, 'currency_symbol'> | null,
) {
  const symbol = settings?.currency_symbol || getCachedSystemSettings()?.currency_symbol || 'GHS';
  return `${symbol} ${(value || 0).toLocaleString()}`;
}
