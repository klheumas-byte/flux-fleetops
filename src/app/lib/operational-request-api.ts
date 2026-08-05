import { apiRequest } from './api';

export const PERSONAL_USE_OPERATION_TYPE = 'personal_use' as const;

export type OperationType =
  | 'internal_company_delivery'
  | 'fuel_station_visit'
  | 'compliance_inspection_visit'
  | 'administrative_errand'
  | 'vehicle_repositioning'
  | typeof PERSONAL_USE_OPERATION_TYPE;

export type OperationStatus =
  | 'draft' | 'pending_approval' | 'approved' | 'scheduled'
  | 'movement_in_progress' | 'awaiting_verification' | 'completed'
  | 'rejected' | 'cancelled' | 'aborted';

export interface OperationRequest {
  id: string;
  request_id: string;
  operation_type: OperationType;
  title: string;
  purpose: string;
  journey_mode: 'one_way' | 'round_trip' | 'multi_stop';
  origin?: string | null;
  destination?: string | null;
  planned_departure_at?: string | null;
  expected_return_at?: string | null;
  status: OperationStatus;
  priority: string;
  vehicle_id?: string | null;
  driver_id?: string | null;
  linked_vehicle_movement_id?: string | null;
  linked_vehicle_movement_status?: string | null;
  vehicle_reservation_id?: string | null;
  acknowledged_at?: string | null;
  opening_check_completed_at?: string | null;
  receiver_confirmation?: Record<string, unknown> | null;
  task_confirmation?: Record<string, unknown> | null;
  destination_acceptance?: Record<string, unknown> | null;
  no_purchase_reason?: string | null;
  fuel_log_id?: string | null;
  vehicle?: { id: string; registration_number: string; make?: string | null; model?: string | null; vehicle_type?: string | null } | null;
  driver?: { id: string; full_name: string } | null;
  created_at?: string | null;
  requested_by?: string | null;
  rejection_reason?: string | null;
  started_at?: string | null;
  returned_at?: string | null;
  distance_travelled?: number | null;
  duration_minutes?: number | null;
  fuel_difference?: number | null;
  return_fault_id?: string | null;
  is_overdue?: boolean;
  late_return?: boolean;
  status_history?: Array<{ status: string; at?: string; note?: string; actor_id?: string }>;
}

export interface OperationOptions {
  operation_types: OperationType[];
  statuses: OperationStatus[];
  vehicles: Array<{ id: string; registration_number: string; make?: string | null; model?: string | null; is_available?: boolean; operational_state?: string; primary_reason?: string | null; availability_label?: string; requires_approval?: boolean; is_target_vehicle?: boolean }>;
  drivers: Array<{ id: string; full_name: string }>;
}

export interface PersonalUseDriverSummary {
  driver_id: string | null; driver_name: string; total_requests: number; approved: number; rejected: number; cancelled: number; completed: number; pending: number;
  total_personal_use_trips: number; total_personal_use_hours: number; total_distance_travelled: number | null; distance_recorded_trips: number;
  vehicles_used: number; target_assigned_vehicle_usage_count: number; other_vehicle_usage_count: number; unknown_target_usage_count: number;
  approval_rate: number; last_personal_use_date: string | null; fuel_impact_total: number | null; fuel_impact_recorded_trips: number; late_return_exception_count: number;
}

export interface PersonalUseHistoryRow {
  request_id: string; date: string | null; driver_id: string | null; driver_name: string; vehicle_id: string | null; vehicle_registration: string;
  target_vehicle: boolean | null; purpose?: string | null; departure: string | null; return: string | null; duration_minutes: number | null; distance: number | null;
  status: string; approved_by: string | null; fuel_impact: number | null; cost_impact: number | null; late_return: boolean; exception: boolean;
}

export interface PersonalUseAnalytics {
  lifetime: boolean;
  totals: { requests: number; trips: number; hours: number; distance: number | null };
  drivers: PersonalUseDriverSummary[];
  history: PersonalUseHistoryRow[];
}

export interface OperationListResponse {
  requests: OperationRequest[];
  pagination: { page: number; page_size: number; total: number; total_pages: number };
}

export async function fetchOperationRequests(filters: { status?: string; operation_type?: string } = {}) {
  const params = new URLSearchParams();
  if (filters.status) params.set('status', filters.status);
  if (filters.operation_type) params.set('operation_type', filters.operation_type);
  const result = await apiRequest<OperationListResponse>(`/operational-requests${params.size ? `?${params}` : ''}`, {
    componentName: 'OperationalRequests', requestLabel: 'list', dedupeKey: `operational-requests:${params}`,
  });
  return result.data;
}

export async function fetchOperationRequest(id: string) {
  const result = await apiRequest<{ request: OperationRequest }>(`/operational-requests/${id}`, {
    componentName: 'OperationalRequests',
    requestLabel: 'detail',
    dedupeKey: `operational-request:${id}`,
  });
  return result.data.request;
}

export async function fetchOperationOptions(filters: { planned_departure_at?: string; expected_return_at?: string } = {}) {
  const params = new URLSearchParams();
  if (filters.planned_departure_at) params.set('planned_departure_at', filters.planned_departure_at);
  if (filters.expected_return_at) params.set('expected_return_at', filters.expected_return_at);
  const result = await apiRequest<OperationOptions>(`/operational-requests/options${params.size ? `?${params}` : ''}`, {
    componentName: 'OperationalRequests', requestLabel: 'options', dedupeKey: `operational-requests:options:${params}`, cacheTtlMs: 15_000,
  });
  return result.data;
}

export async function fetchPersonalUseAnalytics(filters: { driver_id?: string; vehicle_id?: string; date_from?: string; date_to?: string; branch_id?: string; status?: string } = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value); });
  const result = await apiRequest<PersonalUseAnalytics>(`/operational-requests/personal-use/analytics${params.size ? `?${params}` : ''}`, {
    componentName: 'PersonalUseAnalytics', requestLabel: 'analytics', dedupeKey: `personal-use-analytics:${params}`,
  });
  return result.data;
}

export async function createOperationRequest(payload: Record<string, unknown>) {
  const result = await apiRequest<{ request: OperationRequest }>('/operational-requests', { method: 'POST', body: JSON.stringify(payload), componentName: 'OperationalRequests', requestLabel: 'create' });
  return result.data.request;
}

export async function mutateOperationRequest(id: string, action: string, payload: Record<string, unknown> = {}) {
  const result = await apiRequest<{ request: OperationRequest }>(`/operational-requests/${id}/${action}`, { method: 'PATCH', body: JSON.stringify(payload), componentName: 'OperationalRequests', requestLabel: action, replacePending: true, cancelGroup: `operation:${id}:${action}` });
  return result.data.request;
}
