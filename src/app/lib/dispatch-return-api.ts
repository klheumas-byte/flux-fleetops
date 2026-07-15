import type { FuelLevelDetails } from './fuel-gauge';
import { apiRequest } from './api';

export type DispatchReturnStatus =
  | 'awaiting_return'
  | 'returned'
  | 'inspection_completed'
  | 'dispatch_closed';

export interface DispatchReturnUserSummary {
  id: string;
  full_name: string;
  phone?: string | null;
  email?: string | null;
  role?: string | null;
  status?: string | null;
}

export interface DispatchReturnVehicleSummary {
  id: string;
  registration_number: string;
  vehicle_type?: string | null;
  make?: string | null;
  model?: string | null;
  status?: string | null;
  tank_capacity_litres?: number | null;
  current_fuel_level?: number | null;
  current_fuel_level_details?: FuelLevelDetails | null;
}

export interface DispatchReturnListItem {
  id: string;
  dispatch_job_id: string;
  dispatch_date?: string | null;
  dispatch_time?: string | null;
  scheduled_start_time?: string | null;
  current_dispatch_status: string;
  driver_workflow_status?: string | null;
  return_status: DispatchReturnStatus;
  return_time?: string | null;
  vehicle?: DispatchReturnVehicleSummary | null;
  driver?: DispatchReturnUserSummary | null;
  movement_id?: string | null;
  movement_status?: string | null;
}

export interface DispatchReturnAccessory {
  name: string;
  status: 'returned' | 'missing' | 'damaged';
}

export interface DispatchReturnChecklist {
  vehicle_id?: string | null;
  driver_id?: string | null;
  return_date?: string | null;
  return_time?: string | null;
  closing_odometer?: number | null;
  closing_fuel_level?: number | null;
  vehicle_condition?: string | null;
  accessories?: DispatchReturnAccessory[];
  existing_damage?: string | null;
  new_damage?: string | null;
  driver_remarks?: string | null;
  admin_remarks?: string | null;
  photos?: string[];
  linked_fault_id?: string | null;
  mark_vehicle_unavailable?: boolean;
  warnings?: string[];
  recorded_at?: string | null;
}

export interface DispatchReturnFaultOption {
  id: string;
  name?: string;
  category_id?: string | null;
  code?: string | null;
}

export interface DispatchReturnFaultRecord {
  id: string;
  vehicle_id: string;
  driver_id: string;
  category_id?: string | null;
  component_id?: string | null;
  severity: string;
  description: string;
  status: string;
  reported_at?: string | null;
}

export interface DispatchReturnMovementRecord {
  id: string;
  movement_id: string;
  status: string;
  requested_departure_time?: string | null;
  departure_time?: string | null;
  expected_return_time?: string | null;
  actual_return_time?: string | null;
  origin?: string | null;
  destination?: string | null;
  opening_odometer?: number | null;
  closing_odometer?: number | null;
  opening_fuel_level?: number | null;
  closing_fuel_level?: number | null;
  opening_fuel_level_details?: FuelLevelDetails | null;
  closing_fuel_level_details?: FuelLevelDetails | null;
  return_checklist?: DispatchReturnChecklist | null;
}

export interface DispatchReturnDetail {
  job: Record<string, unknown> & {
    id: string;
    dispatch_job_id: string;
    status: string;
    driver_workflow_status?: string | null;
    return_status?: string | null;
    scheduled_start_time?: string | null;
    expected_return_time?: string | null;
    goods_description?: string | null;
    dispatch_instructions?: string | null;
    closure_note?: string | null;
  };
  movement?: DispatchReturnMovementRecord | null;
  vehicle?: DispatchReturnVehicleSummary | null;
  driver?: DispatchReturnUserSummary | null;
  return_status: DispatchReturnStatus;
  return_checklist: DispatchReturnChecklist;
  vehicle_conditions: string[];
  accessory_statuses: string[];
  default_accessories: string[];
  fault_options: {
    categories: DispatchReturnFaultOption[];
    components: DispatchReturnFaultOption[];
  };
  existing_faults: DispatchReturnFaultRecord[];
  linked_fault?: DispatchReturnFaultRecord | null;
}

export interface DispatchReturnListResponse {
  returns: DispatchReturnListItem[];
  pagination: {
    page: number;
    page_size: number;
    total: number;
    total_pages: number;
  };
  filters: {
    q?: string | null;
    return_status?: string | null;
  };
}

interface DispatchReturnListEnvelope {
  success: boolean;
  data: DispatchReturnListResponse;
}

interface DispatchReturnDetailEnvelope {
  success: boolean;
  data: DispatchReturnDetail;
}

interface DispatchReturnActionEnvelope {
  success: boolean;
  data: {
    detail: DispatchReturnDetail;
    warnings?: string[];
    reservation_release?: {
      vehicle_reservation_released: boolean;
      driver_reservation_released: boolean;
    };
    created_fault?: DispatchReturnFaultRecord | null;
  };
}

export async function fetchDispatchReturns(params: {
  page?: number;
  page_size?: number;
  q?: string;
  return_status?: string;
} = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value).trim() !== '') {
      query.set(key, String(value));
    }
  });
  const response = await apiRequest<DispatchReturnListEnvelope>(`/dispatch/returns${query.toString() ? `?${query.toString()}` : ''}`, {
    cacheTtlMs: 5000,
    dedupeKey: `dispatch-returns:${query.toString() || 'default'}`,
    componentName: 'DispatchReturns',
    requestLabel: 'list',
    cancelGroup: 'dispatch-returns-list',
    replacePending: true,
  });
  return response.data;
}

export async function fetchDispatchReturnDetail(jobId: string) {
  const response = await apiRequest<DispatchReturnDetailEnvelope>(`/dispatch/returns/${jobId}`, {
    cacheTtlMs: 3000,
    dedupeKey: `dispatch-return-detail:${jobId}`,
    componentName: 'DispatchReturns',
    requestLabel: 'detail',
  });
  return response.data;
}

async function patchDispatchReturnAction(jobId: string, action: string, payload?: Record<string, unknown>) {
  const response = await apiRequest<DispatchReturnActionEnvelope>(`/dispatch/returns/${jobId}/${action}`, {
    method: 'PATCH',
    body: JSON.stringify(payload || {}),
  });
  return response.data;
}

export async function confirmDispatchReturn(jobId: string, payload: {
  actual_return_time?: string;
  closing_odometer?: number;
  closing_fuel_level?: number;
  notes?: string;
}) {
  return patchDispatchReturnAction(jobId, 'confirm-return', payload);
}

export async function saveDispatchReturnInspection(jobId: string, payload: Record<string, unknown>) {
  return patchDispatchReturnAction(jobId, 'inspection', payload);
}

export async function linkOrCreateDispatchReturnFault(jobId: string, payload: {
  fault_id?: string;
  mark_vehicle_unavailable?: boolean;
  fault_payload?: Record<string, unknown>;
}) {
  return patchDispatchReturnAction(jobId, 'fault', payload);
}

export async function closeDispatchReturn(jobId: string, payload?: { closure_note?: string }) {
  return patchDispatchReturnAction(jobId, 'close', payload);
}
