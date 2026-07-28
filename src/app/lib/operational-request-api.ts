import { apiRequest } from './api';

export type OperationType =
  | 'internal_company_delivery'
  | 'fuel_station_visit'
  | 'compliance_inspection_visit'
  | 'administrative_errand'
  | 'vehicle_repositioning';

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
}

export interface OperationOptions {
  operation_types: OperationType[];
  statuses: OperationStatus[];
  vehicles: Array<{ id: string; registration_number: string; make?: string | null; model?: string | null; is_available?: boolean; primary_reason?: string | null }>;
  drivers: Array<{ id: string; full_name: string }>;
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

export async function fetchOperationOptions() {
  const result = await apiRequest<OperationOptions>('/operational-requests/options', {
    componentName: 'OperationalRequests', requestLabel: 'options', dedupeKey: 'operational-requests:options', cacheTtlMs: 15_000,
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
