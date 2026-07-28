import { apiRequest } from './api';

export interface MaintenanceOverride {
  id: string; vehicle_id: string; linked_record_type: 'fault' | 'maintenance'; linked_record_id: string;
  fault_severity: string; operational_restriction: string; business_justification: string;
  repair_deadline: string; expires_at: string; status: 'active' | 'expired' | 'resolved' | 'revoked';
  is_overdue: boolean; maximum_mileage?: number | null; maximum_hours?: number | null;
  acknowledgements: Array<{ driver_id: string; acknowledged_at: string }>;
}

export async function fetchMaintenanceOverrides(filters: { vehicle_id?: string; status?: string } = {}) {
  const params = new URLSearchParams(); Object.entries(filters).forEach(([key, value]) => value && params.set(key, value));
  const response = await apiRequest<{ data: { records: MaintenanceOverride[] } }>(`/maintenance-overrides${params.toString() ? `?${params}` : ''}`);
  return response.data.records;
}
export async function createMaintenanceOverride(payload: Record<string, unknown>) {
  const response = await apiRequest<{ data: { override: MaintenanceOverride } }>('/maintenance-overrides', { method: 'POST', body: JSON.stringify(payload) });
  return response.data.override;
}
export async function transitionMaintenanceOverride(id: string, action: 'revoke' | 'resolve', notes?: string) {
  const response = await apiRequest<{ data: { override: MaintenanceOverride } }>(`/maintenance-overrides/${id}/${action}`, { method: 'PATCH', body: JSON.stringify({ notes }) });
  return response.data.override;
}
export async function acknowledgeMaintenanceOverride(id: string) {
  const response = await apiRequest<{ data: { override: MaintenanceOverride } }>(`/maintenance-overrides/${id}/acknowledge`, { method: 'PATCH' });
  return response.data.override;
}
